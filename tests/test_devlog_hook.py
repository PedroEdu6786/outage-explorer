"""Behavior checks for the local session journal; Python standard library only."""

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import importlib.util
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch


SPEC = importlib.util.spec_from_file_location(
    "devlog_hook", Path(__file__).resolve().parents[1] / "scripts" / "devlog_hook.py"
)
hook = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(hook)
NOW = datetime(2026, 10, 1, 12, 0, tzinfo=timezone.utc)


class DevlogHookTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.log = self.root / "docs/devlog/2026-10-01.md"

    def send(self, event, session="session-1", turn="turn-1", summary="Tested the connector."):
        return hook.handle_event({
            "hook_event_name": event, "tool_name": "Bash",
            "tool_input": {"command": "git commit -m test"}, "session_id": session,
            "turn_id": turn, "cwd": str(self.root),
            "last_assistant_message": summary,
        }, self.root, NOW)

    def test_writes_only_before_commit_and_preserves_existing_notes(self):
        self.log.parent.mkdir(parents=True)
        original = "# 2026-10-01\n\nHuman notes.\n"
        self.log.write_text(original)
        self.send("Stop")
        self.send("SessionEnd")
        self.assertEqual(self.log.read_text(), original)
        result = self.send("PreToolUse")
        self.assertEqual(result["hookSpecificOutput"]["permissionDecision"], "deny")
        self.assertIsNone(self.send("PreToolUse"))
        self.assertTrue(self.log.read_text().startswith(original))
        self.assertIn("Tested the connector.", self.log.read_text())

    def test_repeated_callbacks_and_resumed_session_do_not_repeat_old_turns(self):
        for _ in range(2):
            self.send("Stop")
            self.send("PreToolUse")
        self.send("Stop", turn="turn-2", summary="Verified authorization.")
        self.send("PreToolUse")
        text = self.log.read_text()
        self.assertEqual(text.count("Tested the connector."), 1)
        self.assertEqual(text.count("Verified authorization."), 1)

    def test_recovers_after_append_before_state_update_across_midnight(self):
        self.send("Stop")
        state_path = next((self.root / ".devlog-state").glob("*.json"))
        before_flush = state_path.read_text()
        self.send("PreToolUse")
        state_path.write_text(before_flush)
        hook.handle_event({"hook_event_name": "PreToolUse", "tool_name": "Bash",
                           "tool_input": {"command": "git commit -m test"}, "session_id": "session-1",
                           "cwd": str(self.root)}, self.root,
                          datetime(2026, 10, 2, tzinfo=timezone.utc))
        self.assertEqual(self.log.read_text().count("Tested the connector."), 1)
        self.assertFalse((self.log.parent / "2026-10-02.md").exists())

    def test_parallel_sessions_preserve_each_summary(self):
        def finish(index):
            self.send("Stop", session=str(index), summary="Completed task " + str(index))
            self.send("PreToolUse", session=str(index))
        with ThreadPoolExecutor(max_workers=4) as pool:
            list(pool.map(finish, range(8)))
        text = self.log.read_text()
        self.assertEqual(text.count("<!-- codex-devlog:"), 8)
        self.assertEqual(text.count("# 2026-10-01\n"), 1)

    def test_ignores_empty_summaries_unrelated_events_and_empty_sessions(self):
        self.send("Stop", summary=None)
        self.send("PreToolUse")
        self.send("SessionStart")
        self.assertFalse(self.log.exists())

    def test_only_final_summary_is_recorded_with_common_secrets_redacted(self):
        hook.handle_event({
            "hook_event_name": "Stop", "session_id": "session-1", "cwd": str(self.root),
            "last_assistant_message": 'Fixed auth. api_key="example-secret" Authorization: Bearer example-token',
            "prompt": "private prompt", "tool_output": "private command output",
        }, self.root, NOW)
        state = next((self.root / ".devlog-state").glob("*.json")).read_text()
        self.send("PreToolUse")
        for text in (state, self.log.read_text()):
            self.assertIn("Fixed auth.", text)
            for secret in ("example-secret", "example-token", "private prompt", "private command output"):
                self.assertNotIn(secret, text)

    def test_subdirectory_cwd_works_and_external_cwd_is_rejected(self):
        subdir = self.root / "src"
        subdir.mkdir()
        payload = {"hook_event_name": "Stop", "session_id": "session-1",
                   "cwd": str(subdir), "last_assistant_message": "Worked in src."}
        hook.handle_event(payload, self.root, NOW)
        self.send("PreToolUse")
        self.assertIn("Worked in src.", self.log.read_text())
        payload["cwd"] = str(self.root.parent)
        with self.assertRaises(ValueError):
            hook.handle_event(payload, self.root, NOW)

    def test_bad_state_is_not_overwritten(self):
        self.send("Stop")
        state_path = next((self.root / ".devlog-state").glob("*.json"))
        state_path.write_text("broken json")
        with self.assertRaises(json.JSONDecodeError):
            self.send("PreToolUse")
        self.assertEqual(state_path.read_text(), "broken json")

    def test_new_session_commit_flushes_previously_closed_sessions(self):
        self.send("Stop", session="old-session", summary="Earlier work.")
        self.send("SessionEnd", session="old-session")
        self.assertFalse(self.log.exists())
        self.send("PreToolUse", session="new-session")
        self.assertIn("Earlier work.", self.log.read_text())

    def test_non_commit_tool_call_does_not_flush_buffer(self):
        self.send("Stop")
        hook.handle_event({"hook_event_name": "PreToolUse", "tool_name": "Bash",
                           "tool_input": {"command": "git status"}}, self.root, NOW)
        self.assertFalse(self.log.exists())
        self.send("PreToolUse")
        self.assertIn("Tested the connector.", self.log.read_text())

    def test_literal_commit_detection(self):
        commands = [
            "git commit -m 'feat: add connector'",
            "git add README.md && git commit -m test",
            "git status\ngit commit -m test",
            "git -c credential.helper= -c 'core.editor=true' commit -m test",
            "git -C '/tmp/repo with spaces' commit --amend --no-edit",
            "GIT_EDITOR=true /usr/bin/git commit -m test",
            "git commit --dry-run; git commit -m test",
        ]
        for command in commands:
            with self.subTest(command=command):
                self.assertTrue(hook.is_commit({"tool_name": "Bash",
                                               "tool_input": {"command": command}}))

    def test_non_commit_commands_and_other_tools_are_ignored(self):
        commands = ["git status", "git log --grep commit", "echo 'git commit'",
                    "printf '%s' 'git commit -m test'", "git commit-tree HEAD",
                    "git commit --dry-run", "git -c alias.ci=commit status",
                    "# git commit -m test", "git commit -m 'unfinished", None]
        for command in commands:
            with self.subTest(command=command):
                self.assertFalse(hook.is_commit({"tool_name": "Bash",
                                                "tool_input": {"command": command}}))
        self.assertFalse(hook.is_commit({"tool_name": "apply_patch",
                                        "tool_input": {"command": "git commit"}}))

    def test_cli_emits_block_decision_as_json(self):
        decision = {"hookSpecificOutput": {"hookEventName": "PreToolUse",
                                            "permissionDecision": "deny"}}
        output = io.StringIO()
        with patch.object(hook.sys, "stdin", io.StringIO('{}')), \
             patch.object(hook.sys, "stdout", output), \
             patch.object(hook, "handle_event", return_value=decision):
            self.assertEqual(hook.main(), 0)
        self.assertEqual(json.loads(output.getvalue()), decision)

    def test_failed_precommit_blocks_without_exposing_payload(self):
        payload = json.dumps({"hook_event_name": "PreToolUse", "private": "secret"})
        errors = io.StringIO()
        with patch.object(hook.sys, "stdin", io.StringIO(payload)), \
             patch.object(hook.sys, "stderr", errors), \
             patch.object(hook, "handle_event", side_effect=OSError("private detail")):
            self.assertEqual(hook.main(), 2)
        self.assertNotIn("secret", errors.getvalue())
        self.assertNotIn("private detail", errors.getvalue())

    def test_config_flushes_before_shell_tools_instead_of_session_end(self):
        config = json.loads((hook.ROOT / ".codex/hooks.json").read_text())
        self.assertEqual(set(config["hooks"]), {"Stop", "PreToolUse"})
        self.assertEqual(config["hooks"]["PreToolUse"][0]["matcher"], "^Bash$")


if __name__ == "__main__":
    unittest.main()
