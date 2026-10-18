"""dev/dogfood/judge.py의 terms 단계(J10, 0.9.0): 점수 계산, 인용 확인, 두 실행의 겹침."""
import importlib.util
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("dogfood_judge", ROOT / "dev/dogfood/judge.py")
judge = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(judge)

ARTICLE = """# STG의 두 리듬

STG(stomatogastric ganglion, 위장 신경절)는 갑각류의 위를 움직이는 뉴런 약 30개의 모임입니다.

STG는 pyloric 리듬과 gastric mill 리듬을 만듭니다. pyloric 리듬은 위의 출구인 유문 쪽 근육을 움직여 먹이를 거릅니다.

망막에는 수평 세포, 양극 세포, amacrine 세포가 있습니다. amacrine 세포는 신호를 옆으로 전합니다.
"""


def term(name, quote, expl="", missing=()):
    return {"term": name, "first_quote": quote, "explanation_quote": expl, "missing": list(missing)}


CENTRAL = {"subject": "STG", "defined_in_one_place": True,
           "quote": "STG(stomatogastric ganglion, 위장 신경절)는 갑각류의 위를 움직이는 뉴런 약 30개의 모임입니다."}


class TermsScoreTest(unittest.TestCase):
    def test_score_follows_rubric_counts(self):
        self.assertEqual(judge.j10_score(0, True), 2)
        self.assertEqual(judge.j10_score(1, True), 1)
        self.assertEqual(judge.j10_score(2, True), 1)
        self.assertEqual(judge.j10_score(3, True), 0)
        self.assertEqual(judge.j10_score(0, False), 0)

    def test_terms_without_quote_in_article_are_dropped(self):
        res = {"central": CENTRAL, "terms": [
            term("pyloric 리듬", "STG는 pyloric 리듬과 gastric mill 리듬을 만듭니다.",
                 "위의 출구인 유문 쪽 근육을 움직여 먹이를 거릅니다"),
            term("gastric mill 리듬", "STG는 pyloric 리듬과 gastric mill 리듬을 만듭니다.", "", ["what", "does", "name"]),
            term("amacrine 세포", "망막에는 수평 세포, 양극 세포, amacrine 세포가 있습니다.",
                 "신호를 옆으로 전합니다", ["what", "list_only"]),
            term("starburst amacrine 세포", "starburst amacrine 세포는 방향을 가립니다.", "", ["what"])]}
        s = judge.terms_summary(res, ARTICLE)
        self.assertEqual((s["terms"], s["invalid_quotes"], s["missing"]), (3, 1, 2))
        self.assertEqual(s["j10"], 1)
        self.assertEqual(s["by_missing"]["list_only"], 1)
        self.assertEqual([t["term"] for t in s["missing_terms"]], ["gastric mill 리듬", "amacrine 세포"])

    def test_explanation_quote_is_checked(self):
        res = {"central": CENTRAL, "terms": [
            term("pyloric 리듬", "STG는 pyloric 리듬과 gastric mill 리듬을 만듭니다.", "유문을 여닫는 리듬")]}
        self.assertEqual(judge.terms_summary(res, ARTICLE)["invalid_explanations"], 1)

    def test_agreement_uses_terms_both_runs_flagged(self):
        runs = [{"missing_terms": [{"term": "pyloric 리듬"}, {"term": "amacrine 세포"}]},
                {"missing_terms": [{"term": "Pyloric  리듬"}, {"term": "STG"}]}]
        agree = judge.terms_agreement(runs)
        self.assertEqual(agree["both"], ["pyloric 리듬"])
        self.assertEqual(agree["jaccard"], round(1 / 3, 3))
        self.assertEqual(judge.terms_agreement([{"missing_terms": []}, {"missing_terms": []}])["jaccard"], 1.0)

    def test_judge_terms_runs_twice_and_scores_the_intersection(self):
        answers = [
            {"central": CENTRAL, "terms": [
                term("gastric mill 리듬", "STG는 pyloric 리듬과 gastric mill 리듬을 만듭니다.", "", ["what"]),
                term("amacrine 세포", "망막에는 수평 세포, 양극 세포, amacrine 세포가 있습니다.", "", ["list_only"]),
                term("양극 세포", "망막에는 수평 세포, 양극 세포, amacrine 세포가 있습니다.", "", ["what"])],
             "_cost": 0.5},
            {"central": CENTRAL, "terms": [
                term("gastric mill 리듬", "STG는 pyloric 리듬과 gastric mill 리듬을 만듭니다.", "", ["name"])],
             "_cost": 0.25}]
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "article.md")
            Path(path).write_text(ARTICLE, encoding="utf-8")
            with patch.object(judge, "call_judge", side_effect=answers) as called:
                out = judge.judge_terms(path, os.path.join(tmp, "judge"), "sonnet")
            self.assertEqual(called.call_count, 2)
            self.assertTrue(os.path.isfile(os.path.join(tmp, "judge", "run1", "result.json")))
        self.assertEqual(out["j10"], [0, 1])
        self.assertEqual(out["agreement"]["both"], ["gastric mill 리듬"])
        self.assertEqual(out["j10_both"], 1)
        self.assertEqual(out["cost"], 0.75)

    def test_prompts_do_not_assume_a_developer_reader(self):
        for name in ("STYLE_PROMPT", "PAIR_PROMPT", "SECTION_PROMPT", "CLARITY_PROMPT", "KOREAN_PROMPT", "TERMS_PROMPT"):
            self.assertNotIn("개발자", getattr(judge, name), name)
        self.assertIn("R", judge.KOREAN_TYPES)
        self.assertNotIn("M", judge.KOREAN_TYPES)
        self.assertNotIn("J10", judge.STYLE_SCHEMA["properties"]["texts"]["items"]["required"])

    def test_human_cache_option_sets_the_article_path(self):
        try:
            judge.HUMAN_CACHE = os.path.join("x", "human")
            self.assertEqual(judge.human_md("work", "kakao-1"), os.path.join("x", "human", "md", "kakao-1.md"))
            judge.HUMAN_CACHE = None
            self.assertEqual(judge.human_md("work", "kakao-1"),
                             os.path.join("work", "baseline", "cache", "md", "kakao-1.md"))
        finally:
            judge.HUMAN_CACHE = None


if __name__ == "__main__":
    unittest.main()
