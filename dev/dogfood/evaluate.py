#!/usr/bin/env python3
"""dogfooding 실행 결과를 결정적으로 점검한다(LLM judge는 judge.py).

케이스 폴더마다
- run.jsonl(stream-json)에서 도구 호출 순서, 권한 거부, 비용, turn 수를 읽는다.
- 스킬이 lint_ko.py와 tone_check.py를 실제로 실행했는지, Default 초안을 Casual보다 먼저 썼는지 본다.
- article.md에 lint_ko.py를 다시 돌리고, Casual이면 초안과 tone_check.py를 다시 돌린다.
- 결과를 eval.json에 쓰고 요약 표를 출력한다.

사용법
  python dev/dogfood/evaluate.py --iter iter-1 [--work DIR]
"""

import argparse
import json
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SCRIPTS = os.path.join(ROOT, "skills", "techblog", "scripts")
DEFAULT_WORK = os.path.join(os.environ.get("TEMP", "/tmp"), "techblog-work", "dogfood")
KEY_METRICS = ("A1.np", "A2.comma_per_sentence", "A2.connective_comma_ratio", "A3.salience", "A4.para_end",
               "A5.style_words_per_1k", "A8.sent_len_mean", "A8.sent_len_cv", "A8.long_ratio", "A8.ending_run4",
               "A9.bold_per_1k", "A9.list_ratio", "A10.triad_per_1k", "A13.demonstrative_start_per_1k")


def parse_transcript(path):
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
            if t == "system" and e.get("subtype") == "init":
                init = {"model": e.get("model"), "permissionMode": e.get("permissionMode"),
                        "techblog_loaded": any("techblog" in str(s) for s in e.get("skills", []))}
            elif t == "assistant":
                for c in e.get("message", {}).get("content", []):
                    if c.get("type") == "tool_use":
                        tools.append({"id": c.get("id"), "name": c.get("name"), "input": c.get("input", {}), "error": False})
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
    init, tools, result = parse_transcript(os.path.join(case_dir, "run.jsonl"))
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
        if e["denials"]:
            print("denials:", json.dumps(e["denials"], ensure_ascii=False)[:500])


if __name__ == "__main__":
    main()
