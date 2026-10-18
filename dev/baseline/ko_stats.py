#!/usr/bin/env python3
"""0.6.0 이후의 한국어 점검 항목이 사람 글에서 얼마나 걸리는지 재고, 걸린 문장을 보여 준다.

새 항목은 사람 글 분포에서 정한 기준치가 아니라 대부분 정책(policy)이나 점검 후보(CHECK)다. 그래서 이 스크립트는
기준치를 계산하지 않고 오탐을 찾는 용도로 쓴다. 사람 글에서 걸린 문장은 모두 읽고, 잘못 걸린 형태는 정규식에서 뺀다.

- 사람 글: measure.py collect로 모은 캐시의 글 중 stats.json에 들어간 글(그룹별)
- --extra 이름=경로: 비교할 글(예시 글, 실행 결과)
- --pairs DIR: 같은 글의 수정 전후 파일 쌍(<이름>.before.md, <이름>.after.md). 수정 전 글에서 바뀐 문장과
  그대로 둔 문장으로 나눠 항목별로 걸린 수를 센다. 사람이 고친 문장을 얼마나 잡는지(recall)와
  고치지 않은 문장을 얼마나 잡는지(오탐)를 보는 용도다.

사용법
  python dev/baseline/ko_stats.py --cache DIR [--groups default casual drift-default drift-casual]
                                  [--extra 이름=경로 ...] [--pairs DIR] [--samples N]
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
           "A20.species_first", "A20.abbr_first", "A14.report_write", "A14.report_write_check", "A14.quote_go",
           "A18.bare_author")
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
}
NOUN_END = set("은는이가을를의에와과도만로서고며면다요지게한할된될던인히니까야여나든엔랑께럼터")


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
        out[name] = [s.text for s in a["_sentences"] if r.search(s.masked)]
    out["명사 4개 이상 연속"] = [s.text for s in a["_sentences"] if noun_stack(s.masked)]
    return a["stats"]["chars"], out


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
    print("| 항목 | 걸린 글 | p50 | p90 | 최댓값 | 1,000자당 |")
    print("|---|---|---|---|---|---|")
    for k in keys:
        vals = [len(r[2][k]) for r in rows]
        hit = sum(1 for v in vals if v)
        print(f"| {k} | {hit}/{len(rows)} | {quantile(vals, .5)} | {quantile(vals, .9)} | {max(vals) if vals else 0} | "
              f"{sum(vals) * 1000 / chars:.3f} |")
    if samples:
        for k in keys:
            shown = [(r[0], x) for r in rows for x in r[2][k]][:samples]
            if shown:
                print(f"\n### {k}")
                for aid, x in shown:
                    print(f"- {aid}: {x[:150]}")


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
    ap.add_argument("--pairs", help="<이름>.before.md, <이름>.after.md 쌍이 있는 폴더")
    ap.add_argument("--samples", type=int, default=8, help="항목마다 보여 줄 걸린 문장 수")
    args = ap.parse_args()
    if args.cache:
        stats = json.load(open(os.path.join(ROOT, "dev", "baseline", "stats.json"), encoding="utf-8"))
        for group in args.groups:
            rows = []
            for a in stats["articles"]:
                path = os.path.join(args.cache, "md", a["id"] + ".md")
                if a["group"] == group and os.path.exists(path):
                    chars, out = measure(L.read_text(path))
                    rows.append((a["id"], chars, out))
            if rows:
                report_group(group, rows, args.samples)
    if args.extra:
        rows = []
        for spec in args.extra:
            name, path = spec.split("=", 1)
            chars, out = measure(L.read_text(path if os.path.isabs(path) else os.path.join(ROOT, path)))
            rows.append((name, chars, out))
        report_group("비교 글", rows, args.samples)
    if args.pairs:
        report_pairs(args.pairs)


if __name__ == "__main__":
    main()
