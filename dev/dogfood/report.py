#!/usr/bin/env python3
"""iteration 결과(eval.json, judge.json)를 REPORT.md에 붙일 markdown 표로 출력한다.

사용법
  python dev/dogfood/report.py --iter iter-1
"""

import argparse
import json
import os
import sys

DEFAULT_WORK = os.path.join(os.environ.get("TEMP", "/tmp"), "techblog-work", "dogfood")
KEYS = (("A9.list_ratio", "목록"), ("A9.bold_per_1k", "bold"), ("A10.triad_per_1k", "셋 묶음"),
        ("A2.connective_comma_ratio", "연결어미 쉼표"), ("A1.np", "부정 대구"))


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except AttributeError:
        pass
    ap = argparse.ArgumentParser()
    ap.add_argument("--iter", required=True)
    ap.add_argument("--work", default=DEFAULT_WORK)
    args = ap.parse_args()
    d = os.path.join(args.work, args.iter)
    judge = {}
    if os.path.exists(os.path.join(d, "judge.json")):
        judge = json.load(open(os.path.join(d, "judge.json"), encoding="utf-8"))
    head = ["case", "lint G/F/W", "tone_check", "글자"] + [k[1] for k in KEYS] + \
           ["종결 반복", "style 평균", "J7/1k", "J9 앞 문장 의존/판정", "fidelity 근거없음/모순", "pairwise", "비용$", "분"]
    print("| " + " | ".join(head) + " |")
    print("|" + "---|" * len(head))
    for c in sorted(os.listdir(d)):
        ep = os.path.join(d, c, "eval.json")
        if not os.path.exists(ep):
            continue
        e = json.load(open(ep, encoding="utf-8"))
        l = e.get("lint", {})
        m = l.get("metrics", {})
        st = judge.get("style", {}).get(c)
        if st:
            sc = [v for r in st["runs"] for v in r["scores"].values()]
            style = f"{sum(sc) / len(sc):.2f}"
            j7 = "/".join(str(r["j7_per_1k"]) for r in st["runs"])
        else:
            style = j7 = "-"
        fd = judge.get("fidelity", {}).get(c)
        fid = f"{len(fd['unsupported'])}/{len(fd['contradicted'])}" if fd else "-"
        pw = judge.get("pairwise", {}).get(c, {}).get("result", "-")
        cl = judge.get("clarity", {}).get(c)
        j9 = f"{cl['dependent']}/{cl['answered']}" if cl else "-"
        run4 = m.get("A8.ending_run4", "-")
        row = [c, f"{l.get('gate')}/{l.get('fail')}/{l.get('warn')}", e.get("tone_check", {}).get("verdict", "-"),
               str(l.get("chars"))] + [str(m.get(k[0], "-")) for k in KEYS] + \
              [str(run4), style, j7, j9, fid, pw, f"{(e.get('cost_usd') or 0):.2f}", f"{(e.get('seconds') or 0) / 60:.1f}"]
        print("| " + " | ".join(row) + " |")
    hcl = [v for v in judge.get("clarity", {}).values() if v["human"]]
    if hcl:
        rates = sorted(v["rate"] for v in hcl if v["rate"] is not None)
        u, a = sum(v["dependent"] for v in hcl), sum(v["answered"] for v in hcl)
        print(f"\n사람 글 대조군 {len(hcl)}편 J9: 앞 문장에 기대거나 이해되지 않는 문장 {u}/{a}({u / a:.3f}), 글별 {rates[0]}~{rates[-1]}")
    hum = {k: v for k, v in judge.get("style", {}).items() if v["human"]}
    if hum:
        j7s = sorted(r["j7_per_1k"] for v in hum.values() for r in v["runs"])
        sc = [x for v in hum.values() for r in v["runs"] for x in r["scores"].values()]
        print(f"\n사람 글 대조군 {len(hum)}편: style 평균 {sum(sc) / len(sc):.2f}, J7/1k {j7s[0]}~{j7s[-1]} "
              f"(p75 {j7s[int(0.75 * (len(j7s) - 1))]})")


if __name__ == "__main__":
    main()
