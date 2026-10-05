#!/usr/bin/env python3
"""techblog 후처리 보조: 초안 사본 만들기, 다시 읽을 반복 후보 찾기, 후처리 전후 비교.

사용법
  python revise_ko.py start ARTICLE [--force]
  python revise_ko.py repeats ARTICLE [--all] [--json]
  python revise_ko.py check ARTICLE [--facts FACTS.md] [--json]

ARTICLE은 후처리할 합니다체 글이다. Default 글이면 출력 파일(<이름>.md), Casual 글이면 Default 초안
(<이름>.draft.md)이다. 초안 사본(<이름>.unrevised.md)과 fact sheet(<이름>.facts.md)의 경로는 ARTICLE 이름에서 정한다.

- start: ARTICLE을 초안 사본으로 복사한다. 사본이 이미 있으면 --force 없이는 덮어쓰지 않는다.
- repeats: 다시 읽을 위치(반복 후보)를 출력한다. 판정은 하지 않는다. 후보마다 이 글의 독자에게 필요한
  반복인지는 글쓴이가 판단한다.
- check: 초안 사본과 ARTICLE을 비교한다. 바뀐 문장 수, 초안에만 있는 수치와 새 수치, 헤딩·코드·표 변경,
  lint 상태가 나빠진 항목, 연결어미가 3개 이상인 새 문장을 출력한다.

종료 코드: 0 정상, 1 check에서 Gate 위반, FAIL, AI 문체 항목 악화 중 하나가 있음, 2 사용법 또는 입력 오류
표준 라이브러리만 쓴다(Python 3.8 이상).
"""

import argparse
import difflib
import json
import os
import re
import shutil
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import lint_ko as L  # noqa: E402

SNAPSHOT_SUFFIX = ".unrevised.md"
FACTS_SUFFIX = ".facts.md"
MAX_LINES = 8
CHANGED_SHARE_RECHECK = 0.25
SHORT_LEN = 35

# 조사 하나를 뗀다. 긴 것부터 대조하고, 뗀 뒤 두 글자 이상 남을 때만 뗀다("차이"는 그대로 둔다).
# "도", "만"은 넣지 않는다. 정확도, 속도, 빈도, 수만처럼 이 글자로 끝나는 명사가 기술 글에 많다.
PARTICLES = sorted(("에서는", "에서", "으로", "보다", "까지", "부터", "처럼", "에는", "은", "는", "이", "가", "을",
                    "를", "의", "와", "과", "에", "로"), key=len, reverse=True)
EDGE = "\"'“”‘’()[]{}<>.,?!:;…·「」『』"
SUBJECT_END = ("은", "는", "이", "가")
DEMONSTRATIVES = ("이", "그", "저", "이런", "그런", "이러한", "그러한", "이번", "해당", "위의", "아래")
# R4에서 세지 않는 일반 종결. 사람 글에서도 이어서 나오는 종결이고, 같은 종결의 연속은 lint A8.ending_run4가 센다.
GENERIC_PREDICATES = ("있습니다", "없습니다", "합니다", "했습니다", "됩니다", "됐습니다", "되었습니다", "않습니다",
                      "같습니다", "입니다", "있었습니다", "없었습니다", "않았습니다")

# R6: 변화량을 말하는 서술어와 비교 기준 표지
CHANGE_RE = re.compile(r"(줄었|줄어들|줄어든|줄였|늘었|늘어났|늘어난|늘렸|올랐|올라갔|올라간|떨어졌|떨어뜨|떨어진|"
                       r"내려갔|내려간|낮아졌|낮아진|낮췄|높아졌|높아진|높였|감소|증가|개선|향상|단축|커졌|커진|작아졌|"
                       r"작아진|빨라졌|빨라진|느려졌|느려진)")
TIMES_RE = re.compile(r"(?<![\w.\-])\d[\d.,]*\s*배(?:$|[^가-힣]|로|가|를|의|에|까지|였|입|이|나|만큼|씩|가량|정도)")
# 단위가 붙은 수치. 뒤에 "까지", "로"가 붙은 값("1,850ms까지 올랐습니다", "0.8초로 줄었습니다")은 바뀐 뒤의 값이라
# 변화량으로 세지 않는다. 배수("2배로")는 그대로 변화량이다.
UNIT_NUM_RE = re.compile(r"(?<![\w.\-])\d[\d.,]*\s*(%p|%|배|x|×|ms|초|분|시간|개|건|명|GB|MB|KB|TB|토큰|점|회|번)"
                         r"(까지|으로|로)?")
BASELINE_RE = re.compile(
    r"(보다|대비|에\s*비해|비교|이전|기준|대신|원래|기존|당초|종전|[가-힣]던\s|"
    r"[\d.,]+\s*[^\s\d]{0,6}에서\s+(?:약\s+)?[\d.,]+|"  # "1,850ms에서 420ms로"
    r"의\s+(?:최대\s+|약\s+|평균\s+)?[\d.,]+\s*배|"     # "Orca의 1.67배"
    r"(?<![가-힣])전(?:보다|에는|과|의|에)?(?=\s|$))")

# check에서 상태 악화를 나누는 기준. 이 접두사로 시작하는 항목은 문장·문단 분포 항목이고,
# 나머지(G, A1~A7, A10~A15, T)는 AI 문체 항목이다.
DIST_PREFIX = ("A8.", "A9.", "A16.", "A17.")
RANK = {"PASS": 0, "INFO": 0, "CHECK": 0, "WARN": 1, "FAIL": 2, "GATE": 3}


# ---------------------------------------------------------------- 경로

def stem_of(path):
    base = path[:-3] if path.endswith(".md") else path
    if base.endswith(".draft"):
        base = base[:-len(".draft")]
    return base


def snapshot_path(path):
    return stem_of(path) + SNAPSHOT_SUFFIX


def facts_path(path):
    return stem_of(path) + FACTS_SUFFIX


# ---------------------------------------------------------------- 문장

def tokens(masked):
    s = L.PH_RE.sub(" ", masked)
    out = []
    for t in s.split():
        t = t.strip(EDGE)
        if t:
            out.append(t)
    return out


def strip_particle(tok):
    for p in PARTICLES:
        if tok.endswith(p) and len(tok) - len(p) >= 2:
            return tok[:-len(p)]
    return tok


def sentence_records(text, include_refs=False):
    """글의 서술 문장을 순서대로 돌려준다. 헤딩, 절 번호, 문단 첫 문장인지, 바로 앞 블록 종류를 함께 적는다."""
    recs = []
    heading, section, in_refs, prev_type = "", 0, False, "start"
    for bi, b in enumerate(L.parse_blocks(L.normalize_text(text))):
        if b.type == "heading":
            heading = L.clean_inline(b.text)[0]
            in_refs = bool(L.REF_HEADING_RE.search(heading)) and b.level >= 2
            section += 1
            prev_type = "heading"
            continue
        if in_refs and not include_refs:
            continue
        if b.type in ("table", "code", "blockquote", "html"):
            prev_type = b.type
            continue
        if b.type not in ("paragraph", "list_item"):
            continue
        clean, _, _ = L.clean_inline(b.text)
        parts = L.split_sentences(clean)
        for i, s in enumerate(parts):
            masked = L.mask_quotes(s)
            word = L.last_word(s)
            cls = L.classify_ending(word, s.rstrip(L.CLOSERS + " ").endswith("?"))
            if b.type == "list_item" and cls in ("NOUN", "OTHER"):
                continue  # 명사구 목록 항목은 서술 문장이 아니다
            recs.append({"line": b.line, "heading": heading, "section": section, "block": bi, "kind": b.type,
                         "first": i == 0, "after": prev_type if i == 0 else "sentence",
                         "text": s, "masked": masked, "toks": tokens(masked), "word": word})
        prev_type = "list" if b.type == "list_item" else "paragraph"
    return recs


def excerpt(s, n=60):
    s = s.strip()
    return s if len(s) <= n else s[:n - 1] + "…"


def fmt_lines(lines, n=6):
    uniq = sorted(set(lines))
    shown = ", ".join(f"L{x}" for x in uniq[:n])
    return shown + (", …" if len(uniq) > n else "")


# ---------------------------------------------------------------- 반복 후보

def _baseline_keys(rec):
    """수치가 든 비교 기준 구절의 키. 예: "무작위 추측 정확도 20%보다" → "추측 정확도 20%"."""
    toks = rec["toks"]
    keys = []
    for j, t in enumerate(toks):
        end = None  # 기준 명사가 붙은 마지막 토큰 위치
        if t.endswith("보다") and len(t) > 2:
            end = j
        elif t == "대비" and j > 0:
            end = j - 1
        elif t.startswith("비해") and j > 0 and toks[j - 1].endswith("에"):
            end = j - 1
        elif t.startswith("비교") and j > 0 and toks[j - 1].endswith(("와", "과")):
            end = j - 1
        if end is None:
            continue
        window = toks[max(0, end - 2):end + 1]
        if not any(L.NUM_RE.search(w) for w in window):
            continue  # 이름만 있는 기준("Orca보다")은 세지 않는다
        norm = [strip_particle(w) for w in window]
        if norm and norm[-1].endswith("에"):
            norm[-1] = norm[-1][:-1]
        keys.append(" ".join(w.lower() for w in norm if w))
    return keys


def find_repeats(text):
    recs = sentence_records(text)
    cands = []

    # R6 비교 기준 없는 변화량
    for idx, r in enumerate(recs):
        m = r["masked"]
        amounts = [u for u in UNIT_NUM_RE.finditer(m) if u.group(1) == "배" or not u.group(2)]
        if not amounts:
            continue
        if not (CHANGE_RE.search(m) or TIMES_RE.search(m)):
            continue
        if BASELINE_RE.search(m):
            continue
        units = [u.group(1) for u in UNIT_NUM_RE.finditer(m)]
        if len(units) >= 2 and len(set(units)) < len(units):
            continue  # 같은 단위의 수치가 둘이면 바뀌기 전과 후 값이 함께 있다
        after_block = r["after"] in ("table", "list", "code")
        prev = recs[idx - 1] if idx > 0 and r["after"] in ("sentence", "paragraph") else None
        if prev is not None and BASELINE_RE.search(prev["masked"]):
            continue
        cands.append({"id": "R6", "item": 2, "lines": [r["line"]], "section": r["heading"],
                      "text": r["text"], "after": "표·목록 뒤" if after_block else "",
                      "label": "비교 기준 없는 변화량" + ("(표·목록 바로 뒤)" if after_block else "")})

    # R1 수치가 든 같은 비교 기준
    occ = {}
    for idx, r in enumerate(recs):
        for k in set(_baseline_keys(r)):
            occ.setdefault(k, []).append(idx)
    for k, idxs in occ.items():
        adjacent = sum(1 for a, b in zip(idxs, idxs[1:]) if b == a + 1 and recs[a]["section"] == recs[b]["section"])
        if len(idxs) >= 3 or adjacent >= 1:
            cands.append({"id": "R1", "item": 1, "lines": [recs[i]["line"] for i in idxs], "section": "",
                          "text": recs[idxs[0]]["text"], "key": k, "count": len(idxs), "adjacent": adjacent,
                          "label": f"같은 비교 기준 «{k}» {len(idxs)}문장" + (f", 이웃 문장 {adjacent}쌍" if adjacent else "")})

    # R4 같은 문형: (첫 어절, 마지막 어절) 쌍이 3회 이상, 같은 마지막 어절이 3문장 연속
    frames = {}
    for idx, r in enumerate(recs):
        toks = r["toks"]
        if len(toks) < 3 or not r["word"]:
            continue
        first = toks[0]
        if first in L.SENT_ADVERBS or r["word"] in GENERIC_PREDICATES:
            continue
        if first in DEMONSTRATIVES and len(toks) > 3:
            first = toks[0] + " " + toks[1]
        frames.setdefault((first, r["word"]), []).append(idx)
    for (first, last), idxs in frames.items():
        if len(idxs) >= 3:
            cands.append({"id": "R4", "item": 3, "lines": [recs[i]["line"] for i in idxs], "section": "",
                          "text": recs[idxs[0]]["text"], "count": len(idxs),
                          "label": f"같은 문형 «{first} … {last}» {len(idxs)}문장"})
    run = [0]
    for idx in range(1, len(recs) + 1):
        if (idx < len(recs) and recs[idx]["word"] and recs[idx]["word"] == recs[run[-1]]["word"]
                and recs[idx]["word"] not in GENERIC_PREDICATES):
            run.append(idx)
            continue
        if len(run) >= 3:
            w = recs[run[0]]["word"]
            cands.append({"id": "R4", "item": 3, "lines": [recs[i]["line"] for i in run], "section": "",
                          "text": recs[run[0]]["text"], "count": len(run),
                          "label": f"같은 서술어 «{w}» {len(run)}문장 연속"})
        run = [idx]

    # R3 같은 주어로 여는 문장이 한 절에서 3문장 이상 연속
    run = []
    for idx in range(len(recs) + 1):
        cur = recs[idx] if idx < len(recs) else None
        key = None
        if cur is not None and cur["toks"] and cur["toks"][0].endswith(SUBJECT_END) and len(cur["toks"][0]) >= 2:
            key = (cur["section"], cur["toks"][0])
        if run and key is not None and key == run[-1][1]:
            run.append((idx, key))
            continue
        if len(run) >= 3:
            cands.append({"id": "R3", "item": 3, "lines": [recs[i]["line"] for i, _ in run], "section": "",
                          "text": recs[run[0][0]]["text"], "count": len(run),
                          "label": f"«{run[0][1][1]}»로 여는 문장 {len(run)}개 연속"})
        run = [(idx, key)] if key is not None else []

    # R5 한 절 안에서 35자 미만 문단 문장이 4개 이상 연속
    run = []
    for idx in range(len(recs) + 1):
        cur = recs[idx] if idx < len(recs) else None
        if (cur is not None and cur["kind"] == "paragraph" and len(cur["text"]) < SHORT_LEN
                and (not run or recs[run[-1]]["section"] == cur["section"])):
            run.append(idx)
            continue
        if len(run) >= 4:
            cands.append({"id": "R5", "item": 3, "lines": [recs[i]["line"] for i in run], "section": "",
                          "text": recs[run[0]]["text"], "count": len(run),
                          "label": f"{SHORT_LEN}자 미만 문장 {len(run)}개 연속"})
        run = [idx] if cur is not None and cur["kind"] == "paragraph" and len(cur["text"]) < SHORT_LEN else []

    order = {"R6": 0, "R1": 1, "R4": 2, "R3": 3, "R5": 4}
    cands.sort(key=lambda c: (order[c["id"]], -c.get("count", 1), c["lines"][0]))
    return {"sentences": len(recs), "candidates": cands}


def render_repeats(path, res, show_all=False):
    cands = res["candidates"]
    lines = [f"techblog repeats | {os.path.basename(path)} | {res['sentences']}문장"]
    if not cands:
        lines.append("반복 후보 없음. 글을 읽으며 적은 곳만 고친다.")
        return "\n".join(lines)
    lines.append("다시 읽을 곳(판정 아님): 후보마다 이 글의 독자에게 필요한 반복인지 판단한다. "
                 "필요한 반복은 그대로 둔다. 괄호의 번호는 references/revision.md의 \"고칠 곳\" 항목이다.")
    shown = cands if show_all else cands[:MAX_LINES]
    for c in shown:
        lines.append(f"[{c['id']}] {fmt_lines(c['lines'])} {c['label']} (항목 {c['item']}): «{excerpt(c['text'])}»")
    if len(cands) > len(shown):
        lines.append(f"+{len(cands) - len(shown)}개 (--all로 모두 본다)")
    return "\n".join(lines)


# ---------------------------------------------------------------- 전후 비교

def _blocks_of(text, kind):
    return [b.text.strip() for b in L.parse_blocks(L.normalize_text(text)) if b.type == kind]


def _numbers(text):
    found = {}
    for b in L.parse_blocks(L.normalize_text(text)):
        if b.type == "code":
            continue
        s = b.text if b.type == "table" else L.clean_inline(b.text)[0]
        for key, raw in L.extract_numbers(s):
            found.setdefault(key, []).append((b.line, raw))
    return found


def _connectives(masked):
    n = 0
    toks = masked.split()
    for i, tok in enumerate(toks[:-1]):
        base = tok.rstrip(",，").rstrip(L.CLOSERS)
        if i == 0 and base in L.SENT_ADVERBS:
            continue
        if L.is_connective(base):
            n += 1
    return n


def _lint(text, facts_text):
    analysis = L.analyze(text, facts_text=facts_text)
    ev = L.evaluate(analysis, L.load_json(L.THRESHOLDS_PATH), "default", max_hits=3)
    return analysis, ev


def compare(before, after, facts_text=None):
    pre = [r["text"] for r in sentence_records(before, include_refs=True)]
    post_recs = sentence_records(after, include_refs=True)
    post = [r["text"] for r in post_recs]
    sm = difflib.SequenceMatcher(None, pre, post, autojunk=False)
    kept = changed = written = 0
    new_idx = []
    for op, i1, i2, j1, j2 in sm.get_opcodes():
        if op == "equal":
            kept += i2 - i1
        else:
            changed += i2 - i1
            written += j2 - j1
            new_idx.extend(range(j1, j2))
    share = round(changed / len(pre), 3) if pre else 0.0

    nb, na = _numbers(before), _numbers(after)
    fact_keys = L.number_set(facts_text) if facts_text else None
    lost = [{"value": k, "count": len(v), "line": v[0][0], "raw": v[0][1]} for k, v in nb.items() if k not in na]
    new = [{"value": k, "line": v[0][0], "raw": v[0][1],
            "in_facts": (k in fact_keys) if fact_keys is not None else None} for k, v in na.items() if k not in nb]

    structure = {
        "headings_same": _blocks_of(before, "heading") == _blocks_of(after, "heading"),
        "code_same": _blocks_of(before, "code") == _blocks_of(after, "code"),
        "tables": [len(_blocks_of(before, "table")), len(_blocks_of(after, "table"))],
        "chars": [L.analyze(before)["stats"]["chars"], L.analyze(after)["stats"]["chars"]],
    }

    _, ev_b = _lint(before, facts_text)
    an_a, ev_a = _lint(after, facts_text)
    st_b = {r["id"]: r["status"] for r in ev_b["results"]}
    worse_ai, worse_dist, bad_now = [], [], []
    for r in ev_a["results"]:
        if r["status"] in ("GATE", "FAIL"):
            bad_now.append(r)
        if RANK.get(r["status"], 0) > RANK.get(st_b.get(r["id"], "PASS"), 0):
            (worse_dist if r["id"].startswith(DIST_PREFIX) else worse_ai).append(r)

    long_new = []
    for j in new_idx:
        r = post_recs[j]
        if _connectives(r["masked"]) >= 3:
            long_new.append({"line": r["line"], "text": r["text"]})

    must_fix = bool(bad_now or worse_ai)
    return {"sentences": [len(pre), len(post)], "kept": kept, "changed": changed, "written": written,
            "changed_share": share, "lost_numbers": lost, "new_numbers": new, "structure": structure,
            "lint_before": ev_b["summary"], "lint_after": ev_a["summary"],
            "worse_ai": worse_ai, "worse_dist": worse_dist, "gate_fail": bad_now, "long_new": long_new,
            "must_fix": must_fix}


def _fmt_metric(r):
    out = [f"    [{r['status']}] {r['id']} {r['title']}: {r['value']}"]
    for h in r.get("hits", [])[:3]:
        m = f" «{h['match']}»" if h.get("match") else ""
        out.append(f"        L{h['line']}{m}: {excerpt(h['text'], 80)}")
    return out


def render_check(snap, path, res):
    st = res["structure"]
    lb, la = res["lint_before"], res["lint_after"]
    lines = [f"techblog check | 초안 사본 {os.path.basename(snap)} → {os.path.basename(path)}"]
    lines.append(f"문장: 초안 {res['sentences'][0]}문장 중 {res['kept']}문장 그대로, {res['changed']}문장 고치거나 지움"
                 f"({res['changed_share'] * 100:.1f}%), 새로 쓴 문장 {res['written']}개")
    if res["changed_share"] > CHANGED_SHARE_RECHECK:
        lines.append(f"    바뀐 문장이 {int(CHANGED_SHARE_RECHECK * 100)}%를 넘었다. 고친 곳마다 revision.md의 판단 질문에 "
                     "답하는지 다시 읽는다.")
    lines.append(f"본문 글자 수: {st['chars'][0]:,}자 → {st['chars'][1]:,}자")
    lost = res["lost_numbers"]
    if lost:
        lines.append(f"초안에만 있는 수치 {len(lost)}개: 사실의 유일한 언급이었으면 되살린다.")
        for x in lost[:8]:
            lines.append(f"    {x['raw']} (초안 L{x['line']}, 초안에서 {x['count']}회)")
    else:
        lines.append("초안에만 있는 수치: 없음")
    new = res["new_numbers"]
    if new:
        lines.append(f"새 수치 {len(new)}개:")
        for x in new[:8]:
            tag = "" if x["in_facts"] is None else (" fact sheet에 있음" if x["in_facts"] else
                                                    " fact sheet에 없음: 계산한 값이면 fact sheet에 적는다(A15)")
            lines.append(f"    {x['raw']} (L{x['line']}){tag}")
    else:
        lines.append("새 수치: 없음")
    lines.append("구조: 헤딩 " + ("같음" if st["headings_same"] else "바뀜(헤딩과 절 구성은 바꾸지 않는다)")
                 + ", 코드 블록 " + ("같음" if st["code_same"] else "바뀜(코드는 바꾸지 않는다)")
                 + f", 표 {st['tables'][0]}개 → {st['tables'][1]}개")
    lines.append(f"lint: 초안 G{lb['gate_fail']} F{lb['fail']} W{lb['warn']} → 후처리 G{la['gate_fail']} F{la['fail']} W{la['warn']}")
    if res["gate_fail"]:
        lines.append("  Gate 위반과 FAIL(고친다):")
        for r in res["gate_fail"]:
            lines += _fmt_metric(r)
    ai_only = [r for r in res["worse_ai"] if r["status"] not in ("GATE", "FAIL")]
    if ai_only:
        lines.append("  나빠진 AI 문체 항목(고친다):")
        for r in ai_only:
            lines += _fmt_metric(r)
    if res["worse_dist"]:
        lines.append("  나빠진 문장·문단 분포 항목(후처리에서 의도했으면 남기고 보고에 이유를 쓴다):")
        for r in res["worse_dist"]:
            lines += _fmt_metric(r)
    if not (res["gate_fail"] or res["worse_ai"] or res["worse_dist"]):
        lines.append("  나빠진 항목 없음")
    if res["long_new"]:
        lines.append(f"연결어미가 3개 이상인 새 문장 {len(res['long_new'])}개(사실 단위로 나눈다):")
        for x in res["long_new"][:5]:
            lines.append(f"    L{x['line']}: {excerpt(x['text'], 80)}")
    lines.append("판정: " + ("고칠 항목 있음" if res["must_fix"] else "고칠 항목 없음"))
    return "\n".join(lines)


# ---------------------------------------------------------------- 명령

def cmd_start(args):
    snap = snapshot_path(args.article)
    if os.path.exists(snap) and not args.force:
        print(f"초안 사본이 이미 있습니다: {snap}. 후처리를 처음부터 다시 하려면 --force를 붙입니다.", file=sys.stderr)
        return 2
    shutil.copyfile(args.article, snap)
    st = L.analyze(L.read_text(args.article))["stats"]
    print(f"초안 사본: {snap} ({st['sentences']}문장, {st['chars']:,}자). 후처리는 {args.article}을 고친다.")
    return 0


def cmd_repeats(args):
    res = find_repeats(L.read_text(args.article))
    if args.json:
        print(json.dumps(dict(res, file=args.article), ensure_ascii=False, indent=1))
    else:
        print(render_repeats(args.article, res, args.all))
    return 0


def cmd_check(args):
    snap = snapshot_path(args.article)
    if not os.path.isfile(snap):
        print(f"초안 사본이 없습니다: {snap}. 후처리를 시작할 때 start를 먼저 실행합니다.", file=sys.stderr)
        return 2
    fp = args.facts or facts_path(args.article)
    facts_text = L.read_text(fp) if os.path.isfile(fp) else None
    res = compare(L.read_text(snap), L.read_text(args.article), facts_text)
    if args.json:
        slim = dict(res)
        for k in ("worse_ai", "worse_dist", "gate_fail"):
            slim[k] = [{"id": r["id"], "status": r["status"], "value": r["value"]} for r in res[k]]
        print(json.dumps(dict(slim, file=args.article, snapshot=snap, facts=fp if facts_text else None),
                         ensure_ascii=False, indent=1))
    else:
        print(render_check(snap, args.article, res))
    return 1 if res["must_fix"] else 0


def main(argv=None):
    L.setup_stdio()
    ap = argparse.ArgumentParser(description="techblog 후처리 보조")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("start", help="초안 사본을 만든다")
    p.add_argument("article")
    p.add_argument("--force", action="store_true")
    p = sub.add_parser("repeats", help="다시 읽을 반복 후보를 출력한다")
    p.add_argument("article")
    p.add_argument("--all", action="store_true")
    p.add_argument("--json", action="store_true")
    p = sub.add_parser("check", help="초안 사본과 비교한다")
    p.add_argument("article")
    p.add_argument("--facts")
    p.add_argument("--json", action="store_true")
    try:
        args = ap.parse_args(argv)
    except SystemExit as e:
        return 2 if e.code else 0
    if args.article.endswith((SNAPSHOT_SUFFIX, FACTS_SUFFIX)):
        print(f"후처리할 글의 경로를 줍니다. 받은 경로는 작업 파일입니다: {args.article}", file=sys.stderr)
        return 2
    if not os.path.isfile(args.article):
        print(f"파일이 없습니다: {args.article}", file=sys.stderr)
        return 2
    try:
        return {"start": cmd_start, "repeats": cmd_repeats, "check": cmd_check}[args.cmd](args)
    except (OSError, ValueError, KeyError) as e:
        print(f"revise_ko 실행 오류: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
