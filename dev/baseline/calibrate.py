#!/usr/bin/env python3
"""사람 글 측정값(stats.json)으로 lint 기준치(thresholds.json)를 다시 만든다.

- 기준치는 holdout이 아닌 사람 글에서 잡는다(holdout은 20%).
- upper: PASS ≤ p95, WARN ≤ max(p99, 최댓값)에 여유(횟수 +1, 비율 ×1.2) / lower: PASS ≥ p5, WARN ≥ min(p1, 최솟값)×0.8 / range: 같은 방식
- info: 점수에 넣지 않고 사람 글 p10/p50/p90만 기록한다.
- poisson: 사람 글 전체 1,000자당 비율(pooled rate)
- 어투별 지표(tone 지정)는 해당 어투 그룹만, 나머지는 두 어투를 합쳐서 잡는다.
- 만든 기준치로 holdout 사람 글을 판정해 통과율과 항목별 FAIL·WARN 비율을 보고한다.

사용법
  python dev/baseline/calibrate.py [--stats dev/baseline/stats.json] [--write]
"""

import argparse
import json
import math
import os
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(ROOT, "skills", "techblog", "scripts"))
import lint_ko as L  # noqa: E402

THRESHOLDS = os.path.join(ROOT, "skills", "techblog", "scripts", "thresholds.json")
REPORT = os.path.join(ROOT, "dev", "baseline", "README.md")
CALIB_GROUPS = ("default", "casual")
# 사람 글에는 적용하지 않는 Gate: 사용자 요구로 정한 어투 규칙
TONE_RULES = ("G4.off_tone", "G4.banned_ending")
COUNT_METRICS_INT = True


def pct(values, q):
    if not values:
        return 0.0
    v = sorted(values)
    if len(v) == 1:
        return float(v[0])
    pos = (len(v) - 1) * q
    lo = math.floor(pos)
    hi = math.ceil(pos)
    return float(v[lo] + (v[hi] - v[lo]) * (pos - lo))


def is_count_metric(mid, values):
    return all(float(x).is_integer() for x in values) and not mid.endswith(("_ratio", "_per_1k", "_cv", "_mean"))


def round_limit(mid, x, values, up=True):
    if is_count_metric(mid, values):
        return int(math.ceil(x)) if up else int(math.floor(x))
    return round(x, 3)


def calibrate(stats, template):
    arts = stats["articles"]
    calib = [a for a in arts if a["group"] in CALIB_GROUPS and not a["holdout"]]
    new = json.loads(json.dumps(template))
    notes = {}
    for mid, spec in new["metrics"].items():
        if "by_tone" in spec and spec.get("kind") == "upper" and not spec.get("fixed"):
            for tone in CALIB_GROUPS:
                tv = [a["metrics"][mid] for a in calib if a["group"] == tone and mid in a["metrics"]]
                if tv:
                    pm = round_limit(mid, pct(tv, 0.95), tv)
                    top = max(pct(tv, 0.99), max(tv))
                    top = top + 1 if is_count_metric(mid, tv) else top * 1.2
                    spec["by_tone"][tone] = {"pass_max": pm, "warn_max": max(pm, round_limit(mid, top, tv)), "n": len(tv)}
            continue
        kind = spec.get("kind")
        pool = [a for a in calib if (not spec.get("tone") or a["group"] == spec["tone"])
                and a["site"] not in spec.get("exclude_sites", [])]
        vals = [a["metrics"][mid] for a in pool if mid in a["metrics"]]
        if kind == "gate" or spec.get("fixed") or not vals:
            continue
        if kind == "info":
            spec["human"] = {"p10": round(pct(vals, .1), 3), "p50": round(pct(vals, .5), 3),
                             "p90": round(pct(vals, .9), 3), "n": len(vals)}
            continue
        if kind == "poisson":
            cnt = sum(a["metrics"].get(mid, 0) for a in pool)
            chars = sum(a["chars"] for a in pool)
            spec["rate_per_1k"] = round(cnt / chars * 1000, 3) if chars else spec["rate_per_1k"]
            notes[mid] = f"pooled {cnt}회 / {chars:,}자"
        elif kind == "upper":
            spec["pass_max"] = round_limit(mid, pct(vals, 0.95), vals)
            top = max(pct(vals, 0.99), max(vals))
            # 기준치를 만든 글이 40편 안팎이라 최댓값이 불안정하다. FAIL 경계에 여유를 둔다.
            top = top + 1 if is_count_metric(mid, vals) else top * 1.2
            spec["warn_max"] = max(spec["pass_max"], round_limit(mid, top, vals))
        elif kind == "lower":
            spec["pass_min"] = round_limit(mid, pct(vals, 0.05), vals, up=False)
            bottom = min(pct(vals, 0.01), min(vals)) * 0.8
            spec["warn_min"] = min(spec["pass_min"], round_limit(mid, bottom, vals, up=False))
        elif kind == "range":
            spec["pass"] = [round(pct(vals, 0.05), 3), round(pct(vals, 0.95), 3)]
            spec["warn"] = [round(min(pct(vals, 0.01), min(vals)) * 0.8, 3), round(max(pct(vals, 0.99), max(vals)) * 1.2, 3)]
        spec["n"] = len(vals)
    try:
        commit = subprocess.run(["git", "-C", ROOT, "rev-parse", "--short", "HEAD"], capture_output=True,
                                text=True).stdout.strip()
    except OSError:
        commit = ""
    n_by = {g: sum(1 for a in calib if a["group"] == g) for g in CALIB_GROUPS}
    new["version"] = "v1"
    new["generated_at"] = time.strftime("%Y-%m-%d")
    new["basis"] = (f"사람 글 baseline(dev/baseline/stats.json, holdout 제외) Default {n_by['default']}편, "
                    f"Casual {n_by['casual']}편. calibrate.py가 생성. 기준 commit {commit}")
    return new, notes


def judge_article(a, thresholds, skip=()):
    tone = a["group"].replace("drift-", "")
    res = {}
    for mid, spec in thresholds["metrics"].items():
        if mid in skip or mid not in a["metrics"] or spec.get("policy"):
            continue
        if spec.get("tone") and spec["tone"] != tone:
            continue
        if "by_tone" in spec:
            spec = dict(spec, **spec["by_tone"].get(tone, {}))
        status, _ = L.judge(a["metrics"][mid], spec, a["chars"])
        if spec.get("min_chars") and a["chars"] < spec["min_chars"] and status != "GATE":
            status = "INFO"
        res[mid] = status
    gate = sum(1 for s in res.values() if s == "GATE")
    fail = sum(1 for s in res.values() if s == "FAIL")
    warn = sum(1 for s in res.values() if s == "WARN")
    verdict = "PASS" if gate == 0 and fail == 0 and warn <= thresholds.get("max_warn", 3) else "FAIL"
    return verdict, res


def report(stats, thresholds, notes):
    arts = stats["articles"]
    lines = ["# 사람 글 baseline", "",
             "토스·카카오·당근 기술 블로그 글을 `lint_ko.py`로 측정한 값이다. `calibrate.py`가 이 값으로 "
             "`skills/techblog/scripts/thresholds.json`을 만든다. 원문은 저장소에 두지 않고 URL 목록(`urls.json`)과 "
             "측정값(`stats.json`)만 둔다.", "",
             "## 그룹", "",
             "- default: 합니다체 글(어투 90% 이상), 2022-11-30 이전",
             "- casual: 해요체 글(어투 90% 이상), 2024-06-30 이전. 2022-11-30 이전 해요체 글이 부족해서 기간을 넓혔다.",
             "- drift-*: 2025년 이후 글. 기준치에는 쓰지 않고 비교만 한다.",
             "- holdout: 글 ID 해시로 20%를 떼어 기준치 계산에서 빼고, 통과율 검증에만 쓴다.", "",
             "| 그룹 | 편수 | holdout | 토스 | 카카오 | 당근 |", "|---|---|---|---|---|---|"]
    for g, s in sorted(stats["groups"].items()):
        lines.append(f"| {g} | {s['n']} | {s['holdout']} | {s['sites'].get('toss', 0)} | "
                     f"{s['sites'].get('kakao', 0)} | {s['sites'].get('daangn', 0)} |")
    # 주요 지표 분포
    keys = ["A1.np", "A2.comma_per_sentence", "A2.comma_sentence_ratio", "A2.connective_comma_ratio",
            "A3.salience", "A4.para_end", "A5.style_words_per_1k", "A5.policy_verbs_per_1k", "A6.calque",
            "A8.sent_len_mean", "A8.sent_len_cv", "A8.long_ratio", "A8.ending_run4", "A8.ending_top_share",
            "A8.sentences_per_para", "A8.single_para_ratio", "A9.bold_per_1k",
            "A9.list_ratio", "A9.heading_per_1k", "A10.triad_per_1k", "A11.body_questions",
            "A13.demonstrative_start_per_1k", "A14.translationese_per_1k", "T.jyo_ratio", "T.geudeun_ratio",
            "T.kkayo_ratio"]
    lines += ["", "## 지표 분포 (holdout 제외, 그룹별 p10 / p50 / p90)", "",
              "| 지표 | default | casual | drift-default | drift-casual |", "|---|---|---|---|---|"]
    for k in keys:
        row = [k]
        for g in ("default", "casual", "drift-default", "drift-casual"):
            vals = [a["metrics"][k] for a in arts if a["group"] == g and not a["holdout"] and k in a["metrics"]]
            if k.startswith("T.") and g.endswith("default") and k != "T.kkayo_ratio":
                row.append("-")
                continue
            row.append(f"{pct(vals, .1):.2f} / {pct(vals, .5):.2f} / {pct(vals, .9):.2f}" if vals else "-")
        lines.append("| " + " | ".join(row) + " |")
    # Gate 위반 비율
    lines += ["", "## 사람 글의 Gate 위반 비율", "",
              "Gate는 사람 글에서 거의 나오지 않아야 한다. policy 표시가 있는 항목은 이 스킬의 출력에만 적용하는 규칙"
              "(자료를 정리하는 글이라 경험담·이모지·자료 메타 언급을 쓰지 않음, 맞춤법 규정, 어투 통일)이라 사람 글 판정에서 뺀다.", "",
              "| Gate | 구분 | default | casual |", "|---|---|---|---|"]
    for mid, spec in thresholds["metrics"].items():
        if spec.get("kind") != "gate":
            continue
        row = [mid, "policy" if spec.get("policy") else "사람 글 기준"]
        for g in ("default", "casual"):
            pool = [a for a in arts if a["group"] == g]
            v = sum(1 for a in pool if a["metrics"].get(mid, 0) > 0)
            row.append(f"{v}/{len(pool)}")
        lines.append("| " + " | ".join(row) + " |")
    # holdout 통과율
    hold = [a for a in arts if a["holdout"] and a["group"] in CALIB_GROUPS]
    passed = 0
    stat_count = {}
    for a in hold:
        verdict, res = judge_article(a, thresholds)
        passed += verdict == "PASS"
        for mid, s in res.items():
            if s in ("FAIL", "WARN", "GATE"):
                stat_count.setdefault(mid, {"FAIL": 0, "WARN": 0, "GATE": 0})[s] += 1
    rate = passed / len(hold) if hold else 0.0
    lines += ["", "## holdout 검증", "",
              f"기준치를 만들 때 쓰지 않은 사람 글 {len(hold)}편 중 {passed}편이 통과했다(통과율 {rate:.0%}). "
              "목표는 85% 이상이다. 통과 조건은 스킬 출력과 같다(Gate 0, FAIL 0, WARN 3 이하). policy Gate는 뺀다.", "",
              "| 지표 | FAIL | WARN | GATE |", "|---|---|---|---|"]
    for mid, c in sorted(stat_count.items(), key=lambda kv: -(kv[1]["FAIL"] * 3 + kv[1]["GATE"] * 3 + kv[1]["WARN"])):
        lines.append(f"| {mid} | {c['FAIL']} | {c['WARN']} | {c['GATE']} |")
    if notes:
        lines += ["", "## pooled rate", ""] + [f"- {k}: {v}" for k, v in notes.items()]
    return "\n".join(lines) + "\n", rate


def main():
    L.setup_stdio()
    ap = argparse.ArgumentParser()
    ap.add_argument("--stats", default=os.path.join(ROOT, "dev", "baseline", "stats.json"))
    ap.add_argument("--write", action="store_true", help="thresholds.json과 README.md를 덮어쓴다")
    args = ap.parse_args()
    stats = json.load(open(args.stats, encoding="utf-8"))
    template = json.load(open(THRESHOLDS, encoding="utf-8"))
    new, notes = calibrate(stats, template)
    text, rate = report(stats, new, notes)
    print(text)
    if args.write:
        with open(THRESHOLDS, "w", encoding="utf-8", newline="\n") as f:
            f.write(json.dumps(new, ensure_ascii=False, indent=2) + "\n")
        with open(REPORT, "w", encoding="utf-8", newline="\n") as f:
            f.write(text)
        print(f"[write] {THRESHOLDS}, {REPORT}")


if __name__ == "__main__":
    main()
