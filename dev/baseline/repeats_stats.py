#!/usr/bin/env python3
"""사람 글에 revise_ko.py의 반복 후보 탐지를 돌려 후보 수 분포를 잰다.

후처리 단계의 반복 후보는 판정이 아니라 다시 읽을 위치다. 사람 글에서도 후보가 많이 나오면 후보 목록이 쓸모없는
목록이 된다. 이 스크립트로 2022-11-30 이전 합니다체 사람 글(stats.json의 default 그룹)에서 후보가 몇 개 나오는지 잰다.

사용법
  python dev/baseline/repeats_stats.py --cache DIR [--extra 이름=경로 ...]
"""

import argparse
import json
import os
import statistics
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(ROOT, "skills", "techblog", "scripts"))
import lint_ko as L  # noqa: E402
import revise_ko as RV  # noqa: E402

IDS = ("R6", "R1", "R4", "R3", "R5")


def counts(text):
    c = {k: 0 for k in IDS}
    for x in RV.find_repeats(text)["candidates"]:
        c[x["id"]] += 1
    return c


def quantile(vals, q):
    vals = sorted(vals)
    if not vals:
        return None
    k = (len(vals) - 1) * q
    lo, hi = int(k), min(int(k) + 1, len(vals) - 1)
    return round(vals[lo] + (vals[hi] - vals[lo]) * (k - lo), 2)


def main():
    L.setup_stdio()
    ap = argparse.ArgumentParser()
    ap.add_argument("--cache", required=True)
    ap.add_argument("--group", default="default")
    ap.add_argument("--extra", action="append", default=[], help="비교할 글: 이름=경로")
    args = ap.parse_args()
    stats = json.load(open(os.path.join(ROOT, "dev", "baseline", "stats.json"), encoding="utf-8"))
    rows = []
    for a in stats["articles"]:
        if a["group"] != args.group:
            continue
        path = os.path.join(args.cache, "md", a["id"] + ".md")
        if not os.path.exists(path):
            continue
        rows.append((a["id"], a["chars"], counts(L.read_text(path))))
    if not rows:
        raise SystemExit("캐시에 사람 글이 없다. measure.py collect를 먼저 실행한다.")
    print(f"사람 글 {args.group} 그룹 {len(rows)}편 (평균 본문 {statistics.mean(r[1] for r in rows):,.0f}자)")
    print("| 후보 | 후보 0개인 글 | p50 | p90 | 최댓값 | 1,000자당 |")
    print("|---|---|---|---|---|---|")
    total_chars = sum(r[1] for r in rows)
    for k in IDS + ("합계",):
        vals = [sum(r[2].values()) if k == "합계" else r[2][k] for r in rows]
        zero = sum(1 for v in vals if v == 0)
        print(f"| {k} | {zero}/{len(vals)} ({zero / len(vals):.0%}) | {quantile(vals, 0.5)} | {quantile(vals, 0.9)} | "
              f"{max(vals)} | {sum(vals) * 1000 / total_chars:.3f} |")
    for spec in args.extra:
        name, path = spec.split("=", 1)
        text = L.read_text(path if os.path.isabs(path) else os.path.join(ROOT, path))
        c = counts(text)
        chars = L.analyze(text)["stats"]["chars"] or 1
        print(f"{name}: {c} 합계 {sum(c.values())} ({sum(c.values()) * 1000 / chars:.3f}/1,000자, 본문 {chars:,}자)")


if __name__ == "__main__":
    main()
