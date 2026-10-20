#!/usr/bin/env python3
"""0.6.0 이후의 한국어 점검 항목이 사람 글에서 얼마나 걸리는지 재고, 걸린 문장을 보여 준다.

새 항목은 사람 글 분포에서 정한 기준치가 아니라 대부분 정책(policy)이나 점검 후보(CHECK)다. 그래서 이 스크립트는
기준치를 계산하지 않고 오탐을 찾는 용도로 쓴다. 사람 글에서 걸린 문장은 모두 읽고, 잘못 걸린 형태는 정규식에서 뺀다.

- 사람 글: measure.py collect로 모은 캐시의 글 중 stats.json에 들어간 글(그룹별)
- --extra 이름=경로: 비교할 글(예시 글, 실행 결과)
- --notes GLOB: StudyNote 노트(.mdx). frontmatter, import와 export 줄, 컴포넌트 줄, 각주 정의, "참고 자료" 절을
  메모리에서 걷어 내고 잰다. 원본 파일은 바꾸지 않는다.
- --pairs DIR: 같은 글의 수정 전후 파일 쌍(<이름>.before.md, <이름>.after.md). 수정 전 글에서 바뀐 문장과
  그대로 둔 문장으로 나눠 항목별로 걸린 수를 센다. 사람이 고친 문장을 얼마나 잡는지(recall)와
  고치지 않은 문장을 얼마나 잡는지(오탐)를 보는 용도다.
- --rates: 그룹마다 항목별 합산 비율(1,000자당 문장 수)을 낸다. poisson 기준치의 rate_per_1k를 정할 때 쓴다.
- --verbs: 같은 뜻의 고유어 동사와 한자어 동사(쓰다와 사용하다 등)가 1,000자당 몇 번 나오는지 그룹마다 낸다(0.9.0).
- --verdicts ID ...: 지금 thresholds.json으로 사람 글(합니다체, 해요체 그룹)을 판정해, 주어진 항목의 WARN과 FAIL 수와
  holdout 글의 통과율(policy 항목과 어투 Gate는 뺀다)을 낸다. 새 항목이 사람 글 통과율을 떨어뜨리는지 볼 때 쓴다.

사용법
  python dev/baseline/ko_stats.py --cache DIR [--groups default casual drift-default drift-casual]
                                  [--extra 이름=경로 ...] [--notes GLOB] [--pairs DIR] [--samples N]
                                  [--no-holdout] [--rates] [--verbs] [--verdicts ID ...]
"""

import argparse
import difflib
import glob
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(ROOT, "skills", "techblog", "scripts"))
import lint_ko as L  # noqa: E402

# lint에 넣은 항목
ADOPTED = ("G6.emdash", "G6.punct_policy", "G10.num_particle", "A6.window_range", "A14.quoted_english_token",
           "A14.quoted_english_check", "A5.archaic_words", "A6.calque_check", "A18.negation_scope", "A19.term_mix",
           "A20.species_first", "A20.abbr_first", "A14.report_write", "A14.report_write_check",
           "A18.bare_author", "A21.sseuda_senses", "A20.term_in_list", "A14.doeeojida", "G11.spelling",
           "A14.causative", "A5.pleonasm", "A14.adverb_pair", "A21.jeokda_as", "A5.native_verbs", "A7.see_judgment",
           "A8.same_predicate_adjacent")
# lint에 넣을지 정하려고 따로 재는 후보. 문장 단위로 센다.
CANDIDATES = {
    "옛(관형사)": r"(?<![가-힣])옛\s",
    "수치적으로(전체)": r"수치적으로",
    "수치적으로 + 0, 같다, 동일": r"수치적으로\s*(?:거의\s*|사실상\s*)?(?:0|같|동일|무시)",
    "제시된": r"제시(?:된|되었|됐)",
    "전술한, 후술할": r"(?:전술|후술)(?:한|할|하는|된)",
    "본 논문, 본 연구, 본 글": r"(?<![가-힣])본\s?(?:논문|연구|글|문서|실험)(?:은|는|이|가|을|를|의|에서|에)",
    "~함에 있어": r"함에\s?있어",
    "~에 기인": r"에\s?기인(?:한|하|합|해|했)",
    "무비판적": r"무비판적",
    "해당 + 명사": r"(?<![가-힣])해당\s+[가-힣]+",
    # 0.9.0 일반 표현 후보(사용자 2차 검토: "쓰다"만이 아니라 글쓰기에서 일반적으로 점검하는 표현)
    "이중 피동(되어지다)": r"되어(?:지|진|질|집|져|졌)",
    "이중 피동(보여지다 등)": r"(?<![가-힣])(?:보여|쓰여|씌여|잊혀|짜여|불려|나뉘어|믿겨)(?:지|진|질|집|져|졌)",
    "이중 피동 후보(열려지다 등)": r"(?<![가-힣])(?:열려|닫혀|읽혀|놓여|담겨|바뀌어|쌓여|섞여|묶여)(?:지|진|질|집|져|졌)",
    "~시키다(좁은 목록)": r"(?<![가-힣])(?:소개|연결|포함|유지|통합|전환|적용|입력|반영|교육|주입|접목|결합|대입)\s?시(?:키|켜|켰|킨|킬|킵|킴)",
    "~시키다(넓은 목록 후보)": r"(?<![가-힣])(?:실행|활성화|변경|종료|분리|고정|정렬|연동|동기화|이동|완료|전달|배포|저장)\s?시(?:키|켜|켰|킨|킬|킵|킴)",
    "겹말": (r"(?<![가-힣])약\s?(?:\d[\d.,]*|한|두|세|네|다섯|여섯|일곱|여덟|아홉|열|수십|수백|수천|몇)\s?[^\s.?!,]{0,6}\s?"
             r"(?:정도|가량|쯤)(?:의|로|이|가|를|은|는|에|까지|만)?(?![가-힣])"
             r"|(?<![가-힣])약\s?\d[\d,]*\s?여\s?[가-힣]"
             r"|(?<![가-힣])다시\s+재(?:개|시작|확인|설정|발|구성|실행|시도|배포|사용|생성|연결|부팅|검토|전송|처리|계산|학습)"
             r"|과반수\s?(?:이상|넘게|를\s?넘)|가장\s+최(?:선|고|적)|먼저\s+선행|새로(?:이|게)?\s+신설|서로\s+상충"
             r"|함께\s+공존|미리\s+(?:예약|예측|예상|예고)"),
    "겹말 후보(가장 최대 등)": r"가장\s+최(?:대|소|신|초)|다시\s+반복|계속\s+지속|사전에\s+미리",
    # 문장 안의 "Next.js" 같은 마침표에서 멈추지 않게 문장 끝까지(.*) 본다.
    "부사 호응(결코, 비록, 왜냐하면, 만약)": (
        r"(?<![가-힣])결코\s(?!.*(?:않|없|못|아니|아닌|아닙|말|모르|모릅|몰라|안\s))"
        r"|(?<![가-힣])비록\s(?!.*(?:지만|더라도|어도|아도|여도|해도|라도|으나|이나|는데|은데|인데|지언정|망정))"
        r"|(?<![가-힣])왜냐(?:하)?면\s(?!.*(?:때문|므로|니까|거든|[아어여해]서(?![가-힣])|라서))"
        r"|(?<![가-힣])만약(?:에)?\s(?!.*(?:면|경우|때|거든|더라도|해도|라도))"),
    "맞춤법(되요, 됬, 몇일, 금새 등)": (
        r"되요(?![가-힣])|됬|(?<![가-힣])되서(?:는|도|야)?(?![가-힣])|(?<![가-힣])되도(?!록)(?![가-힣])"
        r"|몇\s?일(?=$|[\s.,?!)]|(?:이|을|은|의|에|이나|도|만|부터|까지|째|간|동안|씩|만에)(?![가-힣]))"
        r"|(?<![가-힣])금새(?![가-힣])|어떻해|왠만|웬지|왠일|뵈요|가르키|역활|오랫만|일일히|깨끗히|틈틈히|곰곰히|희안|어의없"
        r"|[할볼줄갈올릴을]께(?:요)?(?![가-힣])"),
    "틀리다(와/과 뒤)": r"(?:와|과|랑)\s+틀(?:리|려|렸|린|립)",
    "X를 Y로 적다": r"(?:을|를)\s+(?:\S+\s+){0,2}?\S+(?:으로|로)\s+(?:적습니다|적어요|적는다|적었|적고|적으며|적을|적겠|적기로)",
    "~의 세 번 연쇄": r"[가-힣]+의\s+[가-힣]+의\s+[가-힣]+의\s",
}
# 같은 뜻의 고유어 동사와 한자어 동사. 낱말이 나온 횟수를 센다(문장 수가 아님).
VERB_PAIRS = [
    ("쓰다(모든 뜻)", r"(?<![가-힣])(?:쓰(?!레|로|루|리|러)[가-힣]*|써(?!드|머|니)[가-힣]*|썼[가-힣]*|씁[가-힣]*|쓴(?!맛)[가-힣]*"
                   r"|쓸(?!모|데|쓸)[가-힣]*)"),
    ("사용하다", r"사용(?:하|했|해|합|한|할|함|됩|되|된|돼|될|됐|중)"),
    ("활용하다", r"활용(?:하|했|해|합|한|할|함|됩|되|된|돼|될|됐)"),
    ("적용하다", r"적용(?:하|했|해|합|한|할|함|됩|되|된|돼|될|됐)"),
    ("바꾸다", r"(?<![가-힣])(?:바꾸|바꿔|바꿨|바꿉|바꾼|바꿀)"),
    ("변경하다", r"변경(?:하|했|해|합|한|할|함|됩|되|된|돼|될|됐)"),
    ("재다", r"(?<![가-힣])(?:잽니다|재요|쟀|잰다|재는|잰(?=\s)|잴(?=\s)|재면|재서|재야|재지|재려|재며)"),
    ("측정하다", r"측정(?:하|했|해|합|한|할|함|됩|되|된|돼|될|됐)"),
    ("두다", r"(?<![가-힣])(?:둬|뒀|둡니|둔다|두었|두면|두는|두며|두기)"),
    ("설정하다", r"설정(?:하|했|해|합|한|할|함|됩|되|된|돼|될|됐)"),
    ("넣다", r"(?<![가-힣])넣(?:고|어|었|습|는|을|으|기|지|게|다|자|은)"),
    ("추가하다", r"추가(?:하|했|해|합|한|할|함|됩|되|된|돼|될|됐)"),
    ("고치다", r"(?<![가-힣])(?:고치|고쳐|고쳤|고칩|고친|고칠)"),
    ("수정하다", r"수정(?:하|했|해|합|한|할|함|됩|되|된|돼|될|됐)"),
    ("돌리다", r"(?<![가-힣])(?:돌리|돌려|돌렸|돌립|돌린|돌릴)"),
    ("실행하다", r"실행(?:하|했|해|합|한|할|함|됩|되|된|돼|될|됐)"),
    ("고르다", r"(?<![가-힣])(?:고르(?!게|지)|골라|골랐|고릅|고른|고를)"),
    ("선택하다", r"선택(?:하|했|해|합|한|할|함|됩|되|된|돼|될|됐)"),
    ("나오다", r"(?<![가-힣])(?:나오|나와|나왔|나옵|나온|나올)"),
    ("나타나다, 발생하다", r"(?:나타나|나타났|나타납|나타난|나타날|발생(?:하|했|해|합|한|할|함|됩|되|된|돼|될|됐))"),
    ("줄다, 줄이다", r"(?<![가-힣])(?:줄어|줄었|줄고|줄면|줄인|줄이|줄여|줄일|줄였|줄입)"),
    ("감소하다", r"감소(?:하|했|해|합|한|할|함|됩|되|된|돼|될|됐)"),
    ("늘다, 늘리다", r"(?<![가-힣])늘(?:어|었|고|면|린|리|려|릴|렸|립|며|기|지)"),
    ("증가하다", r"증가(?:하|했|해|합|한|할|함|됩|되|된|돼|될|됐)"),
    ("만들다", r"(?<![가-힣])(?:만들|만든|만드|만듭|만듦)"),
    ("생성하다, 구현하다", r"(?:생성|구현)(?:하|했|해|합|한|할|함|됩|되|된|돼|될|됐)"),
    ("판단의 보다(~라고/다고/것으로 봅니다)", r"(?:다고|라고|것으로)\s*(?:봅니다|봐요|봤|본다|보았|보고(?![가-힣])|보는\s|봐야|보며|보지)"),
    ("추정하다, 해석하다", r"(?:추정|해석)(?:하|했|해|합|한|할|함|됩|되|된|돼|될|됐)"),
]
# 쓰다로 세지 않는 낱말(쓰레드, 쓰기 비율처럼 명사로 굳은 말, 덮어쓰다)
SSEUDA_EXCL_RE = re.compile(r"(?:쓰레드|쓰레기|쓰로틀|쓰루풋|쓰리|덮어쓰|덮어써|덮어썼|글쓰기|쓰기\s*(?:요청|작업|연산|비율|성능|"
                            r"지연|부하|경로|트래픽|버퍼|락|권한|모드|속도|량)|쓰기와|쓰기가|쓰기를|쓰기는|쓰기에|쓰기의)")
NOUN_END = set("은는이가을를의에와과도만로서고며면다요지게한할된될던인히니까야여나든엔랑께럼터")
TONE_RULES = ("G4.off_tone", "G4.banned_ending")


def noun_stack(masked, n=4):
    """조사나 어미 없이 이어진 한글 낱말이 n개 이상인지(형태소 분석 없는 어림). 명사 쌓기 후보 측정용."""
    run = 0
    for tok in L.PH_RE.sub(" ", masked).replace(",", " ").split():
        bare = re.fullmatch(r"[가-힣]{2,}", tok) is not None and tok[-1] not in NOUN_END
        run = run + 1 if bare else 0
        if run >= n:
            return True
    return False


def measure(text):
    """항목별 걸린 수와 걸린 문장. 후보는 문장마다 한 번 센다."""
    a = L.analyze(text)
    out = {k: [h.get("match", "") + " | " + h["text"] for h in a["metrics"].get(k, {}).get("hits", [])]
           for k in ADOPTED}
    for name, rx in CANDIDATES.items():
        r = re.compile(rx)
        out[name] = [r.search(s.masked).group(0) + " | " + s.text for s in a["_sentences"] if r.search(s.masked)]
    out["명사 4개 이상 연속"] = [s.text for s in a["_sentences"] if noun_stack(s.masked)]
    return a["stats"]["chars"], out


def verb_counts(text):
    """VERB_PAIRS의 낱말이 본문(참고자료 절 밖 문장)에 나온 횟수."""
    a = L.analyze(text)
    body = " ".join(s.masked for s in a["_sentences"] if not s.in_refs)
    clean = SSEUDA_EXCL_RE.sub(" ", body)
    return a["stats"]["chars"], {name: len(re.findall(rx, clean if name.startswith("쓰다") else body))
                                 for name, rx in VERB_PAIRS}


def strip_note(text):
    """StudyNote 노트(.mdx)에서 글 본문만 남긴다."""
    text = re.sub(r"\A---\n.*?\n---\n", "", text, flags=re.S)
    text = re.sub(r"^\s*(?:import|export)\s.*$", "", text, flags=re.M)
    text = re.sub(r"^\s*<[A-Za-z][^>]*/?>\s*$", "", text, flags=re.M)
    text = re.sub(r"^\[\^[^\]]+\]:.*$", "", text, flags=re.M)
    text = re.split(r"^#{1,3}\s*참고\s*자료\s*$", text, maxsplit=1, flags=re.M)[0]
    return text


def quantile(vals, q):
    vals = sorted(vals)
    if not vals:
        return 0.0
    k = (len(vals) - 1) * q
    lo, hi = int(k), min(int(k) + 1, len(vals) - 1)
    return round(vals[lo] + (vals[hi] - vals[lo]) * (k - lo), 2)


def report_group(name, rows, samples):
    keys = list(ADOPTED) + list(CANDIDATES) + ["명사 4개 이상 연속"]
    chars = sum(r[1] for r in rows) or 1
    print(f"\n## {name}: {len(rows)}편, 본문 {chars:,}자")
    print("| 항목 | 걸린 글 | p50 | p90 | 최댓값 | 합계 | 1,000자당 |")
    print("|---|---|---|---|---|---|---|")
    for k in keys:
        vals = [len(r[2][k]) for r in rows]
        hit = sum(1 for v in vals if v)
        print(f"| {k} | {hit}/{len(rows)} | {quantile(vals, .5)} | {quantile(vals, .9)} | {max(vals) if vals else 0} | "
              f"{sum(vals)} | {sum(vals) * 1000 / chars:.3f} |")
    if samples:
        for k in keys:
            shown = [(r[0], x) for r in rows for x in r[2][k]][:samples]
            if shown:
                print(f"\n### {k}")
                for aid, x in shown:
                    print(f"- {aid}: {x[:150]}")


def report_verbs(groups):
    """groups: [(이름, [(chars, counts)])]. 1,000자당 횟수와 낱말이 나온 글 수."""
    print("\n## 같은 뜻의 고유어 동사와 한자어 동사(1,000자당 횟수, 괄호는 나온 글 수)")
    print("| 낱말 | " + " | ".join(f"{g} ({len(rows)}편)" for g, rows in groups) + " |")
    print("|---|" + "---|" * len(groups))
    for name, _ in VERB_PAIRS:
        cells = []
        for _, rows in groups:
            chars = sum(c for c, _ in rows) or 1
            total = sum(v[name] for _, v in rows)
            cells.append(f"{total * 1000 / chars:.2f} ({sum(1 for _, v in rows if v[name])})")
        print(f"| {name} | " + " | ".join(cells) + " |")


def report_verdicts(arts, cache, ids):
    """지금 thresholds.json으로 사람 글을 판정한다. 주어진 항목의 WARN, FAIL 수와 holdout 통과율."""
    th = L.load_json(L.THRESHOLDS_PATH)
    skip = {mid for mid, spec in th["metrics"].items() if spec.get("policy")} | set(TONE_RULES)
    th_judged = dict(th, metrics={mid: spec for mid, spec in th["metrics"].items() if mid not in skip})
    per = {mid: {"WARN": 0, "FAIL": 0, "GATE": 0} for mid in ids}
    hold_n = hold_pass = 0
    for a in arts:
        path = os.path.join(cache, "md", a["id"] + ".md")
        if a["group"] not in ("default", "casual") or not os.path.exists(path):
            continue
        ev = L.evaluate(L.analyze(L.read_text(path)), th_judged, a["group"])
        for r in ev["results"]:
            if r["id"] in per and r["status"] in per[r["id"]]:
                per[r["id"]][r["status"]] += 1
        if a.get("holdout"):
            hold_n += 1
            hold_pass += ev["summary"]["verdict"] == "PASS"
    print("\n## 사람 글 판정(합니다체, 해요체 그룹. policy 항목과 어투 Gate는 뺌)")
    print(f"holdout {hold_n}편 중 {hold_pass}편 통과({hold_pass / max(hold_n, 1):.0%})")
    print("| 항목 | WARN | FAIL | GATE |\n|---|---|---|---|")
    for mid, c in per.items():
        print(f"| {mid} | {c['WARN']} | {c['FAIL']} | {c['GATE']} |")


def report_rates(name, rows):
    keys = list(ADOPTED) + list(CANDIDATES)
    chars = sum(r[1] for r in rows) or 1
    print(f"\n## {name} 합산 비율: {len(rows)}편, 본문 {chars:,}자")
    for k in keys:
        n = sum(len(r[2][k]) for r in rows)
        if n:
            print(f"- {k}: {n}문장, 1,000자당 {n * 1000 / chars:.4f}")


def report_pairs(folder):
    """수정 전후 쌍에서 바뀐 문장과 그대로 둔 문장에 걸린 수."""
    keys = list(ADOPTED) + list(CANDIDATES) + ["명사 4개 이상 연속"]
    count = {k: [0, 0, 0] for k in keys}  # 바뀐 문장, 그대로 둔 문장, 수정 뒤 글
    n_changed = n_kept = 0
    for before in sorted(glob.glob(os.path.join(folder, "*.before.md"))):
        after = before[:-len(".before.md")] + ".after.md"
        if not os.path.exists(after):
            continue
        tb, ta = L.read_text(before), L.read_text(after)
        sb = [s.text for s in L.analyze(tb)["_sentences"]]
        sa = [s.text for s in L.analyze(ta)["_sentences"]]
        changed = set()
        for op, i1, i2, _, _ in difflib.SequenceMatcher(None, sb, sa, autojunk=False).get_opcodes():
            if op != "equal":
                changed.update(sb[i1:i2])
        n_changed += len(changed)
        n_kept += len(set(sb) - changed)
        _, mb = measure(tb)
        _, ma = measure(ta)
        for k in keys:
            for x in mb[k]:
                sent = x.split(" | ", 1)[-1]
                in_changed = any(sent[:50] in s or s[:50] in sent for s in changed)
                count[k][0 if in_changed else 1] += 1
            count[k][2] += len(ma[k])
    print(f"\n## 수정 전후 쌍: 수정 전 글의 문장 중 바뀐 문장 {n_changed}, 그대로 둔 문장 {n_kept}")
    print("| 항목 | 바뀐 문장에 걸림 | 그대로 둔 문장에 걸림 | 수정 뒤 글에 걸림 |")
    print("|---|---|---|---|")
    for k in keys:
        print(f"| {k} | {count[k][0]} | {count[k][1]} | {count[k][2]} |")


def main():
    L.setup_stdio()
    ap = argparse.ArgumentParser()
    ap.add_argument("--cache", help="measure.py collect의 캐시 폴더")
    ap.add_argument("--groups", nargs="*", default=["default", "casual", "drift-default", "drift-casual"])
    ap.add_argument("--extra", action="append", default=[], help="비교할 글: 이름=경로")
    ap.add_argument("--notes", help="StudyNote 노트 glob(.mdx). 본문만 남겨 잰다")
    ap.add_argument("--pairs", help="<이름>.before.md, <이름>.after.md 쌍이 있는 폴더")
    ap.add_argument("--samples", type=int, default=8, help="항목마다 보여 줄 걸린 문장 수")
    ap.add_argument("--no-holdout", action="store_true", help="holdout 글을 뺀다(기준치 계산과 같은 조건)")
    ap.add_argument("--rates", action="store_true", help="그룹마다 항목별 합산 비율을 낸다")
    ap.add_argument("--verbs", action="store_true", help="같은 뜻의 고유어 동사와 한자어 동사 비율을 낸다")
    ap.add_argument("--verdicts", nargs="*", help="지금 기준치로 사람 글을 판정할 항목 ID")
    args = ap.parse_args()
    verb_groups = []
    if args.cache:
        stats = json.load(open(os.path.join(ROOT, "dev", "baseline", "stats.json"), encoding="utf-8"))
        for group in args.groups:
            rows, vrows = [], []
            for a in stats["articles"]:
                path = os.path.join(args.cache, "md", a["id"] + ".md")
                if a["group"] != group or not os.path.exists(path) or (args.no_holdout and a.get("holdout")):
                    continue
                text = L.read_text(path)
                chars, out = measure(text)
                rows.append((a["id"], chars, out))
                if args.verbs:
                    vrows.append(verb_counts(text))
            if rows:
                report_group(group, rows, args.samples)
                if args.rates:
                    report_rates(group, rows)
            if vrows:
                verb_groups.append((f"사람 글 {group}", vrows))
        if args.verdicts is not None:
            report_verdicts(stats["articles"], args.cache, args.verdicts)
    extra_rows, extra_verbs = [], []
    for spec in args.extra:
        name, path = spec.split("=", 1)
        text = L.read_text(path if os.path.isabs(path) else os.path.join(ROOT, path))
        chars, out = measure(text)
        extra_rows.append((name, chars, out))
        if args.verbs:
            extra_verbs.append((name, [verb_counts(text)]))
    if args.notes:
        rows, vrows = [], []
        for path in sorted(glob.glob(args.notes)):
            text = strip_note(L.read_text(path))
            chars, out = measure(text)
            rows.append((os.path.basename(path), chars, out))
            if args.verbs:
                vrows.append(verb_counts(text))
        if rows:
            report_group(f"노트 {len(rows)}편", rows, args.samples)
        if vrows:
            verb_groups.append((f"노트 {len(rows)}편", vrows))
    if extra_rows:
        report_group("비교 글", extra_rows, args.samples)
    if args.verbs and (verb_groups or extra_verbs):
        report_verbs(verb_groups + extra_verbs)
    if args.pairs:
        report_pairs(args.pairs)


if __name__ == "__main__":
    main()
