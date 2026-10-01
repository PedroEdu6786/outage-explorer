"""Behavior checks for the local session journal; Python standard library only."""

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest


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
        hook.handle_event({
            "hook_event_name": event, "session_id": session,
            "turn_id": turn, "cwd": str(self.root),
            "last_assistant_message": summary,
        }, self.root, NOW)

    def test_writes_only_at_session_end_and_preserves_existing_notes(self):
        self.log.parent.mkdir(parents=True)
        original = "# 2026-10-01\n\nHuman notes.\n"
        self.log.write_text(original)
        self.send("Stop")
        self.assertEqual(self.log.read_text(), original)
        self.send("SessionEnd")
        self.assertTrue(self.log.read_text().startswith(original))
        self.assertIn("Tested the connector.", self.log.read_text())

    def test_repeated_callbacks_and_resumed_session_do_not_repeat_old_turns(self):
        for _ in range(2):
            self.send("Stop")
            self.send("SessionEnd")
        self.send("Stop", turn="turn-2", summary="Verified authorization.")
        self.send("SessionEnd")
        text = self.log.read_text()
        self.assertEqual(text.count("Tested the connector."), 1)
        self.assertEqual(text.count("Verified authorization."), 1)

    def test_recovers_after_append_before_state_update_across_midnight(self):
        self.send("Stop")
        state_path = next((self.root / ".devlog-state").glob("*.json"))
        before_flush = state_path.read_text()
        self.send("SessionEnd")
        state_path.write_text(before_flush)
        hook.handle_event({"hook_event_name": "SessionEnd", "session_id": "session-1",
                           "cwd": str(self.root)}, self.root,
                          datetime(2026, 10, 2, tzinfo=timezone.utc))
        self.assertEqual(self.log.read_text().count("Tested the connector."), 1)
        self.assertFalse((self.log.parent / "2026-10-02.md").exists())

    def test_parallel_sessions_preserve_each_summary(self):
        def finish(index):
            self.send("Stop", session=str(index), summary="Completed task " + str(index))
            self.send("SessionEnd", session=str(index))
        with ThreadPoolExecutor(max_workers=4) as pool:
            list(pool.map(finish, range(8)))
        text = self.log.read_text()
        self.assertEqual(text.count("<!-- codex-devlog:"), 8)
        self.assertEqual(text.count("# 2026-10-01\n"), 1)

    def test_ignores_empty_summaries_unrelated_events_and_empty_sessions(self):
        self.send("Stop", summary=None)
        self.send("SessionEnd")
        self.send("SessionStart")
        self.assertFalse(self.log.exists())

    def test_only_final_summary_is_recorded_with_common_secrets_redacted(self):
        hook.handle_event({
            "hook_event_name": "Stop", "session_id": "session-1", "cwd": str(self.root),
            "last_assistant_message": 'Fixed auth. api_key="example-secret" Authorization: Bearer example-token',
            "prompt": "private prompt", "tool_output": "private command output",
        }, self.root, NOW)
        state = next((self.root / ".devlog-state").glob("*.json")).read_text()
        self.send("SessionEnd")
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
        self.send("SessionEnd")
        self.assertIn("Worked in src.", self.log.read_text())
        payload["cwd"] = str(self.root.parent)
        with self.assertRaises(ValueError):
            hook.handle_event(payload, self.root, NOW)

    def test_bad_state_is_not_overwritten(self):
        self.send("Stop")
        state_path = next((self.root / ".devlog-state").glob("*.json"))
        state_path.write_text("broken json")
        with self.assertRaises(json.JSONDecodeError):
            self.send("SessionEnd")
        self.assertEqual(state_path.read_text(), "broken json")


if __name__ == "__main__":
    unittest.main()
