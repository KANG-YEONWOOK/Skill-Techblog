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


GOOD_DEFAULT = """# Antislop 논문으로 보는 LLM 반복 표현 억제 방법

모델이 같은 표현을 반복하면 독자는 몇 문장 만에 기계가 쓴 글이라고 알아챕니다. Paech 등이 2025년에 발표한 Antislop 논문은 이 반복 표현을 찾아내고 억제하는 방법을 다룹니다.

이번 글에서는 논문의 측정 방법과 억제 기법을 정리합니다.

## 반복 표현을 어떻게 찾았나

저자들은 모델 출력의 n-gram 빈도를 사람 글 빈도와 비교했습니다. 사람 글보다 1,000배 이상 자주 나오는 패턴도 있었습니다. 비교 기준은 Reddit 창작 글과 Project Gutenberg 텍스트입니다.

## 억제 방법

Antislop Sampler는 금지 패턴이 나오면 그 패턴의 첫 토큰으로 돌아가 확률을 낮추고 다시 샘플링합니다. 저자들은 이 방법으로 8,000개 넘는 패턴을 억제했다고 보고합니다.

## 마치며

FTPO는 금지 패턴을 90% 줄이면서 GSM8K와 MMLU 점수를 유지했습니다.
"""

BAD_TEXT = """# AI 문체: 단순한 도구를 넘어서

오늘날 개발 환경은 빠르게 변화하고 있습니다. 이것은 단순한 기능이 아니라 패러다임의 전환입니다.

그리고, 제공된 자료에 따르면 이 방식은 매우 중요합니다. 중요한 것은 속도가 아니라 방향입니다.

결론적으로, 앞으로가 더 기대됩니다 🚀
"""


class SplitTest(unittest.TestCase):
    def test_decimal_and_version(self):
        s = L.split_sentences("지연이 3.5초 줄었습니다. v2.1에서 바뀌었습니다.")
        self.assertEqual(s, ["지연이 3.5초 줄었습니다.", "v2.1에서 바뀌었습니다."])

    def test_abbreviation_and_paren(self):
        s = L.split_sentences("여러 지표(e.g. 정확도, 재현율)를 봤습니다. 결과는 표 1과 같습니다.")
        self.assertEqual(len(s), 2)

    def test_quote_inside(self):
        s = L.split_sentences("저자들은 \"모델이 실패했다. 다시 했다.\"라고 썼습니다. 다음 문장입니다.")
        self.assertEqual(len(s), 2)

    def test_question(self):
        s = L.split_sentences("왜 그럴까요? 이유는 두 가지입니다.")
        self.assertEqual(s, ["왜 그럴까요?", "이유는 두 가지입니다."])


class EndingTest(unittest.TestCase):
    def cls(self, sent):
        return L.classify_ending(L.last_word(sent), sent.endswith("?"))

    def test_hapnida(self):
        for s in ("사용합니다.", "줄었습니다.", "방식입니다.", "있습니다.", "확인하십시오.", "되었습니까?"):
            self.assertEqual(self.cls(s), "HAPNIDA", s)

    def test_haeyo(self):
        for s in ("사용해요.", "줄었어요.", "방식이에요.", "비싸거든요.", "그렇죠.", "있나요?"):
            self.assertEqual(self.cls(s), "HAEYO", s)

    def test_kkayo_and_haera(self):
        self.assertEqual(self.cls("어떻게 해결했을까요?"), "Q_KKAYO")
        self.assertEqual(self.cls("결과가 달라졌다."), "HAERA")

    def test_noun_and_nominal(self):
        self.assertEqual(self.cls("추가 검증이 필요."), "NOUN")
        self.assertEqual(self.cls("캐시를 사용함."), "NOMINAL")
        self.assertEqual(self.cls("결과는 표 2(부록 A)에 있습니다."), "HAPNIDA")

    def test_bucket(self):
        self.assertEqual(L.ending_bucket("측정했습니다.", "측정했습니다", "HAPNIDA"), "D_PAST")
        self.assertEqual(L.ending_bucket("쓸 수 있습니다.", "있습니다", "HAPNIDA"), "D_CAN")
        self.assertEqual(L.ending_bucket("비싸거든요.", "비싸거든요", "HAEYO"), "C_GEUDEUN")


class ParseTest(unittest.TestCase):
    def test_blocks(self):
        md = "# 제목\n\n문단 하나.\n둘째 줄.\n\n- 항목 1\n- 항목 2\n\n```python\nx = 1; y = 2\n```\n\n| a | b |\n|---|---|\n| 1 | 2 |\n\n> 인용문입니다.\n"
        types = [b.type for b in L.parse_blocks(md)]
        self.assertEqual(types, ["heading", "paragraph", "list_item", "list_item", "code", "table", "blockquote"])

    def test_code_excluded_from_semicolon(self):
        a = L.analyze("문단입니다.\n\n```js\nlet a = 1;\n```\n\n`b;` 코드를 씁니다.\n")
        self.assertEqual(a["metrics"]["G6.semicolon"]["value"], 0)


class PatternTest(unittest.TestCase):
    def setUp(self):
        self.a = L.analyze(BAD_TEXT)
        self.m = self.a["metrics"]

    def test_gates(self):
        self.assertGreaterEqual(self.m["G7.conj_comma"]["value"], 1)
        self.assertGreaterEqual(self.m["G3.source_meta"]["value"], 1)
        self.assertGreaterEqual(self.m["G8.beyond_simple"]["value"], 1)  # 제목
        self.assertGreaterEqual(self.m["G9.cliche_intro"]["value"], 1)
        self.assertGreaterEqual(self.m["G9.cliche_outro"]["value"], 1)
        self.assertGreaterEqual(self.m["G9.summary_opener"]["value"], 1)
        self.assertGreaterEqual(self.m["G6.emoji"]["value"], 1)

    def test_np_and_salience(self):
        self.assertGreaterEqual(self.m["A1.np"]["value"], 2)
        self.assertEqual(self.m["A1.np_simple"]["value"], 1)
        self.assertGreaterEqual(self.m["A3.salience"]["value"], 1)

    def test_quotes_are_masked(self):
        a = L.analyze("저자들은 “단순한 도구가 아니라 파트너”라는 문장을 예로 듭니다.")
        self.assertEqual(a["metrics"]["A1.np"]["value"], 0)
        self.assertEqual(a["metrics"]["A1.np_simple"]["value"], 0)

    def test_good_text_has_no_gate(self):
        a = L.analyze(GOOD_DEFAULT)
        for mid, m in a["metrics"].items():
            if mid.startswith(("G2", "G3", "G6", "G7", "G8", "G9")):
                self.assertEqual(m["value"], 0, (mid, m["hits"]))

    def test_emdash_label_allowed(self):
        a = L.analyze("- 1단계 — 설정을 바꿉니다.\n- 2단계 — 배포합니다.\n\n문단 안에서 — 이렇게 — 쓰면 걸립니다.\n")
        self.assertEqual(a["metrics"]["G6.emdash"]["value"], 1)

    def test_connective_comma(self):
        a = L.analyze("캐시를 붙였지만, 지연은 줄지 않았습니다. 데이터를 모으고 모델을 학습했습니다.")
        m = a["metrics"]["A2.connective_comma_ratio"]
        self.assertEqual(m["extra"]["comma"], 1)
        self.assertEqual(m["extra"]["total"], 2)

    def test_connective_noun_guard(self):
        for w in ("문서", "순서", "참고", "측면", "화면", "에서"):
            self.assertFalse(L.is_connective(w), w)
        for w in ("해서", "하고", "있으며", "하지만", "보면"):
            self.assertTrue(L.is_connective(w), w)

    def test_triad(self):
        self.assertTrue(L.is_triad("빠르고, 안정적이고, 확장 가능합니다."))
        self.assertFalse(L.is_triad("1,000건을 처리했습니다."))


class ToneTest(unittest.TestCase):
    def test_off_tone_default(self):
        a = L.analyze("첫 문장입니다. 둘째 문장이에요. 셋째 문장이다.")
        t = L.tone_metrics(a, "default")
        self.assertEqual(t["G4.off_tone"]["value"], 2)

    def test_casual_banned(self):
        a = L.analyze("써 보니 빠르더라고요. 결과가 좋네요. 정리해요.")
        t = L.tone_metrics(a, "casual")
        self.assertEqual(t["G4.banned_ending"]["value"], 2)
        self.assertEqual(a["metrics"]["G2.exp_ending"]["value"], 2)

    def test_kkayo_allowed_in_default(self):
        a = L.analyze("어떻게 해결했을까요? 저자들은 두 방법을 비교했습니다.")
        t = L.tone_metrics(a, "default")
        self.assertEqual(t["G4.off_tone"]["value"], 0)


class FactsTest(unittest.TestCase):
    def test_unknown_numbers(self):
        facts = "- 패턴 8,000개 억제\n- 슬롭 90% 감소\n- 2025년 발표"
        a = L.analyze("2025년 논문은 8,000개 패턴을 억제하고 슬롭을 90% 줄였습니다. 처리량은 69% 떨어졌습니다.",
                      facts_text=facts)
        m = a["metrics"]["A15.unknown_numbers"]
        self.assertEqual(m["value"], 1)
        self.assertEqual(m["hits"][0]["match"], "69%")


class CliTest(unittest.TestCase):
    def test_cli_runs_on_default_console(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "a.md")
            with open(p, "w", encoding="utf-8") as f:
                f.write(BAD_TEXT)
            env = dict(os.environ)
            env.pop("PYTHONUTF8", None)
            env.pop("PYTHONIOENCODING", None)
            r = subprocess.run([sys.executable, os.path.join(SCRIPTS, "lint_ko.py"), p, "--tone", "default"],
                               capture_output=True, env=env)
            self.assertEqual(r.returncode, 1)
            out = r.stdout.decode("utf-8")
            self.assertIn("판정: FAIL", out)
            self.assertIn("G7.conj_comma", out)
            r2 = subprocess.run([sys.executable, os.path.join(SCRIPTS, "lint_ko.py"), p, "--json"],
                                capture_output=True, env=env)
            data = json.loads(r2.stdout.decode("utf-8"))
            self.assertEqual(data["summary"]["verdict"], "FAIL")

    def test_missing_file_exit_2(self):
        r = subprocess.run([sys.executable, os.path.join(SCRIPTS, "lint_ko.py"), "없는파일.md"], capture_output=True)
        self.assertEqual(r.returncode, 2)


if __name__ == "__main__":
    unittest.main()
