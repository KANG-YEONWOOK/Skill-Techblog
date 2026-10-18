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
        self.assertGreaterEqual(self.m["A4.summary_opener"]["value"], 1)
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
            if mid.startswith(("G2", "G3", "G6", "G7", "G8", "G9", "A4.summary_opener")):
                self.assertEqual(m["value"], 0, (mid, m["hits"]))

    def test_emdash_policy_includes_labels(self):
        # 0.6.0부터 라벨 구분자의 em dash도 Gate다. 라벨은 콜론으로 쓴다.
        a = L.analyze("- 1단계 — 설정을 바꿉니다.\n- 2단계: 배포합니다.\n\n문단 안에서 — 이렇게 — 쓰면 걸립니다.\n")
        self.assertEqual(a["metrics"]["G6.emdash"]["value"], 3)

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

    def test_must_may(self):
        a = L.analyze("모델이 바뀌면 분류기를 다시 학습해야 할 수 있습니다. 설정을 바꿔야 할 수도 있어요. "
                      "다시 학습이 필요할 수 있습니다. 모델이 바뀌면 다시 학습해야 합니다.")
        self.assertEqual(a["metrics"]["A7.must_may"]["value"], 2)

    def test_read_as(self):
        a = L.analyze("표에서 지연 대부분이 배치 대기에서 생긴다고 읽을 수 있습니다. 이 평가는 차이에서 나온 것으로 읽힙니다. "
                      "로그를 읽을 수 있습니다. 표의 측정값대로라면 지연의 72%는 배치 대기에서 생깁니다.")
        self.assertEqual(a["metrics"]["A7.read_as"]["value"], 2)

    def test_a18_check_candidates(self):
        text = ("무효화 메시지의 배치 크기를 10으로 줄인 설정에서 12개 서비스의 p99 무효화 지연은 0.8초였습니다. "
                "기존 설정과 비교하면 최대 5배입니다.\n\n"
                "OPT-13B로 잰 결과입니다.\n\n"
                "차이는 배치 대기에서 나옵니다.\n\n"
                "측정 대상(write-back 캐시만 해당, 12개 서비스)은 로그로 골랐습니다. 입력/출력 길이를 따로 쟀습니다.\n\n"
                "지연의 72%는 배치 대기 시간이었습니다. 요청 수만큼 스레드를 띄웠습니다.\n")
        m = L.analyze(text)["metrics"]
        self.assertEqual(m["A18.number_predicate"]["value"], 1)  # 45자를 넘는 첫 문장은 후보에서 빠진다
        self.assertEqual(m["A18.generic_predicate"]["value"], 1)
        self.assertEqual(m["A18.bare_reference"]["value"], 1)
        self.assertEqual(m["A18.paren_clause"]["value"], 1)
        self.assertEqual(m["A18.bundle"]["value"], 1)

    def test_a7_see_as(self):
        text = ("표에서 지연 대부분이 배치 대기에서 생긴다고 볼 수 있습니다. "
                "이 설정이 처리량을 낮췄다고 볼 수 있어요. "
                "그래프에서 p99 지연이 줄어든 결과를 볼 수 있습니다.\n")
        m = L.analyze(text)["metrics"]
        self.assertEqual(m["A7.see_as"]["value"], 2)  # "결과를 볼 수 있습니다"는 추론 표지가 아니다

    def test_a16_source_subject(self):
        text = ("원문은 배치 크기를 10으로 줄였다고 씁니다. 논문은 지연을 쟀습니다. 저자들은 원인을 추정합니다. "
                "원문 그대로 옮기면 메시지가 늦게 도착합니다. 배치 크기를 10으로 줄인 설정에서 p99 지연은 0.8초였습니다.\n")
        m = L.analyze(text)["metrics"]
        self.assertEqual(m["A16.source_subject_share"]["extra"]["count"], 3)

    def test_check_status_not_in_verdict(self):
        text = "\n\n".join(["기존 설정과 비교하면 최대 5배입니다.", "입력/출력 길이를 따로 측정했습니다."] * 3)
        a = L.analyze(text)
        ev = L.evaluate(a, L.load_json(L.THRESHOLDS_PATH), "default")
        st = {r["id"]: r["status"] for r in ev["results"]}
        self.assertEqual(st["A18.number_predicate"], "CHECK")
        self.assertEqual(st["A18.bundle"], "INFO")  # 사람 글과 비율이 비슷한 후보는 참고 지표로만 센다
        self.assertEqual(ev["summary"]["fail"] + ev["summary"]["gate_fail"], 0)
        self.assertIn("단독 읽기 점검 후보", L.render_text("x.md", "default", a, ev))

    def test_single_para_ratio_lower_bound(self):
        dense = "\n\n".join("첫 문장입니다. 둘째 문장입니다. 셋째 문장입니다. 넷째 문장입니다." for _ in range(5))
        short = "\n\n".join(["첫 문장입니다. 둘째 문장입니다.", "한 문장 문단입니다."] * 3)
        th = L.load_json(L.THRESHOLDS_PATH)["metrics"]["A8.single_para_ratio"]
        self.assertEqual(th["kind"], "lower")
        v_dense = L.analyze(dense)["metrics"]["A8.single_para_ratio"]["value"]
        v_short = L.analyze(short)["metrics"]["A8.single_para_ratio"]["value"]
        self.assertEqual(L.judge(v_dense, th, 2000)[0], "FAIL")
        self.assertEqual(L.judge(v_short, th, 2000)[0], "PASS")

    def test_triad(self):
        self.assertTrue(L.is_triad("빠르고, 안정적이고, 확장 가능합니다."))
        self.assertFalse(L.is_triad("1,000건을 처리했습니다."))
        self.assertFalse(L.is_triad("정확도는 각각 20%, 25%, 25%입니다."))
        self.assertFalse(L.is_triad("논문은 이들을 ChatGPT, Claude, Grok으로 부릅니다."))


class PunctPolicyTest(unittest.TestCase):
    """문장 부호 정책(G6): 사용자 검토에서 가운뎃점, em dash, en dash, 빼기 기호를 쓰지 않기로 정했다."""

    def m(self, text):
        return L.analyze(text)["metrics"]

    def test_policy_chars_in_body_heading_table(self):
        text = ("# 결과 — 요약\n\nPD·LP·PY 뉴런은 Morris–Lecar 모델로 씁니다. 막전위는 −52 mV입니다.\n\n"
                "| 지표 | 범위 |\n|---|---|\n| 적분 기간 | 12–24시간 |\n\n> 인용 — 문장입니다.\n")
        m = self.m(text)
        self.assertEqual(m["G6.emdash"]["value"], 2)  # 헤딩, 인용
        self.assertEqual(m["G6.punct_policy"]["value"], 5)  # 가운뎃점 2, en dash 2, 빼기 기호 1

    def test_spaced_hyphen_label_is_emdash(self):
        m = self.m("1단계 - 설정을 바꿉니다. 값은 n - 1입니다. Morris-Lecar 모델을 씁니다.\n")
        self.assertEqual(m["G6.emdash"]["value"], 1)
        self.assertEqual(m["G6.punct_policy"]["value"], 0)

    def test_code_math_url_are_excluded(self):
        text = ("코드는 `a — b · c`로 씁니다. 식 $x−1$을 봅니다. 링크는 [자료](https://example.com/a–b)입니다.\n\n"
                "```\nx = a — b\n```\n\n가격은 $5에서 $10으로 올랐습니다.\n")
        m = self.m(text)
        self.assertEqual(m["G6.emdash"]["value"], 0)
        self.assertEqual(m["G6.punct_policy"]["value"], 0)

    def test_references_only_page_ranges(self):
        text = "본문입니다.\n\n## 참고자료\n\n- [1] Kim, Title — Subtitle (2025), pp. 1016–1054.\n"
        m = self.m(text)
        self.assertEqual(m["G6.emdash"]["value"], 0)
        self.assertEqual(m["G6.punct_policy"]["value"], 1)

    def test_reference_heading_must_be_whole_heading(self):
        # "데이터 출처와 전처리"는 본문 절이다. 예전 정규식은 이 헤딩 뒤의 em dash를 세지 않았다.
        for heading in ("참고자료", "참고 자료", "References", "출처", "더 읽을 거리", "참고 자료 및 링크"):
            self.assertTrue(L.REF_HEADING_RE.search(heading), heading)
        for heading in ("데이터 출처와 전처리", "참고할 설정", "출처를 밝히지 않은 수치"):
            self.assertFalse(L.REF_HEADING_RE.search(heading), heading)
        m = self.m("## 데이터 출처와 전처리\n\n수집은 — 이렇게 — 했습니다.\n")
        self.assertEqual(m["G6.emdash"]["value"], 2)


class NumParticleTest(unittest.TestCase):
    """숫자 뒤 조사(G10). 사례는 사용자 검토에서 나온 interactive component 출력이다."""

    def hits(self, text):
        return [h["match"] for h in L.analyze(text)["metrics"]["G10.num_particle"]["hits"]]

    def test_review_cases(self):
        self.assertEqual(len(self.hits("최댓값은 0.7717예요.")), 1)
        self.assertEqual(len(self.hits("diffusive에서 0.120예요.")), 1)
        self.assertEqual(len(self.hits("현재 표본의 상관은 0.512이에요.")), 1)
        self.assertEqual(self.hits("값은 0.7717였습니다."), ["0.7717였 → 0.7717이었"])
        self.assertEqual(self.hits("7으로 나눕니다."), ["7으로 → 7로"])

    def test_correct_or_skipped(self):
        for text in ("값을 10으로 바꿨습니다.", "지연은 3초예요.", "2,000개가 있습니다.", "GPT-3은 컸습니다.",
                     "Llama 3은 컸습니다.", "Windows 11은 무겁습니다.", "비율은 15%예요.", "1로 나눕니다.",
                     "값은 3이었습니다.", "값은 0.5이었습니다.", "HTTP/3는 빠릅니다.", "포트 8080을 씁니다.",
                     "식 $x=2$를 씁니다."):
            self.assertEqual(self.hits(text), [], text)

    def test_percent_and_heading(self):
        self.assertEqual(len(self.hits("비율은 15%이에요.")), 1)
        self.assertEqual(len(self.hits("# 1,400으로 줄인 방법\n\n본문입니다.\n")), 0)
        self.assertEqual(len(self.hits("# 1,400로 줄인 방법\n\n본문입니다.\n")), 1)


class KoreanPatternTest(unittest.TestCase):
    """사용자 검토에서 고친 문장(신경과학 학습 노트)과 고치지 않기로 한 표현(과교정 예외)."""

    def m(self, text, facts=None):
        return L.analyze(text, facts_text=facts)["metrics"]

    def test_window_range(self):
        for text in ("추정한 적분 창 길이를 씁니다.", "STDP의 20 ms 시간 창을 봅니다.", "TANGO의 적분창은 깁니다.",
                     "고정 창 방식의 rate limiter를 씁니다.", "20 ms 창 안에서 셉니다.", "적분 창으로 보면 깁니다."):
            self.assertEqual(self.m(text)["A6.window_range"]["value"], 1, text)
        for text in ("검색창에 입력합니다.", "시간 창고에 둡니다.", "분석 창구를 엽니다.", "브라우저 창이 열립니다.",
                     "새 창을 열면 됩니다.", "fixed window를 씁니다.", "학습 창의성을 봅니다.", "비교 기준은 Reddit 창작 글입니다."):
            self.assertEqual(self.m(text)["A6.window_range"]["value"], 0, text)

    def test_window_range_in_heading_and_table(self):
        m = self.m("# 적분 창 정리\n\n| 지표 | 값 |\n|---|---|\n| 시간 창 | 20 ms |\n\n본문입니다.\n")
        self.assertEqual(m["A6.window_range"]["value"], 2)

    def test_quoted_english_token(self):
        for text in ('Inagaki 2012가 "likely"로 쓴 추정입니다.', '13개 뉴런은 "suggest"로 쓴 추정입니다.',
                     '"over"로 적은 하한입니다.', "저자들은 이 효과를 'strong'으로 표현했습니다."):
            self.assertEqual(self.m(text)["A14.quoted_english_token"]["value"], 1, text)
        for text in ('원문은 "the three S\'s"입니다.', '저자들은 이를 "the three S\'s"라고 부릅니다.',
                     '"slow" modulatory 반응입니다.', '상태가 "RUNNING"으로 바뀌면 다시 시도합니다.',
                     '로그에 "timeout"으로 적힌 요청을 셉니다.', '원문은 "This is likely"라고 씁니다.'):
            self.assertEqual(self.m(text)["A14.quoted_english_token"]["value"], 0, text)

    def test_quoted_english_check(self):
        m = self.m('뉴런이 "overconnected"로 보일 것입니다. 원문의 목록이 "etc."로 끝나므로 다 적지 않았습니다.')
        self.assertEqual(m["A14.quoted_english_check"]["value"], 2)

    def test_archaic_and_calque(self):
        m = self.m("diffusive의 옛 진폭 값은 수치적으로 거의 0입니다. additive에는 큰 변화가 남아 있습니다. "
                   "FC를 손으로 다시 계산할 때는 시간이 걸립니다.")
        self.assertEqual(m["A5.archaic_words"]["value"], 1)
        self.assertEqual(m["A6.calque_check"]["value"], 2)
        m = self.m("notebook에 출력이 남아 있습니다. 문제가 남아 있습니다. 수치적으로 안정적인 softmax를 씁니다. 옛날 방식입니다.")
        self.assertEqual(m["A5.archaic_words"]["value"], 0)
        self.assertEqual(m["A6.calque_check"]["value"], 0)

    def test_negation_scope(self):
        for text in ("모든 영역이 한 값에 머물지 않았습니다.", "80개 영역이 모두 한 값에 머물지 않았습니다."):
            self.assertEqual(self.m(text)["A18.negation_scope"]["value"], 1, text)
        for text in ("선점한 시퀀스가 모두 끝날 때까지 새 요청을 받지 않습니다.",
                     "블록을 전부 내보내거나 하나도 내보내지 않습니다.", "모든 테스트가 통과하지는 않았습니다.",
                     "80개 영역이 모두 한 값에 머문 상태는 아니었습니다.",
                     "인접 행렬은 모든 쌍에 칸을 두지만 모든 쌍이 이어졌다고 가정하지 않습니다.",
                     "모든 셀을 다시 실행하지 않았다면 출력은 이전 결과일 수 있습니다."):
            self.assertEqual(self.m(text)["A18.negation_scope"]["value"], 0, text)

    def test_term_mix(self):
        # 사용자 검토의 7편: 제목은 retina, 본문은 첫 등장의 retina(망막) 뒤로 망막을 썼다.
        m = self.m("# retina와 회로\n\nretina(망막)는 빛을 받습니다. 망막의 회로는 작습니다.\n")
        self.assertEqual(m["A19.term_mix"]["value"], 1)
        m = self.m("호르몬(hormone)이 퍼집니다. 이 hormone은 혈액으로 갑니다. 호르몬이 다시 줄어듭니다.")
        self.assertEqual(m["A19.term_mix"]["value"], 1)
        for text in ("다중 버전 동시성 제어(MVCC)를 씁니다. MVCC는 버전을 남깁니다.",
                     "망막(retina)은 빛을 받습니다. 망막의 회로는 작습니다.",
                     "캐시(cache)를 씁니다. 캐시를 KV cache와 비교합니다.",
                     "attention(주의를 기울이는) 연산을 씁니다. attention은 비쌉니다.",
                     "excitability(흥분성)를 잽니다. excitability가 높습니다. 흥분성 뉴런은 따로 셉니다.",
                     "시냅스 밖에서도(extrasynaptic) 퍼집니다. extrasynaptic 신호와 시냅스를 비교합니다."):
            self.assertEqual(self.m(text)["A19.term_mix"]["value"], 0, text)

    def test_term_avoid_from_fact_sheet(self):
        facts = ("## 용어\n\n| 원어 | 글에 쓸 표기 | 근거 | 쓰지 않을 표기 |\n|---|---|---|---|\n"
                 "| retina | 망막 | 의학 교과서 표기 | retina |\n| reporter gene | reporter | 원어로 씀 | 보고자 |\n")
        self.assertEqual(L.avoid_terms(facts), ["retina", "보고자"])
        m = self.m("망막(retina)은 빛을 받습니다. 보고자 유전자를 넣었습니다. retina 신호가 갑니다.", facts)
        self.assertEqual(m["A19.term_avoid"]["value"], 2)
        self.assertNotIn("A19.term_avoid", self.m("보고자 유전자를 넣었습니다."))

    def test_term_table_with_description_column(self):
        # 0.8.0: 용어 표에 "처음 나올 때 설명" 열을 더해도 A19.term_avoid는 "쓰지 않을" 열만 읽는다.
        facts = ("| 원어 | 글에 쓸 표기 | 근거 | 쓰지 않을 표기 | 처음 나올 때 설명(근거) |\n|---|---|---|---|---|\n"
                 "| lease | lease | 원어로 씀 | 임대 | 캐시 노드가 정해진 시간 동안 값을 바꿀 수 있는 권한(자료 2쪽) |\n"
                 "| service | 서비스 | 일상에서 쓰는 말 | - | 설명하지 않음(일상어) |\n"
                 "| C. elegans | C. elegans(예쁜꼬마선충) | 교과서 이름 | 선충 | 흙에 사는 아주 작은 벌레(범주 설명) |\n")
        self.assertEqual(L.avoid_terms(facts), ["임대", "선충"])
        self.assertEqual(L.described_terms(facts), ["lease", "C. elegans"])
        m = self.m("캐시 노드는 lease(임대)를 받습니다. lease가 끝나면 값을 바꾸지 못합니다. "
                   "서비스는 12개입니다. C. elegans(예쁜꼬마선충)는 작습니다.", facts)
        self.assertEqual([h["match"] for h in m["A20.term_first"]["hits"]], ["lease", "C. elegans"])
        self.assertEqual(m["A19.term_avoid"]["value"], 0)
        self.assertNotIn("A20.term_first", self.m("lease가 끝납니다."))

    def test_species_first(self):
        # 사용자 검토 1편: "C. elegans라는 선충"은 이름과 범주만 쓰고 무엇인지 설명하지 않았다.
        m = self.m("C. elegans라는 선충의 신경계에는 뉴런이 302개 있습니다. C. elegans는 작습니다.\n\n"
                   "게 *Cancer borealis*의 STG를 봅니다. _Homarus americanus_에서도 잽니다. *In vivo* 실험입니다.\n")
        self.assertEqual([h["match"] for h in m["A20.species_first"]["hits"]],
                         ["C. elegans", "Cancer borealis", "Homarus americanus"])
        for text in ("U.S. 시장을 봅니다.", "J. Nagumo가 회로를 만들었습니다.", "Fig. 5C를 봅니다.", "e.g. 캐시",
                     "_M.call()을 부릅니다.", "R.id 값을 씁니다."):
            self.assertEqual(self.m(text)["A20.species_first"]["value"], 0, text)

    def test_abbr_first(self):
        m = self.m("STG는 신경절입니다. STG에는 뉴런이 있습니다. STG는 리듬을 만듭니다.")
        self.assertEqual([h["match"] for h in m["A20.abbr_first"]["hits"]], ["STG"])
        # 0.9.0: 독자를 개발자로 가정하지 않으므로 API 같은 분야 약어도 후보에 오른다.
        m = self.m("API를 부릅니다. API는 빠릅니다. API도 느려집니다.")
        self.assertEqual([h["match"] for h in m["A20.abbr_first"]["hits"]], ["API"])
        for text in ("STG(stomatogastric ganglion)는 신경절입니다. STG는 작습니다. STG에는 뉴런이 있습니다.",
                     "stomatogastric ganglion(STG)은 신경절입니다. STG는 작습니다. STG에는 뉴런이 있습니다.",
                     "STG는 신경절입니다. STG는 작습니다.",
                     "PDF를 엽니다. PDF는 작습니다. PDF도 큽니다.",
                     "메모리는 8 GB입니다. 디스크는 4 GB입니다. 캐시는 16 GB입니다.",
                     "WHERE 절을 씁니다. WHERE 조건이 없습니다. WHERE를 지웁니다.",
                     "K1 키가 있습니다. K1 뒤에 둡니다. K1을 지웁니다."):
            self.assertEqual(self.m(text)["A20.abbr_first"]["value"], 0, text)

    TERM_HEADER = "| 원어 | 글에 쓸 표기 | 근거 | 쓰지 않을 표기 | 처음 나올 때 설명(근거) |\n|---|---|---|---|---|\n"

    def test_term_table_split_and_combined_rows(self):
        # 0.8.0 실행의 fact sheet는 "수평 세포 / 양극 세포 / amacrine 세포"를 한 행에 묶어서 lint가 세 용어를 찾지 못했다.
        facts = (self.TERM_HEADER +
                 "| horizontal / bipolar / amacrine cell | 수평 세포 / 양극 세포 / amacrine 세포 | 교과서 | - | 망막 뉴런 부류(자료 6쪽) |\n"
                 "| spike | 스파이크 | 교과서 | - | 뉴런이 내는 짧은 전기 신호(자료 2쪽) |\n\n"
                 "| 원문 | 원문 낱말 | 글에 쓸 표현 |\n|---|---|---|\n| likely / may | likely | 가능성이 높다 / 수 있다 |\n")
        self.assertEqual(L.described_terms(facts), ["수평 세포", "양극 세포", "amacrine 세포", "스파이크"])
        hits = L.combined_row_hits(facts)
        self.assertEqual([(h["line"], h["match"]) for h in hits], [(0, "수평 세포 / 양극 세포 / amacrine 세포")])
        a = L.analyze("양극 세포가 있습니다.\n", facts_text=facts)
        ev = L.evaluate(a, L.load_json(L.THRESHOLDS_PATH), "default")
        self.assertIn("fact sheet «수평 세포 / 양극 세포 / amacrine 세포»", L.render_text("x.md", "default", a, ev))

    def test_term_first_lists_every_first_appearance(self):
        # 0.8.0은 앞쪽 용어 몇 개만 보여 줘서 뒤 절의 용어(pyloric 리듬, amacrine 세포)가 점검 목록에 오르지 않았다.
        names = ["가지돌기", "축삭", "신경절", "시냅스", "막전위", "수용체", "도파민", "활동전위", "억제성", "흥분성",
                 "교세포", "척수"]
        facts = self.TERM_HEADER + "".join(f"| x{i} | {n} | 교과서 | - | 설명 {i}(자료 1쪽) |\n" for i, n in enumerate(names))
        a = L.analyze("\n\n".join(f"{n}이 있습니다." for n in names) + "\n", facts_text=facts)
        self.assertEqual(a["metrics"]["A20.term_first"]["value"], 12)
        ev = L.evaluate(a, L.load_json(L.THRESHOLDS_PATH), "default")
        r = next(r for r in ev["results"] if r["id"] == "A20.term_first")
        self.assertEqual((len(r["hits"]), len(r["more"])), (5, 7))
        out = L.render_text("x.md", "default", a, ev)
        self.assertIn("나머지 7곳", out)
        self.assertIn("«척수»", out)
        # 같은 문장에 처음 나온 용어는 한 줄로 묶는다. 다른 영어 낱말에 붙은 자리는 세지 않는다.
        facts2 = (self.TERM_HEADER + "| a | amacrine 세포 | 교과서 | - | 망막 뉴런(자료 6쪽) |\n"
                  "| b | 양극 세포 | 교과서 | - | 망막 뉴런(자료 6쪽) |\n")
        m = self.m("starburst amacrine 세포가 있습니다. 양극 세포와 amacrine 세포가 있습니다.", facts2)
        self.assertEqual([h["match"] for h in m["A20.term_first"]["hits"]], ["amacrine 세포, 양극 세포"])

    def test_term_in_list(self):
        listed = ("망막에는 광수용 세포, 수평 세포, 양극 세포, amacrine 세포, 망막 신경절 세포가 있습니다. "
                  "광수용 세포는 빛을 받습니다.\n\n망막 신경절 세포는 신호를 뇌로 보냅니다.\n\n"
                  "amacrine 세포는 넓게 퍼진 가지로 신호를 바꿉니다. starburst amacrine 세포는 움직임을 감지합니다.\n")
        hits = self.m(listed)["A20.term_in_list"]["hits"]
        self.assertEqual([h["match"].split(":")[0] for h in hits], ["amacrine"])
        facts = self.TERM_HEADER + "| amacrine cell | amacrine 세포 | 원어로 씀 | - | 망막 뉴런(자료 6쪽) |\n"
        hits = self.m(listed, facts)["A20.term_in_list"]["hits"]
        self.assertEqual([h["match"].split(":")[0] for h in hits], ["amacrine 세포"])
        self.assertIn("목록 L1, 혼자 L5", hits[0]["match"])
        for text in (
                # 나열 바로 다음 문장에서 설명한다
                "망막에는 광수용 세포, 수평 세포, amacrine 세포, 망막 신경절 세포가 있습니다. "
                "amacrine 세포는 신호를 조절합니다.\n\namacrine 세포는 넓게 퍼집니다.\n",
                # 꾸미는 말이 붙은 항목
                "이 실험은 접촉을 감지하는 기계감각 뉴런, 신호를 전달하는 interneuron, 운동 뉴런을 찾았습니다.\n\n"
                "다른 실험도 있습니다.\n\ninterneuron은 신호를 모읍니다. interneuron이 끊기면 반응이 사라집니다.\n"):
            self.assertEqual(self.m(text, facts)["A20.term_in_list"]["value"], 0, text)

    def test_untabled(self):
        facts = (self.TERM_HEADER +
                 "| gap junction | gap junction | 원어로 씀 | 간극 연접 | 두 뉴런을 잇는 통로(자료 2쪽) |\n"
                 "| burst / spike | burst / spike | 원어로 씀 | - | 몰아서 내는 신호(자료 3쪽) |\n")
        text = ("Inagaki 등(2012)의 TANGO-mapping은 수용체를 봅니다. TANGO-mapping은 느립니다. "
                "gap junction이 있습니다. gap junction이 닫힙니다. burst가 납니다. burst가 멈춥니다. "
                "Bargmann과 Marder(2013)는 회로를 다룹니다. C. elegans(예쁜꼬마선충)는 작습니다. C. elegans는 흙에 삽니다. "
                "`pip install`을 합니다. `pip install`을 다시 합니다. Nature Methods에 실렸습니다. Nature Methods는 학술지입니다. "
                "interneuron PVC가 있습니다.\n\n"
                "## 참고자료\n\n[1] Inagaki, H.K. et al., Visualizing neuromodulation in vivo: TANGO-mapping (2012). Nature Methods.\n")
        self.assertEqual([h["match"] for h in self.m(text, facts)["A20.untabled"]["hits"]], ["tango-mapping"])
        self.assertNotIn("A20.untabled", self.m(text))

    def test_general_knowledge_numbers_do_not_count_for_a15(self):
        # 용어 표의 일반 지식 설명(사전, 교과서)에는 수치를 쓰지 않는다. 그 칸의 수치는 자료의 수치로 치지 않는다.
        facts = (self.TERM_HEADER +
                 "| pylorus | 유문 | 표준국어대사전 | - | 위와 십이지장이 이어지는 부분, 길이 35mm(일반 지식: 표준국어대사전) |\n\n"
                 "- STG에는 뉴런 27개가 있다(자료 2쪽).\n")
        m = self.m("STG에는 뉴런 27개가 있습니다. 유문의 길이는 35mm입니다.", facts)
        self.assertEqual(m["A15.unknown_numbers"]["value"], 1)
        self.assertNotIn("27", [h["match"] for h in m["A15.unknown_numbers"]["hits"]])

    def test_term_checks_render_in_own_group(self):
        a = L.analyze("C. elegans라는 선충입니다.\n")
        ev = L.evaluate(a, L.load_json(L.THRESHOLDS_PATH), "default")
        st = {r["id"]: r for r in ev["results"]}
        self.assertEqual(st["A20.species_first"]["status"], "CHECK")
        self.assertEqual(st["A20.species_first"]["group"], "term")
        out = L.render_text("x.md", "default", a, ev)
        self.assertIn("용어 설명 점검 후보", out)
        self.assertNotIn("단독 읽기 점검 후보", out)

    def test_report_write(self):
        # 사용자 검토 2편 190줄: "저자들은 결론에서 "..."고 써요"를 "...라고 말해요"로 고쳤다.
        for text in ('저자들은 결론에서 "성별 차이와 사춘기는 각각 관련된다"고 써요.',
                     'Sporns et al.(2005)은 "기본 요소는 정의하기 어렵다"라고 썼습니다.',
                     '저자들은 지연이 줄었다고 결론에서 써요.', '이 글은 그 값을 0이라고 적어요.',
                     'Bargmann(2012)은 100종류 넘게 있다고 쓰고 다른 글은 200개라고 했어요.'):
            self.assertEqual(self.m(text)["A14.report_write"]["value"], 1, text)
        for text in ('논문에는 "..."라고 쓰여 있어요.', '로그에는 "timeout"이라고 적혀 있습니다.', '글을 씁니다.',
                     '이 방법을 사람 뇌에 썼어요.', '뉴런 수가 적어요.', '이 값은 적어도 두 배입니다.',
                     'Herting et al.(2012)의 저자들은 결론에서 "각각 관련된다"라고 말해요.'):
            self.assertEqual(self.m(text)["A14.report_write"]["value"], 0, text)
        # 따옴표 친 영어 낱말에 이미 걸린 문장은 다시 세지 않는다.
        m = self.m('저자들은 "likely"라고 씁니다.')
        self.assertEqual((m["A14.quoted_english_token"]["value"], m["A14.report_write"]["value"]), (1, 0))
        m = self.m('저자들이 "~로 보인다(suggest)"고 쓴 추정입니다. 그 수보다 많다고 적은 하한입니다.')
        self.assertEqual((m["A14.report_write"]["value"], m["A14.report_write_check"]["value"]), (0, 2))

    def test_quote_go_is_not_checked(self):
        # 0.8.0은 따옴표 뒤의 "고"를 FAIL로 셌다(A14.quote_go). 사용자 검토(2026-10-18)에서 직접 인용 뒤에도
        # "고"를 쓴다고 해서 0.9.0에서 뺐다. 사람 글 224편 중 19편도 이 형태를 쓴다.
        thresholds = L.load_json(L.THRESHOLDS_PATH)
        for text in ('Herting et al.(2012)은 "각각 관련된다"고 말해요.', '“구조가 기능을 풀어 주지는 않는다”고 정리했어요.'):
            a = L.analyze(text)
            self.assertNotIn("A14.quote_go", a["metrics"], text)
            ev = L.evaluate(a, thresholds, "casual")
            self.assertEqual([r["id"] for r in ev["results"] if r["status"] in ("FAIL", "GATE")], [], text)
        self.assertNotIn("A14.quote_go", thresholds["metrics"])
        self.assertNotIn("A14.quote_go", thresholds["short"]["drop"])
        # 자료의 말을 "쓰다"로 옮긴 문장은 따옴표 뒤 조사와 상관없이 FAIL로 남는다.
        for text in ('저자들은 "관련된다"고 써요.', '저자들은 "관련된다"라고 써요.'):
            ev = L.evaluate(L.analyze(text), thresholds, "casual")
            st = {r["id"]: r["status"] for r in ev["results"]}
            self.assertEqual(st["A14.report_write"], "FAIL", text)

    def test_bare_author(self):
        two = ("Herting et al.(2012)은 청소년 77명의 DTI를 분석했어요. 남자는 testosterone 수치가 FA를 예측했어요. "
               "저자들은 결론에서 성호르몬이 관계의 일부를 설명한다고 봐요.\n\nSporns et al.(2005)은 첫 초안을 제안했어요.\n")
        m = self.m(two)
        self.assertEqual([h["match"] for h in m["A18.bare_author"]["hits"]], ["저자들은"])
        for text in (
                # 연구 이름이 같은 문장이나 바로 앞 문장에 있다
                "Herting et al.(2012)은 DTI를 분석했어요. 저자들은 성호르몬이 관계를 설명한다고 봐요. "
                "세 저자는 개인차도 쟀어요.\n\nSporns et al.(2005)은 첫 초안을 제안했어요.\n",
                "Herting et al.(2012)의 저자들은 결론에서 관계를 말해요. Sporns et al.(2005)은 초안을 제안했어요.",
                # 연구가 하나뿐인 글
                "김 등(2025)은 로그를 모았습니다. 지연이 줄었습니다. 저자들은 배치 대기가 원인이라고 봅니다.",
                # 이름이 붙은 연구팀
                "Kim et al.(2020)이 먼저 썼습니다. 2014년에 Facebook의 AI 연구팀이 논문을 발표했습니다. Lee(2021)도 있습니다.",
                # 바로 앞 문장이 저자 이름을 산문으로 썼다(0.8.0 실제 실행에서 찾은 오탐)
                "Cornelia Bargmann과 Eve Marder는 2013년 Nature Methods에 관점 글을 발표했어요. "
                "이 글에서는 두 저자가 든 사례를 정리해요. Jang 등(2012)도 다뤄요.\n\nMacosko 등(2009)도 있어요.\n"):
            self.assertEqual(self.m(text)["A18.bare_author"]["value"], 0, text)
        # 헤딩을 지나면 바로 앞 문장으로 치지 않는다.
        m = self.m("Herting et al.(2012)은 DTI를 분석했어요. Sporns et al.(2005)도 있어요.\n\n## 결론\n\n저자들은 관계를 설명해요.\n")
        self.assertEqual(m["A18.bare_author"]["value"], 1)

    def test_sseuda_senses(self):
        # 사용자 검토: 한 노트가 "쓰다"를 '사용하다'와 '자료에 적다'로 함께 썼다.
        text = ("Bargmann & Marder(2013)는 neuromodulator가 표적에 닿는 길을 세 가지로 써요.\n\n"
                "이 방법을 C. elegans에 썼어요. 확률을 연결 세기로 써요.\n")
        hits = self.m(text)["A21.sseuda_senses"]["hits"]
        self.assertEqual(len(hits), 1)
        self.assertIn("'사용하다' 2곳", hits[0]["match"])
        self.assertIn("'자료의 말' 1곳", hits[0]["match"])
        m = self.m('저자들은 "관련된다"라고 썼어요. 쓰기 비율이 높습니다.')
        self.assertEqual(m["A21.sseuda_senses"]["value"], 0)
        for text in ("이 방법을 C. elegans에 썼어요. 확률을 세기로 써요.",
                     "Kim(2020)은 로그를 모았어요. 이 값을 기준으로 써요."):
            self.assertEqual(self.m(text)["A21.sseuda_senses"]["value"], 0, text)
        ev = L.evaluate(L.analyze(text), L.load_json(L.THRESHOLDS_PATH), "casual")
        self.assertEqual({r["id"]: r["group"] for r in ev["results"] if r["id"] == "A21.sseuda_senses"},
                         {"A21.sseuda_senses": "ko"})

    def test_general_expressions(self):
        # 0.9.0: "쓰다"만이 아니라 글쓰기에서 일반적으로 점검하는 표현(사용자 2차 검토). 사람 글 측정은
        # dev/baseline/README.md의 "동사 격식과 일반 표현 항목 (0.9.0)".
        cases = {
            "A14.doeeojida": (["개선되어졌습니다.", "Go로 쓰여진 코드가 있습니다.", "흔히 보여지는 오류입니다.",
                               "두 그룹으로 나뉘어집니다.", "문이 열려집니다."],
                              ["개선되었습니다.", "믿어지지 않는 결과입니다.", "만들어진 모델입니다.", "주어진 값입니다."]),
            "A14.causative": (["두 서비스를 연결시켰습니다.", "값을 결과에 포함시킵니다."],
                              ["두 서비스를 연결했습니다.", "처리량을 향상시켰습니다.", "모델을 학습시켰습니다."]),
            "A5.pleonasm": (["약 10% 정도 줄었습니다.", "서버를 다시 재시작했습니다.", "과반수 이상이 찬성했습니다.",
                             "미리 예측한 값입니다.", "약 100여 개의 서비스가 있습니다."],
                            ["약 10% 줄었습니다.", "10% 정도 줄었습니다.", "재시작했습니다.", "가장 최근 버전입니다."]),
            "A14.adverb_pair": (["결코 쉬운 일입니다.", "비록 느립니다.", "왜냐하면 캐시가 비어 있습니다.",
                                 "만약 캐시가 비어 있습니다."],
                                ["결코 우연이 아닙니다.", "결코 쉽지 않습니다.", "비록 느리지만 정확합니다.",
                                 "왜냐하면 Next.js가 느리기 때문입니다.", "만약 캐시가 비어 있으면 다시 읽습니다.",
                                 "만약 충돌이 나더라도 다시 시도합니다.", "만약의 경우를 대비합니다."]),
            "G11.spelling": (["안 되요.", "됬습니다.", "몇일 걸렸습니다.", "몇 일 동안 걸렸습니다.", "금새 끝났습니다.",
                              "가르키는 값입니다.", "역활을 합니다.", "알려드릴께요.", "일일히 확인합니다."],
                             ["되도록 빨리 합니다.", "몇 일자리가 남았습니다.", "몇 일요일이 지났습니다.", "금세 끝났습니다.",
                              "가리키는 값입니다.", "선생님께서 말합니다.", '로그에는 "되요"라고 찍힙니다.']),
            "A21.jeokda_as": (["아래에서는 이 글을 Bargmann & Marder(2013)로 적어요.",
                               "Bargmann & Marder(2013)는 STG의 뉴런을 약 27개로 적었습니다."],
                              ["로그에는 timeout이라고 적혀 있습니다.", "뉴런 수가 적어요.", "결과를 표에 적었습니다.",
                               '"over"로 적은 하한입니다.']),
        }
        for mid, (pos, neg) in cases.items():
            for text in pos:
                self.assertEqual(self.m(text)[mid]["value"], 1, (mid, text))
            for text in neg:
                self.assertEqual(self.m(text)[mid]["value"], 0, (mid, text))
        th = L.load_json(L.THRESHOLDS_PATH)
        st = {r["id"]: r for r in L.evaluate(L.analyze("안 되요. 흔히 보여지는 오류입니다. 두 서비스를 연결시켰습니다."),
                                             th, "default")["results"]}
        self.assertEqual((st["G11.spelling"]["status"], st["A14.doeeojida"]["status"]), ("GATE", "FAIL"))
        self.assertEqual((st["A14.causative"]["status"], st["A14.causative"]["group"]), ("CHECK", "ko"))
        self.assertTrue(th["metrics"]["G11.spelling"]["policy"] and th["metrics"]["A14.doeeojida"]["policy"])

    def test_native_verbs_and_see_judgment(self):
        # 0.9.0: 정보 전달 글은 같은 뜻에 한자어 동사를 더 많이 쓴다(사용자 2차 검토). 사람 글에서 걸린 문장을 모두 읽고
        # 고친 오탐은 dev/baseline/README.md의 "동사 항목의 기준치".
        cases = {
            "A5.native_verbs": (["Redis를 쓰고 있습니다.", "Orca가 쓰는 iteration-level scheduling은 끝난 요청을 뺍니다.",
                                 "KV cache에 쓸 수 있는 메모리는 20GB입니다.", "Shuffle Partition이 쓰입니다.",
                                 "처리량을 쟀습니다.", "고정된 요청률에서 잰 지연입니다.", "배치 크기를 10으로 두면 지연이 줄어듭니다.",
                                 "기본 임베딩 차원을 최대 2,048로 두고 학습했습니다.", "코드를 고칠 때마다 커밋합니다.",
                                 "테스트를 돌리고 결과를 봅니다.", "모델을 고른 후 실행합니다.",
                                 "인터넷에서 가져다 쓸 수 있는 Helm 차트입니다."],
                                ["장애가 나면 장애일지를 씁니다.", "어떻게 프롬프트를 써야 할지 모르겠습니다.", "PRD를 쓰고 유저를 만납니다.",
                                 "CPU Bound를 신경 쓰며 구성했습니다.", "손을 쓸 수 없는 경우가 생깁니다.", "반나절을 써야 했습니다.",
                                 "시간의 상당수가 코드를 검토하는 데 쓰입니다.", "값을 읽고 쓸 수 있는 스토리지입니다.",
                                 "샘플 A1이 마지막 logical block에 새 KV cache를 쓰려 하면 새 블록을 잡습니다.",
                                 "디스크에 로그를 씁니다.", "핵심 목표로 두고 학습했습니다.", "별도 상태로 둔 이유가 있습니다.",
                                 "모든 벤치마크에서 고른 성능을 유지합니다.", "GitOps 리포지토리에 넣어서 관리합니다.",
                                 "설정을 바꿨습니다.", "지연이 줄었습니다.", "Go로 쓰인 서버입니다.", "사람이 쓴 글입니다."]),
            "A7.see_judgment": (["저자들은 병목이 될 것으로 봅니다.", "저자들은 지연이 배치 대기에서 생긴다고 봅니다.",
                                 "요청의 KV cache를 logical block의 목록으로 보고 채웁니다.",
                                 "가능하다고 보고 추가 실험을 진행했습니다.", "AI를 도구로 보는 것이 중요합니다."],
                                ["영역을 주로 봅니다.", "그 변경을 바로 봐야 합니다.", "파일 변환을 기준으로 봤을 때 0.3초입니다.",
                                 "전체적으로 봤을 때 좋습니다.", "차이가 크지 않다고 보고 했으며 다음 연구로 이어졌습니다.",
                                 "그래프로 보면 지연이 줄었습니다.", "결과를 볼 수 있습니다.", "저자들은 지연을 보고했습니다."]),
        }
        for mid, (pos, neg) in cases.items():
            for text in pos:
                self.assertEqual(self.m(text)[mid]["value"], 1, (mid, text))
            for text in neg:
                self.assertEqual(self.m(text)[mid]["value"], 0, (mid, text))
        # 어투만 바꾼 Casual 문장도 같은 수로 센다
        default = "Redis를 씁니다. 처리량을 쟀습니다. 저자들은 병목이 될 것으로 봅니다."
        casual = "Redis를 써요. 처리량을 쟀어요. 저자들은 병목이 될 것으로 봐요."
        for mid in ("A5.native_verbs", "A7.see_judgment"):
            self.assertEqual(self.m(default)[mid]["value"], self.m(casual)[mid]["value"], mid)
        # 사람 글 합산 비율의 Poisson 상한으로 판정하고, 짧은 글 모드에서는 판정하지 않는다
        th = L.load_json(L.THRESHOLDS_PATH)
        body = "\n\n".join(["배치 크기를 10으로 줄이자 p99 지연이 4.2초에서 0.8초로 줄었습니다. " * 4] * 20)
        many = body + "\n\n" + " ".join(f"Redis {i}개를 썼습니다." for i in range(8))
        st = {r["id"]: r for r in L.evaluate(L.analyze(many), th, "default")["results"]}
        self.assertEqual(st["A5.native_verbs"]["limit"]["basis"], "poisson")
        self.assertEqual(st["A5.native_verbs"]["status"], "FAIL")
        st = {r["id"]: r for r in L.evaluate(L.analyze(body + "\n\nRedis를 썼습니다."), th, "default")["results"]}
        self.assertEqual(st["A5.native_verbs"]["status"], "PASS")
        for mid in ("A5.native_verbs", "A7.see_judgment"):
            self.assertTrue(th["metrics"][mid]["fixed"], mid)
            self.assertIn(mid, th["short"]["drop"])

    def test_korean_checks_render_in_own_group(self):
        text = "모든 영역이 한 값에 머물지 않았습니다.\n\n기존 설정과 비교하면 최대 5배입니다.\n"
        a = L.analyze(text)
        ev = L.evaluate(a, L.load_json(L.THRESHOLDS_PATH), "default")
        st = {r["id"]: r for r in ev["results"]}
        self.assertEqual(st["A18.negation_scope"]["status"], "CHECK")
        self.assertEqual(st["A18.negation_scope"]["group"], "ko")
        out = L.render_text("x.md", "default", a, ev)
        self.assertIn("단독 읽기 점검 후보", out)
        self.assertIn("한국어 점검 후보", out)
        self.assertLess(out.index("단독 읽기 점검 후보"), out.index("한국어 점검 후보"))

    def test_window_and_quoted_english_fail_the_draft(self):
        a = L.analyze('저자들은 "likely"로 쓴 적분 창을 씁니다.')
        ev = L.evaluate(a, L.load_json(L.THRESHOLDS_PATH), "default")
        st = {r["id"]: r["status"] for r in ev["results"]}
        self.assertEqual(st["A6.window_range"], "FAIL")
        self.assertEqual(st["A14.quoted_english_token"], "FAIL")


class ExampleRegressionTest(unittest.TestCase):
    """Codex smoke의 retone 케이스는 예시 글을 입력으로 쓰고, exit 0인 lint 실행이 있어야 통과한다.

    0.4.0 예시 글은 0.9.0에서 더한 A5.native_verbs('사용' 뜻의 쓰다, 재다 등)와 A7.see_judgment("~라고 봅니다")
    기준을 넘는다(1,000자당 2.40번과 0.44번, 사람 글 0.096번과 0.011번). 예시 글을 0.9.0 실행 결과로 바꿀 때까지
    두 항목을 빼고 판정한다. 바꾼 뒤에는 이 제외를 지운다."""

    PENDING = ("A5.native_verbs", "A7.see_judgment")

    def test_examples_pass_new_checks(self):
        thresholds = L.load_json(L.THRESHOLDS_PATH)
        thresholds = dict(thresholds, metrics={k: v for k, v in thresholds["metrics"].items() if k not in self.PENDING})
        for name, tone in (("paged-attention.default.md", "default"), ("paged-attention.casual.md", "casual")):
            a = L.analyze(L.read_text(os.path.join(ROOT, "examples", name)))
            ev = L.evaluate(a, thresholds, tone)
            self.assertEqual(ev["summary"]["verdict"], "PASS", name)
            for mid in ("G6.emdash", "G6.punct_policy", "G10.num_particle", "A6.window_range",
                        "A14.quoted_english_token", "A5.archaic_words", "A14.report_write", "A14.doeeojida",
                        "G11.spelling"):
                self.assertEqual(a["metrics"][mid]["value"], 0, (name, mid))


class ToneTest(unittest.TestCase):
    def test_reference_entries_are_not_tone_checked(self):
        # 0.6.0 실행에서 참고자료의 "공개 URL 없음."이 어투 혼용 Gate로 걸려 서지 항목을 고쳤다.
        text = ("공개 API는 고정 윈도우를 썼습니다. 지연은 1,850ms에서 420ms로 줄었습니다.\n\n"
                "## 참고자료\n\n[1] 사내 엔지니어링 노트, Migrating the API rate limiter (2026). 공개 URL 없음.\n")
        a = L.analyze(text)
        self.assertEqual(L.tone_metrics(a, "default")["G4.off_tone"]["value"], 0)
        body = text.replace("## 참고자료", "## 정리")
        self.assertEqual(L.tone_metrics(L.analyze(body), "default")["G4.off_tone"]["value"], 1)

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


class ApproxQuantityTest(unittest.TestCase):
    def test_korean_approx_quantity_needs_fact(self):
        text = "수십만 명이 모인 서버에서 요청 수만큼 스레드를 띄웠습니다. 노드는 수천 개입니다."
        a = L.analyze(text, facts_text="노드: 수천 개(원문 thousands of nodes)")
        hits = [h["match"] for h in a["metrics"]["A15.unknown_numbers"]["hits"]]
        self.assertEqual(hits, ["수십만"])

    def test_count_with_particle_man_is_not_approx(self):
        # 0.6.0 실행에서 "요청 수만 줄였습니다"(개수 + 조사 "만")가 어림 수량어로 걸려 맞는 문장을 고쳤다.
        text = ("토큰 버킷은 한 번에 보낼 수 있는 요청 수만 줄였습니다. 사용자 수만 늘리면 됩니다. "
                "하루 수만 건의 요청이 들어옵니다. 수만 개의 연결을 엽니다. 코드 수만 줄을 옮겼습니다.")
        a = L.analyze(text, facts_text="- 요청 600개")
        hits = [h["match"] for h in a["metrics"]["A15.unknown_numbers"]["hits"]]
        self.assertEqual(hits, ["수만", "수만", "수만"])
        self.assertEqual([h["text"][:2] for h in a["metrics"]["A15.unknown_numbers"]["hits"]], ["하루", "수만", "코드"])


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
