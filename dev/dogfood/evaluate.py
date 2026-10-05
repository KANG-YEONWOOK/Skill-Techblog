#!/usr/bin/env python3
"""dogfooding 실행 결과를 결정적으로 점검한다(LLM judge는 judge.py).

케이스 폴더마다
- run.jsonl(stream-json)에서 도구 호출 순서, 권한 거부, 비용, turn 수를 읽는다.
- 스킬이 lint_ko.py와 tone_check.py를 실제로 실행했는지, Default 초안을 Casual보다 먼저 썼는지 본다.
- article.md에 lint_ko.py를 다시 돌리고, Casual이면 초안과 tone_check.py를 다시 돌린다.
- 후처리(6단계): 초안 사본(article.unrevised.md)과 후처리를 마친 합니다체 글(Default는 article.md, Casual은
  article.draft.md)을 revise_ko.compare로 비교하고, 반복 후보 수, revise_ko.py 실행 순서, start 이후의 토큰 비율,
  context compaction 횟수를 기록한다.
- 결과를 eval.json에 쓰고 요약 표를 출력한다.

사용법
  python dev/dogfood/evaluate.py --iter iter-1 [--work DIR]
"""

import argparse
import datetime
import json
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SCRIPTS = os.path.join(ROOT, "skills", "techblog", "scripts")
sys.path.insert(0, SCRIPTS)
import lint_ko as L  # noqa: E402
import revise_ko as RV  # noqa: E402
DEFAULT_WORK = os.path.join(os.environ.get("TEMP", "/tmp"), "techblog-work", "dogfood")
KEY_METRICS = ("A1.np", "A2.comma_per_sentence", "A2.connective_comma_ratio", "A3.salience", "A4.para_end",
               "A5.style_words_per_1k", "A8.sent_len_mean", "A8.sent_len_cv", "A8.long_ratio", "A8.ending_run4",
               "A9.bold_per_1k", "A9.list_ratio", "A10.triad_per_1k", "A13.demonstrative_start_per_1k")


def parse_transcript(path, events=None):
    """도구 호출 목록, init, result를 돌려준다. events에 list를 주면 순서대로 ("ts", timestamp),
    ("tool", 도구 번호), ("usage", 메시지 id, usage), ("compact",) 항목을 채운다."""
    tools, init, result = [], {}, {}
    if not os.path.exists(path):
        return init, tools, result
    with open(path, encoding="utf-8", errors="replace") as f:
        for line in f:
            try:
                e = json.loads(line)
            except ValueError:
                continue
            t = e.get("type")
            if events is not None and e.get("timestamp"):
                events.append(("ts", e["timestamp"]))
            if t == "system" and e.get("subtype") == "init":
                init = {"model": e.get("model"), "permissionMode": e.get("permissionMode"),
                        "techblog_loaded": any("techblog" in str(s) for s in e.get("skills", []))}
            elif t == "assistant":
                msg = e.get("message", {})
                if events is not None and msg.get("usage"):
                    events.append(("usage", msg.get("id"), msg["usage"]))
                for c in msg.get("content", []):
                    if c.get("type") == "tool_use":
                        tools.append({"id": c.get("id"), "name": c.get("name"), "input": c.get("input", {}), "error": False})
                        if events is not None:
                            events.append(("tool", len(tools) - 1))
            elif t == "system" and e.get("subtype") == "compact_boundary" and events is not None:
                events.append(("compact",))
            elif t == "user":
                content = e.get("message", {}).get("content")
                if isinstance(content, list):
                    for c in content:
                        if c.get("type") == "tool_result" and c.get("is_error"):
                            for tl in tools:
                                if tl["id"] == c.get("tool_use_id"):
                                    tl["error"] = True
            elif t == "result":
                result = {k: e.get(k) for k in ("is_error", "num_turns", "duration_ms", "total_cost_usd",
                                                "permission_denials", "subtype")}
    return init, tools, result


def final_default(case_dir, tone):
    """후처리를 마친 합니다체 글. Casual 케이스는 Default 초안(article.draft.md)이다."""
    if tone == "casual" and os.path.isfile(os.path.join(case_dir, "article.draft.md")):
        return os.path.join(case_dir, "article.draft.md")
    return os.path.join(case_dir, "article.md")


def _ts(v):
    try:
        return datetime.datetime.fromisoformat(v.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return None


def _usage_share(events, start_tool):
    """start 명령 이후의 입력 토큰 비율과 경과 시간 비율.
    stream-json의 assistant 이벤트는 메시지 시작 시점의 사용량만 담아서 출력 토큰은 메시지별로 셀 수 없다.
    입력 토큰(cache 포함)은 메시지마다 한 번만 센다."""
    seen, total, after = set(), 0, 0
    passed, first, last, start = False, None, None, None
    for ev in events:
        if ev[0] == "ts":
            t = _ts(ev[1])
            if t is not None:
                first = first or t
                last = t
            continue
        if ev[0] == "tool" and ev[1] == start_tool and not passed:
            passed, start = True, last
        if ev[0] != "usage" or ev[1] in seen:
            continue
        seen.add(ev[1])
        u = ev[2]
        inp = sum(u.get(k) or 0 for k in ("input_tokens", "cache_creation_input_tokens", "cache_read_input_tokens"))
        total += inp
        if passed:
            after += inp
    out = {"input_share": round(after / total, 3) if total else None}
    if first and last and start:
        whole = (last - first).total_seconds()
        out["minutes_after_start"] = round((last - start).total_seconds() / 60, 1)
        out["time_share"] = round((last - start).total_seconds() / whole, 3) if whole else None
    return out


def revise_summary(case_dir, tone, tools, events):
    """6단계 후처리를 점검한다. 초안 사본이 없으면 None."""
    snap = os.path.join(case_dir, "article.unrevised.md")
    if not os.path.isfile(snap):
        return None
    post = final_default(case_dir, tone)
    target = os.path.basename(post)
    facts = os.path.join(case_dir, "article.facts.md")
    facts_text = L.read_text(facts) if os.path.isfile(facts) else None
    res = RV.compare(L.read_text(snap), L.read_text(post), facts_text)

    def cmd_index(sub):
        for i, t in enumerate(tools):
            c = t["input"].get("command", "") if t["name"] in ("Bash", "PowerShell") else ""
            if "revise_ko.py" in c and f" {sub} " in c + " ":
                return i
        return None

    def path_of(t):
        return os.path.basename(str(t["input"].get("file_path", "")))

    i_start, i_rep, i_check = cmd_index("start"), cmd_index("repeats"), cmd_index("check")
    edits_after = sum(1 for i, t in enumerate(tools)
                      if i_start is not None and i > i_start and t["name"] in ("Edit", "Write") and path_of(t) == target)
    read_before_repeats = None
    if i_start is not None and i_rep is not None:
        read_before_repeats = any(t["name"] == "Read" and path_of(t) == target for t in tools[i_start + 1:i_rep])

    def counts(path):
        c = {}
        for x in RV.find_repeats(L.read_text(path))["candidates"]:
            c[x["id"]] = c.get(x["id"], 0) + 1
        return c
    return {"target": target, "sentences": res["sentences"], "changed": res["changed"], "written": res["written"],
            "changed_share": res["changed_share"], "chars": res["structure"]["chars"],
            "headings_same": res["structure"]["headings_same"], "code_same": res["structure"]["code_same"],
            "tables": res["structure"]["tables"],
            "lost_numbers": [x["raw"] for x in res["lost_numbers"]],
            "new_numbers": [[x["raw"], x["in_facts"]] for x in res["new_numbers"]],
            "lint_before": res["lint_before"], "lint_after": res["lint_after"],
            "worse_ai": [f"{r['status']} {r['id']}={r['value']}" for r in res["worse_ai"]],
            "worse_dist": [f"{r['status']} {r['id']}={r['value']}" for r in res["worse_dist"]],
            "long_new": len(res["long_new"]), "must_fix": res["must_fix"],
            "repeats_before": counts(snap), "repeats_after": counts(post),
            "ran": {"start": i_start is not None, "repeats": i_rep is not None, "check": i_check is not None},
            "read_before_repeats": read_before_repeats, "edits_after_start": edits_after,
            "usage_after_start": _usage_share(events, i_start) if i_start is not None else None,
            "compactions": sum(1 for ev in events if ev[0] == "compact")}


def run_json(cmd):
    p = subprocess.run([sys.executable] + cmd, capture_output=True)
    out = p.stdout.decode("utf-8", "replace")
    try:
        return json.loads(out)
    except ValueError:
        return {"error": out[:500] + p.stderr.decode("utf-8", "replace")[:500]}


def evaluate_case(case_dir):
    meta = json.load(open(os.path.join(case_dir, "meta.json"), encoding="utf-8"))
    case = meta["case"]
    tone = case.get("tone", "default")
    events = []
    init, tools, result = parse_transcript(os.path.join(case_dir, "run.jsonl"), events)
    bash = [t["input"].get("command", "") for t in tools if t["name"] in ("Bash", "PowerShell")]
    writes = [os.path.basename(t["input"].get("file_path", "")) for t in tools if t["name"] == "Write"]
    reads = [t["input"] for t in tools if t["name"] == "Read" and str(t["input"].get("file_path", "")).endswith(".pdf")]
    ev = {
        "case": case["name"], "mode": case.get("mode", "skill"), "tone": tone,
        "exit": meta.get("exit"), "seconds": meta.get("seconds"), "claude_version": meta.get("claude_version"),
        "model": init.get("model"), "turns": result.get("num_turns"), "cost_usd": result.get("total_cost_usd"),
        "is_error": result.get("is_error"), "denials": result.get("permission_denials") or [],
        "lint_runs": sum("lint_ko.py" in b for b in bash),
        "tone_runs": sum("tone_check.py" in b and "--cleanup" not in b for b in bash),
        "cleanup_runs": sum("--cleanup" in b for b in bash),
        "pdf_reads": [r.get("pages") for r in reads],
        "writes": writes,
        "tool_errors": [t["name"] for t in tools if t["error"]],
    }
    if "article.draft.md" in writes and "article.md" in writes:
        ev["draft_before_final"] = writes.index("article.draft.md") < writes.index("article.md")
    art = os.path.join(case_dir, "article.md")
    facts = os.path.join(case_dir, "article.facts.md")
    draft = os.path.join(case_dir, "article.draft.md")
    if case.get("mode") == "retone":
        draft = os.path.join(case_dir, "input.md")
    if os.path.exists(art):
        cmd = [os.path.join(SCRIPTS, "lint_ko.py"), art, "--tone", tone, "--json"]
        if os.path.exists(facts):
            cmd += ["--facts", facts]
        lint = run_json(cmd)
        ev["lint"] = summarize_lint(lint)
        if tone == "casual" and os.path.exists(draft):
            tc = run_json([os.path.join(SCRIPTS, "tone_check.py"), draft, art, "--json"])
            ev["tone_check"] = {k: tc.get(k) for k in ("verdict", "pairs", "fail", "warn")}
            ev["tone_check"]["issues"] = [f"{i['level']} {i['code']} {i['note']}" for i in tc.get("issues", [])][:10]
            dl = run_json([os.path.join(SCRIPTS, "lint_ko.py"), draft, "--tone", "default", "--json"]
                          + (["--facts", facts] if os.path.exists(facts) else []))
            ev["draft_lint"] = summarize_lint(dl)
    else:
        ev["lint"] = {"verdict": "NO_ARTICLE"}
    rv = revise_summary(case_dir, tone, tools, events)
    if rv:
        ev["revise"] = rv
        snap_lint = run_json([os.path.join(SCRIPTS, "lint_ko.py"), os.path.join(case_dir, "article.unrevised.md"),
                              "--tone", "default", "--json"] + (["--facts", facts] if os.path.exists(facts) else []))
        ev["unrevised_lint"] = summarize_lint(snap_lint)
    with open(os.path.join(case_dir, "eval.json"), "w", encoding="utf-8") as f:
        json.dump(ev, f, ensure_ascii=False, indent=1)
    return ev


def summarize_lint(lint):
    if "summary" not in lint:
        return {"verdict": "ERROR", "detail": lint.get("error", "")[:300]}
    res = {r["id"]: r for r in lint["results"]}
    bad = [f"{r['status']} {r['id']}={r['value']}" for r in lint["results"] if r["status"] in ("GATE", "FAIL", "WARN")]
    return {"verdict": lint["summary"]["verdict"], "gate": lint["summary"]["gate_fail"],
            "fail": lint["summary"]["fail"], "warn": lint["summary"]["warn"], "chars": lint["stats"]["chars"],
            "sentences": lint["stats"]["sentences"], "title": lint["stats"].get("title"), "issues": bad,
            "metrics": {k: res[k]["value"] for k in KEY_METRICS if k in res}}


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except AttributeError:
        pass
    ap = argparse.ArgumentParser()
    ap.add_argument("--iter", required=True)
    ap.add_argument("--work", default=DEFAULT_WORK)
    ap.add_argument("--only", nargs="*")
    args = ap.parse_args()
    iter_dir = os.path.join(args.work, args.iter)
    rows = []
    for name in sorted(os.listdir(iter_dir)):
        d = os.path.join(iter_dir, name)
        if not os.path.isfile(os.path.join(d, "meta.json")) or (args.only and name not in args.only):
            continue
        rows.append(evaluate_case(d))
    print("| case | lint | G/F/W | 글자 | tone_check | lint 실행 | 거부 | turn | 비용$ | 분 |")
    print("|---|---|---|---|---|---|---|---|---|---|")
    for e in rows:
        l = e.get("lint", {})
        tc = e.get("tone_check", {}).get("verdict", "-")
        print(f"| {e['case']} | {l.get('verdict')} | {l.get('gate')}/{l.get('fail')}/{l.get('warn')} | {l.get('chars')} | "
              f"{tc} | {e['lint_runs']} | {len(e['denials'])} | {e['turns']} | {e['cost_usd']} | "
              f"{round((e['seconds'] or 0) / 60, 1)} |")
    for e in rows:
        l = e.get("lint", {})
        print(f"\n## {e['case']}  {l.get('title')}")
        print("lint:", "; ".join(l.get("issues", [])) or "-")
        if e.get("draft_lint"):
            print("draft lint:", e["draft_lint"].get("verdict"), "; ".join(e["draft_lint"].get("issues", [])))
        if e.get("tone_check"):
            print("tone_check:", e["tone_check"])
        print("metrics:", json.dumps(l.get("metrics", {}), ensure_ascii=False))
        print("writes:", e["writes"], "| pdf pages:", e["pdf_reads"], "| draft_before_final:", e.get("draft_before_final"))
        rv = e.get("revise")
        if rv:
            lb, la = rv["lint_before"], rv["lint_after"]
            print(f"revise: {rv['target']} 바뀐 문장 {rv['changed']}/{rv['sentences'][0]}({rv['changed_share']}) "
                  f"새 문장 {rv['written']} 글자 {rv['chars'][0]}→{rv['chars'][1]} 헤딩 같음={rv['headings_same']} "
                  f"표 {rv['tables']} lint {lb['gate_fail']}/{lb['fail']}/{lb['warn']}→{la['gate_fail']}/{la['fail']}/{la['warn']}")
            print(f"    실행 {rv['ran']} 읽고 나서 repeats={rv['read_before_repeats']} start 뒤 Edit {rv['edits_after_start']} "
                  f"compaction {rv['compactions']} 토큰 비율 {rv['usage_after_start']}")
            print(f"    반복 후보 {rv['repeats_before']} → {rv['repeats_after']} | 사라진 수치 {rv['lost_numbers']} | "
                  f"새 수치 {rv['new_numbers']} | AI 악화 {rv['worse_ai']} | 분포 악화 {rv['worse_dist']} | "
                  f"긴 새 문장 {rv['long_new']}")
        if e["denials"]:
            print("denials:", json.dumps(e["denials"], ensure_ascii=False)[:500])


if __name__ == "__main__":
    main()
