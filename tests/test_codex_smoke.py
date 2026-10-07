import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("codex_smoke", ROOT / "dev/codex/smoke.py")
smoke = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(smoke)


class CodexEvidenceTest(unittest.TestCase):
    def test_quoted_installed_checker_path(self):
        command = '/bin/zsh -lc \'python3 "/tmp/설치 폴더/scripts/revise_ko.py" check "article.md"\''
        self.assertEqual(smoke.checker_invocations(command), [{"script": "revise_ko.py", "action": "check"}])

    def test_reading_checker_is_not_running_it(self):
        for command in ('rg -n "def" /tmp/scripts/lint_ko.py', 'cat "/tmp/scripts/revise_ko.py"'):
            self.assertEqual(smoke.checker_invocations(command), [])

    def test_completed_failed_commands_are_not_lost_or_duplicated(self):
        item = {"type": "command_execution", "command": 'python3 "/tmp/lint_ko.py" article.md'}
        events = [{"type": "item.started", "item": item},
                  {"type": "item.completed", "item": dict(item, exit_code=1)},
                  {"type": "item.completed", "item": {"type": "agent_message", "text": "PASS"}}]
        with tempfile.TemporaryDirectory() as tmp:
            log = Path(tmp) / "run.jsonl"
            log.write_text("\n".join(json.dumps(e) for e in events), encoding="utf-8")
            self.assertEqual(smoke.command_events(log), [{"command": item["command"], "exit_code": 1}])


if __name__ == "__main__":
    unittest.main()
