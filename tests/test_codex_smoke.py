import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("codex_smoke", ROOT / "dev/codex/smoke.py")
smoke = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(smoke)


class CodexEvidenceTest(unittest.TestCase):
    def test_windows_auth_link_fallback_does_not_copy_or_remove_source(self):
        with tempfile.TemporaryDirectory() as tmp:
            auth, link = Path(tmp) / "auth.json", Path(tmp) / "linked.json"
            auth.write_text("test fixture", encoding="utf-8")
            denied = OSError("symlink privilege unavailable")
            denied.winerror = 1314
            with patch.object(Path, "symlink_to", side_effect=denied):
                self.assertEqual(smoke.link_auth(auth, link), "hardlink")
            self.assertTrue(auth.samefile(link))
            link.unlink()
            self.assertEqual(auth.read_text(encoding="utf-8"), "test fixture")

    def test_powershell_checker_with_unicode_and_spaces(self):
        command = 'powershell.exe -NoProfile -Command \'python "C:\\설치 폴더\\scripts\\revise_ko.py" check "article.md"\''
        self.assertEqual(smoke.checker_invocations(command), [{"script": "revise_ko.py", "action": "check"}])

    def test_runtime_truncation_warning_is_a_failure_diagnostic(self):
        warning = "Skill `techblog:techblog` exceeded the main prompt context limit and was truncated."
        events = [{"type": "item.completed", "item": {"type": "error", "message": warning}},
                  {"type": "turn.completed"}]
        with tempfile.TemporaryDirectory() as tmp:
            log = Path(tmp) / "run.jsonl"
            log.write_text("\n".join(json.dumps(e) for e in events), encoding="utf-8")
            err = Path(tmp) / "run.err"
            err.write_text("WARNING: " + warning, encoding="utf-8")
            self.assertEqual(smoke.skill_load_errors(log, err), [warning])

    def test_stderr_load_failure_is_detected(self):
        with tempfile.TemporaryDirectory() as tmp:
            log = Path(tmp) / "run.jsonl"
            log.write_text("", encoding="utf-8")
            err = Path(tmp) / "run.err"
            message = "Failed to load skill techblog at C:/설치/SKILL.md: missing file"
            err.write_text(message, encoding="utf-8")
            self.assertEqual(smoke.skill_load_errors(log, err), [message])

    def test_quoted_warning_and_unrelated_diagnostics_are_not_load_failures(self):
        warning = "Skill `techblog:techblog` exceeded the main prompt context limit and was truncated."
        events = [{"type": "item.completed", "item": {"type": "agent_message", "text": warning}},
                  {"type": "item.completed", "item": {"type": "error", "message": "unrelated warning"}}]
        with tempfile.TemporaryDirectory() as tmp:
            log = Path(tmp) / "run.jsonl"
            log.write_text("not JSON\n" + "\n".join(json.dumps(e) for e in events), encoding="utf-8")
            self.assertEqual(smoke.skill_load_errors(log, Path(tmp) / "run.err"), [])

    def test_plugin_prompt_targets_installed_skill(self):
        with tempfile.TemporaryDirectory(prefix="techblog 공백 ") as tmp:
            base = Path(tmp)
            project, profile = base / "work", base / "profile"
            project.mkdir()
            path = profile / "plugins/cache/skill-techblog/techblog/0.5.1/skills/techblog/SKILL.md"
            path.parent.mkdir(parents=True)
            path.write_text("test", encoding="utf-8")
            actual = smoke.installed_skill(project, profile, "plugin")
            self.assertEqual(actual, path)
            mention = "[$techblog:techblog]({})".format(actual.as_posix())
            prompt, originals = smoke.prepare_case(project, "default", skill_mention=mention)
            self.assertTrue(prompt.startswith(mention + " default "))
            self.assertEqual(len(originals), 1)

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
