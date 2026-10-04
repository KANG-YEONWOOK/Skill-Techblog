#!/usr/bin/env python3
"""dogfooding 결과를 LLM judge로 평가한다. judge는 새 `claude -p` 프로세스(기본 sonnet)로 실행한다.

- style: 이번 iteration의 글과 사람 블로그 글(대조군)을 섞어 누가 썼는지 알리지 않고 채점한다.
  J2~J6, J8 점수와 "AI가 쓴 것처럼 읽히는 문장" 인용을 받고, 인용이 원문에 그대로 있는지 확인해 J7을 센다.
- fidelity: 글의 수치·주장을 자료 원문과 대조한다(supported / unsupported / contradicted, coverage).
- pairwise: 같은 자료로 쓴 두 글(이번 iteration과 비교 대상)을 순서를 바꿔 두 번 비교한다.

사용법
  python dev/dogfood/judge.py --iter iter-1 [--compare iter-0] [--skip style fidelity pairwise]
"""

import argparse
import hashlib
import json
import os
import random
import re
import shutil
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DEFAULT_WORK = os.path.join(os.environ.get("TEMP", "/tmp"), "techblog-work")
sys.path.insert(0, os.path.join(ROOT, "skills", "techblog", "scripts"))
import lint_ko as L  # noqa: E402

MOVES = ["salience", "contrast_reframe", "summary_marker", "lesson_ending", "hedge_stack", "calque_metaphor",
         "triplet", "rhetorical_q", "translationese", "tone_slip", "generic_claim", "other"]

STYLE_SCHEMA = {
    "type": "object",
    "properties": {"texts": {"type": "array", "items": {
        "type": "object",
        "properties": {
            "label": {"type": "string"},
            "scores": {"type": "object", "properties": {k: {"type": "integer", "minimum": 0, "maximum": 2}
                                                         for k in ("J2", "J3", "J4", "J5", "J6", "J8")},
                       "required": ["J2", "J3", "J4", "J5", "J6", "J8"]},
            "ai_like": {"type": "array", "items": {"type": "object", "properties": {
                "quote": {"type": "string"}, "move": {"type": "string", "enum": MOVES},
                "lost_if_deleted": {"type": "string"}}, "required": ["quote", "move", "lost_if_deleted"]}},
            "comment": {"type": "string"}},
        "required": ["label", "scores", "ai_like", "comment"]}}},
    "required": ["texts"]}

STYLE_PROMPT = """당신은 한국 테크 기업 기술 블로그의 편집자입니다. 현재 폴더의 {files} 파일을 Read 도구로 모두 끝까지 읽고 글마다 평가하세요. 이 중 일부는 사람이 썼고 일부는 AI가 썼을 수 있습니다. 글쓴이에 대한 정보는 주지 않습니다.

글마다 아래 항목을 0~2점으로 매기세요.
- J2 구체성: 주장마다 수치, 이름, 동작 원리가 붙어 있는가. 2: 평가어만 있는 문장이 없다 / 1: 1~2개 / 0: 3개 이상
- J3 deletion test: 지워도 정보(사실, 수치, 동작 원리, 할 일)가 줄지 않는 문장(강조, 의의 부여, 예고, 교훈)이 있는가. 2: 없다 / 1: 1~2개 / 0: 3개 이상
- J4 구조: 제목이 내용을 특정하는가, 도입이 독자 상황이나 다루는 문제에서 시작하는가, 마무리가 구체 사실이나 열린 질문으로 끝나는가. 2: 모두 그렇다 / 1: 하나가 어긋난다 / 0: 둘 이상
- J5 한국어 자연스러움: 한국 개발자가 쓴 기술 블로그처럼 읽히는가. 번역투, 추상 명사 나열, 어색한 조사, 억지 번역어가 있는가. 2: 없다 / 1: 1~2곳 / 0: 3곳 이상
- J6 어투 품질: 합니다체 글이면 공문체가 아닌가, 해요체 글이면 정중하고 반말·과한 구어·이모지가 없는가, 어투가 섞이지 않았는가. 2 / 1 / 0
- J8 과교정: 문장이 지나치게 단조롭거나, 자연스러운 대조·단서·괄호 보충·긴 문장이 사라져 기계적으로 읽히는가. 2: 자연스럽다 / 1: 다소 단조롭다 / 0: 내용이나 흐름이 손상됐다

그리고 "AI가 쓴 것처럼 읽히는 문장"을 모두 찾아 ai_like에 원문 그대로 인용하세요. 인용은 글에 있는 문자열과 정확히 같아야 하고 한 문장 이내여야 합니다. 각 인용에 수사 동작(move)을 하나 고르고, 그 구절을 지우면 잃는 정보(lost_if_deleted, 없으면 "없음")를 적으세요.
move: salience(중요하다고 말하기), contrast_reframe(X가 아니라 Y), summary_marker(결국·요컨대 등), lesson_ending(문단 끝 교훈), hedge_stack(추정 중첩), calque_metaphor(번역투 표현·상투 은유), triplet(근거 없는 셋 묶음), rhetorical_q(자문자답), translationese(번역투 문장), tone_slip(어투 이탈), generic_claim(근거 없는 일반론), other.
사람이 쓴 글에도 이런 문장이 있을 수 있습니다. 실제로 그렇게 읽히는 문장만 고르세요. comment에는 글 전체에 대한 판단을 두세 문장으로 적으세요. label은 파일 이름에서 .md를 뺀 값입니다."""

FIDELITY_SCHEMA = {
    "type": "object",
    "properties": {
        "claims": {"type": "array", "items": {"type": "object", "properties": {
            "article_quote": {"type": "string"}, "source_ref": {"type": "string"},
            "verdict": {"type": "string", "enum": ["supported", "unsupported", "contradicted"]},
            "note": {"type": "string"}}, "required": ["article_quote", "source_ref", "verdict", "note"]}},
        "coverage": {"type": "object", "properties": {k: {"type": "boolean"} for k in
                                                        ("problem", "method", "results", "limitations")},
                     "required": ["problem", "method", "results", "limitations"]},
        "missing": {"type": "array", "items": {"type": "string"}},
        "j1": {"type": "integer", "minimum": 0, "maximum": 2}},
    "required": ["claims", "coverage", "missing", "j1"]}

FIDELITY_PROMPT = """현재 폴더의 article.md는 자료 {source}를 정리한 한국어 기술 블로그 글입니다. 자료를 Read 도구(또는 URL이면 WebFetch)로 끝까지 읽은 뒤 article.md의 사실 관계를 검증하세요.
1. claims: article.md에서 수치, 고유명사, 실험 결과, 인과 주장, 인용이 들어 있는 문장을 빠짐없이 뽑아 원문 그대로 인용하고(article_quote), 자료의 근거 위치(source_ref: 쪽, 절, 표)와 판정(verdict)을 적으세요.
   - supported: 자료가 그대로 뒷받침한다.
   - unsupported: 자료에서 찾을 수 없다(지어낸 수치, 경험, 출처, 사례 포함).
   - contradicted: 자료와 다르다(수치 오류, 조건이 빠져 뜻이 바뀜, 추정을 단정으로 바꿈, 대상을 혼동함).
   note에는 판정 이유를 짧게 적으세요.
2. coverage: 자료의 문제(problem), 방법(method), 핵심 결과(results), 한계(limitations)가 글에 있는지 각각 true/false로 적으세요.
3. missing: 글에 빠진 자료의 핵심 내용을 최대 5개 적으세요.
4. j1: 2 = 문제·방법·결과·한계가 모두 있다, 1 = 하나가 빠졌다, 0 = 둘 이상 빠졌거나 핵심 결과가 없다."""

PAIR_SCHEMA = {
    "type": "object",
    "properties": {"winner": {"type": "string", "enum": ["X", "Y", "tie"]},
                   "reasons": {"type": "array", "items": {"type": "string"}}},
    "required": ["winner", "reasons"]}

PAIR_PROMPT = """X.md와 Y.md는 같은 자료를 정리한 한국어 기술 블로그 글입니다. 두 글을 Read 도구로 끝까지 읽고, 한국 테크 기업 기술 블로그 편집자의 관점에서 어느 글이 나은지 고르세요.
기준(앞의 것이 더 중요): 1) 사람 개발자가 쓴 것처럼 자연스러운 한국어인가(강조 문장, 부정 대구, 요약 표지, 번역투, 상투 은유, 기계적인 리듬이 적은가) 2) 자료의 핵심을 정확하고 구체적으로 전달하는가 3) 구조와 읽기 쉬움.
어투(합니다체/해요체) 차이는 판단에 넣지 마세요. winner는 "X", "Y", "tie" 중 하나, reasons에는 판단 근거 2~4개를 각 글의 문장을 인용해 적으세요."""


def call_judge(prompt, schema, cwd, model, extra_tools=None, timeout=1800):
    tools = ["Read"] + (extra_tools or [])
    cmd = [shutil.which("claude") or "claude", "-p", prompt, "--model", model, "--output-format", "json",
           "--json-schema", json.dumps(schema, ensure_ascii=False), "--tools", ",".join(tools),
           "--disable-slash-commands", "--no-session-persistence", "--strict-mcp-config",
           "--allowedTools", ",".join(tools)]
    env = dict(os.environ)
    env.update({"CLAUDE_CODE_DISABLE_CLAUDE_MDS": "1", "CLAUDE_CODE_DISABLE_AUTO_MEMORY": "1"})
    p = subprocess.run(cmd, cwd=cwd, env=env, stdin=subprocess.DEVNULL, capture_output=True, timeout=timeout)
    out = p.stdout.decode("utf-8", "replace")
    try:
        data = json.loads(out)
    except ValueError:
        return {"error": out[:800] + p.stderr.decode("utf-8", "replace")[:400]}
    so = data.get("structured_output")
    if so is None:
        return {"error": str(data.get("result"))[:800], "cost": data.get("total_cost_usd")}
    so["_cost"] = data.get("total_cost_usd")
    return so


def _norm(s):
    return re.sub(r"\s+", " ", L.normalize_text(s)).strip()


def human_controls(work, tone, n, seed):
    """baseline 캐시에서 같은 어투, 비슷한 길이의 사람 글을 고른다."""
    stats = json.load(open(os.path.join(ROOT, "dev", "baseline", "stats.json"), encoding="utf-8"))
    pool = [a for a in stats["articles"] if a["group"] == tone and 3500 <= a["chars"] <= 10000]
    rnd = random.Random(seed)
    rnd.shuffle(pool)
    out = []
    for a in pool[:n]:
        path = os.path.join(work, "baseline", "cache", "md", a["id"] + ".md")
        if os.path.exists(path):
            out.append((a["id"], path))
    return out


def run_style(iter_dir, work, model, runs=2):
    cases = [d for d in sorted(os.listdir(iter_dir)) if os.path.isfile(os.path.join(iter_dir, d, "article.md"))]
    results = {}
    for r in range(runs):
        for tone in ("default", "casual"):
            items = []
            for c in cases:
                meta = json.load(open(os.path.join(iter_dir, c, "meta.json"), encoding="utf-8"))
                if meta["case"].get("tone", "default") == tone:
                    items.append((c, os.path.join(iter_dir, c, "article.md"), False))
            if not items:
                continue
            for hid, hpath in human_controls(work, tone, 2, seed=f"{iter_dir}-{tone}-{r}"):
                items.append((hid, hpath, True))
            rnd = random.Random(f"{iter_dir}-{tone}-{r}")
            rnd.shuffle(items)
            jdir = os.path.join(iter_dir, "_judge", f"style-{tone}-{r}")
            os.makedirs(jdir, exist_ok=True)
            labels = {}
            for i, (name, path, human) in enumerate(items, 1):
                label = f"T{i}"
                shutil.copyfile(path, os.path.join(jdir, label + ".md"))
                labels[label] = (name, human, path)
            files = ", ".join(f"{k}.md" for k in labels)
            res = call_judge(STYLE_PROMPT.format(files=files), STYLE_SCHEMA, jdir, model)
            json.dump({"labels": {k: [v[0], v[1]] for k, v in labels.items()}, "result": res},
                      open(os.path.join(jdir, "result.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
            for t in res.get("texts", []):
                if t.get("label") not in labels:
                    continue
                name, human, path = labels[t["label"]]
                body = _norm(L.read_text(path))
                chars = L.analyze(L.read_text(path))["stats"]["chars"] or 1
                valid = [q for q in t["ai_like"] if _norm(q["quote"]) and _norm(q["quote"]) in body]
                rec = results.setdefault(name, {"human": human, "runs": []})
                rec["runs"].append({"scores": t["scores"], "ai_like": valid, "invalid_quotes": len(t["ai_like"]) - len(valid),
                                    "j7_per_1k": round(len(valid) * 1000 / chars, 2), "comment": t.get("comment", "")})
    return results


def run_fidelity(iter_dir, model, only=None):
    out = {}
    for c in sorted(os.listdir(iter_dir)):
        d = os.path.join(iter_dir, c)
        if not os.path.isfile(os.path.join(d, "article.md")) or (only and c not in only):
            continue
        meta = json.load(open(os.path.join(d, "meta.json"), encoding="utf-8"))
        src = meta["case"].get("source", "")
        if meta["case"].get("mode") == "retone":
            continue
        jdir = os.path.join(iter_dir, "_judge", f"fidelity-{c}")
        os.makedirs(jdir, exist_ok=True)
        shutil.copyfile(os.path.join(d, "article.md"), os.path.join(jdir, "article.md"))
        extra = []
        if src.startswith("http"):
            source_desc = src
            extra = ["WebFetch"]
        else:
            ext = os.path.splitext(src)[1]
            for cand in ("input" + ext,):
                if os.path.exists(os.path.join(d, cand)):
                    shutil.copyfile(os.path.join(d, cand), os.path.join(jdir, "source" + ext))
            source_desc = "source" + ext
        res = call_judge(FIDELITY_PROMPT.format(source=source_desc), FIDELITY_SCHEMA, jdir, model, extra)
        body = _norm(L.read_text(os.path.join(d, "article.md")))
        claims = res.get("claims", [])
        bad = [x for x in claims if x["verdict"] != "supported"]
        out[c] = {"j1": res.get("j1"), "coverage": res.get("coverage"), "missing": res.get("missing"),
                  "claims": len(claims), "unsupported": [x for x in bad if x["verdict"] == "unsupported"],
                  "contradicted": [x for x in bad if x["verdict"] == "contradicted"],
                  "quote_not_found": sum(1 for x in claims if _norm(x["article_quote"]) not in body),
                  "cost": res.get("_cost"), "error": res.get("error")}
    return out


def run_pairwise(iter_dir, cmp_dir, model):
    out = {}
    if not cmp_dir or not os.path.isdir(cmp_dir):
        return out
    for c in sorted(os.listdir(iter_dir)):
        a = os.path.join(iter_dir, c, "article.md")
        key = c.split("-")[0]
        match = [d for d in os.listdir(cmp_dir) if d.split("-")[0] == key or d.split("-")[0] == key + "0"]
        if not os.path.isfile(a) or not match:
            continue
        b = os.path.join(cmp_dir, match[0], "article.md")
        if not os.path.isfile(b):
            continue
        votes = []
        for order in (0, 1):
            jdir = os.path.join(iter_dir, "_judge", f"pair-{c}-{order}")
            os.makedirs(jdir, exist_ok=True)
            x, y = (a, b) if order == 0 else (b, a)
            shutil.copyfile(x, os.path.join(jdir, "X.md"))
            shutil.copyfile(y, os.path.join(jdir, "Y.md"))
            res = call_judge(PAIR_PROMPT, PAIR_SCHEMA, jdir, model)
            w = res.get("winner")
            cur = {"X": "current", "Y": "compare", "tie": "tie"}.get(w) if order == 0 else \
                {"X": "compare", "Y": "current", "tie": "tie"}.get(w)
            votes.append({"winner": cur, "reasons": res.get("reasons"), "error": res.get("error")})
        final = votes[0]["winner"] if votes[0]["winner"] == votes[1]["winner"] else "split"
        out[c] = {"against": os.path.basename(cmp_dir) + "/" + match[0], "result": final, "votes": votes}
    return out


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except AttributeError:
        pass
    ap = argparse.ArgumentParser()
    ap.add_argument("--iter", required=True)
    ap.add_argument("--compare", help="pairwise 비교 대상 iteration(예: iter-0)")
    ap.add_argument("--work", default=DEFAULT_WORK)
    ap.add_argument("--model", default="sonnet")
    ap.add_argument("--skip", nargs="*", default=[])
    ap.add_argument("--only", nargs="*")
    args = ap.parse_args()
    iter_dir = os.path.join(args.work, "dogfood", args.iter)
    report = {}
    if "style" not in args.skip:
        report["style"] = run_style(iter_dir, args.work, args.model)
    if "fidelity" not in args.skip:
        report["fidelity"] = run_fidelity(iter_dir, args.model, args.only)
    if "pairwise" not in args.skip and args.compare:
        report["pairwise"] = run_pairwise(iter_dir, os.path.join(args.work, "dogfood", args.compare), args.model)
    with open(os.path.join(iter_dir, "judge.json"), "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=1)
    # 요약
    for name, rec in report.get("style", {}).items():
        sc = {}
        for r in rec["runs"]:
            for k, v in r["scores"].items():
                sc.setdefault(k, []).append(v)
        avg = {k: round(sum(v) / len(v), 2) for k, v in sc.items()}
        j7 = [r["j7_per_1k"] for r in rec["runs"]]
        print(f"[style] {'HUMAN ' if rec['human'] else ''}{name}: {avg} J7/1k={j7}")
        for r in rec["runs"]:
            for q in r["ai_like"][:6]:
                print(f"    - ({q['move']}) {q['quote'][:90]}")
    for name, f in report.get("fidelity", {}).items():
        print(f"[fidelity] {name}: j1={f['j1']} claims={f['claims']} unsupported={len(f['unsupported'])} "
              f"contradicted={len(f['contradicted'])} coverage={f['coverage']} missing={f['missing']}")
        for x in (f["unsupported"] + f["contradicted"])[:6]:
            print(f"    - {x['verdict']}: {x['article_quote'][:90]} | {x['note'][:120]}")
    for name, p in report.get("pairwise", {}).items():
        print(f"[pairwise] {name} vs {p['against']}: {p['result']}")


if __name__ == "__main__":
    main()
