"""짧은 글 모드(SKILL.md의 short): lint_ko.py --short의 기준과 원문 대조(F 항목)."""
import json
import os
import subprocess
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPTS = os.path.join(ROOT, "skills", "techblog", "scripts")
sys.path.insert(0, SCRIPTS)

import lint_ko as L  # noqa: E402

SOURCE = """**google sign-in**: Which port should the dev server use?

The API already listens on `8080`, and the docs at https://example.com/dev mention 3000.

- `3000`: the docs' default
- `8085`: free on this Mac

If you want, reply with another port in this thread. <@U123> {link}

```bash
npm run dev -- --port 3000
```
"""

GOOD = """**google sign-in**: 개발 서버는 어떤 포트를 쓸까요?

API가 이미 `8080`을 쓰고 있고, https://example.com/dev 문서는 3000을 안내합니다.

- `3000`: 문서의 기본값
- `8085`: 이 Mac에서 비어 있는 포트

원하시면 이 스레드에 다른 포트를 답해 주세요. <@U123> {link}

```bash
npm run dev -- --port 3000
```
"""


class ShortModeTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def write(self, name, text):
        path = os.path.join(self.tmp.name, name)
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)
        return path

    def lint(self, text, *extra, source=SOURCE):
        ko = self.write("out.ko.md", text)
        src = self.write("src.en.md", source)
        out, verdict = L.run(ko, "default", as_json=True, short=True, source=src,
                             terms=self.write("terms.json", json.dumps(dict(extra))) if extra else None)
        return json.loads(out), verdict

    def failed(self, report):
        return {r["id"] for r in report["results"] if r["status"] in ("GATE", "FAIL")}

    def test_a_faithful_short_post_passes(self):
        report, verdict = self.lint(GOOD)
        self.assertEqual(verdict, "PASS", self.failed(report))

    def test_direct_address_and_requests_are_allowed_only_in_short_mode(self):
        ko = self.write("good.md", GOOD)
        _, article = L.run(ko, "default")
        self.assertEqual(article, "FAIL")                 # 아티클로는 "원하시면"과 "주세요"가 걸린다
        _, short = L.run(ko, "default", short=True)
        self.assertEqual(short, "PASS")

    def test_dropped_or_changed_source_parts_are_gates(self):
        bad = GOOD.replace("`8080`", "8080").replace("https://example.com/dev ", "").replace(" <@U123> {link}", "")
        bad = bad.replace("- `3000`: 문서의 기본값\n- `8085`: 이 Mac에서 비어 있는 포트",
                          "- `3000`은 문서의 기본값이고 `8085`는 비어 있습니다.")
        bad = bad.replace("--port 3000", "--port 3001")
        report, verdict = self.lint(bad)
        self.assertEqual(verdict, "FAIL")
        self.assertTrue({"F1.code_blocks", "F2.inline_code", "F3.urls", "F4.slack_tokens", "F6.list_items"}
                        <= self.failed(report), self.failed(report))

    def test_a_dropped_number_and_an_added_heading_are_gates(self):
        bad = "## 포트\n\n" + GOOD.replace("문서는 3000을 안내합니다", "문서는 다른 포트를 안내합니다")
        report, _ = self.lint(bad)
        self.assertTrue({"F5.numbers", "F7.headings"} <= self.failed(report), self.failed(report))

    def test_the_glossary_is_followed(self):
        report, _ = self.lint(GOOD, ("dev server", "개발 서버"), ("thread", "스레드"))
        self.assertNotIn("F8.terms", self.failed(report))
        report, _ = self.lint(GOOD, ("dev server", "dev 서버"))
        self.assertIn("F8.terms", self.failed(report))

    def test_translationese_is_counted_in_short_texts(self):
        bad = GOOD.replace("API가 이미 `8080`을 쓰고 있고", "API는 이미 `8080`을 가지고 있습니다. 그것은 중요한 역할을 하고")
        report, verdict = self.lint(bad)
        rows = {r["id"]: r for r in report["results"]}
        self.assertGreaterEqual(rows["A14.translationese_per_1k"]["value"], 2)
        self.assertEqual(verdict, "FAIL")

    def test_the_cli_needs_short_for_source_and_terms(self):
        ko = self.write("good.md", GOOD)
        src = self.write("src.md", SOURCE)
        script = os.path.join(SCRIPTS, "lint_ko.py")
        done = subprocess.run([sys.executable, script, ko, "--source", src], capture_output=True, text=True)
        self.assertEqual(done.returncode, 2)
        done = subprocess.run([sys.executable, script, ko, "--short", "--source", src, "--tone", "default"],
                              capture_output=True, text=True)
        self.assertEqual(done.returncode, 0, done.stdout)


if __name__ == "__main__":
    unittest.main()
