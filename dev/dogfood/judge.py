#!/usr/bin/env python3
"""dogfooding 결과를 LLM judge로 평가한다. judge는 새 `claude -p` 프로세스(기본 sonnet)로 실행한다.

- style: 이번 iteration의 글과 사람 블로그 글(대조군)을 섞어 누가 썼는지 알리지 않고 채점한다.
  J2~J6, J8 점수와 "AI가 쓴 것처럼 읽히는 문장" 인용을 받고, 인용이 원문에 그대로 있는지 확인해 J7을 센다.
- fidelity: 글의 수치·주장을 자료 원문과 대조한다(supported / unsupported / contradicted, coverage).
- pairwise: 같은 자료로 쓴 두 글(이번 iteration과 비교 대상)을 순서를 바꿔 두 번 비교한다.
- clarity(J9): 글 한 편씩 판정한다. 문단의 첫 문장, 수치가 든 문장, A18에 걸린 문장을 뽑아
  헤딩과 바로 앞 문장과 함께 보여 준다. judge는 문장마다 그 문장만으로 무엇에 대한 말인지 알 수 있는지(self_contained),
  바로 앞 문장을 읽어야 알 수 있는지(needs_prev), 앞 문장까지 읽어도 알 수 없는지(unclear)를 고른다.
  사람 글 대조군 6편(합니다체 3, 해요체 3)도 같은 방식으로 판정하고 결과를 work 폴더에 저장해 다시 쓴다.

- within: 같은 실행의 초안 사본(article.unrevised.md)과 후처리를 마친 합니다체 글(Default는 article.md, Casual은
  article.draft.md)을 비교한다. 전체 pairwise, 바뀐 절만 모은 절 A/B, 문장을 맞춘 clarity, 두 글의 fidelity(걸린 주장을
  바뀐 문장과 바뀌지 않은 문장으로 나눔), 케이스마다 두 글과 사람 글 2편을 한 묶음으로 채점하는 style을 실행한다.
- cross: 이번 iteration과 다른 iteration의 같은 케이스에서 후처리를 마친 합니다체 글끼리 pairwise로 비교한다.

사용법
  python dev/dogfood/judge.py --iter iter-1 [--compare iter-0] [--skip style fidelity pairwise clarity]
  python dev/dogfood/judge.py --iter iter-8b --skip style fidelity pairwise --extra s1-930779c=examples/paged-attention.casual.md
  python dev/dogfood/judge.py --iter iter-11 --within [--skip sections style] [--only B-idiosyncrasies-default]
  python dev/dogfood/judge.py --iter iter-11 --cross iter-11r
"""

import argparse
import copy
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
- J4 구조: 제목이 내용을 특정하는가, 글의 핵심 주제가 제목과 도입에 드러나고 각 절이 그 주제를 설명하는가, 도입이 독자 상황이나 다루는 문제에서 시작하는가, 마무리가 구체 사실이나 열린 질문으로 끝나는가. 2: 모두 그렇다 / 1: 하나가 어긋난다 / 0: 둘 이상
- J5 한국어 자연스러움: 한국 개발자가 쓴 기술 블로그처럼 읽히는가. 번역투, 추상 명사 나열, 어색한 조사, 억지 번역어가 있는가. 2: 없다 / 1: 1~2곳 / 0: 3곳 이상
- J6 어투 품질: 합니다체 글이면 공문체가 아닌가, 해요체 글이면 정중하고 반말·과한 구어·이모지가 없는가, 어투가 섞이지 않았는가. 2 / 1 / 0
- J8 과교정: 문장이 지나치게 단조롭거나, 자연스러운 대조, 단서, 원어와 단위 보충, 긴 문장이 사라져 기계적으로 읽히는가. 같은 주어를 문장마다 되풀이해 늘어진 곳도 과교정이다. 2: 자연스럽다 / 1: 다소 단조롭다 / 0: 내용이나 흐름이 손상됐다

그리고 "AI가 쓴 것처럼 읽히는 문장"을 모두 찾아 ai_like에 원문 그대로 인용하세요. 인용은 글에 있는 문자열과 정확히 같아야 하고 한 문장 이내여야 합니다. 각 인용에 수사 동작(move)을 하나 고르고, 그 구절을 지우면 잃는 정보(lost_if_deleted, 없으면 "없음")를 적으세요.
move: salience(중요하다고 말하기), contrast_reframe(X가 아니라 Y), summary_marker(결국·요컨대 등), lesson_ending(문단 끝 교훈), hedge_stack(추정 중첩), calque_metaphor(번역투 표현·상투 은유), triplet(근거 없는 셋 묶음), rhetorical_q(자문자답), translationese(번역투 문장), tone_slip(어투 이탈), generic_claim(근거 없는 일반론), other.
사람이 쓴 글에도 이런 문장이 있을 수 있습니다. 실제로 그렇게 읽히는 문장만 고르세요. comment에는 글 전체에 대한 판단을 두세 문장으로 적으세요. label은 파일 이름에서 .md를 뺀 값입니다."""

FIDELITY_SCHEMA = {
    "type": "object",
    "properties": {
        "claims": {"type": "array", "items": {"type": "object", "properties": {
            "article_quote": {"type": "string"}, "source_ref": {"type": "string"},
            "verdict": {"type": "string", "enum": ["supported", "interpretation", "unsupported", "contradicted"]},
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
   - interpretation: 글쓴이의 해석이나 추론이고, 문장에 해석·추론임이 드러나 있으며("~라면 ~할 수 있습니다", "표를 보면 ~로 읽힙니다"), 자료의 사실과 모순되지 않는다. 자료의 결론처럼 단정했다면 unsupported로 판정한다.
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
기준(앞의 것이 더 중요): 1) 독자가 이해하기 쉬운가(문장을 따로 읽어도 무엇에 대한 말인지, 수치가 무엇을 잰 값인지 알 수 있는가, 글의 핵심 주제가 분명한가) 2) 사람 개발자가 쓴 것처럼 자연스러운 한국어인가(강조 문장, 부정 대구, 요약 표지, 번역투, 상투 은유, 기계적인 리듬이 적은가) 3) 자료의 핵심을 정확하고 구체적으로 전달하는가 4) 구조.
어투(합니다체/해요체) 차이는 판단에 넣지 마세요. winner는 "X", "Y", "tie" 중 하나, reasons에는 판단 근거 2~4개를 각 글의 문장을 인용해 적으세요."""

CLARITY_SCHEMA = {
    "type": "object",
    "properties": {"items": {"type": "array", "items": {"type": "object", "properties": {
        "id": {"type": "integer"},
        "verdict": {"type": "string", "enum": ["self_contained", "needs_prev", "unclear"]},
        "question": {"type": "string"}},
        "required": ["id", "verdict", "question"]}}},
    "required": ["items"]}

CLARITY_PROMPT = """현재 폴더의 items.md에는 한국어 기술 블로그 글 한 편에서 뽑은 문장이 번호와 함께 있습니다. 번호마다 그 문장이 속한 절의 헤딩, 바로 앞 문장, 판정할 문장이 적혀 있습니다. Read 도구로 items.md를 끝까지 읽고 모든 번호에 답하세요.

판정할 문장이 무엇에 대한 말인지(주어와 목적어), 문장 안의 수치가 무엇을 잰 값이고 무엇과 비교한 값인지를 기준으로 셋 중 하나를 고르세요.
- self_contained: 헤딩과 이 문장만 읽어도 알 수 있다.
- needs_prev: 이 문장만으로는 알 수 없고, 바로 앞 문장을 읽어야 알 수 있다. 예: 앞 문장의 주어를 생략한 문장, "그 값은", "차이는"처럼 앞 문장을 가리키는 말로 시작하는 문장, 비교 기준이 앞 문장에만 있는 수치 문장.
- unclear: 바로 앞 문장까지 읽어도 알 수 없다.
needs_prev나 unclear이면 question에 이 문장만 읽은 독자가 갖게 되는 질문을 한 문장으로 적습니다. 예: "무엇이 22배인가?", "무엇과 무엇의 차이인가?", "'이 방식'은 어떤 방식인가?" self_contained이면 question은 빈 문자열로 둡니다. 독자는 그 분야를 아는 개발자이므로 전문 용어를 모르는 것은 판정 이유가 아닙니다. 판정할 문장이 표나 목록 바로 뒤에 있으면 앞 문장 칸에 그렇게 적혀 있습니다."""

CLARITY_CONTROLS = 3  # 어투마다 사람 글 대조군 수


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
    for a in pool:
        path = os.path.join(work, "baseline", "cache", "md", a["id"] + ".md")
        if os.path.exists(path):
            out.append((a["id"], path))
        if len(out) == n:
            break
    if len(out) < n:
        raise SystemExit(f"사람 글 대조군({tone})이 캐시에 {len(out)}편뿐이다. measure.py collect를 먼저 실행한다.")
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
            cand = os.path.join(d, "input" + ext)
            if not os.path.exists(cand):
                # pasted 케이스는 자료를 프롬프트에 붙여넣고 실행 폴더의 사본을 지운다. 원본 경로에서 가져온다.
                cand = src.replace("{work}", os.path.dirname(os.path.dirname(iter_dir))).replace("{root}", ROOT)
                if not os.path.isabs(cand):
                    cand = os.path.join(ROOT, cand)
            if os.path.exists(cand):
                shutil.copyfile(cand, os.path.join(jdir, "source" + ext))
            source_desc = "source" + ext
        res = call_judge(FIDELITY_PROMPT.format(source=source_desc), FIDELITY_SCHEMA, jdir, model, extra)
        body = _norm(L.read_text(os.path.join(d, "article.md")))
        claims = res.get("claims", [])
        bad = [x for x in claims if x["verdict"] in ("unsupported", "contradicted")]
        out[c] = {"j1": res.get("j1"), "coverage": res.get("coverage"), "missing": res.get("missing"),
                  "claims": len(claims), "interpretation": sum(1 for x in claims if x["verdict"] == "interpretation"),
                  "unsupported": [x for x in bad if x["verdict"] == "unsupported"],
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


def _restore_inline(sentences, codes):
    """clean_inline이 바꾼 placeholder를 judge가 읽을 수 있는 글자로 되돌린다."""
    out, ci = [], 0
    for s in sentences:
        def rep(m):
            nonlocal ci
            if m.group(0) == L.PH_CODE:
                ci += 1
                return "`" + codes[ci - 1] + "`" if ci <= len(codes) else ""
            return "URL" if m.group(0) == L.PH_URL else ""
        out.append(L.PH_RE.sub(rep, s).strip())
    return out


def _check_sentences(text):
    """lint 점검 후보(A18)로 걸린 문장의 앞부분 목록. lint에 A18이 없으면 빈 집합."""
    keys = set()
    for mid, m in L.analyze(text)["metrics"].items():
        if mid.startswith("A18."):
            for h in m["hits"]:
                keys.add(_norm(h["text"])[:60])
    return keys


def clarity_items(text):
    """문단의 첫 문장, 수치가 든 문장, A18 후보 문장을 헤딩과 바로 앞 문장과 함께 뽑는다."""
    flagged = _check_sentences(text)
    items, heading, prev, in_refs = [], "(헤딩 없음)", None, False
    for b in L.parse_blocks(L.normalize_text(text)):
        if b.type == "heading":
            heading, _, _ = L.clean_inline(b.text)
            in_refs = bool(L.REF_HEADING_RE.search(heading)) and b.level >= 2
            prev = None
            continue
        if in_refs:
            continue
        if b.type in ("table", "code", "blockquote"):
            prev = {"table": "(바로 앞은 표)", "code": "(바로 앞은 코드 블록)"}.get(b.type, "(바로 앞은 인용문)")
            continue
        if b.type not in ("paragraph", "list_item"):
            continue
        clean, _, codes = L.clean_inline(b.text)
        sents = _restore_inline(L.split_sentences(clean), codes)
        for i, s in enumerate(sents):
            if not s or len(re.findall(r"[가-힣]", s)) < 4:
                continue  # 목록 번호("1.")나 영어 조각은 판정하지 않는다
            first = b.type == "paragraph" and i == 0
            numeric = bool(L.NUM_RE.search(s))
            check = _norm(s)[:60] in flagged
            if first or numeric or check:
                items.append({"heading": heading, "prev": prev or "(절의 첫 문장)", "sentence": s,
                              "first": first, "numeric": numeric, "check": check})
            prev = s
    return items


def judge_clarity(path, jdir, model):
    os.makedirs(jdir, exist_ok=True)
    text = L.read_text(path)
    items = clarity_items(text)
    lines = []
    for n, it in enumerate(items, 1):
        lines += [f"## {n}", f"- 헤딩: {it['heading']}", f"- 바로 앞 문장: {it['prev']}", f"- 판정할 문장: {it['sentence']}", ""]
    with open(os.path.join(jdir, "items.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    res = call_judge(CLARITY_PROMPT, CLARITY_SCHEMA, jdir, model)
    verdict = {x["id"]: x for x in res.get("items", []) if isinstance(x.get("id"), int)}
    flagged = []  # needs_prev 또는 unclear
    for n, it in enumerate(items, 1):
        v = verdict.get(n)
        if v is not None and v["verdict"] != "self_contained":
            flagged.append(dict(it, verdict=v["verdict"], question=v.get("question", "")))
    answered = sum(1 for n in range(1, len(items) + 1) if n in verdict)
    unclear = [x for x in flagged if x["verdict"] == "unclear"]
    all_items = [{"sentence": it["sentence"], "prev": it["prev"], "verdict": verdict[n]["verdict"]}
                 for n, it in enumerate(items, 1) if n in verdict]
    chars = L.analyze(text)["stats"]["chars"] or 1

    def share(sel):
        tot = [n for n, it in enumerate(items, 1) if sel(it) and n in verdict]
        dep = [n for n in tot if verdict[n]["verdict"] != "self_contained"]
        return [len(dep), len(tot)]
    return {"checked": len(items), "answered": answered,
            "dependent": len(flagged), "unclear": len(unclear),
            "rate": round(len(flagged) / answered, 3) if answered else None,
            "unclear_rate": round(len(unclear) / answered, 3) if answered else None,
            "first_dep": share(lambda it: it["first"]), "numeric_dep": share(lambda it: it["numeric"]),
            "per_1k": round(len(flagged) * 1000 / chars, 2), "chars": chars,
            "check_hits": sum(1 for it in items if it["check"]),
            "check_flagged": sum(1 for it in flagged if it["check"]),
            "unclear_items": flagged, "items_all": all_items, "cost": res.get("_cost"), "error": res.get("error")}


def clarity_controls(work, tones=("default", "casual")):
    """사람 글 대조군: 어투마다 길이가 비슷한 글을 고정 seed로 고른다. 원문이 캐시에 없으면 멈춘다."""
    stats = json.load(open(os.path.join(ROOT, "dev", "baseline", "stats.json"), encoding="utf-8"))
    out = []
    for tone in tones:
        pool = sorted((a for a in stats["articles"] if a["group"] == tone and 3500 <= a["chars"] <= 10000),
                      key=lambda a: a["id"])
        random.Random(f"clarity-controls-{tone}").shuffle(pool)
        picked = []
        for a in pool:
            path = os.path.join(work, "baseline", "cache", "md", a["id"] + ".md")
            if os.path.exists(path):
                picked.append((a["id"], path))
            if len(picked) == CLARITY_CONTROLS:
                break
        if len(picked) < CLARITY_CONTROLS:
            raise SystemExit(f"사람 글 대조군({tone})이 캐시에 부족하다: {len(picked)}편. measure.py collect를 먼저 실행한다.")
        out += picked
    return out


def human_clarity(work, model, tones=("default", "casual")):
    cache_path = os.path.join(work, "dogfood", "_clarity_humans.json")
    key = hashlib.sha1((CLARITY_PROMPT + model).encode("utf-8")).hexdigest()[:12]
    cache = json.load(open(cache_path, encoding="utf-8")) if os.path.exists(cache_path) else {}
    out = {}
    for hid, hpath in clarity_controls(work, tones):
        ck = f"{key}:{hid}"
        if ck not in cache or "items_all" not in cache[ck]:
            cache[ck] = judge_clarity(hpath, os.path.join(work, "dogfood", "_clarity_humans", hid), model)
            with open(cache_path, "w", encoding="utf-8") as f:
                json.dump(cache, f, ensure_ascii=False, indent=1)
        out[hid] = dict(cache[ck], human=True)
    return out


def run_clarity(iter_dir, work, model, extras=()):
    out = {}
    for c in sorted(os.listdir(iter_dir)):
        path = os.path.join(iter_dir, c, "article.md")
        if os.path.isfile(path):
            out[c] = dict(judge_clarity(path, os.path.join(iter_dir, "_judge", f"clarity-{c}"), model), human=False)
    for spec in extras:
        name, path = spec.split("=", 1)
        path = path if os.path.isabs(path) else os.path.join(ROOT, path)
        out[name] = dict(judge_clarity(path, os.path.join(iter_dir, "_judge", f"clarity-{name}"), model), human=False)
    cache_path = os.path.join(work, "dogfood", "_clarity_humans.json")
    key = hashlib.sha1((CLARITY_PROMPT + model).encode("utf-8")).hexdigest()[:12]
    cache = json.load(open(cache_path, encoding="utf-8")) if os.path.exists(cache_path) else {}
    for hid, hpath in clarity_controls(work):
        ck = f"{key}:{hid}"
        if ck not in cache:
            cache[ck] = judge_clarity(hpath, os.path.join(work, "dogfood", "_clarity_humans", hid), model)
            with open(cache_path, "w", encoding="utf-8") as f:
                json.dump(cache, f, ensure_ascii=False, indent=1)
        out[hid] = dict(cache[ck], human=True)
    return out


# ---------------------------------------------------------------- within: 초안 사본 대 후처리를 마친 글

SECTION_SCHEMA = {
    "type": "object",
    "properties": {"sections": {"type": "array", "items": {"type": "object", "properties": {
        "id": {"type": "integer"}, "winner": {"type": "string", "enum": ["A", "B", "tie"]},
        "reason": {"type": "string"}}, "required": ["id", "winner", "reason"]}}},
    "required": ["sections"]}

SECTION_PROMPT = """현재 폴더의 sections.md에는 같은 자료를 정리한 한국어 기술 블로그 글의 두 버전에서 내용이 다른 절만 모아 두었습니다. 절마다 A안과 B안이 있습니다. Read 도구로 끝까지 읽고, 절마다 한국 테크 기업 기술 블로그 편집자의 관점에서 더 나은 쪽을 고르세요.
기준(앞의 것이 더 중요): 1) 독자가 이해하기 쉬운가(문장을 따로 읽어도 무엇에 대한 말인지, 수치가 무엇을 잰 값이고 무엇과 비교한 값인지 알 수 있는가) 2) 사람 개발자가 쓴 것처럼 자연스러운 한국어인가(불필요한 반복, 같은 문형의 연속, 강조 문장, 부정 대구, 요약 표지, 번역투, 기계적인 리듬이 적은가) 3) 자료의 내용을 정확하고 구체적으로 전달하는가.
두 안의 차이가 판단에 영향을 주지 않을 만큼 작으면 tie를 고르세요. reason에는 판단 근거를 한두 문장으로 적고, 두 안의 문장을 인용하세요. id는 절 번호입니다."""

WITHIN_STYLE_SCHEMA = copy.deepcopy(STYLE_SCHEMA)
_item = WITHIN_STYLE_SCHEMA["properties"]["texts"]["items"]
_item["properties"]["repetitive"] = {"type": "array", "items": {"type": "object", "properties": {
    "quote": {"type": "string"}}, "required": ["quote"]}}
_item["required"] = _item["required"] + ["repetitive"]
WITHIN_STYLE_PROMPT = STYLE_PROMPT + """
그리고 같은 정보나 같은 문형이 되풀이돼 단조롭게 읽히는 문장을 repetitive에 원문 그대로 인용하세요. 인용은 한 문장 이내이고 글에 있는 문자열과 정확히 같아야 합니다. 그런 문장이 없으면 빈 목록으로 둡니다."""


def _meta(case_dir):
    return json.load(open(os.path.join(case_dir, "meta.json"), encoding="utf-8"))


def final_default(case_dir, tone):
    if tone == "casual" and os.path.isfile(os.path.join(case_dir, "article.draft.md")):
        return os.path.join(case_dir, "article.draft.md")
    return os.path.join(case_dir, "article.md")


def within_cases(iter_dir, only=None):
    out = []
    for c in sorted(os.listdir(iter_dir)):
        d = os.path.join(iter_dir, c)
        snap = os.path.join(d, "article.unrevised.md")
        if not os.path.isfile(snap) or not os.path.isfile(os.path.join(d, "meta.json")) or (only and c not in only):
            continue
        meta = _meta(d)
        out.append((c, d, meta, snap, final_default(d, meta["case"].get("tone", "default"))))
    return out


def pair_vote(a, b, jdir_base, model, prompt=PAIR_PROMPT, schema=PAIR_SCHEMA):
    """a를 current, b를 compare로 두고 순서를 바꿔 두 번 묻는다."""
    votes = []
    for order in (0, 1):
        jdir = f"{jdir_base}-{order}"
        os.makedirs(jdir, exist_ok=True)
        x, y = (a, b) if order == 0 else (b, a)
        shutil.copyfile(x, os.path.join(jdir, "X.md"))
        shutil.copyfile(y, os.path.join(jdir, "Y.md"))
        res = call_judge(prompt, schema, jdir, model)
        w = res.get("winner")
        cur = {"X": "current", "Y": "compare", "tie": "tie"}.get(w) if order == 0 else \
            {"X": "compare", "Y": "current", "tie": "tie"}.get(w)
        votes.append({"winner": cur, "reasons": res.get("reasons"), "error": res.get("error")})
    final = votes[0]["winner"] if votes[0]["winner"] == votes[1]["winner"] else "split"
    return {"result": final, "votes": votes}


def h2_sections(text):
    lines = L.normalize_text(text).split("\n")
    secs, cur, title, in_code = [], [], "(도입)", False
    for line in lines:
        if L.FENCE_RE.match(line):
            in_code = not in_code
        m = None if in_code else re.match(r"^##\s+(.*?)\s*#*\s*$", line)
        if m:
            secs.append((title, "\n".join(cur).strip()))
            title, cur = m.group(1).strip(), []
        else:
            cur.append(line)
    secs.append((title, "\n".join(cur).strip()))
    return secs


def section_ab(pre, post, jdir_base, model):
    sp, sq = h2_sections(L.read_text(pre)), h2_sections(L.read_text(post))
    if [t for t, _ in sp] != [t for t, _ in sq]:
        post_by = dict(sq)
        pairs = [(t, a, post_by.get(t)) for t, a in sp if t in post_by]
    else:
        pairs = [(t, a, b) for (t, a), (_, b) in zip(sp, sq)]
    changed = [(t, a, b) for t, a, b in pairs if b is not None and _norm(a) != _norm(b)]
    if not changed:
        return {"sections": 0, "votes": [], "post": 0, "pre": 0, "tie": 0}
    votes = []
    for order in (0, 1):
        jdir = f"{jdir_base}-{order}"
        os.makedirs(jdir, exist_ok=True)
        lines = []
        for k, (t, a, b) in enumerate(changed, 1):
            first, second = (b, a) if order == 0 else (a, b)  # order 0: A안이 후처리 글
            lines += [f"# 절 {k}: {t}", "", "## A안", "", first, "", "## B안", "", second, "", "---", ""]
        with open(os.path.join(jdir, "sections.md"), "w", encoding="utf-8") as f:
            f.write("\n".join(lines))
        res = call_judge(SECTION_PROMPT, SECTION_SCHEMA, jdir, model)
        for it in res.get("sections", []):
            k = it.get("id")
            if not isinstance(k, int) or not 1 <= k <= len(changed):
                continue
            w = it.get("winner")
            if w == "tie":
                who = "tie"
            else:
                post_is_a = order == 0
                who = "post" if (w == "A") == post_is_a else "pre"
            votes.append({"section": changed[k - 1][0], "order": order, "vote": who, "reason": it.get("reason", "")})
        if res.get("error"):
            votes.append({"section": None, "order": order, "vote": "error", "reason": res["error"][:300]})
    cnt = {k: sum(1 for v in votes if v["vote"] == k) for k in ("post", "pre", "tie")}
    return dict({"sections": len(changed), "votes": votes}, **cnt)


def align_clarity(pre_c, post_c):
    """문장과 바로 앞 문장이 같은 항목은 판정 잡음(뒤집힌 비율)을, 나머지는 바뀐 항목으로 센다."""
    def key(it):
        return (_norm(it["sentence"]), _norm(it["prev"]))
    a = {key(it): it["verdict"] for it in pre_c.get("items_all", [])}
    b = {key(it): it["verdict"] for it in post_c.get("items_all", [])}
    same = [k for k in a if k in b]
    flips = sum(1 for k in same if a[k] != b[k])

    def dist(d, keys):
        out = {"self_contained": 0, "needs_prev": 0, "unclear": 0}
        for k in keys:
            out[d[k]] = out.get(d[k], 0) + 1
        return out
    return {"unchanged_items": len(same), "flips": flips,
            "flip_rate": round(flips / len(same), 3) if same else None,
            "pre_only": dist(a, [k for k in a if k not in b]), "post_only": dist(b, [k for k in b if k not in a])}


def fidelity_one(article, case_dir, meta, jdir, model, work):
    os.makedirs(jdir, exist_ok=True)
    shutil.copyfile(article, os.path.join(jdir, "article.md"))
    case = meta["case"]
    src = case.get("source", "")
    extra = []
    local = case.get("source_local")
    if local:
        local = local.replace("{work}", work)
        shutil.copyfile(local, os.path.join(jdir, "source" + os.path.splitext(local)[1]))
        source_desc = "source" + os.path.splitext(local)[1]
    elif src.startswith("http"):
        source_desc, extra = src, ["WebFetch"]
    else:
        ext = os.path.splitext(src)[1]
        cand = os.path.join(case_dir, "input" + ext)
        if not os.path.exists(cand):
            cand = src.replace("{work}", work).replace("{root}", ROOT)
            if not os.path.isabs(cand):
                cand = os.path.join(ROOT, cand)
        if os.path.exists(cand):
            shutil.copyfile(cand, os.path.join(jdir, "source" + ext))
        source_desc = "source" + ext
    res = call_judge(FIDELITY_PROMPT.format(source=source_desc), FIDELITY_SCHEMA, jdir, model, extra)
    claims = res.get("claims", [])
    body = _norm(L.read_text(article))
    return {"j1": res.get("j1"), "coverage": res.get("coverage"), "missing": res.get("missing"), "claims": len(claims),
            "unsupported": [x for x in claims if x["verdict"] == "unsupported"],
            "contradicted": [x for x in claims if x["verdict"] == "contradicted"],
            "quote_not_found": sum(1 for x in claims if _norm(x["article_quote"]) not in body),
            "cost": res.get("_cost"), "error": res.get("error")}


def within_style(case, pre, post, jdir_base, work, model, runs=2):
    out = {"pre": [], "post": []}
    for r in range(runs):
        items = [("pre", pre), ("post", post)] + [(hid, hp) for hid, hp in
                                                 human_controls(work, "default", 2, seed=f"within-{case}-{r}")]
        rnd = random.Random(f"within-{case}-{r}")
        rnd.shuffle(items)
        jdir = f"{jdir_base}-{r}"
        os.makedirs(jdir, exist_ok=True)
        labels = {}
        for i, (name, path) in enumerate(items, 1):
            shutil.copyfile(path, os.path.join(jdir, f"T{i}.md"))
            labels[f"T{i}"] = (name, path)
        res = call_judge(WITHIN_STYLE_PROMPT.format(files=", ".join(f"{k}.md" for k in labels)), WITHIN_STYLE_SCHEMA,
                         jdir, model)
        json.dump({"labels": {k: v[0] for k, v in labels.items()}, "result": res},
                  open(os.path.join(jdir, "result.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        for t in res.get("texts", []):
            if t.get("label") not in labels:
                continue
            name, path = labels[t["label"]]
            body = _norm(L.read_text(path))
            chars = L.analyze(L.read_text(path))["stats"]["chars"] or 1
            ai = [q for q in t.get("ai_like", []) if _norm(q["quote"]) and _norm(q["quote"]) in body]
            rp = [q for q in t.get("repetitive", []) if _norm(q["quote"]) and _norm(q["quote"]) in body]
            rec = {"scores": t["scores"], "j7_per_1k": round(len(ai) * 1000 / chars, 2), "ai_like": ai,
                   "repetitive": rp, "repetitive_per_1k": round(len(rp) * 1000 / chars, 2), "comment": t.get("comment", "")}
            out.setdefault(name if name in ("pre", "post") else "human", []).append(rec)
    return out


def run_within(iter_dir, work, model, skip=(), only=None):
    out = {}
    path = os.path.join(iter_dir, "judge.json")
    for c, d, meta, pre, post in within_cases(iter_dir, only):
        rec = {"pre": os.path.basename(pre), "post": os.path.basename(post)}
        jb = os.path.join(iter_dir, "_judge", "within", c)
        if "pairwise" not in skip:
            rec["pairwise"] = pair_vote(post, pre, os.path.join(jb, "pair"), model)
        if "sections" not in skip:
            rec["sections"] = section_ab(pre, post, os.path.join(jb, "sections"), model)
        if "clarity" not in skip:
            cp = judge_clarity(pre, os.path.join(jb, "clarity-pre"), model)
            cq = judge_clarity(post, os.path.join(jb, "clarity-post"), model)
            rec["clarity"] = {"pre": cp, "post": cq, "aligned": align_clarity(cp, cq)}
        if "fidelity" not in skip and meta["case"].get("mode") != "retone":
            fp = fidelity_one(pre, d, meta, os.path.join(jb, "fidelity-pre"), model, work)
            fq = fidelity_one(post, d, meta, os.path.join(jb, "fidelity-post"), model, work)
            pre_body = _norm(L.read_text(pre))
            for x in fq["unsupported"] + fq["contradicted"]:
                x["in_unchanged_text"] = _norm(x["article_quote"]) in pre_body
            rec["fidelity"] = {"pre": fp, "post": fq,
                               "introduced": sum(1 for x in fq["unsupported"] + fq["contradicted"]
                                                 if not x["in_unchanged_text"])}
        if "style" not in skip:
            rec["style"] = within_style(c, pre, post, os.path.join(jb, "style"), work, model)
        out[c] = rec
        # 케이스마다 저장해서 중간에 멈춰도 결과가 남게 한다
        latest = json.load(open(path, encoding="utf-8")) if os.path.exists(path) else {}
        latest.setdefault("within", {})[c] = rec
        with open(path, "w", encoding="utf-8") as f:
            json.dump(latest, f, ensure_ascii=False, indent=1)
    if "clarity" not in skip:
        hum = human_clarity(work, model, tones=("default",))
        latest = json.load(open(path, encoding="utf-8")) if os.path.exists(path) else {}
        latest["within_humans"] = hum
        with open(path, "w", encoding="utf-8") as f:
            json.dump(latest, f, ensure_ascii=False, indent=1)
    return out


def run_cross(iter_dir, other_dir, model, only=None):
    out = {}
    for c, d, meta, pre, post in within_cases(iter_dir, only):
        od = os.path.join(other_dir, c)
        if not os.path.isfile(os.path.join(od, "meta.json")):
            continue
        other = final_default(od, _meta(od)["case"].get("tone", "default"))
        if not os.path.isfile(other):
            continue
        r = pair_vote(post, other, os.path.join(iter_dir, "_judge", "cross", os.path.basename(other_dir), c), model)
        out[c] = dict(r, against=f"{os.path.basename(other_dir)}/{c}/{os.path.basename(other)}")
    return out


def print_within(report):
    for c, r in report.get("within", {}).items():
        line = [f"[within] {c}"]
        if "pairwise" in r:
            line.append(f"pairwise={r['pairwise']['result']}")
        if "sections" in r:
            sx = r["sections"]
            line.append(f"절 A/B {sx['sections']}절: 후처리 {sx['post']} 초안 {sx['pre']} 무 {sx['tie']}")
        if "clarity" in r:
            cp, cq, al = r["clarity"]["pre"], r["clarity"]["post"], r["clarity"]["aligned"]
            line.append(f"J9 {cp['dependent']}/{cp['answered']}→{cq['dependent']}/{cq['answered']} "
                        f"unclear {cp['unclear']}→{cq['unclear']} 잡음 {al['flips']}/{al['unchanged_items']}")
        if "fidelity" in r:
            fp, fq = r["fidelity"]["pre"], r["fidelity"]["post"]
            line.append(f"fidelity {len(fp['unsupported'])}/{len(fp['contradicted'])}→"
                        f"{len(fq['unsupported'])}/{len(fq['contradicted'])} 후처리로 생김 {r['fidelity']['introduced']}")
        if "style" in r:
            def avg(recs, k):
                v = [x["scores"][k] for x in recs]
                return round(sum(v) / len(v), 2) if v else None

            def rp(recs):
                return [x["repetitive_per_1k"] for x in recs]
            st = r["style"]
            line.append(f"J5 {avg(st['pre'], 'J5')}→{avg(st['post'], 'J5')} J8 {avg(st['pre'], 'J8')}→{avg(st['post'], 'J8')} "
                        f"반복 인용/1k {rp(st['pre'])}→{rp(st['post'])}")
        print(" | ".join(line))
    for hid, h in report.get("within_humans", {}).items():
        print(f"[within] HUMAN {hid}: J9 {h['dependent']}/{h['answered']} unclear {h['unclear']}")
    for c, r in report.get("cross", {}).items():
        print(f"[cross] {c} vs {r['against']}: {r['result']}")


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
    ap.add_argument("--extra", action="append", default=[], help="clarity만 판정할 추가 글: 이름=경로")
    ap.add_argument("--within", action="store_true", help="초안 사본과 후처리를 마친 글을 비교한다")
    ap.add_argument("--cross", help="다른 iteration의 같은 케이스와 후처리를 마친 글끼리 비교한다")
    args = ap.parse_args()
    iter_dir = os.path.join(args.work, "dogfood", args.iter)
    report_path = os.path.join(iter_dir, "judge.json")
    if args.within or args.cross:
        if args.within:
            run_within(iter_dir, args.work, args.model, args.skip, args.only)
        if args.cross:
            res = run_cross(iter_dir, os.path.join(args.work, "dogfood", args.cross), args.model, args.only)
            latest = json.load(open(report_path, encoding="utf-8")) if os.path.exists(report_path) else {}
            latest.setdefault("cross", {}).update(res)
            with open(report_path, "w", encoding="utf-8") as f:
                json.dump(latest, f, ensure_ascii=False, indent=1)
        print_within(json.load(open(report_path, encoding="utf-8")))
        return
    # 이미 판정한 단계는 남기고 이번에 실행한 단계만 덮어쓴다.
    report = json.load(open(report_path, encoding="utf-8")) if os.path.exists(report_path) else {}
    if "style" not in args.skip:
        report["style"] = run_style(iter_dir, args.work, args.model)
    if "fidelity" not in args.skip:
        report["fidelity"] = run_fidelity(iter_dir, args.model, args.only)
    if "pairwise" not in args.skip and args.compare:
        report["pairwise"] = run_pairwise(iter_dir, os.path.join(args.work, "dogfood", args.compare), args.model)
    if "clarity" not in args.skip:
        report["clarity"] = run_clarity(iter_dir, args.work, args.model, args.extra)
    # 같은 iteration에 judge를 동시에 돌려도 서로의 결과를 덮어쓰지 않게, 저장 직전에 파일을 다시 읽고
    # 이번에 실행한 단계만 바꾼다.
    ran = [k for k in ("style", "fidelity", "pairwise", "clarity") if k in report and k not in args.skip]
    latest = json.load(open(report_path, encoding="utf-8")) if os.path.exists(report_path) else {}
    latest.update({k: report[k] for k in ran})
    report = latest
    with open(report_path, "w", encoding="utf-8") as f:
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
    for name, c in report.get("clarity", {}).items():
        print(f"[clarity] {'HUMAN ' if c['human'] else ''}{name}: 앞 문장 필요 {c['dependent']}/{c['answered']} "
              f"(rate {c['rate']}), unclear {c['unclear']}, 문단 첫 문장 {c['first_dep']}, 수치 문장 {c['numeric_dep']}, "
              f"check_hits={c['check_hits']} check_flagged={c['check_flagged']}"
              + (f" error={c['error'][:80]}" if c.get("error") else ""))
        for it in c["unclear_items"][:6]:
            print(f"    - ({it['verdict']}) {it['sentence'][:80]} | {it['question'][:60]}")


if __name__ == "__main__":
    main()
