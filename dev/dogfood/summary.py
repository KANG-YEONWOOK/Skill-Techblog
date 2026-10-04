#!/usr/bin/env python3
"""사람 글 baseline, 스킬 없는 Claude, 스킬 Default, 스킬 Casual의 지표를 한 표로 모은다(README 비교표).

- 사람 글: dev/baseline/stats.json의 default, casual 그룹(2025년 이전 글) 중앙값
- 생성 글: article.md를 lint_ko.py로 다시 잰 값, eval.json의 lint 판정, judge.json(style, fidelity). 케이스 값의 중앙값
  케이스는 `<iteration>/<case>` 형식으로 지정한다. mode가 baseline이면 "스킬 없음", 아니면 tone별로 묶는다.

사용법
  python dev/dogfood/summary.py --runs iter-0/A0-antislop-baseline iter-6/A-antislop-casual ...
"""

import argparse
import json
import os
import statistics
import sys

ROOT_FOR_IMPORT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(ROOT_FOR_IMPORT, "skills", "techblog", "scripts"))
import lint_ko as L  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DEFAULT_WORK = os.path.join(os.environ.get("TEMP", "/tmp"), "techblog-work", "dogfood")
METRICS = (
    ("chars", "본문 글자 수(공백 제외)", 0),
    ("A9.list_ratio", "목록 줄 비율", 3),
    ("A9.bold_per_1k", "bold(1,000자당)", 2),
    ("A10.triad_per_1k", "셋 묶음 나열(1,000자당)", 2),
    ("A2.connective_comma_ratio", "연결어미 뒤 쉼표 비율", 3),
    ("A1.np", "부정 대구(X가 아니라 Y) 문장 수", 1),
    ("A8.ending_top_share", "가장 많은 종결의 비율", 2),
    ("A8.sent_len_mean", "평균 문장 길이(공백 포함)", 1),
    ("A8.single_para_ratio", "한 문장 문단 비율", 2),
)
COLUMNS = (("human-default", "사람 글 합니다체"), ("human-casual", "사람 글 해요체"),
           ("baseline", "스킬 없는 Claude"), ("default", "스킬 Default"), ("casual", "스킬 Casual"))


def med(values, nd):
    values = [v for v in values if isinstance(v, (int, float))]
    if not values:
        return "-"
    m = statistics.median(values)
    return f"{m:,.0f}" if nd == 0 else f"{m:.{nd}f}"


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except AttributeError:
        pass
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs", nargs="+", required=True, help="<iteration>/<case> 목록")
    ap.add_argument("--work", default=DEFAULT_WORK)
    args = ap.parse_args()

    cols = {k: {"metrics": {}, "n": 0, "lint_pass": 0, "fid": [], "style": [], "j7": [], "cases": []} for k, _ in COLUMNS}
    stats = json.load(open(os.path.join(ROOT, "dev", "baseline", "stats.json"), encoding="utf-8"))
    for a in stats["articles"]:
        if a.get("included") and a.get("group") in ("default", "casual"):
            col = cols["human-" + a["group"]]
            col["n"] += 1
            m = dict(a["metrics"], chars=a["chars"])
            for key, _, _ in METRICS:
                col["metrics"].setdefault(key, []).append(m.get(key))

    judges = {}
    for spec in args.runs:
        it, case = spec.split("/", 1)
        d = os.path.join(args.work, it, case)
        e = json.load(open(os.path.join(d, "eval.json"), encoding="utf-8"))
        if it not in judges:
            jp = os.path.join(args.work, it, "judge.json")
            judges[it] = json.load(open(jp, encoding="utf-8")) if os.path.exists(jp) else {}
        key = "baseline" if e.get("mode") == "baseline" else e.get("tone", "default")
        col = cols[key]
        col["n"] += 1
        col["cases"].append(spec)
        lint = e.get("lint", {})
        # eval.json에는 주요 지표만 있으므로 글을 다시 재서 모든 지표를 쓴다.
        a = L.analyze(L.read_text(os.path.join(d, "article.md")))
        m = {k: v["value"] for k, v in a["metrics"].items()}
        m["chars"] = a["stats"]["chars"]
        for k, _, _ in METRICS:
            col["metrics"].setdefault(k, []).append(m.get(k))
        if lint.get("verdict") == "PASS":
            col["lint_pass"] += 1
        fd = judges[it].get("fidelity", {}).get(case)
        if fd:
            col["fid"].append(len(fd["unsupported"]) + len(fd["contradicted"]))
        st = judges[it].get("style", {}).get(case)
        if st:
            sc = [v for r in st["runs"] for v in r["scores"].values()]
            col["style"].append(sum(sc) / len(sc))
            col["j7"].extend(r["j7_per_1k"] for r in st["runs"])

    print("| 지표 | " + " | ".join(f"{name} (n={cols[k]['n']})" for k, name in COLUMNS) + " |")
    print("|---|" + "---|" * len(COLUMNS))
    for key, label, nd in METRICS:
        print(f"| {label} | " + " | ".join(med(cols[k]["metrics"].get(key, []), nd) for k, _ in COLUMNS) + " |")
    gen = [k for k, _ in COLUMNS if not k.startswith("human")]
    print("| lint 통과 | - | - | " + " | ".join(f"{cols[k]['lint_pass']}/{cols[k]['n']}" for k in gen) + " |")
    print("| 자료와 다르거나 근거 없는 주장(글당) | - | - | " +
          " | ".join(med(cols[k]["fid"], 1) for k in gen) + " |")
    print("| style judge 평균(0~2) | - | - | " + " | ".join(med(cols[k]["style"], 2) for k in gen) + " |")
    print("| AI처럼 읽힌다고 인용된 문장(1,000자당) | - | - | " + " | ".join(med(cols[k]["j7"], 2) for k in gen) + " |")
    for k, name in COLUMNS:
        if cols[k]["cases"]:
            print(f"\n{name}: " + ", ".join(cols[k]["cases"]))


if __name__ == "__main__":
    main()
