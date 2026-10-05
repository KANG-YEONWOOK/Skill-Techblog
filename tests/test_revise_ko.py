import json
import os
import subprocess
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPTS = os.path.join(ROOT, "skills", "techblog", "scripts")
sys.path.insert(0, SCRIPTS)

import revise_ko as R  # noqa: E402


TABLE_ARTICLE = """# 토큰 버킷으로 바꾼 rate limiter

## 롤아웃 전후 지표

롤아웃 전과 후의 지표는 아래 표와 같습니다.

| 지표 | 롤아웃 전 | 롤아웃 후 |
|---|---|---|
| p99 지연 | 1,850ms | 420ms |
| 거절 비율 | 2.1% | 2.6% |

거절 비율은 0.5%p 올랐습니다. Redis CPU 사용량은 8%p 늘었습니다.

p99 무효화 지연은 4.2초에서 0.8초로 줄었습니다. vLLM의 처리량은 Orca의 1.67배였습니다.

burst 때문에 gateway의 p99 latency가 1,850ms까지 올랐습니다.
"""

BASELINE_ARTICLE = """# LLM 응답으로 모델 계열 맞히기

## 분류 정확도

GPT 계열 응답의 5-way 분류 정확도는 무작위 추측 정확도 20%보다 65.5%p 높았습니다. Claude 계열은 무작위 추측 정확도 20%보다 70.1%p 높았습니다.

Gemini 계열의 분류 정확도도 무작위 추측 정확도 20%보다 60.2%p 높았습니다.

## 서빙 처리량

vLLM의 처리량은 Orca (Oracle)보다 높았습니다. 긴 프롬프트에서도 vLLM은 Orca (Oracle)보다 높았습니다.

짧은 프롬프트에서도 Orca (Oracle)보다 높았습니다. beam search에서도 Orca (Oracle)보다 높았습니다.
"""

FRAME_ARTICLE = """# 저자들의 해석

## 해석

저자들은 지연 대부분이 배치 대기에서 생긴다고 봅니다. 저자들은 처리량 손실이 쓰기 비율에 따라 커진다고 봅니다.

이 측정은 12개 서비스에서 했습니다. 저자들은 write-through 캐시에서도 같은 경향이 나올 수 있다고 봅니다.

## 동작

vLLM은 KV cache를 고정 크기의 블록 단위로 나눠서 GPU 메모리에 둡니다. vLLM은 블록 테이블로 요청마다 논리 블록과 물리 블록을 잇습니다. vLLM은 요청이 토큰을 생성해서 블록이 찰 때만 새 블록을 할당합니다.

블록 크기는 16입니다. 블록은 고정 크기입니다. 표는 GPU에 있습니다. 매핑은 CPU가 합니다.
"""


class TestHelpers(unittest.TestCase):
    def test_strip_particle(self):
        self.assertEqual(R.strip_particle("정확도는"), "정확도")
        self.assertEqual(R.strip_particle("20%보다"), "20%")
        self.assertEqual(R.strip_particle("차이"), "차이")  # 조사를 떼면 한 글자만 남는다
        self.assertEqual(R.strip_particle("서버에서는"), "서버")

    def test_paths(self):
        self.assertEqual(R.stem_of(os.path.join("x", "a.draft.md")), os.path.join("x", "a"))
        self.assertEqual(R.snapshot_path("a.md"), "a.unrevised.md")
        self.assertEqual(R.snapshot_path("a.draft.md"), "a.unrevised.md")
        self.assertEqual(R.facts_path("a.draft.md"), "a.facts.md")


class TestRepeats(unittest.TestCase):
    def ids(self, text, rid):
        return [c for c in R.find_repeats(text)["candidates"] if c["id"] == rid]

    def test_r6_change_without_baseline(self):
        texts = [c["text"] for c in self.ids(TABLE_ARTICLE, "R6")]
        self.assertIn("거절 비율은 0.5%p 올랐습니다.", texts)
        self.assertIn("Redis CPU 사용량은 8%p 늘었습니다.", texts)
        after = [c for c in self.ids(TABLE_ARTICLE, "R6") if c["text"].startswith("거절")][0]
        self.assertTrue(after["after"])  # 표 바로 뒤
        self.assertNotIn("p99 무효화 지연은 4.2초에서 0.8초로 줄었습니다.", texts)
        self.assertNotIn("vLLM의 처리량은 Orca의 1.67배였습니다.", texts)
        self.assertFalse(any("1,850ms까지" in t for t in texts))  # 바뀐 뒤의 값

    def test_r1_numeric_baseline(self):
        r1 = self.ids(BASELINE_ARTICLE, "R1")
        self.assertEqual(len(r1), 1)
        self.assertEqual(r1[0]["key"], "추측 정확도 20%")
        self.assertEqual(r1[0]["count"], 3)
        self.assertEqual(r1[0]["adjacent"], 2)

    def test_r1_ignores_named_baseline(self):
        self.assertFalse(any("oracle" in c["key"] for c in self.ids(BASELINE_ARTICLE, "R1")))

    def test_r4_frame(self):
        labels = [c["label"] for c in self.ids(FRAME_ARTICLE, "R4")]
        self.assertTrue(any("저자들은 … 봅니다" in x for x in labels), labels)

    def test_r3_same_subject(self):
        r3 = self.ids(FRAME_ARTICLE, "R3")
        self.assertTrue(any("vLLM은" in c["label"] and c["count"] == 3 for c in r3), r3)

    def test_r5_short_run(self):
        r5 = self.ids(FRAME_ARTICLE, "R5")
        self.assertTrue(any(c["count"] == 4 for c in r5), r5)

    def test_render_limits_lines(self):
        res = {"sentences": 10, "candidates": [{"id": "R5", "item": 3, "lines": [i], "label": "x", "text": "y"}
                                               for i in range(12)]}
        out = R.render_repeats("a.md", res)
        self.assertEqual(sum(1 for line in out.splitlines() if line.startswith("[R5]")), R.MAX_LINES)
        self.assertIn("+4개", out)


DRAFT = """# 토큰 버킷으로 바꾼 rate limiter

## 배경

공개 API는 클라이언트마다 60초 윈도에 600건을 허용했습니다. 윈도가 열리는 첫 1초에 최대 4,800 requests/s가 몰렸습니다.

## 결과

Redis CPU 사용량은 롤아웃 전보다 8%p 늘었습니다. 거절 비율은 2.1%에서 2.6%로 올랐습니다.
"""

FACTS = "600건, 60초, 첫 1초, 4,800 requests/s, 8 percentage points, 2.1%, 2.6%, 1,850 ms, 420 ms\n"


class TestCli(unittest.TestCase):
    def run_cli(self, *args):
        env = dict(os.environ)
        env.pop("PYTHONUTF8", None)
        r = subprocess.run([sys.executable, os.path.join(SCRIPTS, "revise_ko.py")] + list(args), capture_output=True,
                           env=env)
        return r.returncode, r.stdout.decode("utf-8"), r.stderr.decode("utf-8")

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.art = os.path.join(self.tmp.name, "article.md")
        with open(self.art, "w", encoding="utf-8") as f:
            f.write(DRAFT)
        with open(os.path.join(self.tmp.name, "article.facts.md"), "w", encoding="utf-8") as f:
            f.write(FACTS)

    def tearDown(self):
        self.tmp.cleanup()

    def write(self, text):
        with open(self.art, "w", encoding="utf-8") as f:
            f.write(text)

    def test_start_refuses_overwrite(self):
        code, out, _ = self.run_cli("start", self.art)
        self.assertEqual(code, 0, out)
        self.assertTrue(os.path.exists(os.path.join(self.tmp.name, "article.unrevised.md")))
        code, _, err = self.run_cli("start", self.art)
        self.assertEqual(code, 2)
        self.assertIn("--force", err)
        self.assertEqual(self.run_cli("start", self.art, "--force")[0], 0)

    def test_check_requires_snapshot(self):
        code, _, err = self.run_cli("check", self.art)
        self.assertEqual(code, 2)
        self.assertIn("start", err)

    def test_check_reports_lost_and_new_numbers(self):
        self.run_cli("start", self.art)
        self.write(DRAFT.replace(" Redis CPU 사용량은 롤아웃 전보다 8%p 늘었습니다.", "")
                   .replace("Redis CPU 사용량은 롤아웃 전보다 8%p 늘었습니다. ", "")
                   + "\np99 지연은 1,850ms에서 420ms로 줄었고 평균 지연은 120ms였습니다.\n")
        code, out, _ = self.run_cli("check", self.art, "--json")
        res = json.loads(out)
        self.assertIn("8", [x["value"] for x in res["lost_numbers"]])
        new = {x["value"]: x["in_facts"] for x in res["new_numbers"]}
        self.assertTrue(new["1850"])
        self.assertFalse(new["120"])
        self.assertEqual(code, 1)  # fact sheet에 없는 120ms는 A15 FAIL

    def test_check_flags_ai_pattern_and_long_sentence(self):
        self.run_cli("start", self.art)
        self.write(DRAFT + "\n이 설계는 단순한 rate limiter를 넘어 트래픽을 고르게 만드는 장치이고 요청을 나누며 재시도를 늦추고 "
                           "부하를 줄입니다.\n")
        code, out, _ = self.run_cli("check", self.art)
        self.assertEqual(code, 1)
        self.assertIn("G8.beyond_simple", out)
        self.assertIn("연결어미가 3개 이상인 새 문장 1개", out)

    def test_check_passes_clean_edit(self):
        self.run_cli("start", self.art)
        self.write(DRAFT.replace("Redis CPU 사용량은 롤아웃 전보다 8%p 늘었습니다.", "Redis CPU 사용량은 8%p 늘었습니다."))
        code, out, _ = self.run_cli("check", self.art)
        self.assertEqual(code, 0, out)
        self.assertIn("1문장 고치거나 지움", out)
        self.assertIn("판정: 고칠 항목 없음", out)

    def test_rejects_work_file_argument(self):
        code, _, err = self.run_cli("repeats", os.path.join(self.tmp.name, "article.facts.md"))
        self.assertEqual(code, 2)


if __name__ == "__main__":
    unittest.main()
