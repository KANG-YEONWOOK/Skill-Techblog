#!/usr/bin/env python3
"""iteration 결과(eval.json, judge.json)를 REPORT.md에 붙일 markdown 표로 출력한다.

사용법
  python dev/dogfood/report.py --iter iter-1
  python dev/dogfood/report.py --iter iter-11 --within   # 초안 사본과 후처리를 마친 글의 비교 표
"""

import argparse
import json
import os
import sys

DEFAULT_WORK = os.path.join(os.environ.get("TEMP", "/tmp"), "techblog-work", "dogfood")
KEYS = (("A9.list_ratio", "목록"), ("A9.bold_per_1k", "bold"), ("A10.triad_per_1k", "셋 묶음"),
        ("A2.connective_comma_ratio", "연결어미 쉼표"), ("A1.np", "부정 대구"))


def _avg(recs, k):
    v = [x["scores"][k] for x in recs]
    return f"{sum(v) / len(v):.2f}" if v else "-"


def _rp(recs):
    v = [x["repetitive_per_1k"] for x in recs]
    return f"{sum(v) / len(v):.2f}" if v else "-"


def within_table(d, judge):
    head = ["case", "바뀐 문장", "글자", "lint G/F/W 초안→최종", "반복 후보 초안→최종", "pairwise", "절 A/B 후처리/초안/무",
            "J9 초안→최종", "unclear 초안→최종", "판정 잡음", "fidelity 근거없음/모순 초안→최종", "후처리로 생긴 오류",
            "J5 초안→최종", "J8 초안→최종", "반복 인용/1k 초안→최종", "start 뒤 시간 비율 / 분"]
    print("| " + " | ".join(head) + " |")
    print("|" + "---|" * len(head))
    for c in sorted(os.listdir(d)):
        ep = os.path.join(d, c, "eval.json")
        if not os.path.exists(ep):
            continue
        rv = json.load(open(ep, encoding="utf-8")).get("revise")
        if not rv:
            continue
        w = judge.get("within", {}).get(c, {})
        lb, la = rv["lint_before"], rv["lint_after"]
        rb, ra = sum(rv["repeats_before"].values()), sum(rv["repeats_after"].values())
        pw = w.get("pairwise", {}).get("result", "-")
        sx = w.get("sections")
        sec = f"{sx['post']}/{sx['pre']}/{sx['tie']} ({sx['sections']}절)" if sx else "-"
        cl = w.get("clarity")
        if cl:
            j9 = f"{cl['pre']['dependent']}/{cl['pre']['answered']}→{cl['post']['dependent']}/{cl['post']['answered']}"
            un = f"{cl['pre']['unclear']}→{cl['post']['unclear']}"
            noise = f"{cl['aligned']['flips']}/{cl['aligned']['unchanged_items']}"
        else:
            j9 = un = noise = "-"
        fd = w.get("fidelity")
        if fd:
            fid = (f"{len(fd['pre']['unsupported'])}/{len(fd['pre']['contradicted'])}→"
                   f"{len(fd['post']['unsupported'])}/{len(fd['post']['contradicted'])}")
            intro = str(fd["introduced"])
        else:
            fid = intro = "-"
        st = w.get("style")
        if st:
            j5 = f"{_avg(st['pre'], 'J5')}→{_avg(st['post'], 'J5')}"
            j8 = f"{_avg(st['pre'], 'J8')}→{_avg(st['post'], 'J8')}"
            rq = f"{_rp(st['pre'])}→{_rp(st['post'])}"
        else:
            j5 = j8 = rq = "-"
        us = rv.get("usage_after_start") or {}
        row = [c, f"{rv['changed']}/{rv['sentences'][0]} ({rv['changed_share'] * 100:.0f}%)",
               f"{rv['chars'][0]:,}→{rv['chars'][1]:,}",
               f"{lb['gate_fail']}/{lb['fail']}/{lb['warn']}→{la['gate_fail']}/{la['fail']}/{la['warn']}",
               f"{rb}→{ra}", pw, sec, j9, un, noise, fid, intro, j5, j8, rq,
               f"{us.get('time_share', '-')} / {us.get('minutes_after_start', '-')}분"]
        print("| " + " | ".join(row) + " |")
    hum = judge.get("within_humans", {})
    if hum:
        u, a = sum(v["dependent"] for v in hum.values()), sum(v["answered"] for v in hum.values())
        un = sum(v["unclear"] for v in hum.values())
        print(f"\n합니다체 사람 글 대조군 {len(hum)}편 J9: {u}/{a}({u / a:.3f}), unclear {un}")
    for c, r in judge.get("cross", {}).items():
        print(f"cross {c} vs {r['against']}: {r['result']}")


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except AttributeError:
        pass
    ap = argparse.ArgumentParser()
    ap.add_argument("--iter", required=True)
    ap.add_argument("--work", default=DEFAULT_WORK)
    ap.add_argument("--within", action="store_true")
    args = ap.parse_args()
    d = os.path.join(args.work, args.iter)
    judge = {}
    if os.path.exists(os.path.join(d, "judge.json")):
        judge = json.load(open(os.path.join(d, "judge.json"), encoding="utf-8"))
    if args.within:
        within_table(d, judge)
        return
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
