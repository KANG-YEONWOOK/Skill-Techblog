import os
import subprocess
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPTS = os.path.join(ROOT, "skills", "techblog", "scripts")
sys.path.insert(0, SCRIPTS)

import tone_check as T  # noqa: E402

DEFAULT = """# Antislop 논문 정리

## 측정 방법

저자들은 모델 출력과 사람 글의 n-gram 빈도를 비교했습니다. 일부 패턴은 사람 글보다 1,000배 이상 자주 나왔습니다. 이렇게 비교하는 것은 빈도 차이를 수치로 보기 위해서입니다.

- 비교 기준: Reddit 창작 글
- 저자들은 금지 목록을 2단계로 나눴습니다.

## 결과

FTPO는 금지 패턴을 90% 줄였습니다. 성능 저하가 없었던 이유는 logit을 토큰 단위로 조정하기 때문입니다. 어떻게 가능했을까요?
"""

CASUAL = """# Antislop 논문 정리

## 측정 방법

저자들은 모델 출력과 사람 글의 n-gram 빈도를 비교했어요. 일부 패턴은 사람 글보다 1,000배 이상 자주 나왔어요. 이렇게 비교하는 건 빈도 차이를 수치로 보기 위해서예요.

- 비교 기준: Reddit 창작 글
- 저자들은 금지 목록을 2단계로 나눴어요.

## 결과

FTPO는 금지 패턴을 90% 줄였어요. 성능 저하가 없었던 이유는 logit을 토큰 단위로 조정하거든요. 어떻게 가능했을까요?
"""


class ToneCheckTest(unittest.TestCase):
    def codes(self, d, c):
        return [(i["code"], i["level"]) for i in T.check(d, c)["issues"]]

    def test_valid_pair(self):
        res = T.check(DEFAULT, CASUAL)
        fails = [i for i in res["issues"] if i["level"] == "FAIL"]
        self.assertEqual(fails, [], fails)
        self.assertEqual(res["pairs"], 7)

    def test_number_change(self):
        c = CASUAL.replace("90% 줄였어요", "80% 줄였어요")
        self.assertIn(("TOKEN", "FAIL"), self.codes(DEFAULT, c))

    def test_sentence_split(self):
        c = CASUAL.replace("비교했어요.", "비교했어요. 그 결과가 흥미로워요.")
        self.assertIn(("SENT_COUNT", "FAIL"), self.codes(DEFAULT, c))

    def test_middle_change(self):
        c = CASUAL.replace("일부 패턴은 사람 글보다", "어떤 패턴은 사람 글보다")
        self.assertIn(("PREFIX", "FAIL"), self.codes(DEFAULT, c))

    def test_heading_frozen(self):
        c = CASUAL.replace("## 결과", "## 결과는요")
        self.assertIn(("FROZEN", "FAIL"), self.codes(DEFAULT, c))
        c2 = CASUAL.replace("## 결과\n\n", "")
        self.assertIn(("STRUCTURE", "FAIL"), self.codes(DEFAULT, c2))

    def test_casual_tone_slip(self):
        c = CASUAL.replace("나눴어요.", "나눴습니다.")
        self.assertIn(("C_TONE", "FAIL"), self.codes(DEFAULT, c))

    def test_banned_ending(self):
        c = CASUAL.replace("자주 나왔어요.", "자주 나오더라고요.")
        self.assertIn(("BANNED", "FAIL"), self.codes(DEFAULT, c))

    def test_geudeun_without_cause(self):
        d = DEFAULT.replace("90% 줄였습니다.", "90% 줄였습니다.")
        c = CASUAL.replace("90% 줄였어요.", "90% 줄였거든요.")
        self.assertIn(("GEUDEUN", "WARN"), self.codes(d, c))

    def test_conjugation_is_not_stem_change(self):
        for d, c in (("코드를 썼습니다.", "코드를 썼어요."), ("값이 같습니다.", "값이 같아요."),
                     ("버킷을 둡니다.", "버킷을 둬요."), ("방식입니다.", "방식이에요.")):
            self.assertNotIn(("STEM", "WARN"), self.codes(d, c), (d, c))
        self.assertIn(("STEM", "WARN"), self.codes("결과가 좋습니다.", "결과가 나빠요."))

    def test_polarity(self):
        c = CASUAL.replace("성능 저하가 없었던 이유는", "성능 저하가 있었던 이유는")
        self.assertIn(("POLARITY", "FAIL"), self.codes(DEFAULT, c))

    def test_cleanup_only_work_files(self):
        with tempfile.TemporaryDirectory() as d:
            keep = os.path.join(d, "article.md")
            work = [os.path.join(d, "article" + suf) for suf in (".facts.md", ".draft.md", ".unrevised.md")]
            for p in [keep] + work:
                with open(p, "w", encoding="utf-8") as f:
                    f.write("x")
            r = subprocess.run([sys.executable, os.path.join(SCRIPTS, "tone_check.py"), "--cleanup", keep] + work,
                               capture_output=True)
            self.assertEqual(r.returncode, 0)
            self.assertTrue(os.path.exists(keep))
            for p in work:
                self.assertFalse(os.path.exists(p), p)

    def test_cli(self):
        with tempfile.TemporaryDirectory() as d:
            a, b = os.path.join(d, "a.draft.md"), os.path.join(d, "a.md")
            with open(a, "w", encoding="utf-8") as f:
                f.write(DEFAULT)
            with open(b, "w", encoding="utf-8") as f:
                f.write(CASUAL)
            env = dict(os.environ)
            env.pop("PYTHONUTF8", None)
            r = subprocess.run([sys.executable, os.path.join(SCRIPTS, "tone_check.py"), a, b], capture_output=True, env=env)
            self.assertEqual(r.returncode, 0, r.stdout.decode("utf-8"))
            self.assertIn("tone_check: PASS", r.stdout.decode("utf-8"))


if __name__ == "__main__":
    unittest.main()
