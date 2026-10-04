#!/usr/bin/env python3
"""Buffer Codex turn summaries, then append them before a commit tool call."""

import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import sys
from datetime import datetime


ROOT = Path(__file__).resolve().parents[1]
MAX_SUMMARY = 2000


def is_commit(payload):
    """Recognize literal git commit commands, without executing shell input.

    This is a workflow helper, not a shell interpreter: aliases, scripts and
    dynamically constructed commands are outside its coverage.
    """
    if payload.get("tool_name") != "Bash":
        return False
    command = payload.get("tool_input", {}).get("command")
    if not isinstance(command, str):
        return False
    lexer = shlex.shlex(command, posix=True, punctuation_chars=";&|()\n")
    lexer.whitespace = " \t\r"
    lexer.whitespace_split = True
    try:
        tokens = list(lexer)
    except ValueError:
        return False
    segments = [[]]
    for token in tokens:
        if token and all(char in ";&|()\n" for char in token):
            segments.append([])
        else:
            segments[-1].append(token)
    for segment in segments:
        while segment and re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", segment[0]):
            segment = segment[1:]
        if not segment or Path(segment[0]).name != "git":
            continue
        index = 1
        while index < len(segment) and segment[index].startswith("-"):
            option = segment[index]
            if option in ("--help", "--version"):
                break
            index += 2 if option in ("-c", "-C", "--git-dir", "--work-tree",
                                     "--namespace", "--config-env") else 1
        if index < len(segment) and segment[index] == "commit":
            if "--dry-run" not in segment[index + 1:]:
                return True
    return False


def digest(value):
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def clean_summary(value):
    """Omit common credential formats; never capture prompts or tool output."""
    value = re.sub(r"(?i)\bBearer\s+\S+", "Bearer [REDACTED]", value)
    value = re.sub(
        r"(?i)\b(api[_-]?key|access[_-]?token|password|secret|authorization)"
        r"\b[\"']?\s*[:=]\s*(?:\"[^\"]*\"|'[^']*'|[^\s,;]+)",
        r"\1=[REDACTED]",
        value,
    )
    value = re.sub(r"\b(?:sk-|xox[baprs]-)[A-Za-z0-9_-]+", "[REDACTED]", value)
    value = " ".join(value.split())
    # Prevent embedded HTML from breaking the hidden deduplication markers.
    value = value.replace("<", "&lt;").replace(">", "&gt;")
    if len(value) > MAX_SUMMARY:
        return value[:MAX_SUMMARY] + "… [truncated]"
    return value


def write_state(path, state):
    temporary = path.with_suffix(".tmp")
    with temporary.open("w", encoding="utf-8") as stream:
        json.dump(state, stream, ensure_ascii=False)
        stream.flush()
        os.fsync(stream.fileno())
    temporary.replace(path)


def append_session(root, state, now):
    directory = root / "docs" / "devlog"
    directory.mkdir(parents=True, exist_ok=True)
    # The caller holds a shared writer lock across read/check/append/state update.
    existing = set()
    for path in directory.glob("????-??-??.md"):
        existing.update(re.findall(r"<!-- codex-devlog:([a-f0-9]{64}) -->", path.read_text()))
    pending = [item for item in state if item["id"] not in existing]
    if not pending:
        return
    date = now.strftime("%Y-%m-%d")
    path = directory / (date + ".md")
    with path.open("a+", encoding="utf-8") as stream:
        stream.seek(0, os.SEEK_END)
        if stream.tell() == 0:
            stream.write("# " + date + "\n")
        stream.write("\n## " + now.strftime("%H:%M %Z") + " — Codex pre-commit summaries\n\n")
        stream.write("Automatically captured assistant summaries; claims are not independently verified.\n\n")
        for item in pending:
            stream.write("- " + item["summary"] + "\n")
            stream.write("<!-- codex-devlog:" + item["id"] + " -->\n")
        stream.flush()
        os.fsync(stream.fileno())
    return path


def handle_event(payload, root=ROOT, now=None):
    event = payload.get("hook_event_name")
    if event not in ("Stop", "PreToolUse"):
        return
    if event == "PreToolUse" and not is_commit(payload):
        return
    session = payload.get("session_id")
    if not isinstance(session, str) or not session:
        raise ValueError("session_id is required")
    cwd = Path(payload.get("cwd", "")).resolve()
    if cwd != root and root not in cwd.parents:
        raise ValueError("hook cwd is outside this repository")
    summary = payload.get("last_assistant_message")
    if event == "Stop" and (not isinstance(summary, str) or not summary.strip()):
        return
    directory = root / ".devlog-state"
    directory.mkdir(mode=0o700, exist_ok=True)
    path = directory / (digest(session) + ".json")
    with (directory / "writer.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        state = json.loads(path.read_text()) if path.exists() else []
        if event == "Stop":
            summary = clean_summary(summary)
            # Turn identity plus text handles repeated Stop callbacks and continued turns.
            identity = digest(session + "\0" + str(payload.get("turn_id", "")) + "\0" + summary)
            if not any(item["id"] == identity for item in state):
                state.append({"id": identity, "summary": summary})
                write_state(path, state)
        else:
            # Include buffered sessions that closed before this commit attempt.
            paths = sorted(directory.glob("*.json"))
            pending = [item for buffered in paths
                       for item in json.loads(buffered.read_text())]
            if not pending:
                return
            written = append_session(root, pending, now or datetime.now().astimezone())
            # Markers in the log prevent duplicates if interrupted before this update.
            for buffered in paths:
                write_state(buffered, [])
            if written:
                return {"hookSpecificOutput": {
                    "hookEventName": "PreToolUse",
                    "permissionDecision": "deny",
                    "permissionDecisionReason": (
                        "Devlog updated: " + str(written.relative_to(root)) + ". "
                        "Review and stage these notes, add any current-turn work "
                        "not yet summarized, then retry the commit. No user "
                        "confirmation is required by this hook."
                    ),
                }}


def main():
    payload = {}
    try:
        payload = json.load(sys.stdin)
        result = handle_event(payload)
    except (OSError, ValueError, TypeError, AttributeError, KeyError):
        # Report failure without echoing a payload that could contain private text.
        print("devlog hook failed; check repository permissions and local state", file=sys.stderr)
        return 2 if isinstance(payload, dict) and payload.get("hook_event_name") == "PreToolUse" else 1
    print(json.dumps(result or {}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
