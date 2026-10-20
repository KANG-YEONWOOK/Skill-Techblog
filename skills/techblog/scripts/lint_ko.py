#!/usr/bin/env python3
"""techblog lint: 한국어 기술 블로그 글에서 rubric의 자동 측정 항목(G, A)을 센다.

사용법
  python lint_ko.py ARTICLE.md [--tone default|casual|auto] [--facts FACTS.md]
                    [--thresholds PATH] [--json] [--all] [--max-hits N]
  python lint_ko.py KO.md --short [--source EN.md] [--terms TERMS.json] [--tone ...]

--short는 짧은 글 모드(SKILL.md의 short)다. thresholds.json의 short 프로필대로
문장 단위 문체 검사만 보고, --source가 있으면 원문과 구조, 코드, URL, 숫자, 멘션,
자리표시자가 같은지 대조한다(F 항목, 어기면 Gate).

종료 코드: 0 통과, 1 기준 미달, 2 사용법 또는 입력 오류
표준 라이브러리만 쓴다(Python 3.8 이상).
"""

import argparse
import json
import math
import os
import re
import sys
import unicodedata

HERE = os.path.dirname(os.path.abspath(__file__))
PATTERNS_PATH = os.path.join(HERE, "patterns_ko.json")
THRESHOLDS_PATH = os.path.join(HERE, "thresholds.json")
LINT_SCHEMA = 1


# ---------------------------------------------------------------- 입출력

def setup_stdio():
    """Windows 콘솔 기본 인코딩(cp949)에서도 한글이 깨지지 않게 UTF-8로 바꾼다."""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):
            pass


def normalize_text(text):
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    return unicodedata.normalize("NFC", text)


def read_text(path):
    with open(path, encoding="utf-8-sig") as f:
        return normalize_text(f.read())


def load_json(path):
    with open(path, encoding="utf-8-sig") as f:
        return json.load(f)


# ---------------------------------------------------------------- markdown 블록

class Block:
    __slots__ = ("type", "text", "line", "level", "list_id", "depth")

    def __init__(self, type_, text, line, level=0, list_id=None, depth=0):
        self.type = type_
        self.text = text
        self.line = line
        self.level = level
        self.list_id = list_id
        self.depth = depth


FENCE_RE = re.compile(r"^ {0,3}(`{3,}|~{3,})")
ATX_RE = re.compile(r"^ {0,3}(#{1,6})(?:[ \t]+(.*?))?[ \t]*#*[ \t]*$")
SETEXT_RE = re.compile(r"^ {0,3}(=+|-+)[ \t]*$")
HR_RE = re.compile(r"^ {0,3}([-*_])(?:[ \t]*\1){2,}[ \t]*$")
LIST_RE = re.compile(r"^([ \t]*)([-*+]|\d{1,3}[.)])[ \t]+(.*)$")
BQ_RE = re.compile(r"^ {0,3}>[ ]?(.*)$")
TABLE_DELIM_RE = re.compile(r"^[ \t]*\|?[ \t]*:?-{2,}:?[ \t]*(\|[ \t]*:?-{2,}:?[ \t]*)*\|?[ \t]*$")
HTML_BLOCK_RE = re.compile(
    r"^ {0,3}</?(div|details|summary|table|thead|tbody|tr|td|th|figure|figcaption|iframe|video|"
    r"picture|source|section|aside|p|img|pre|ul|ol|li|hr|center|blockquote|script|style)\b", re.I)
HTML_COMMENT_RE = re.compile(r"^ {0,3}<!--")


def _is_block_start(line):
    return bool(FENCE_RE.match(line) or ATX_RE.match(line) or BQ_RE.match(line)
                or LIST_RE.match(line) or HR_RE.match(line) or HTML_BLOCK_RE.match(line))


def parse_blocks(text):
    """줄 단위로 markdown을 블록(heading, paragraph, list_item, blockquote, code, table, html)으로 나눈다."""
    lines = text.split("\n")
    n = len(lines)
    blocks = []
    i = 0
    if n and lines[0].strip() == "---":  # front matter
        for j in range(1, min(n, 300)):
            if lines[j].strip() in ("---", "..."):
                i = j + 1
                break
    para = []
    para_start = 0
    list_counter = 0
    cur_list = None  # [list_id, base_indent]

    def flush():
        nonlocal para
        if para:
            blocks.append(Block("paragraph", " ".join(p.strip() for p in para), para_start))
            para = []

    while i < n:
        line = lines[i]
        stripped = line.strip()
        if not stripped:
            flush()
            i += 1
            continue
        m = FENCE_RE.match(line)
        if m:
            flush()
            cur_list = None
            fence = m.group(1)
            close_re = re.compile(r"^ {0,3}" + re.escape(fence[0]) + "{" + str(len(fence)) + r",}[ \t]*$")
            start = i
            i += 1
            body = []
            while i < n and not close_re.match(lines[i]):
                body.append(lines[i])
                i += 1
            i += 1
            blocks.append(Block("code", "\n".join(body), start + 1))
            continue
        if HTML_COMMENT_RE.match(line):
            flush()
            start = i
            while i < n and "-->" not in lines[i]:
                i += 1
            i += 1
            blocks.append(Block("html", "", start + 1))
            continue
        m = ATX_RE.match(line)
        if m:
            flush()
            cur_list = None
            blocks.append(Block("heading", (m.group(2) or "").strip(), i + 1, level=len(m.group(1))))
            i += 1
            continue
        if para and SETEXT_RE.match(line):
            title = " ".join(p.strip() for p in para)
            blocks.append(Block("heading", title, para_start, level=1 if stripped.startswith("=") else 2))
            para = []
            i += 1
            continue
        if HR_RE.match(line):
            flush()
            cur_list = None
            i += 1
            continue
        if "|" in line and not para and i + 1 < n and TABLE_DELIM_RE.match(lines[i + 1]):
            cur_list = None
            start = i
            rows = []
            while i < n and lines[i].strip() and "|" in lines[i]:
                rows.append(lines[i])
                i += 1
            blocks.append(Block("table", "\n".join(rows), start + 1))
            continue
        m = BQ_RE.match(line)
        if m:
            flush()
            cur_list = None
            start = i
            parts = []
            while i < n:
                mm = BQ_RE.match(lines[i])
                if mm:
                    parts.append(mm.group(1).strip())
                elif lines[i].strip() and parts and parts[-1] and not _is_block_start(lines[i]):
                    parts.append(lines[i].strip())  # lazy continuation
                else:
                    break
                i += 1
            blocks.append(Block("blockquote", " ".join(p for p in parts if p), start + 1))
            continue
        m = LIST_RE.match(line)
        if m:
            flush()
            indent = len(m.group(1).replace("\t", "    "))
            if cur_list is None:
                list_counter += 1
                cur_list = [list_counter, indent]
            depth = 0 if indent <= cur_list[1] else 1 + (indent - cur_list[1]) // 2
            start = i
            parts = [m.group(3).strip()]
            i += 1
            while i < n:
                nxt = lines[i]
                if not nxt.strip() or _is_block_start(nxt):
                    break
                parts.append(nxt.strip())
                i += 1
            blocks.append(Block("list_item", " ".join(parts), start + 1, list_id=cur_list[0], depth=depth))
            j = i
            while j < n and not lines[j].strip():
                j += 1
            if j < n and LIST_RE.match(lines[j]):
                i = j
            elif j < n and lines[j].startswith(("  ", "\t")) and not FENCE_RE.match(lines[j]):
                # 들여 쓴 문단은 같은 목록 항목의 이어지는 내용으로 본다.
                start2 = j
                parts2 = []
                while j < n and lines[j].strip() and not LIST_RE.match(lines[j]):
                    parts2.append(lines[j].strip())
                    j += 1
                blocks.append(Block("list_item", " ".join(parts2), start2 + 1, list_id=cur_list[0], depth=depth + 1))
                i = j
            else:
                cur_list = None
            continue
        if HTML_BLOCK_RE.match(line):
            flush()
            cur_list = None
            start = i
            while i < n and lines[i].strip():
                i += 1
            blocks.append(Block("html", "", start + 1))
            continue
        if not para and line.startswith(("    ", "\t")) and cur_list is None:
            start = i
            body = []
            while i < n and (lines[i].startswith(("    ", "\t")) or not lines[i].strip()):
                body.append(lines[i])
                i += 1
            blocks.append(Block("code", "\n".join(body), start + 1))
            continue
        if not para:
            para_start = i + 1
            cur_list = None
        para.append(line)
        i += 1
    flush()
    return blocks


# ---------------------------------------------------------------- 인라인 정리

PH_CODE, PH_URL, PH_REF, PH_QUOTE = "⟦C⟧", "⟦U⟧", "⟦R⟧", "⟦Q⟧"
PH_RE = re.compile(r"⟦[CURQ]⟧")
INLINE_CODE_RE = re.compile(r"(`+)(.+?)\1")
IMAGE_RE = re.compile(r"!\[([^\]]*)\]\((?:[^()]|\([^()]*\))*\)")
LINK_RE = re.compile(r"\[([^\]]+)\]\((?:[^()]|\([^()]*\))*\)")
REFLINK_RE = re.compile(r"\[([^\]]+)\]\[[^\]]*\]")
AUTOLINK_RE = re.compile(r"<(?:https?|ftp)://[^>\s]+>")
URL_RE = re.compile(r"(?:https?|ftp)://[^\s<>\"')\]]+")
FOOTNOTE_RE = re.compile(r"\[\^[^\]]+\]")
CITE_RE = re.compile(r"\[\d+(?:\s*[,–\-]\s*\d+)*\]")
HTML_TAG_RE = re.compile(r"</?[a-zA-Z][^<>]*>")
BOLD_RE = re.compile(r"(\*\*|__)(?=\S)(.+?)(?<=\S)\1")
EM_RE = re.compile(r"(?<![\w*])\*(?=\S)([^*\n]+?)(?<=\S)\*(?![\w*])")
ESCAPE_RE = re.compile(r"\\([\\`*_{}\[\]()#+\-.!|>])")


def clean_inline(s):
    """인라인 markdown을 걷어 낸 문장 텍스트, bold 개수, 인라인 코드 목록을 돌려준다."""
    codes = []

    def code_sub(m):
        codes.append(m.group(2))
        return PH_CODE

    s = INLINE_CODE_RE.sub(code_sub, s)
    s = IMAGE_RE.sub("", s)
    s = LINK_RE.sub(lambda m: m.group(1), s)
    s = REFLINK_RE.sub(lambda m: m.group(1), s)
    s = AUTOLINK_RE.sub(PH_URL, s)
    s = URL_RE.sub(PH_URL, s)
    s = FOOTNOTE_RE.sub("", s)
    s = CITE_RE.sub(PH_REF, s)
    s = HTML_TAG_RE.sub("", s)
    bold = len(BOLD_RE.findall(s))
    s = BOLD_RE.sub(lambda m: m.group(2), s)
    s = EM_RE.sub(lambda m: m.group(1), s)
    s = ESCAPE_RE.sub(r"\1", s)
    s = re.sub(r"[ \t]+", " ", s).strip()
    return s, bold, codes


QUOTE_PAIRS = (("“", "”"), ("「", "」"), ("『", "』"), ("‘", "’"))


def mask_quotes(s):
    """따옴표 안 텍스트를 ⟦Q⟧로 가린다. 자료의 표현을 인용한 부분은 패턴 검사에서 뺀다."""
    for a, b in QUOTE_PAIRS:
        s = re.sub(re.escape(a) + "[^" + re.escape(b) + r"\n]{0,200}" + re.escape(b), PH_QUOTE, s)
    s = re.sub(r"\"[^\"\n]{0,200}\"", PH_QUOTE, s)
    s = re.sub(r"'([^'\n]{1,60})'", lambda m: PH_QUOTE if re.search("[가-힣]", m.group(1)) else m.group(0), s)
    return s


PH_MATH = "⟦M⟧"
# 한글이 없는 $...$와 $$...$$를 수식으로 본다. "$5에서 $10으로" 같은 통화 표기에는 한글이 들어 있어 가리지 않는다.
MATH_RE = re.compile(r"\$\$[^$]+\$\$|\$[^$\n가-힣]+\$")


def mask_math(s):
    """수식을 ⟦M⟧로 가린다. 문장 부호 정책(G6)과 숫자 뒤 조사(G10) 검사에만 쓴다."""
    return MATH_RE.sub(PH_MATH, s)


def visible_chars(s):
    return len(re.sub(r"\s", "", PH_RE.sub("", s)))


# ---------------------------------------------------------------- 문장 분리

TERMINATORS = ".?!…"
CLOSERS = "\"'”’)]}」』"
DEPTH_OPEN = "(「『[{“‘"
DEPTH_CLOSE = ")」』]}”’"
ABBREVIATIONS = {"e.g", "i.e", "vs", "etc", "cf", "fig", "figs", "eq", "al", "approx", "ref", "sec",
                 "ch", "vol", "pp", "no", "mr", "dr", "jr", "sr", "inc", "ltd", "u.s", "ph.d"}


def _is_abbrev(text, i):
    m = re.search(r"([A-Za-z][A-Za-z.]{0,5})$", text[:i])
    if not m:
        return False
    tok = m.group(1).lower().rstrip(".")
    if tok in ABBREVIATIONS:
        return True
    return len(tok) == 1 and text[i - 1].isupper()  # 이니셜(J. Smith)


def _split_flat(s):
    return [p.strip() for p in re.split(r"(?<=[.?!…])\s+", s) if p.strip()]


def split_sentences(text):
    """마침표, 물음표, 느낌표 뒤 공백을 경계로 나눈다. 괄호와 따옴표 안, 숫자(3.5), 약어(e.g.)에서는 나누지 않는다."""
    sents = []
    start = 0
    depth = 0
    in_dq = False
    i = 0
    n = len(text)
    while i < n:
        ch = text[i]
        if ch in DEPTH_OPEN:
            depth += 1
        elif ch in DEPTH_CLOSE:
            if depth > 0:
                depth -= 1
        elif ch == '"':
            in_dq = not in_dq
        elif ch in TERMINATORS and depth == 0 and not in_dq:
            j = i
            while j + 1 < n and text[j + 1] in TERMINATORS:
                j += 1
            k = j
            while k + 1 < n and text[k + 1] in CLOSERS and text[k + 1] != '"':
                k += 1
            if (k + 1 >= n or text[k + 1].isspace()) and not _is_abbrev(text, i):
                seg = text[start:k + 1].strip()
                if seg:
                    sents.append(seg)
                start = k + 1
                i = k + 1
                continue
            i = j
        i += 1
    tail = text[start:].strip()
    if tail:
        sents.append(tail)
    out = []
    for s in sents:
        out.extend(_split_flat(s) if len(s) > 400 else [s])
    return out


# ---------------------------------------------------------------- 종결어미 분류

HANGUL_RE = re.compile(r"[가-힣]")
JONG_B, JONG_SS = 17, 20  # 받침 ㅂ, ㅆ
NOUN_YO = ("필요", "중요", "주요", "수요", "개요", "강요", "소요", "요요")
HAERA_NOUNS = ("람다", "판다", "바다", "어젠다", "아젠다")
NOMINAL_RE = re.compile(r"(함|됨|했음|됐음|였음|었음|았음|있음|없음|같음|좋음|않음)$")
NOMINAL_EXCEPT = ("결함", "포함")
TRAIL_STRIP = " \t.?!…\"'”’)]}」』:;~*_,"
BANNED_ENDINGS = ("더라고요", "더군요", "네요", "잖아요", "답니다")
EXPERIENCE_ENDINGS = ("더라고요", "더군요", "네요")


def _jong(ch):
    code = ord(ch) - 0xAC00
    return code % 28 if 0 <= code < 11172 else -1


def _jung(ch):
    code = ord(ch) - 0xAC00
    return (code // 28) % 21 if 0 <= code < 11172 else -1


def last_word(sentence):
    s = PH_RE.sub(" ", sentence).strip()
    for _ in range(3):  # 문장 끝 괄호 보충("적용했습니다(그림 1).")은 떼고 본다.
        s2 = re.sub(r"\s*[(\[][^()\[\]]*[)\]]\s*[.?!…]*\s*$", "", s)
        if s2 == s:
            break
        s = s2
    s = s.rstrip(TRAIL_STRIP)
    toks = s.split()
    return toks[-1] if toks else ""


def classify_ending(word, question=False):
    """마지막 어절로 문장 종결을 분류한다: HAPNIDA, HAEYO, Q_KKAYO, HAERA, NOMINAL, NOUN, OTHER."""
    if not word or not HANGUL_RE.match(word[-1]):
        return "OTHER"
    if len(word) >= 3 and word.endswith(("니다", "니까")) and _jong(word[-3]) == JONG_B:
        return "HAPNIDA"
    if word.endswith("십시오") or (len(word) >= 3 and word.endswith("시다") and _jong(word[-3]) == JONG_B):
        return "HAPNIDA"
    if word.endswith(("요", "죠")):
        if word.endswith(NOUN_YO):
            return "NOUN"
        if word.endswith("까요"):
            return "Q_KKAYO"
        return "HAEYO"
    if word.endswith("다") and not word.endswith(HAERA_NOUNS):
        return "HAERA"
    if question and word.endswith(("까", "냐", "니", "가", "나")):
        return "HAERA"
    if NOMINAL_RE.search(word) and not word.endswith(NOMINAL_EXCEPT):
        return "NOMINAL"
    return "NOUN"


def ending_bucket(sentence, word, cls):
    """같은 종결 반복과 어미 분포를 세기 위한 세부 분류."""
    w = word
    tail = PH_RE.sub(" ", sentence).rstrip(TRAIL_STRIP)
    if cls == "HAPNIDA":
        if w.endswith("니까"):
            return "D_Q"
        if w.endswith("십시오") or w.endswith("시다"):
            return "D_IMP"
        if re.search(r"수\s*있습니다$", tail):
            return "D_CAN"
        if w.endswith("겠습니다"):
            return "D_FUT"
        if w.endswith(("있습니다", "없습니다")):
            return "D_EXIST"
        if w.endswith("것입니다"):
            return "D_GEOT"
        if w.endswith("입니다"):
            return "D_COP"
        if w.endswith("습니다") and len(w) >= 4 and _jong(w[-4]) == JONG_SS and w[-4] not in "있겠":
            return "D_PAST"
        if w.endswith("습니다"):
            return "D_S_PRES"
        return "D_B_PRES"
    if cls == "Q_KKAYO":
        return "Q_KKAYO"
    if cls == "HAEYO":
        for suf, name in (("더라고요", "C_DEORAGO"), ("더군요", "C_DEORAGO"), ("잖아요", "C_JANAYO"),
                          ("네요", "C_NEYO"), ("거든요", "C_GEUDEUN"), ("는데요", "C_NEUNDEYO"),
                          ("은데요", "C_NEUNDEYO"), ("인데요", "C_NEUNDEYO"), ("고요", "C_GOYO"),
                          ("게요", "C_WILL"), ("세요", "C_SEYO"), ("나요", "C_Q"), ("가요", "C_Q")):
            if w.endswith(suf):
                return name
        if w.endswith(("죠", "지요")):
            return "C_JYO"
        if re.search(r"수\s*있어요$", tail):
            return "C_CAN"
        if w.endswith(("있어요", "없어요")):
            return "C_EXIST"
        if w.endswith(("거예요", "거에요")):
            return "C_GEO"
        if w.endswith(("이에요", "예요", "이에요", "에요")):
            return "C_COP"
        if len(w) >= 3 and w.endswith(("어요", "아요")) and _jong(w[-3]) == JONG_SS and w[-3] not in "있겠":
            return "C_PAST"
        return "C_PRES"
    return cls


# ---------------------------------------------------------------- 쉼표, 나열

CONNECTIVE_SUFFIXES = ("면서도", "으면서", "면서", "지만", "는데", "은데", "인데", "던데", "으며", "며",
                       "니까", "므로", "도록", "더라도", "다가", "거나", "든지", "려고", "다면", "라면",
                       "으면", "면", "고서", "고", "서")
GO_STOP = ("참고", "최고", "보고", "경고", "광고", "사고", "재고", "창고", "원고", "신고", "라고", "다고",
           "자고", "냐고", "제고", "등고")
MYEON_STOP = ("측면", "반면", "화면", "표면", "전면", "단면", "국면", "방면", "장면", "정면", "평면", "이면",
              "내면", "지면", "대면", "직면", "수면", "후면", "앞면", "뒷면", "한편")
SEO_VOWELS = {0, 1, 4, 6, 9, 10, 14}  # ㅏ ㅐ ㅓ ㅕ ㅘ ㅙ ㅝ
SENT_ADVERBS = ("그리고", "그러나", "그런데", "그러므로", "하지만", "그래서", "따라서", "그러니까", "또한",
                "반면", "즉", "특히", "다만", "예를", "결과적으로", "한편", "게다가", "물론", "아울러", "덧붙여")
G7_ADVERBS = ("그리고", "그러나", "그런데", "그러므로", "하지만", "그래서", "따라서")


def is_connective(word):
    if len(word) < 2 or not HANGUL_RE.match(word[-1]):
        return False
    for suf in CONNECTIVE_SUFFIXES:
        if not word.endswith(suf):
            continue
        if suf == "고" and word.endswith(GO_STOP):
            return False
        if suf == "면" and word.endswith(MYEON_STOP):
            return False
        if suf == "서":
            if word.endswith(("에서", "께서")):
                return False
            prev = word[-2]
            if _jong(prev) != 0 or _jung(prev) not in SEO_VOWELS:
                return False
        return True
    return False


DIGIT_COMMA_RE = re.compile(r"(?<=\d),(?=\d{3})")


def comma_count(masked):
    return len(re.findall(r"[,，]", DIGIT_COMMA_RE.sub("", masked)))


TRIAD_DATA_RE = re.compile(r"[0-9A-Za-z⟦]")


def is_triad(masked):
    """수사적 셋 묶음("빠르고, 안정적이고, 확장 가능한")을 센다.
    수치, 영문 이름, 인용이 든 나열은 자료의 데이터를 옮긴 것이라 세지 않는다."""
    s = DIGIT_COMMA_RE.sub("", masked)
    parts = [p.strip() for p in re.split(r"[,，]", s)]
    if len(parts) < 3:
        return False
    if any(TRIAD_DATA_RE.search(p) for p in parts[1:-1]) or TRIAD_DATA_RE.search(parts[0].split()[-1] if parts[0].split() else ""):
        return False
    return all(1 <= len(p.split()) <= 4 for p in parts[1:-1])


# ---------------------------------------------------------------- 수치

# "수십만 명", "수천 개", "몇백 건"처럼 숫자 없이 쓴 어림 수량어
KO_APPROX_RE = re.compile(r"(?<![가-힣])(?:수|몇)(?:십|백|천)?(?:만|억|조)?(?<=[십백천만억조])(?!큼)")
# "요청 수만 줄였습니다"의 "수만"은 개수를 뜻하는 "수"에 조사 "만"이 붙은 말이다. 앞에 명사가 있고 뒤에 단위가 없으면 어림 수량어로 세지 않는다.
KO_APPROX_UNIT_AFTER_RE = re.compile(
    r"\s?(?:[0-9A-Za-z]|(?:명|건|개|원|대|줄|번|회|곳|종|편|장|권|배|여|가지|시간|초|분|일|년|달|주|자|단어|토큰|행|쪽|바이트|달러)"
    r"(?:의|이|가|을|를|은|는|에|씩|도|만|과|와|으로|로)?(?![가-힣]))")


def ko_approx_hits(text):
    """text에서 어림 수량어를 찾는다. "명사 + 수만 + 동사"의 "수만"(개수 + 조사 "만")은 뺀다."""
    hits = []
    for m in KO_APPROX_RE.finditer(text):
        if m.group(0) in ("수만", "몇만"):
            before, after = text[:m.start()], text[m.end():]
            if re.search(r"[가-힣]\s$", before) and not KO_APPROX_UNIT_AFTER_RE.match(after):
                continue
        hits.append(m.group(0))
    return hits


NUM_RE = re.compile(
    r"(?<![\w.\-])(\d{1,3}(?:,\d{3})+|\d+)(?:\.(\d+))?"
    r"(\s*(?:%p|%|배|x|×|ms|초|분|시간|개|건|명|만|억|천|조|GB|MB|KB|TB|토큰|단어|문장|편|회|번|자|어절|쌍|년|점))?")


def extract_numbers(text):
    """(정규화한 값, 원문) 목록. 한 자리 정수는 단위가 없으면 뺀다(\"3단계\" 같은 서수 표현)."""
    out = []
    for m in NUM_RE.finditer(PH_RE.sub(" ", text)):
        ip, frac, unit = m.group(1), m.group(2), (m.group(3) or "").strip()
        key = ip.replace(",", "")
        if frac:
            frac = frac.rstrip("0")
            if frac:
                key += "." + frac
        if len(key) == 1 and not unit:
            continue
        out.append((key.lstrip("0") or "0", m.group(0).strip()))
    return out


def number_set(text):
    keys = set()
    for m in NUM_RE.finditer(text):
        ip, frac = m.group(1), m.group(2)
        key = ip.replace(",", "")
        if frac and frac.rstrip("0"):
            key += "." + frac.rstrip("0")
        keys.add(key.lstrip("0") or "0")
    return keys


# ---------------------------------------------------------------- 분석

EMOJI_RE = re.compile("[\U0001F000-\U0001FAFF☀-⛿✀-➿⭐⭕‼⁉]")
# 문장 부호 정책(G6). em dash 계열, 줄표 대신 띄어 쓴 하이픈, 가운뎃점 계열, en dash와 빼기 기호를 센다.
EMDASH_CHAR_RE = re.compile("[—―]")
SPACED_HYPHEN_RE = re.compile(r"[가-힣][)\]'\"”’]?\s+-{1,2}\s+\S|\S\s+-{1,2}\s+[가-힣]")
POLICY_CHAR_RE = re.compile("[·•‧∙・･–‒−]")
PAGE_RANGE_RE = re.compile(r"\d\s?[–‒—―−]\s?\d")
# 참고자료 절의 헤딩. 헤딩 전체가 참고자료를 뜻하는 낱말일 때만 참고자료 절로 본다
# ("데이터 출처와 전처리", "참고할 설정"은 본문 절이다).
REF_STRONG = r"(?:참고|레퍼런스|references?|bibliography|출처|각주|(?:더\s*)?읽을\s*거리)"
REF_HEADING_RE = re.compile(r"^\s*(?:\d+[.)]?\s*)?(?=.*" + REF_STRONG + r")"
                            r"(?:(?:" + REF_STRONG + r"|자료|문헌|링크|links?|및|and|&|/|,)\s*)+:?\s*$", re.I)
QUESTION_HEADING_RE = re.compile(r"(\?|을까|를까|할까|일까|될까|볼까|까요|나요|는가|인가)$")

# 숫자 뒤 조사(G10). 마지막 숫자를 한국어로 읽은 소리의 받침에 맞춰 조사를 고른다.
NUM_PARTICLE_RE = re.compile(
    r"(?<![\w.,\-/@])(\d[\d,]*(?:\.\d+)?)(%p|%)?"
    r"(?:(이에요|예요|이|가|을|를|은|는|과|와|으로|로)(?=[\s.,?!:;)\]」』”’\"']|$)|(였)(?=[가-힣]))")
# 영문과 숫자로만 된 낱말 바로 뒤의 숫자는 영어로 읽는 이름이나 버전으로 보고 건너뛴다(Llama 3, Windows 11).
LATIN_TOKEN_BEFORE_RE = re.compile(r"(?:^|\s)[A-Za-z][A-Za-z0-9.+\-]*\s$")
DIGIT_FINAL = {"0": "ㅇ", "1": "ㄹ", "2": "", "3": "ㅁ", "4": "", "5": "", "6": "ㄱ", "7": "ㄹ", "8": "ㄹ", "9": ""}
PARTICLE_ALT = {"이에요": "예요", "예요": "이에요", "이": "가", "가": "이", "을": "를", "를": "을", "은": "는",
                "는": "은", "과": "와", "와": "과", "으로": "로", "로": "으로", "였": "이었"}

# 병기한 용어(A19). "한국어(원어)"와 "원어(한국어)" 쌍을 모은다.
TERM_KE_RE = re.compile(r"((?:[가-힣]{1,12} )?[가-힣]{2,12}) ?\(([A-Za-z][A-Za-z0-9 .'\-]{0,40}[A-Za-z0-9.]|[A-Za-z])\)")
TERM_EK_RE = re.compile(r"(?<![A-Za-z0-9_\-])([A-Za-z][A-Za-z0-9.\-]*(?: [A-Za-z][A-Za-z0-9.\-]*){0,3})"
                        r" ?\(([가-힣]+(?: [가-힣]+)?)\)")
ACRONYM_RE = re.compile(r"^[A-Z][A-Z0-9]{1,6}s?$")
IDENTIFIER_RE = re.compile(r"[a-z][A-Z]|\d|_")  # sessionID, Q10, max_tokens 같은 식별자는 용어 쌍으로 보지 않는다
GLOSS_PARTICLE_RE = re.compile(r"(을|를|은|는|이|가|의|에|로|와|과|하는|되는|한|된|여|고|서|며|면|게|어|아)$")
PHRASE_END_RE = re.compile(r"(에서도|에서|에는|에게|으로|까지|부터|처럼|하는|되는|하고|이고|[가-힣]{2}(?:은|는|을|를|이|가|의|에|와|과))$")
PAREN_RE = re.compile(r"\([^()]*\)")
KO_PARTICLES = r"(?:에서는|에서도|에서|에는|으로|처럼|보다|까지|부터|은|는|이|가|을|를|의|에|과|와|도|만|로)"

# 처음 나오는 용어의 설명(A20). 학명("C. elegans", 기울임꼴 "*Cancer borealis*")과 대문자 약어를 찾는다.
SPECIES_ABBR_RE = re.compile(r"(?<![A-Za-z0-9_.])[A-Z]\.\s[a-z]{3,}(?![A-Za-z])")
SPECIES_ITALIC_RE = re.compile(r"(?<![*_A-Za-z0-9])[*_]([A-Z][a-z]+ [a-z]{3,})[*_](?![*_A-Za-z0-9])")
LATIN_PHRASES = frozenset(("In vivo", "In vitro", "In silico", "In situ", "Ex vivo", "De novo"))
ABBR_RE = re.compile(r"(?<![A-Za-z0-9_\-])[A-Z]{2}[A-Z0-9]{0,5}(?![A-Za-z0-9_\-])")
# 처음 나올 때 풀네임이 없어도 후보로 보여 주지 않는 대문자 낱말. 0.9.0부터 독자를 개발자로 가정하지 않으므로
# API, CPU, HTTP 같은 분야 약어는 넣지 않는다(자료 분야의 지식이 없을 수 있는 독자는 이 약어도 모른다).
# GENERAL_ABBR: 분야를 공부하지 않은 사람도 생활과 뉴스에서 설명 없이 접하는 약어와 회사 이름
GENERAL_ABBR = frozenset((
    "AI", "IT", "PC", "TV", "USB", "PDF", "DNA", "CEO", "SNS", "GPS", "ID", "OK", "ON", "OFF", "FAQ", "CCTV", "LED",
    "QR", "SMS", "MRI", "CT", "ATM", "VR", "GPT", "AMD", "IBM", "NVIDIA", "LG", "SK", "KT"))
# CODE_WORDS: 약어가 아니라 대문자로 쓰는 낱말(SQL과 HTTP 키워드, 로그 레벨), 용량 단위, 시간대, 로마 숫자
CODE_WORDS = frozenset((
    "ALTER", "AND", "AS", "ASC", "BY", "CREATE", "DELETE", "DESC", "DISTINCT", "DROP", "EXISTS", "FALSE", "FORCE",
    "FROM", "GET", "GROUP", "HAVING", "HEAD", "IN", "INDEX", "INNER", "INSERT", "INTO", "IS", "JOIN", "LEFT", "LIKE",
    "LIMIT", "NOT", "NULL", "OFFSET", "OPTIONS", "OR", "ORDER", "OUTER", "PATCH", "POST", "PUT", "RIGHT", "SELECT",
    "SET", "TABLE", "TEXT", "TRUE", "UNION", "UNIQUE", "UPDATE", "VALUES", "WHERE", "WITH",
    "DEBUG", "INFO", "WARN", "ERROR", "FATAL", "TODO",
    "KB", "MB", "GB", "TB", "PB", "KST", "UTC", "GMT",
    "II", "III", "IV", "VI", "VII", "VIII", "IX", "XI", "XII"))
COMMON_ABBR = GENERAL_ABBR | CODE_WORDS
DESC_SKIP = ("-", "—", "없음")

# 출처를 밝히지 않은 주어(A18.bare_author). 본문이 연구를 둘 이상 인용할 때만 본다.
WORK_CITE_RE = re.compile(
    r"([A-Z][A-Za-z'’\-]+)(?:\s+(?:et\s+al\.|등|외)|\s*(?:&|and)\s*[A-Z][A-Za-z'’\-]+)?\s*\(\s*((?:19|20)\d{2})[a-z]?\s*\)"
    r"|([A-Z][A-Za-z'’\-]+)\s+et\s+al\."
    r"|([가-힣]{1,4})\s*(?:등|외)\s*\(\s*((?:19|20)\d{2})[a-z]?\s*\)")
# 저자 이름 뒤에 조사가 붙은 말("Cornelia Bargmann과 Eve Marder는", "Marder는")도 연구를 이름으로 가리킨 것으로 본다.
NAMED_SOURCE_RE = re.compile(r"[A-Z][a-z]{2,}(?:\s+(?:et\s+al\.|등))?(?:은|는|이|가|과|와|의|도)(?=[\s,]|$)")
# "연구진", "연구팀", "이 연구", "이 논문", "원문"은 문장 첫머리에 올 때만 본다("Facebook의 AI 연구팀이"는 이름이 있다).
BARE_AUTHOR_RE = re.compile(r"(?:^|[\s(])((?:저자들?|세\s저자|두\s저자|네\s저자|같은\s연구|같은\s논문|같은\s글|두\s글)"
                            r"(?:은|는|이|가|도))\s|^((?:연구진|연구팀|이\s연구|이\s논문|원문)(?:은|는|이|가|도))\s")


class Sentence:
    __slots__ = ("text", "masked", "kind", "block", "para", "line", "first", "last",
                 "word", "cls", "bucket", "question", "in_refs")


def _compile_patterns(spec):
    compiled = {}
    for pid, p in spec["patterns"].items():
        compiled[pid] = {
            "title": p.get("title", pid),
            "scope": p.get("scope", "sentence"),
            "max_len": p.get("max_len"),
            "hint": p.get("hint", ""),
            "raw": bool(p.get("raw")),
            "headings": bool(p.get("headings")),
            "tables": bool(p.get("tables")),
            "regex": [re.compile(r) for r in p["regex"]],
        }
    return compiled


def _hit(sent, match=None):
    h = {"line": sent.line, "text": sent.text[:160]}
    if match is not None:
        h["match"] = match
    return h


def same_predicate_adjacent_hits(paragraphs):
    """같은 문단의 이웃한 서술문이 같은 마지막 어절로 끝나는 검토 후보.

    형태소 분석이나 어미 분포(C_PRES 등)가 아니라 표면 어절을 비교한다. 따라서
    '점도 들어요', '라고도 말해요'도 잡되 활용이 다른 동사와 문장 안 반복은 판정하지 않는다.
    질문, 명령, 명사구, 인용문을 건너뛰어 떨어진 두 문장을 이어 붙이지 않는다.
    """
    hits = []
    for sentences in paragraphs:
        previous, previous_word = None, None
        for sent in sentences:
            # 인라인 인용, 코드, 링크 주소는 서술어로 세지 않는다. 링크의 표시 글자와
            # 강조 표시는 clean_inline에서 처리하며, 밑줄 강조의 남은 여는 표지도 뗀다.
            word = last_word(sent.masked).lstrip("*_~")
            cls = classify_ending(word, sent.question)
            declarative = (not sent.in_refs and not sent.question
                           and cls in ("HAPNIDA", "HAEYO", "HAERA")
                           and not word.endswith(("십시오", "세요", "시다", "니까"))
                           and bool(re.fullmatch(r"[가-힣]+", word)))
            if declarative and previous_word == word:
                hit = _hit(sent, word)
                hit["previous"] = _hit(previous)
                hits.append(hit)
            previous, previous_word = sent, word if declarative else None
    return hits


def _unit_hit(line, text, target, m):
    """문장이 아닌 단위(헤딩, 표 행, 블록)에서 찾은 위치. match에는 앞뒤 여덟 글자를 붙인다."""
    a, b = max(0, m.start() - 8), min(len(target), m.end() + 8)
    return {"line": line, "text": text[:160], "match": target[a:b].strip()}


def punct_hits(blocks):
    """문장 부호 정책(G6) 위반을 센다. 헤딩, 문단, 목록, 인용, 표 셀을 보고 코드, 인라인 코드, 수식, URL은 뺀다.
    참고자료 절에서는 숫자 사이의 대시(쪽 범위)만 센다. 돌려주는 값: (em dash 계열, 가운뎃점과 en dash와 빼기 기호)."""
    emdash, policy = [], []
    in_refs = False
    for b in blocks:
        if b.type == "heading":
            text = clean_inline(b.text)[0]
            in_refs = bool(REF_HEADING_RE.search(text)) and b.level >= 2
            units = [(b.line, text)]
        elif b.type in ("paragraph", "list_item", "blockquote"):
            units = [(b.line, clean_inline(b.text)[0])]
        elif b.type == "table":
            units = [(b.line + k, clean_inline(row)[0]) for k, row in enumerate(b.text.split("\n"))
                     if not TABLE_DELIM_RE.match(row)]
        else:
            continue
        for line, text in units:
            target = mask_math(text)
            if in_refs and b.type != "heading":
                policy += [_unit_hit(line, text, target, m) for m in PAGE_RANGE_RE.finditer(target)]
                continue
            emdash += [_unit_hit(line, text, target, m) for m in EMDASH_CHAR_RE.finditer(target)]
            emdash += [_unit_hit(line, text, target, m) for m in SPACED_HYPHEN_RE.finditer(target)]
            policy += [_unit_hit(line, text, target, m) for m in POLICY_CHAR_RE.finditer(target)]
    return emdash, policy


def particle_mismatch(final, particle):
    """final은 마지막 소리의 받침("" 이면 받침 없음). 조사가 그 받침과 맞지 않으면 True."""
    if particle in ("이에요", "이", "을", "은", "과"):
        return not final
    if particle in ("예요", "가", "를", "는", "와", "였"):
        return bool(final)
    if particle == "으로":
        return not final or final == "ㄹ"
    if particle == "로":
        return bool(final) and final != "ㄹ"
    return False


def num_particle_hits(units):
    """units: (줄 번호, 원문, 따옴표를 가린 문장). 숫자와 %, %p 바로 뒤 조사가 읽는 소리와 맞지 않는 곳을 찾는다."""
    hits = []
    for line, text, masked in units:
        target = mask_math(masked)
        for m in NUM_PARTICLE_RE.finditer(target):
            if LATIN_TOKEN_BEFORE_RE.search(target[:m.start()]):
                continue
            particle = m.group(3) or m.group(4)
            final = "" if m.group(2) else DIGIT_FINAL[m.group(1)[-1]]
            if particle_mismatch(final, particle):
                fix = m.group(1) + (m.group(2) or "") + PARTICLE_ALT[particle]
                hits.append({"line": line, "text": text[:160], "match": f"{m.group(0)} → {fix}"})
    return hits


def term_pairs(text):
    """한 문장에서 병기 쌍을 찾는다. 돌려주는 값: (본문 표기, 괄호 안 표기, 괄호 안이 영어인지, 위치)."""
    out = []
    for m in TERM_KE_RE.finditer(text):
        ko, en = m.group(1), m.group(2).strip()
        words = ko.split(" ")
        if len(words) == 2 and GLOSS_PARTICLE_RE.search(words[0]):
            ko = words[1]  # "이 글의 망막(retina)"에서 앞 낱말은 용어가 아니다
        if ACRONYM_RE.match(en) or IDENTIFIER_RE.search(en) or len(en.split()) > 3 or PHRASE_END_RE.search(ko):
            continue  # 약어 정의("다중 버전 동시성 제어(MVCC)"), 식별자, 구절의 원문("시냅스 밖에서도(extrasynaptic)")
        out.append((ko, en, True, m.span()))
    for m in TERM_EK_RE.finditer(text):
        en, ko = m.group(1).strip(), m.group(2).strip()
        if ACRONYM_RE.match(en) or IDENTIFIER_RE.search(en) or any(GLOSS_PARTICLE_RE.search(w) for w in ko.split(" ")):
            continue  # 약어, 식별자, 풀이("attention(주의를 기울이는)")는 표기 쌍이 아니다
        out.append((en, ko, False, m.span()))
    return out


def _latin_term_re(term):
    # 다른 영어 낱말과 붙은 합성어("KV cache"의 cache)는 따로 세지 않는다.
    return re.compile(r"(?<![A-Za-z0-9_\-])(?<![A-Za-z0-9] )" + re.escape(term) + r"(?! ?[A-Za-z0-9_\-])", re.I)


def _hangul_term_re(term):
    # 조사가 붙거나 문장 부호가 뒤따르는 낱말만 센다. "흥분성 뉴런", "인접 행렬"처럼 다른 명사 앞에 붙은 말은
    # 다른 개념의 합성어일 수 있어서 세지 않는다.
    return re.compile(r"(?<![가-힣])" + re.escape(term) + r"(?:" + KO_PARTICLES + r"|(?![가-힣])(?!\s[가-힣]))")


def term_mix_hits(units, max_hits=5):
    """units: (줄 번호, 원문, 따옴표를 가린 문장). 병기한 쌍의 두 표기가 모두 병기한 곳 밖(괄호 밖)에 다시 나오면
    한 개념을 두 표기로 쓴 후보로 보여 준다. 괄호 안은 원어, 약어 풀이, 단위 변환이라 세지 않는다."""
    pairs = []
    cleaned = []
    for line, text, masked in units:
        found = term_pairs(masked)
        pairs += [(main, alt, alt_latin, line) for main, alt, alt_latin, _ in found]
        cleaned.append((line, text, PAREN_RE.sub(" ", masked)))
    hits, seen = [], set()
    for main, alt, alt_latin, pair_line in pairs:
        key = (main.lower(), alt.lower())
        if key in seen:
            continue
        seen.add(key)
        rx_alt = _latin_term_re(alt) if alt_latin else _hangul_term_re(alt)
        rx_main = _hangul_term_re(main) if alt_latin else _latin_term_re(main)
        alt_where = [(line, text) for line, text, c in cleaned if rx_alt.search(c)]
        main_where = [line for line, _, c in cleaned if rx_main.search(c)]
        if alt_where and main_where:
            hits.append({"line": alt_where[0][0], "text": alt_where[0][1][:160],
                         "match": f"{main}({alt}) L{pair_line}: 괄호 밖에서 «{main}» {len(main_where)}문장, "
                                  f"«{alt}» {len(alt_where)}문장"})
        if len(hits) >= max_hits:
            break
    return hits


def avoid_terms(facts_text):
    """fact sheet 용어 표에서 "쓰지 않을 표기" 열의 낱말을 모은다. 표가 없으면 빈 목록."""
    terms = []
    lines = facts_text.split("\n")
    for i, ln in enumerate(lines):
        if "|" not in ln or "쓰지 않을" not in ln:
            continue
        header = [c.strip() for c in ln.strip().strip("|").split("|")]
        col = next(j for j, c in enumerate(header) if "쓰지 않을" in c)
        for row in lines[i + 1:]:
            if "|" not in row:
                break
            if TABLE_DELIM_RE.match(row):
                continue
            cells = [c.strip() for c in row.strip().strip("|").split("|")]
            if col < len(cells):
                for t in re.split(r"[,，;]", cells[col]):
                    t = t.strip().strip("`\"'“”‘’ ")
                    if t and t not in ("-", "없음", "—") and (len(t) >= 2 or re.fullmatch(r"[A-Za-z]+", t)):
                        terms.append(t)
    return terms


def term_avoid_hits(units, terms, max_hits=10):
    """fact sheet가 쓰지 않기로 한 표기가 괄호 밖에 나온 곳."""
    hits = []
    for term in terms:
        latin = re.fullmatch(r"[A-Za-z0-9 .'\-]+", term) is not None
        # 쓰지 않기로 한 한국어 표기는 합성어 안에 있어도 센다("보고자 유전자").
        rx = _latin_term_re(term) if latin else re.compile(r"(?<![가-힣])" + re.escape(term))
        for line, text, masked in units:
            if rx.search(PAREN_RE.sub(" ", masked)):
                hits.append({"line": line, "text": text[:160], "match": term})
                break
        if len(hits) >= max_hits:
            break
    return hits


TERM_TABLE_HEADER = "글에 쓸 표기"
TERM_SPLIT_RE = re.compile(r"\s+/\s+|\s*[,，;]\s*")


def term_table_rows(facts_text):
    """fact sheet 용어 표의 행. 헤더에 "글에 쓸 표기"가 있는 표만 본다(추정 표현 표의 "글에 쓸 표현"은 뺀다).
    돌려주는 값: (fact sheet 줄 번호, 헤더 칸 목록, 행 칸 목록)의 목록."""
    rows = []
    lines = facts_text.split("\n")
    i = 0
    while i < len(lines):
        if "|" in lines[i] and TERM_TABLE_HEADER in lines[i]:
            header = [c.strip() for c in lines[i].strip().strip("|").split("|")]
            j = i + 1
            while j < len(lines) and "|" in lines[j]:
                if not TABLE_DELIM_RE.match(lines[j]):
                    rows.append((j + 1, header, [c.strip() for c in lines[j].strip().strip("|").split("|")]))
                j += 1
            i = j
        else:
            i += 1
    return rows


def _col(header, key):
    return next((j for j, c in enumerate(header) if key in c), None)


def _cell(cells, j):
    return cells[j] if j is not None and j < len(cells) else ""


def split_terms(cell):
    """"글에 쓸 표기" 칸의 용어들. 괄호("C. elegans(예쁜꼬마선충)")를 걷어 내고, 한 행에 묶어 적은 용어
    ("수평 세포 / 양극 세포 / amacrine 세포", "tonic spiking, burst")는 나눈다. 네 낱말이 넘는 조각은 뺀다."""
    out = []
    for part in TERM_SPLIT_RE.split(PAREN_RE.sub("", cell)):
        part = part.strip().strip("`\"'“”‘’ ")
        if part and part not in DESC_SKIP and len(part.split()) <= 4 and part not in out:
            out.append(part)
    return out


def described_terms(facts_text):
    """fact sheet 용어 표에서 "처음 나올 때 설명" 열에 설명을 적은 용어의 "글에 쓸 표기"를 모은다.
    설명 열이 없거나 "설명하지 않음"으로 적은 용어는 뺀다."""
    terms = []
    for _, header, cells in term_table_rows(facts_text):
        desc = _cell(cells, _col(header, "설명"))
        if not desc or desc in DESC_SKIP or desc.startswith("설명하지 않"):
            continue
        for term in split_terms(_cell(cells, _col(header, "글에 쓸"))):
            if term not in terms:
                terms.append(term)
    return terms


def combined_row_hits(facts_text):
    """용어 표에서 한 행에 용어 여러 개를 묶은 곳(A20.table_combined_row). 묶은 행은 용어마다 다른 특징을 쓸 수
    없고, 묶은 칸 전체를 용어 하나로 찾으면 본문에서 찾지 못한다. hit의 줄 번호 0은 fact sheet를 뜻한다."""
    hits = []
    for n, header, cells in term_table_rows(facts_text):
        cell = _cell(cells, _col(header, "글에 쓸"))
        if len(split_terms(cell)) > 1:
            hits.append({"line": 0, "text": f"fact sheet {n}줄: {cell}"[:160], "match": cell})
    return hits


def strip_general_knowledge(facts_text):
    """용어 표에서 근거가 "일반 지식"인 설명 칸을 비운 fact sheet. 일반 지식 설명에는 수치를 쓰지 않으므로
    그 칸의 수치는 A15가 자료의 수치로 치지 않는다."""
    lines = facts_text.split("\n")
    for n, header, cells in term_table_rows(facts_text):
        j = _col(header, "설명")
        if j is not None and j < len(cells) and "일반 지식" in cells[j]:
            cells = list(cells)
            cells[j] = ""
            lines[n - 1] = "| " + " | ".join(cells) + " |"
    return "\n".join(lines)


def _term_re(term):
    if re.fullmatch(r"[A-Za-z0-9 .'\-]+", term):
        return _latin_term_re(term)
    if re.match(r"[A-Za-z]", term):
        # "starburst amacrine 세포"의 "amacrine 세포"처럼 다른 영어 낱말에 붙은 자리는 세지 않는다.
        return re.compile(r"(?<![A-Za-z0-9_\-])(?<![A-Za-z0-9] )" + re.escape(term), re.I)
    return re.compile(r"(?<![가-힣])" + re.escape(term))


def term_first_hits(units, terms):
    """units: (줄 번호, 원문, 따옴표를 가린 문장). fact sheet가 설명을 적은 용어가 본문에 처음 나온 문장.
    설명이 있는지는 문장을 읽어야 알 수 있어서 괄호가 있어도 보여 준다. 같은 문장에 처음 나온 용어는 한 줄로 묶는다.
    0.8.0은 앞쪽 10개만 보여 줘서(그나마 출력은 5개) 뒤 절의 용어가 점검 목록에 오르지 않았다."""
    first = {}
    for term in terms:
        rx = _term_re(term)
        for idx, (_, _, masked) in enumerate(units):
            if rx.search(masked):
                first.setdefault(idx, []).append(term)
                break
    return [{"line": units[idx][0], "text": units[idx][1][:160], "match": ", ".join(first[idx])}
            for idx in sorted(first)]


# 파일 이름("index.wasm")과 LaTeX 명령("\mathbb")의 조각은 영어 구간으로 세지 않는다.
LATIN_RUN_RE = re.compile(r"(?<![A-Za-z0-9_\-'.\\])[A-Za-z][A-Za-z\-']*(?: [A-Za-z][A-Za-z\-']*)*"
                          r"(?![A-Za-z0-9_\-]|\.[A-Za-z0-9])")
# 수식 기호가 셋 넘게 있는 문장(달러 기호 없이 쓴 수식)에서는 영어 구간을 세지 않는다.
MATH_SYMBOL_RE = re.compile(r"[=∼∣∑∏√≤≥∈⋅∥ϵθπρϕ^{}\\]")
LATIN_STOP = frozenset(("et al", "vs", "etc", "e.g", "i.e", "cf"))
LATIN_PHRASES_LOWER = frozenset(p.lower() for p in LATIN_PHRASES)


def latin_runs(masked, skip_names=()):
    """문장에서 영어 낱말이 이어진 구간(소문자로). 괄호 안, 저자(연도) 인용, 학명, 대문자 약어, 사람과 기관 이름처럼
    모든 낱말이 대문자로 시작하는 구간, 두 글자 이하는 뺀다. skip_names: 기울임꼴 학명과 참고자료 절의 이름."""
    if len(MATH_SYMBOL_RE.findall(masked)) > 3:
        return []
    text = PAREN_RE.sub(" ", masked)
    text = WORK_CITE_RE.sub(" ", text)
    text = SPECIES_ABBR_RE.sub(" ", text)
    out = []
    for m in LATIN_RUN_RE.finditer(text):
        whole = m.group(0).strip(" -'")
        if whole in skip_names:
            continue
        # 대문자 약어 낱말("interneuron PVC"의 PVC)에서 구간을 나눈다. 약어는 A20.abbr_first가 본다.
        groups, cur = [], []
        for w in whole.split():
            if re.fullmatch(r"[A-Z][A-Z0-9]+", w):
                groups.append(cur)
                cur = []
            else:
                cur.append(w)
        groups.append(cur)
        for words in groups:
            run = " ".join(words).strip(" -'")
            if (len(run) <= 2 or run.lower() in LATIN_STOP or run.lower() in LATIN_PHRASES_LOWER
                    or run in skip_names):
                continue
            if all(re.fullmatch(r"[A-Z][a-z]+", w) for w in words):
                continue
            if any(w in skip_names for w in words if w[:1].isupper()):
                continue
            out.append(run.lower())
    return out


def table_latin_vocab(facts_text):
    """용어 표의 원어, 글에 쓸 표기, 쓰지 않을 표기 칸(괄호 안 포함)에 있는 영어 구간(소문자). A20.untabled가 본문의
    영어 낱말이 용어 표에 있는지 볼 때 쓴다."""
    vocab = set()
    for _, header, cells in term_table_rows(facts_text):
        for key in ("원어", "글에 쓸", "쓰지 않을"):
            cell = _cell(cells, _col(header, key))
            for part in TERM_SPLIT_RE.split(cell.replace("(", " / ").replace(")", " ")):
                for m in LATIN_RUN_RE.finditer(part):
                    run = m.group(0).strip(" -'").lower()
                    if run:
                        vocab.add(run)
                        vocab.add(run[:-1] if run.endswith("s") else run + "s")
    return vocab


def untabled_hits(units, facts_text, skip_names=(), min_count=2):
    """본문에 min_count번 이상 나오는 영어 낱말 가운데 fact sheet 용어 표에 없는 것(A20.untabled).
    용어 표에 없는 말은 설명할지 정한 적이 없는 말이다."""
    vocab = table_latin_vocab(facts_text)
    count, first = {}, {}
    for line, text, masked in units:
        for run in latin_runs(masked, skip_names):
            count[run] = count.get(run, 0) + 1
            first.setdefault(run, (line, text))
    hits = [{"line": first[r][0], "text": first[r][1][:160], "match": r}
            for r in count if count[r] >= min_count and r not in vocab]
    hits.sort(key=lambda h: h["line"])
    return hits


LIST_PRED_END_RE = re.compile(r"(?:다|요|고|며|서|면|지만|는데|니다|든지|거나)$")
LIST_ADNOMINAL_RE = re.compile(r"(?:하는|되는|있는|없는|하던|되던|한|된|적인)$")


def list_item_spans(masked):
    """쉼표로 셋 넘게 나열한 항목의 위치(시작, 끝). 가운데 조각이 네 낱말 이하이고 서술어로 끝나지 않을 때 나열로
    본다. 첫 조각은 끝의 네 낱말, 마지막 조각은 앞의 네 낱말만 항목으로 본다. "A, B와 C"처럼 쉼표가 하나인
    나열은 보지 않는다."""
    parts, pos = [], 0
    for seg in masked.split(","):
        parts.append((pos, pos + len(seg), [m.span() for m in re.finditer(r"\S+", seg)]))
        pos += len(seg) + 1

    def inner(k):
        start, end, toks = parts[k]
        return len(toks) <= 4 and not LIST_PRED_END_RE.search(masked[start:end].strip())
    spans, i = [], 0
    while i < len(parts):
        j = i + 1
        while j < len(parts) - 1 and inner(j):
            j += 1
        if j - i >= 2:
            start, end, toks = parts[i]
            spans.append((start + (toks[-4][0] if len(toks) >= 4 else 0), end))
            spans += [parts[k][:2] for k in range(i + 1, j)]
            start, end, toks = parts[j]
            spans.append((start, start + toks[4][0] if len(toks) > 4 else end))
            i = j
        else:
            i += 1
    return spans


def term_in_list_hits(units, terms):
    """여럿을 나열한 문장에서 처음 나왔고, 바로 다음 문장에 다시 나오지 않으며(그 자리에서 설명하지 않음), 뒤에서
    나열 밖에 혼자 다시 나오는 용어(A20.term_in_list). 0.8.0 실행 글은 망막 세포 다섯 부류를 나열한 문장 하나로
    amacrine 세포를 소개하고, 그 뒤 세 문장에서 amacrine 세포를 혼자 주어로 썼다."""
    hits = []
    blank = [PAREN_RE.sub(lambda p: " " * len(p.group(0)), masked) for _, _, masked in units]
    spans = [list_item_spans(b) for b in blank]
    for term in terms:
        rx = _term_re(term)
        occ = []
        for idx, b in enumerate(blank):
            m = rx.search(b)
            if m:
                occ.append((idx, m.start()))
        if len(occ) < 2:
            continue
        idx0, pos0 = occ[0]
        if not any(a <= pos0 < e for a, e in spans[idx0]):
            continue
        if occ[1][0] == idx0 + 1:
            continue
        # 나열 안에서도 꾸미는 말이 붙은 항목("접촉을 감지하는 머리와 꼬리의 기계감각 뉴런")은 그 자리에서 설명한 것으로 본다.
        before = blank[idx0][:pos0].rsplit(",", 1)[-1].split()[-4:]
        if any(LIST_ADNOMINAL_RE.search(w) for w in before):
            continue
        alone = [units[i][0] for i, p in occ[1:] if not any(a <= p < e for a, e in spans[i])]
        if alone:
            more = ", ".join(f"L{n}" for n in alone[:4]) + (f" 외 {len(alone) - 4}곳" if len(alone) > 4 else "")
            hits.append({"line": units[idx0][0], "text": units[idx0][1][:160],
                         "match": f"{term}: 목록 L{units[idx0][0]}, 혼자 {more}"})
    hits.sort(key=lambda h: h["line"])
    return hits


def species_first_hits(units, italic_names, max_hits=5):
    """학명이 본문에 처음 나온 문장. "C. elegans(예쁜꼬마선충)"처럼 괄호가 있어도 무엇인지 쓴 설명인지는
    읽어야 알 수 있어서 괄호와 상관없이 보여 준다. italic_names는 기울임꼴로 쓴 학명("Cancer borealis")."""
    hits, seen = [], set()
    italic_rx = [(n, re.compile(r"(?<![A-Za-z])" + re.escape(n) + r"(?![A-Za-z])")) for n in italic_names]
    for line, text, masked in units:
        found = [(m.start(), re.sub(r"\s+", " ", m.group(0))) for m in SPECIES_ABBR_RE.finditer(masked)]
        found += [(m.start(), n) for n, rx in italic_rx for m in rx.finditer(masked)]
        for _, name in sorted(found):
            key = name.replace(" ", "")
            if key in seen:
                continue
            seen.add(key)
            hits.append({"line": line, "text": text[:160], "match": name})
    return hits[:max_hits]


def cited_works(sentences):
    """본문에 저자(연도)나 "저자 et al."로 나온 연구의 수. 같은 저자의 다른 해 연구는 따로 센다."""
    with_year, without_year = set(), set()
    for s in sentences:
        for m in WORK_CITE_RE.finditer(s.text):
            if m.group(1):
                with_year.add((m.group(1).lower(), m.group(2)))
            elif m.group(3):
                without_year.add(m.group(3).lower())
            else:
                with_year.add((m.group(4), m.group(5)))
    return len(with_year) + len(without_year - {name for name, _ in with_year})


def bare_author_hits(blocks, sentences, max_hits=10):
    """본문이 연구를 둘 이상 인용하는데 "저자들은", "세 저자는", "같은 논문은"처럼 어느 연구인지 밝히지 않은 주어가 있고,
    그 문장과 바로 앞 문장에 연구 이름이 없는 곳. 바로 앞 문장이 같은 방식으로 풀린 문장이면 이어진 것으로 본다.
    헤딩, 표, 코드 블록을 지나면 바로 앞 문장으로 치지 않는다."""
    body = [s for s in sentences if not s.in_refs]
    if cited_works(body) < 2:
        return []
    hits, prev, prev_ok = [], None, False
    for s in body:
        if prev is not None and any(blocks[k].type not in ("paragraph", "list_item")
                                    for k in range(prev.block + 1, s.block)):
            prev, prev_ok = None, False
        named = bool(WORK_CITE_RE.search(s.text) or NAMED_SOURCE_RE.search(s.masked))
        m = BARE_AUTHOR_RE.search(s.masked.lstrip())
        if m and not named:
            if not prev_ok:
                hits.append(_hit(s, m.group(1) or m.group(2)))
        else:
            prev_ok = named
        prev = s
    return hits[:max_hits]


SSEUDA_RE = re.compile(r"(?<![가-힣])(?:씁니다|써요|썼|쓴다|쓰고|쓰는|쓴\s|쓸\s|쓰면|쓰지|써서|써야|써도|쓰게|쓰려|쓰며)")
SSEUDA_USE_RE = re.compile(r"(?:을|를)\s+(?:\S+\s+){0,2}(?:씁니다|써요|썼|쓴다|쓰고|쓰는|쓴\s|쓸\s|쓰면|쓰지|써서|써야|써도|쓰게|쓰려|쓰며)"
                           r"|(?<![가-힣])쓸\s+수\s|(?<![가-힣])쓰는\s+(?:방법|방식|곳|값|도구)")


def sseuda_senses_hits(sentences, quote_rxs):
    """한 글에서 "쓰다"를 '사용하다'와 '자료의 말을 옮기다'의 두 뜻으로 함께 쓴 곳. 자료의 말은 인용 동사 패턴
    (quote_rxs)에 걸리거나 저자(연도)가 있는 문장의 "쓰다"이고, '사용하다'는 목적어("~를 썼어요")나 "쓸 수"가 붙은
    "쓰다"다. 두 뜻이 모두 있으면 뜻마다 줄 번호를 한 줄로 보여 준다."""
    use, said = [], []
    for s in sentences:
        if s.in_refs or not SSEUDA_RE.search(s.masked):
            continue
        if any(rx.search(s.masked) for rx in quote_rxs) or WORK_CITE_RE.search(s.text):
            said.append(s)
        elif SSEUDA_USE_RE.search(s.masked):
            use.append(s)
    if not use or not said:
        return []

    def lines(group):
        out = ", ".join(f"L{s.line}" for s in group[:6])
        return out + (f" 외 {len(group) - 6}곳" if len(group) > 6 else "")
    return [{"line": said[0].line, "text": said[0].text[:160],
             "match": f"'사용하다' {len(use)}곳({lines(use)}), '자료의 말' {len(said)}곳({lines(said)})"}]


# 정보 전달 글의 동사(A5.native_verbs, 0.9.0). 2022년 이전 합니다체 사람 글 57편은 같은 뜻에 한자어 동사를 더 많이 썼다
# (사용하다 1,000자당 2.97번 대 쓰다 0.22번, 측정하다 0.04번 대 재다 0번, dev/baseline/README.md의 0.9.0 절).
# 고유어를 한자어의 1/10 이하로 쓴 짝만 센다. 넣다(추가하다의 1/5), 바꾸다(변경하다의 1/2.6), 나오다(나타나다·발생하다의 1/4)는
# 사람 글도 자주 써서 세지 않고, 한국어 점검(유형 R)이 문장의 뜻을 보고 고른다.
# 뜻을 가릴 수 있는 틀만 센다. 글, 코드, 기록, 시간을 "쓰다"와 데이터를 메모리, 디스크, 블록에 "쓰다"는 세지 않는다.
NV_WRITE_OBJ = ("글", "문서", "코드", "테스트", "메시지", "리뷰", "주석", "논문", "책", "편지", "답장", "일기", "보고서",
                "기사", "블로그", "아티클", "포스트", "이름", "답", "소설", "노트", "README", "문장", "후기", "회고",
                "칼럼", "원고", "글자", "숫자", "공식", "수식", "식", "로그", "파일", "레코드", "데이터", "기록", "시간",
                "신경", "힘", "애", "돈", "비용", "예산", "마음", "모자", "안경", "마스크", "누명", "억지", "떼", "손",
                "머리", "가면", "우산", "답안", "보고", "설명", "결론", "말", "매뉴얼", "가이드", "명세", "스펙", "PRD", "RFC",
                "ADR", "기획서", "제안서", "프롬프트", "편", "log", "페이지", "위키", "티켓", "이슈", "일지", "근거", "케이스",
                "나절", "하루", "며칠", "주일", "개월")
# 목적어 없이 앞에 붙는 굳은 말("CPU Bound를 신경 쓰며", "인프라를 신경 쓰지 않고")
NV_IDIOM = ("신경", "손", "애", "힘", "머리", "마음", "떼", "억지")
# 수동 "쓰이다"의 주어가 이 낱말이면 '사용' 뜻이 아니다("시간의 상당수가 검토에 쓰입니다", "장애일지는 성실하게 쓰였고")
NV_PASSIVE_SUBJ = ("시간", "비용", "돈", "예산", "노력", "글", "문서", "일지", "일기", "기사", "논문", "책", "편지", "보고서",
                   "원고", "소설", "매뉴얼", "가이드", "답장", "후기", "회고", "칼럼")
NV_SSEUDA = re.compile(r"(?:씁니다|써요|썼(?:습니다|어요|다|고|으며|는데|지만|던|을)?|쓴다|쓰고|쓰는|쓴|쓸|쓰면|쓰지|써서|"
                       r"써야|써도|쓰게|쓰려|쓰며)")
# 목적어 앞의 저장 위치("logical block에 새 KV cache를 쓰려 하면")는 '기록하다' 뜻이다.
NV_STORE_AT = re.compile(r"(?:블록|block|메모리|memory|디스크|disk|버퍼|buffer|파일|캐시|cache|테이블|table|레지스터|register|"
                         r"스토리지|storage|DB|슬롯|slot|페이지|page|셀|칸|필드|컬럼|로그)(?:\s+\d+)?에(?:\s|$)")
NV_EXPR_TO = re.compile(r"(?:식|함수|형태|꼴|기호|표기|약어|이름|말|표현|문장|단어|한국어|영어|숫자|글|코드)(?:으로|로)$")
NV_PATTERNS = (
    ("재다", re.compile(r"(?<![가-힣])(?:잽니다|재요|쟀(?:습니다|어요|다|고|던|으며|는데|지만)?|잰다|재는|잰|잴|재면|재서|재야|재지|재려|"
                       r"재며)(?![가-힣])")),
    ("두다", re.compile(r"(?:(?<![\w.])\d[\d,.]*\s*(?:%|[A-Za-z]{1,3}|초|분|시간|개|배|번|바이트|자|줄|건|회)?|값|상수|"
                       r"(?<![A-Za-z])(?:true|false|True|False|null|None))(?:으로|로)\s+(?:둡니다|둬요|두어요|뒀(?:습니다|어요|다|고)?|두었(?:습니다|어요|다|고)?|둔다|두고|두는|둔|두면|"
                       r"둬서|두어서|둬야|두어야|두려|두며)(?![가-힣])|가정을\s+(?:둡니다|둬요|뒀|두었|둔다|두고|두는|둔|두면)(?![가-힣])")),
    ("고치다", re.compile(r"(?<![가-힣])(?:고칩니다|고쳐요|고쳤(?:습니다|어요|다|고|으며|는데|지만|던)?|고친다|고치고|고치는|고친|"
                         r"고칠|고치면|고치지|고쳐서|고쳐야|고치려|고치며)(?![가-힣])")),
    ("돌리다", re.compile(r"(?:테스트|코드|모델|실험|시뮬레이션|배치|작업|잡|스크립트|프로그램|쿼리|학습|벤치마크|파이프라인|크론|"
                         r"서버|노트북|셀|루프|빌드|job|cron|CI)(?:을|를)?\s+(?:\S+\s+){0,2}?돌(?:립니다|려요|렸(?:습니다|어요|다|고)?|"
                         r"린다|리고|리는|린|릴|리면|리지|려서|려야|려도|리려|리며)(?![가-힣])")),
    ("고르다", re.compile(r"(?<![가-힣])(?:고릅니다|골라요|골랐(?:습니다|어요|다|고|으며|는데|지만|던)?|고른다|고르고|고르는|"
                         r"고른(?!\s+(?:성능|분포|품질|수준|결과|성적|발전|성장|비율|값))|"
                         r"고를|고르면|골라서|골라야|고르려|고르며)(?![가-힣])")),
)
NV_SSEUDA_EXTRA = (
    # "쓸 수 있다/없다"(쓰기 비율 같은 명사와 "~로 쓸 수"는 뺀다)
    re.compile(r"(?<![가-힣])(?<!식으로\s)(?<!함수로\s)(?<!형태로\s)(?<!기호로\s)(?<!말로\s)(?<!표현으로\s)(?<!문장으로\s)"
               r"(?<!한국어로\s)(?<!영어로\s)(?<!글로\s)(?<!숫자로\s)(?<!읽고\s)쓸\s+수\s+(?:있|없)"),
    re.compile(r"(?<![가-힣])(?<!을\s)(?<!를\s)(?<!글\s)(?<!코드\s)(?<!문서\s)쓰는\s+(?:방법|방식|도구|경우|이유|곳|쪽)(?![가-힣])"),
    # 수동 "쓰이다": "널리 쓰입니다", "~에 쓰이는". "Go로 쓰였습니다"(쓴 언어), "~라고 쓰여 있다"(적힌 글)는 뺀다.
    re.compile(r"(?<![가-힣])(?<![A-Za-z]로\s)(?<![A-Za-z]으로\s)(?<!고\s)(?:쓰입니다|쓰여요|쓰였(?:습니다|어요|다|고|으며|는데|지만|던)?|"
               r"쓰인다|쓰이는|쓰이고|쓰이며|쓰이면|쓰이지|쓰일)(?![가-힣])"),
)


def native_verb_hits(sentences):
    """정보 전달 글에서 사람 글이 한자어 동사를 더 많이 쓰는 자리의 고유어 동사(A5.native_verbs). 문장마다 한 번 센다.
    '사용' 뜻의 쓰다는 목적어 틀("이 방법을 씁니다"), "쓸 수 있다", "쓰는 방법", 수동 "쓰이다"로 가린다."""
    hits = []
    for s in sentences:
        if s.in_refs:
            continue
        toks = s.masked.split()
        found = []
        for i, tok in enumerate(toks):
            m = NV_SSEUDA.match(tok)
            if not m or m.end() != len(tok.rstrip(".,?!")):
                continue
            counted = False
            if i + 1 < len(toks) and toks[i + 1].startswith("읽"):
                continue                                   # "쓰고 읽힐 수 있어야"(쓰기와 읽기)
            for j in range(i - 1, max(-1, i - 4), -1):
                if (re.search(r"(?:에|에서|에게|고|라고|다고)$", toks[j]) or NV_EXPR_TO.search(toks[j])
                        or toks[j] in NV_IDIOM):
                    break
                if re.search(r"[을를]$", toks[j]):
                    obj = toks[j][:-1]
                    if (not any(obj.endswith(w) for w in NV_WRITE_OBJ)
                            and not NV_STORE_AT.search(" ".join(toks[max(0, j - 3):j]))):
                        found.append(tok)
                        counted = True
                    break
            # 주어 뒤 관형형("Orca가 쓰는 스케줄링"). 꾸밈을 받는 말이 글, 코드처럼 쓰는 대상이면 세지 않는다("사람이 쓴 글").
            if (not counted and tok in ("쓰는", "쓴", "쓸", "쓰던") and i > 0 and re.search(r"[이가]$", toks[i - 1])
                    and i + 1 < len(toks) and not any(toks[i + 1].startswith(w) for w in NV_WRITE_OBJ)):
                found.append(tok)
        for k, rx in enumerate(NV_SSEUDA_EXTRA):
            m = rx.search(s.masked)
            if m:
                before = s.masked[:m.start()].split()
                # 바로 앞 낱말이 쓰는 대상이면 '사용' 뜻이 아니다("손을 쓸 수 없을", "신경 쓸 수 없는")
                prev = (before or [""])[-1]
                bare = prev[:-1] if prev.endswith(("을", "를")) else prev
                if bare and (bare in NV_WRITE_OBJ or (bare != prev and any(bare.endswith(w) for w in NV_WRITE_OBJ))):
                    continue
                if k == len(NV_SSEUDA_EXTRA) - 1 and any(
                        re.search(r"(?:은|는|이|가|의)$", t) and re.sub(r"(?:은|는|이|가|의)$", "", t).endswith(NV_PASSIVE_SUBJ)
                        for t in before[-6:]):
                    continue
                found.append(m.group(0))
        for name, rx in NV_PATTERNS:
            m = rx.search(s.masked)
            if m:
                found.append(m.group(0).split()[-1])
        if found:
            hits.append(_hit(s, ", ".join(dict.fromkeys(found))))
    return hits


# 판단을 옮기는 "~라고 봅니다"(A7.see_judgment, 0.9.0). 사람 글은 1,000자당 0.01~0.03번, 0.8.0 실행 글은 0.45번 썼다.
SEE_JUDGMENT_RES = (
    re.compile(r"(?:다고|라고)\s*(?:봅니다|봐요|봤(?:습니다|어요|다|고|으며|는데|지만|던)?|본다|보았(?:습니다|어요|다|고)?|"
               r"보고(?![가-힣])(?!\s+(?:했|하|합|한|할|된|됐|되|드))|보는\s|봐야|보며|보지)"),
    re.compile(r"것으로\s+(?:봅니다|봐요|봤(?:습니다|어요|다|고|으며|는데|지만|던)?|본다|보았(?:습니다|어요|다|고)?|"
               r"보고(?![가-힣])(?!\s+(?:했|하|합|한|할|된|됐|되|드)))"),
    re.compile(r"(?:을|를)\s+(?:\S+\s+){0,3}?[^\s]*[가-힣](?:으로|로)(?<!그래프로)(?<!차트로)(?<!화면으로)(?<!그림으로)(?<!사진으로)"
               r"(?<!영상으로)(?<!로그로)(?<!눈으로)(?<!예로)(?<!표로)(?<!현미경으로)(?<!대시보드로)(?<!코드로)(?<!숫자로)(?<!수치로)"
               r"(?<!기준으로)\s+(?:봅니다|봐요|봤(?:습니다|어요|다|고)?|본다|보았(?:습니다|어요|다|고)?|"
               r"보고(?![가-힣])(?!\s+(?:했|하|합|한|할|된|됐|되|드))|보는\s|봐야)"),
)
# "X를 Y로 봅니다"의 Y 자리에 오는 부사("영역을 주로 봅니다", "변경을 바로 봐야")
SEE_ADVERB_RO = ("주로", "새로", "따로", "서로", "별로", "제대로", "그대로", "실제로", "대체로", "바로", "스스로", "이대로",
                 "저절로", "절대로", "정말로", "때로", "함부로", "억지로", "멋대로", "마음대로", "임의로")


def see_judgment_hits(sentences):
    hits = []
    for s in sentences:
        if s.in_refs:
            continue
        m = next((m for rx in SEE_JUDGMENT_RES for m in rx.finditer(s.masked) if not _see_adverb(m.group(0))), None)
        if m:
            hits.append(_hit(s, m.group(0)))
    return hits


def _see_adverb(match):
    # Y 자리가 부사이거나 "-적으로"("전체적으로 봤을 때")이면 판단을 옮기는 말이 아니다
    ro = [t for t in match.split() if t.endswith("로")]
    return bool(ro) and (ro[-1] in SEE_ADVERB_RO or ro[-1].endswith("적으로"))


def abbr_first_hits(units, exclude=(), min_count=3, max_hits=None):
    """본문에 min_count번 이상 나오는 대문자 약어가 처음 나온 자리에 괄호가 없는 문장.
    "STG(stomatogastric ganglion)"처럼 바로 뒤에 괄호가 있거나 "stomatogastric ganglion(STG)"처럼
    괄호 안에서 처음 나오면 세지 않는다. 흔한 약어(COMMON_ABBR)와 exclude(용어 표의 용어)도 세지 않는다.
    0.9.0부터 개수를 자르지 않는다. 출력은 thresholds.json의 compact 설정대로 줄인다."""
    counts, first = {}, {}
    for line, text, masked in units:
        for m in ABBR_RE.finditer(masked):
            a = m.group(0)
            counts[a] = counts.get(a, 0) + 1
            if a not in first:
                before = masked[:m.start()]
                in_paren = before.count("(") > before.count(")")
                after_paren = masked[m.end():m.end() + 2].lstrip().startswith("(")
                first[a] = (line, text, in_paren or after_paren)
    skip = COMMON_ABBR | {e.upper() for e in exclude}
    hits = [{"line": first[a][0], "text": first[a][1][:160], "match": a}
            for a in first if counts[a] >= min_count and a not in skip and not first[a][2]]
    hits.sort(key=lambda h: h["line"])
    return hits if max_hits is None else hits[:max_hits]


def analyze(text, patterns_spec=None, facts_text=None):
    """글을 분석해 metric 원값과 근거 문장을 돌려준다. 기준치 판정은 evaluate()가 한다."""
    if patterns_spec is None:
        patterns_spec = load_json(PATTERNS_PATH)
    patterns = _compile_patterns(patterns_spec)
    text = normalize_text(text)
    blocks = parse_blocks(text)

    sentences = []
    headings = []
    list_items = []
    para_sents = []  # 문단별 문장 목록
    bold = 0
    prose_chars = 0
    list_chars = 0
    in_refs = False
    emoji_hits = []
    semicolon_hits = []
    # 헤딩과 표 행: (줄 번호, 원문, 따옴표를 가린 텍스트). 패턴의 headings, tables 옵션과 한국어 점검 항목이 쓴다.
    heading_units = []
    table_units = []

    for bi, b in enumerate(blocks):
        if b.type == "heading":
            clean, bcount, _ = clean_inline(b.text)
            headings.append({"level": b.level, "text": clean, "line": b.line})
            in_refs = bool(REF_HEADING_RE.search(clean)) and b.level >= 2
            heading_units.append((b.line, clean, mask_quotes(clean)))
            if EMOJI_RE.search(clean):
                emoji_hits.append({"line": b.line, "text": clean[:160]})
            continue
        if b.type == "table" and not in_refs:
            for k, row in enumerate(b.text.split("\n")):
                if TABLE_DELIM_RE.match(row):
                    continue
                cells = [clean_inline(c)[0] for c in row.strip().strip("|").split("|")]
                row_text = " | ".join(c for c in cells if c)
                table_units.append((b.line + k, row_text, mask_quotes(row_text)))
            continue
        if b.type not in ("paragraph", "list_item"):
            continue
        clean, bcount, _ = clean_inline(b.text)
        if not clean:
            continue
        bold += bcount
        chars = visible_chars(clean)
        if b.type == "list_item":
            list_items.append({"line": b.line, "text": clean, "raw": b.text, "list_id": b.list_id,
                               "depth": b.depth})
            list_chars += chars
        prose_chars += chars
        if EMOJI_RE.search(clean):
            emoji_hits.append({"line": b.line, "text": clean[:160]})
        if not in_refs and ";" in PH_RE.sub("", clean):
            semicolon_hits.append({"line": b.line, "text": clean[:160]})
        parts = split_sentences(clean)
        block_sents = []
        for si, st in enumerate(parts):
            s = Sentence()
            s.text = st
            s.masked = mask_quotes(st)
            s.kind = b.type
            s.block = bi
            s.para = len(para_sents) if b.type == "paragraph" else None
            s.line = b.line
            s.first = si == 0
            s.last = si == len(parts) - 1
            s.question = st.rstrip(CLOSERS + " ").endswith("?") and not s.masked.rstrip(" .").endswith(PH_QUOTE)
            s.word = last_word(st)
            s.cls = classify_ending(s.word, s.question)
            s.bucket = ending_bucket(st, s.word, s.cls)
            s.in_refs = in_refs
            block_sents.append(s)
            sentences.append(s)
        if b.type == "paragraph":
            para_sents.append(block_sents)

    body = [s for s in sentences if s.kind == "paragraph" or s.cls not in ("NOUN", "OTHER")]
    metrics = {}

    def put(mid, value, hits=None, **extra):
        metrics[mid] = {"value": value, "hits": hits or []}
        if extra:
            metrics[mid]["extra"] = extra

    # 패턴 기반 metric. scope "all"은 명사구 목록 항목까지 포함한 모든 문장이다.
    # raw 패턴은 따옴표를 가리기 전 문장에 적용한다. headings, tables 옵션이 있으면 헤딩과 표 행에도 적용한다.
    for pid, p in patterns.items():
        hits = []
        if p["scope"] == "para_last":
            pool = [ps[-1] for ps in para_sents if ps]
        elif p["scope"] == "paragraph":
            pool = [s for s in body if s.kind == "paragraph"]
        elif p["scope"] == "all":
            pool = [s for s in sentences if not s.in_refs]
        else:
            pool = body
        for s in pool:
            if p["max_len"] and len(s.text) > p["max_len"]:
                continue
            target = (s.text if p["raw"] else s.masked).lstrip()
            for rx in p["regex"]:
                m = rx.search(target)
                if m:
                    hits.append(_hit(s, m.group(0)))
                    break
        units = (heading_units if p["headings"] else []) + (table_units if p["tables"] else [])
        for line, raw_text, masked in units:
            target = raw_text if p["raw"] else masked
            for rx in p["regex"]:
                m = rx.search(target)
                if m:
                    hits.append({"line": line, "text": raw_text[:160], "match": m.group(0)})
                    break
        metrics[pid] = {"value": len(hits), "hits": hits}

    # A14: 따옴표 친 영어 낱말에 이미 걸린 문장("\"likely\"라고 적었어요")은 인용 동사 항목에서 다시 세지 않는다.
    quoted = {(h["line"], h["text"]) for h in metrics["A14.quoted_english_token"]["hits"]}
    for pid in ("A14.report_write", "A14.report_write_check"):
        kept = [h for h in metrics[pid]["hits"] if (h["line"], h["text"]) not in quoted]
        metrics[pid] = {"value": len(kept), "hits": kept}

    # A5: 자료가 쓰는 용어는 감점하지 않는다
    if facts_text:
        for pid in ("A5.style_words",):
            kept = []
            for h in metrics[pid]["hits"]:
                stem = re.sub(r"(인|으로|하는\s*바|하|합|해|한|할|했|점|니다|요)$", "", h.get("match", ""))
                if stem and stem in facts_text:
                    continue
                kept.append(h)
            metrics[pid] = {"value": len(kept), "hits": kept}

    # 헤딩과 제목
    title = next((h for h in headings if h["level"] == 1), headings[0] if headings else None)
    title_text = title["text"] if title else ""
    np_rx = [rx for pid in ("A1.np_anira", "A1.np_rather", "A1.np_geuchi", "A1.np_neomeo",
                            "A1.np_deoisang", "A1.np_simple") for rx in patterns[pid]["regex"]]
    g8_rx = patterns["G8.beyond_simple"]["regex"]
    np_title = [{"line": title["line"], "text": title_text}] if title and any(rx.search(mask_quotes(title_text)) for rx in np_rx) else []
    for h in headings:
        if any(rx.search(mask_quotes(h["text"])) for rx in g8_rx):
            metrics["G8.beyond_simple"]["hits"].append({"line": h["line"], "text": h["text"]})
    metrics["G8.beyond_simple"]["value"] = len(metrics["G8.beyond_simple"]["hits"])
    put("A1.np_title", len(np_title), np_title)

    # A1: 부정 대구(문장당 1회) + 문장을 나눈 "X가 아닙니다. Y입니다."
    np_sents = set()
    for pid in ("A1.np_anira", "A1.np_rather", "A1.np_geuchi", "A1.np_neomeo", "A1.np_deoisang", "A1.np_simple"):
        for h in metrics[pid]["hits"]:
            np_sents.add((h["line"], h["text"]))
    cross = []
    for ps in para_sents:
        for a, b2 in zip(ps, ps[1:]):
            if re.search(r"(아닙니다|아니에요|아니다|않습니다|않아요)[.]?$", a.masked) and len(b2.text.split()) <= 12:
                cross.append(_hit(a, "X가 아닙니다. Y입니다."))
                np_sents.add((a.line, a.text))
    np_hits = [{"line": l, "text": t} for (l, t) in sorted(np_sents)]
    put("A1.np", len(np_hits), np_hits, cross=len(cross))
    first_para = para_sents[0] if para_sents else []
    np_first = [_hit(s) for s in first_para if (s.line, s.text) in np_sents]
    put("A1.np_first_para", len(np_first), np_first)
    same_para = []
    for ps in para_sents:
        c = [s for s in ps if (s.line, s.text) in np_sents]
        if len(c) >= 2:
            same_para.append(_hit(c[0]))
    put("A1.np_same_para", len(same_para), same_para)

    # G6, G7
    put("G6.emoji", len(emoji_hits), emoji_hits)
    put("G6.semicolon", len(semicolon_hits), semicolon_hits)
    emdash_hits, policy_hits = punct_hits(blocks)
    put("G6.emdash", len(emdash_hits), emdash_hits)
    put("G6.punct_policy", len(policy_hits), policy_hits)

    # G10 숫자 뒤 조사, A19 병기한 용어. 제목과 헤딩, 참고자료 절 밖의 문장을 본다.
    ko_units = heading_units + [(s.line, s.text, s.masked) for s in sentences if not s.in_refs]
    num_hits = num_particle_hits(ko_units)
    put("G10.num_particle", len(num_hits), num_hits)
    mix_hits = term_mix_hits(ko_units)
    put("A19.term_mix", len(mix_hits), mix_hits)
    if facts_text is not None:
        avoid_hits = term_avoid_hits(ko_units, avoid_terms(facts_text))
        put("A19.term_avoid", len(avoid_hits), avoid_hits)

    # A20 처음 나오는 용어의 설명. 제목과 헤딩은 빼고 본문 문장(목록 항목 포함)에서 첫 등장을 찾는다.
    body_units = [(s.line, s.text, s.masked) for s in sentences if not s.in_refs]
    italic_names = []
    for b in blocks:
        if b.type in ("paragraph", "list_item"):
            for m in SPECIES_ITALIC_RE.finditer(b.text):
                if m.group(1) not in italic_names and m.group(1) not in LATIN_PHRASES:
                    italic_names.append(m.group(1))
    species = species_first_hits(body_units, italic_names)
    put("A20.species_first", len(species), species)
    described = described_terms(facts_text) if facts_text is not None else []
    # 참고자료 절의 대문자로 시작하는 낱말(저자, 학술지 이름)과 기울임꼴 학명은 용어가 아니라 이름이다.
    # "TANGO-mapping"처럼 논문 제목에 든 용어는 이름이 아니므로 첫 글자만 대문자인 낱말만 모은다.
    skip_names = set(italic_names)
    for s in sentences:
        if s.in_refs:
            skip_names.update(re.findall(r"(?<![A-Za-z\-])[A-Z][a-z]+(?![A-Za-z\-])", s.text))
    if facts_text is not None:
        firsts = term_first_hits(body_units, described)
        put("A20.term_first", sum(len(h["match"].split(", ")) for h in firsts), firsts, sentences=len(firsts))
        combined = combined_row_hits(facts_text)
        put("A20.table_combined_row", len(combined), combined)
        untabled = untabled_hits(body_units, facts_text, skip_names)
        put("A20.untabled", len(untabled), untabled)
    latin = {}
    for _, _, masked in body_units:
        for run in latin_runs(masked, skip_names):
            latin[run] = latin.get(run, 0) + 1
    # 용어 표의 용어("amacrine 세포")에 든 영어 구간("amacrine")은 따로 세지 않는다.
    in_described = {m.group(0).lower() for d in described for m in LATIN_RUN_RE.finditer(d)}
    listed = term_in_list_hits(body_units, described + [r for r, c in latin.items() if c >= 2
                                                      and r not in in_described])
    put("A20.term_in_list", len(listed), listed)
    abbrs = abbr_first_hits(body_units, exclude=described)
    put("A20.abbr_first", len(abbrs), abbrs)

    # A18 출처를 밝히지 않은 주어
    authors = bare_author_hits(blocks, sentences)
    put("A18.bare_author", len(authors), authors)

    # A21 한 글에서 두 뜻으로 쓴 "쓰다"
    quote_rxs = patterns["A14.report_write"]["regex"] + patterns["A14.report_write_check"]["regex"]
    senses = sseuda_senses_hits(sentences, quote_rxs)
    put("A21.sseuda_senses", len(senses), senses)

    # A5.native_verbs, A7.see_judgment 정보 전달 글의 동사(0.9.0)
    nv = native_verb_hits(sentences)
    put("A5.native_verbs", len(nv), nv)
    sj = see_judgment_hits(sentences)
    put("A7.see_judgment", len(sj), sj)
    g7 = []
    adverb_comma = []
    for s in body:
        t = s.masked.lstrip()
        m = re.match(r"^(\S+?)\s*[,，]", t)
        if m and m.group(1) in G7_ADVERBS:
            g7.append(_hit(s, m.group(0)))
        elif m and m.group(1) in SENT_ADVERBS:
            adverb_comma.append(_hit(s, m.group(0)))
    put("G7.conj_comma", len(g7), g7)
    put("INFO.adverb_comma", len(adverb_comma), adverb_comma)

    # G2: 직접 겪었다는 종결
    exp = [_hit(s, s.word) for s in body if s.word.endswith(EXPERIENCE_ENDINGS)]
    put("G2.exp_ending", len(exp), exp)

    # A2 쉼표
    n_body = len(body) or 1
    commas = [comma_count(s.masked) for s in body]
    conn_total = conn_comma = 0
    conn_hits = []
    for s in body:
        toks = s.masked.split()
        for idx, tok in enumerate(toks[:-1]):
            has_comma = tok.endswith((",", "，"))
            base = tok.rstrip(",，").rstrip(CLOSERS)
            if idx == 0 and base in SENT_ADVERBS:
                continue
            if is_connective(base):
                conn_total += 1
                if has_comma:
                    conn_comma += 1
                    conn_hits.append(_hit(s, tok))
    put("A2.comma_per_sentence", round(sum(commas) / n_body, 3))
    put("A2.comma_sentence_ratio", round(sum(1 for c in commas if c) / n_body, 3))
    put("A2.connective_comma_ratio", round(conn_comma / conn_total, 3) if conn_total else 0.0,
        conn_hits, comma=conn_comma, total=conn_total)

    # A17 같은 첫 두 어절로 여는 문장("표를 보면", "결론부터 말하면")의 최다 반복 횟수
    openers = {}
    for s_ in body:
        toks = re.sub(r"^[^\w가-힣⟦]+", "", s_.masked).split()[:2]
        if len(toks) == 2:
            openers.setdefault(" ".join(toks), []).append(s_)
    top = max(openers.items(), key=lambda kv: len(kv[1])) if openers else None
    put("A17.opener_repeat", len(top[1]) if top else 0,
        [_hit(x, top[0]) for x in top[1]] if top and len(top[1]) > 1 else [])

    # A16 자료를 주어로 여는 문장의 비율
    src_hits = metrics["A16.source_subject"]["hits"]
    put("A16.source_subject_share", round(len(src_hits) / n_body, 3), src_hits, count=len(src_hits))

    # A4 문단 끝 요약 문장과 교훈 문장의 합계
    para_end = metrics["A4.summary_start"]["hits"] + metrics["A4.lesson_end"]["hits"]
    put("A4.para_end", len(para_end), para_end)

    # A8 리듬
    lens = [len(s.text) for s in body if s.kind == "paragraph"]
    if lens:
        mean = sum(lens) / len(lens)
        sd = math.sqrt(sum((x - mean) ** 2 for x in lens) / len(lens))
        put("A8.sent_len_mean", round(mean, 1))
        put("A8.sent_len_cv", round(sd / mean, 3) if mean else 0.0)
        put("A8.long_ratio", round(sum(1 for x in lens if x >= 80) / len(lens), 3))
    else:
        put("A8.sent_len_mean", 0.0)
        put("A8.sent_len_cv", 0.0)
        put("A8.long_ratio", 0.0)
    runs = []
    run_len = 1
    prev = None
    seq = [s for s in body if s.kind == "paragraph"]
    for s in seq:
        if prev is not None and s.bucket == prev.bucket and s.bucket not in ("NOUN", "OTHER"):
            run_len += 1
            if run_len == 4:
                runs.append(_hit(s, s.bucket))
        else:
            run_len = 1
        prev = s
    put("A8.ending_run4", len(runs), runs)
    same_predicates = same_predicate_adjacent_hits(para_sents)
    put("A8.same_predicate_adjacent", len(same_predicates), same_predicates)
    pred = [s_.bucket for s_ in body if s_.bucket not in ("NOUN", "OTHER")]
    if pred:
        top_bucket = max(set(pred), key=pred.count)
        put("A8.ending_top_share", round(pred.count(top_bucket) / len(pred), 3), [], bucket=top_bucket)
    else:
        put("A8.ending_top_share", 0.0)
    paras = [ps for ps in para_sents if ps]
    put("A8.sentences_per_para", round(sum(len(p) for p in paras) / len(paras), 2) if paras else 0.0)
    put("A8.single_para_ratio", round(sum(1 for p in paras if len(p) == 1) / len(paras), 3) if paras else 0.0)

    # A9 서식
    per_k = 1000.0 / prose_chars if prose_chars else 0.0
    sub_heads = [h for h in headings if h["level"] >= 2]
    label_items = [li for li in list_items if re.match(r"^\s*(\*\*|__)[^*_]{1,40}(\*\*|__)\s*[:：]", li["raw"])
                   or re.match(r"^[^\s:：]{1,20}\s*[:：]\s", li["text"])]
    put("A9.bold_per_1k", round(bold * per_k, 2))
    put("A9.list_ratio", round(list_chars / prose_chars, 3) if prose_chars else 0.0)
    put("A9.label_list_ratio", round(len(label_items) / len(list_items), 3) if list_items else 0.0)
    put("A9.heading_per_1k", round(len(sub_heads) * per_k, 2))
    colon_heads = [h for h in sub_heads if re.search(r"[:：]", h["text"])]
    put("A9.heading_colon_ratio", round(len(colon_heads) / len(sub_heads), 3) if sub_heads else 0.0,
        [{"line": h["line"], "text": h["text"]} for h in colon_heads])

    # A10 셋 묶음
    triads = [_hit(s) for s in body if is_triad(s.masked)]
    lists_by_id = {}
    for li in list_items:
        if li["depth"] == 0:
            lists_by_id.setdefault(li["list_id"], []).append(li)
    triad_lists = [v[0] for v in lists_by_id.values() if len(v) == 3]
    triad_total = len(triads) + len(triad_lists)
    put("A10.triad_per_1k", round(triad_total * per_k, 2), triads + [{"line": t["line"], "text": t["text"][:160]} for t in triad_lists],
        sentences=len(triads), lists=len(triad_lists))
    tri_para = []
    for ps in para_sents:
        c = [s for s in ps if is_triad(s.masked)]
        if len(c) >= 2:
            tri_para.append(_hit(c[0]))
    put("A10.triad_same_para", len(tri_para), tri_para)

    # A11 질문
    qs = [_hit(s) for s in body if s.question]
    put("A11.body_questions", len(qs), qs)
    q_heads = [h for h in sub_heads if QUESTION_HEADING_RE.search(h["text"].rstrip())]
    put("A11.question_heading_ratio", round(len(q_heads) / len(sub_heads), 3) if sub_heads else 0.0,
        [{"line": h["line"], "text": h["text"]} for h in q_heads])

    # 1,000자당 비율로 쓰는 패턴
    for pid in ("A5.style_words", "A5.policy_verbs", "A12.progressive", "A13.demonstrative_start",
                "A14.translationese"):
        metrics[pid + "_per_1k"] = {"value": round(metrics[pid]["value"] * per_k, 2), "hits": metrics[pid]["hits"]}
    word_counts = {}
    for h in metrics["A5.style_words"]["hits"]:
        key = re.sub(r"(인|으로|하는\s*바|하|합|해|한|할|했|점|니다|요)$", "", h.get("match", ""))
        word_counts[key] = word_counts.get(key, 0) + 1
    over = {k: v for k, v in word_counts.items() if v > 2}
    put("A5.word_max", max(word_counts.values()) if word_counts else 0,
        [{"line": 0, "text": f"{k} {v}회"} for k, v in over.items()])

    # A15 fact sheet에 없는 수치. "수십만", "수천" 같은 어림 수량어도 fact sheet에 같은 말이 있어야 한다.
    if facts_text is not None:
        # 용어 표의 일반 지식 설명 칸(사전, 교과서에서 가져온 설명)의 수치는 자료의 수치로 치지 않는다.
        known = number_set(strip_general_knowledge(facts_text))
        facts_norm = re.sub(r"\s+", "", facts_text)
        unknown = []
        for s in sentences:
            for key, raw in extract_numbers(s.text):
                if key not in known:
                    unknown.append(_hit(s, raw))
            for word in ko_approx_hits(s.masked):
                if word not in facts_norm:
                    unknown.append(_hit(s, word))
        for h in headings:
            for key, raw in extract_numbers(h["text"]):
                if key not in known:
                    unknown.append({"line": h["line"], "text": h["text"][:160], "match": raw})
            for word in ko_approx_hits(h["text"]):
                if word not in facts_norm:
                    unknown.append({"line": h["line"], "text": h["text"][:160], "match": word})
        put("A15.unknown_numbers", len(unknown), unknown)

    # 종결 분포
    dist = {}
    for s in body:
        dist[s.bucket] = dist.get(s.bucket, 0) + 1
    cls_count = {}
    for s in body:
        cls_count[s.cls] = cls_count.get(s.cls, 0) + 1

    stats = {
        "chars": prose_chars,
        "sentences": len(body),
        "paragraphs": len(paras),
        "headings": len(sub_heads),
        "list_items": len(list_items),
        "title": title_text,
    }
    return {
        "stats": stats,
        "metrics": metrics,
        "endings": {"class": cls_count, "bucket": dist},
        "_sentences": body,
    }


# ---------------------------------------------------------------- 어투 판정

def detect_tone(analysis):
    c = analysis["endings"]["class"]
    return "casual" if c.get("HAEYO", 0) > c.get("HAPNIDA", 0) else "default"


def tone_metrics(analysis, tone, imperative_ok=False, inga_ok=False):
    """G4 어투 혼용과 Casual 허용 변형 비율. 참고자료 절의 서지 항목("공개 URL 없음")은 문장이 아니라서 보지 않는다.
    imperative_ok(짧은 글 모드)면 Default 글의 요청문 "~해 주세요", "~하세요"도 어투에 맞는 것으로 본다.
    inga_ok(짧은 글 모드)면 Default 글의 질문 "~인가요?"도 어투에 맞는 것으로 본다(references/short.md 4번)."""
    off = []
    banned = []
    for s in analysis["_sentences"]:
        if s.cls in ("NOUN", "OTHER") or getattr(s, "in_refs", False):
            continue
        if s.word.endswith(BANNED_ENDINGS) and tone == "casual":
            banned.append(_hit(s, s.word))
            continue
        ok = {"default": ("HAPNIDA", "Q_KKAYO"), "casual": ("HAEYO", "Q_KKAYO")}[tone]
        if s.cls == "NOMINAL" and s.kind != "paragraph":
            continue
        if imperative_ok and tone == "default" and s.word.rstrip(".!").endswith("세요") \
                and not s.text.rstrip().endswith("?"):
            continue                                    # Slack 글의 요청문(짧은 글 모드)
        if inga_ok and tone == "default" and s.text.rstrip().endswith("?") and s.word.rstrip("?").endswith("인가요"):
            continue                                    # 짧은 글 모드의 질문 "~인가요?"
        if s.cls not in ok:
            off.append(_hit(s, f"{s.cls}:{s.word}"))
    n = sum(1 for s in analysis["_sentences"] if s.cls not in ("NOUN", "OTHER")) or 1
    b = analysis["endings"]["bucket"]
    out = {
        "G4.off_tone": {"value": len(off), "hits": off},
        "G4.banned_ending": {"value": len(banned), "hits": banned},
        "T.jyo_ratio": {"value": round(b.get("C_JYO", 0) / n, 3), "hits": []},
        "T.geudeun_ratio": {"value": round(b.get("C_GEUDEUN", 0) / n, 3), "hits": []},
        "T.kkayo_ratio": {"value": round(b.get("Q_KKAYO", 0) / n, 3), "hits": []},
        "T.neundeyo_ratio": {"value": round(b.get("C_NEUNDEYO", 0) / n, 3), "hits": []},
    }
    return out


# ---------------------------------------------------------------- 기준치 판정

def poisson_ppf(q, lam):
    if lam <= 0:
        return 0
    k = 0
    p = math.exp(-lam)
    cdf = p
    while cdf < q and k < 100000:
        k += 1
        p *= lam / k
        cdf += p
    return k


def judge(value, spec, chars):
    """기준치 종류별로 PASS/WARN/FAIL/GATE/INFO를 정한다."""
    kind = spec.get("kind", "info")
    if kind == "info":
        return "INFO", {}
    if kind == "check":
        # 점검 후보: 판정에 넣지 않고 걸린 문장만 보여 준다
        return ("CHECK" if value > 0 else "PASS"), {}
    if kind == "gate":
        return ("GATE" if value > 0 else "PASS"), {"max": 0}
    if kind == "poisson":
        lam = spec["rate_per_1k"] * chars / 1000.0
        floor = spec.get("_floor", 0)
        p = max(floor, poisson_ppf(spec.get("pass_q", 0.9), lam))
        w = max(floor, poisson_ppf(spec.get("warn_q", 0.975), lam))
        lim = {"pass_max": p, "warn_max": w, "basis": "poisson", "rate_per_1k": spec["rate_per_1k"]}
        return ("PASS" if value <= p else "WARN" if value <= w else "FAIL"), lim
    if kind == "upper":
        lim = {"pass_max": spec["pass_max"], "warn_max": spec["warn_max"]}
        return ("PASS" if value <= spec["pass_max"] else "WARN" if value <= spec["warn_max"] else "FAIL"), lim
    if kind == "lower":
        lim = {"pass_min": spec["pass_min"], "warn_min": spec["warn_min"]}
        return ("PASS" if value >= spec["pass_min"] else "WARN" if value >= spec["warn_min"] else "FAIL"), lim
    if kind == "range":
        lo, hi = spec["pass"]
        wlo, whi = spec["warn"]
        lim = {"pass": spec["pass"], "warn": spec["warn"]}
        return ("PASS" if lo <= value <= hi else "WARN" if wlo <= value <= whi else "FAIL"), lim
    return "INFO", {}


def evaluate(analysis, thresholds, tone, max_hits=5, patterns_spec=None):
    if patterns_spec is None:
        patterns_spec = load_json(PATTERNS_PATH)
    pmeta = patterns_spec.get("patterns", {})
    metrics = dict(analysis["metrics"])
    metrics.update(tone_metrics(analysis, tone, imperative_ok=bool(thresholds.get("allow_imperative")),
                                inga_ok=bool(thresholds.get("allow_inga_question"))))
    chars = analysis["stats"]["chars"]
    results = []
    for mid, spec in thresholds["metrics"].items():
        if mid not in metrics:
            continue
        if spec.get("tone") and spec["tone"] != tone:
            continue
        if "by_tone" in spec:
            spec = dict(spec, **spec["by_tone"].get(tone, {}))
        if thresholds.get("poisson_floor"):
            spec = dict(spec, _floor=thresholds["poisson_floor"])     # 짧은 글: 한 번은 허용
        m = metrics[mid]
        value = len(m["hits"]) if spec.get("count") else m["value"]
        status, lim = judge(value, spec, chars)
        if spec.get("min_chars") and chars < spec["min_chars"] and status not in ("GATE",):
            status, lim = "INFO", {"note": f"본문 {spec['min_chars']}자 미만이라 판정하지 않음"}
        base_id = mid[:-len("_per_1k")] if mid.endswith("_per_1k") else mid
        title = spec.get("title") or pmeta.get(base_id, {}).get("title", mid)
        hint = spec.get("hint") or pmeta.get(base_id, {}).get("hint", "")
        r = {"id": mid, "title": title, "value": value, "status": status, "limit": lim}
        if spec.get("group"):
            r["group"] = spec["group"]
        if m.get("extra"):
            r["extra"] = m["extra"]
        if status not in ("PASS", "INFO") or max_hits < 0:
            r["hits"] = m["hits"][:max_hits] if max_hits >= 0 else m["hits"]
            # compact 항목(용어 설명 점검 후보)은 잘린 hit도 줄 번호와 걸린 말만 남긴다. 0.8.0은 앞의 5개만 보여 줘서
            # 뒤 절의 용어가 5단계 점검 목록에 오르지 않았다.
            if spec.get("compact") and 0 <= max_hits < len(m["hits"]):
                r["more"] = [{"line": h["line"], "match": h.get("match", "")} for h in m["hits"][max_hits:]]
        if hint and status not in ("PASS", "INFO"):
            r["hint"] = hint
        results.append(r)
    gate_fail = sum(1 for r in results if r["status"] == "GATE")
    fail = sum(1 for r in results if r["status"] == "FAIL")
    warn = sum(1 for r in results if r["status"] == "WARN")
    verdict = "PASS" if gate_fail == 0 and fail == 0 and warn <= thresholds.get("max_warn", 2) else "FAIL"
    return {"results": results,
            "summary": {"gate_fail": gate_fail, "fail": fail, "warn": warn, "verdict": verdict}}


# ---------------------------------------------------------------- 출력

STATUS_ORDER = {"GATE": 0, "FAIL": 1, "WARN": 2, "CHECK": 3, "PASS": 4, "INFO": 5}


def _fmt_limit(lim):
    if not lim:
        return ""
    if "max" in lim:
        return "기준 0회"
    if "pass_max" in lim:
        return f"PASS ≤{lim['pass_max']}, WARN ≤{lim['warn_max']}"
    if "pass_min" in lim:
        return f"PASS ≥{lim['pass_min']}, WARN ≥{lim['warn_min']}"
    if "pass" in lim:
        return f"PASS {lim['pass'][0]}~{lim['pass'][1]}, WARN {lim['warn'][0]}~{lim['warn'][1]}"
    return ""


def render_text(path, tone, analysis, ev, show_all=False):
    st = analysis["stats"]
    sm = ev["summary"]
    lines = [
        f"techblog lint | {os.path.basename(path)} | tone={tone} | {st['chars']:,}자, {st['sentences']}문장, "
        f"{st['paragraphs']}문단, 헤딩 {st['headings']}개",
        f"판정: {sm['verdict']} (Gate 위반 {sm['gate_fail']}, FAIL {sm['fail']}, WARN {sm['warn']})",
    ]
    checks = [r for r in ev["results"] if r["status"] == "CHECK"]
    for r in sorted(ev["results"], key=lambda r: STATUS_ORDER[r["status"]]):
        if r["status"] == "CHECK" or (r["status"] in ("PASS", "INFO") and not show_all):
            continue
        lines.append(f"[{r['status']}] {r['id']} {r['title']}: {r['value']} ({_fmt_limit(r['limit'])})")
        if r.get("hint"):
            lines.append(f"    고치는 방향: {r['hint']}")
        for h in r.get("hits", []):
            m = f" «{h['match']}»" if h.get("match") else ""
            lines.append(f"    L{h['line']}{m}: {h['text']}")
    groups = (
        ([r for r in checks if r.get("group") not in ("ko", "term", "rhythm")], False,
         "단독 읽기 점검 후보 (판정에 들어가지 않음): 이 문장과 바로 앞 문장만 읽고 무엇에 대한 말인지, "
         "누구의 말인지, 수치가 무엇을 잰 값인지 알 수 있으면 그대로 둔다."),
        ([r for r in checks if r.get("group") == "rhythm"], True,
         "서술어 반복 점검 후보 (판정에 들어가지 않음): 이웃한 두 문장을 함께 읽는다. 반복 때문에 읽기가 "
         "끊기고 뜻과 조건을 더 명확하게 쓸 수 있을 때만 항목을 묶거나 근거와 결과를 잇는다. 자연스러운 반복과 "
         "필요한 주어와 목적어는 남기고, 남긴 후보의 문맥과 이유를 기록한다."),
        ([r for r in checks if r.get("group") == "ko"], True,
         "한국어 점검 후보 (판정에 들어가지 않음): 걸린 말이 references/ai-patterns.md의 \"과교정하지 않기\"에 "
         "있는 쓰임이면 그대로 두고, 아니면 사람이 쓴 한국어 기술 블로그 글에서 사용하는 말로 고친다."),
        ([r for r in checks if r.get("group") == "term"], True,
         "용어 설명 점검 후보 (판정에 들어가지 않음): 걸린 말이 처음 나온 이 문장이나 바로 다음 문장에 그 말이 "
         "무엇인지 쓴 설명이 있으면 그대로 둔다. 이름을 옮긴 말이나 약어의 풀네임뿐이면 references/style-guide.md의 "
         "\"처음 나오는 용어와 중심 대상 설명\"대로 고친다."),
    )
    for group, show_match, header in groups:
        if not group:
            continue
        lines.append("")
        lines.append(header)
        for r in group:
            lines.append(f"[CHECK] {r['id']} {r['title']}: {r['value']}")
            if r.get("hint"):
                lines.append(f"    고치는 방향: {r['hint']}")
            for h in r.get("hits", []):
                m = f" «{h['match']}»" if show_match and h.get("match") else ""
                where = f"L{h['line']}" if h["line"] else "fact sheet"
                if h.get("previous"):
                    p = h["previous"]
                    lines.append(f"    앞 문장 L{p['line']}: {p['text']}")
                lines.append(f"    {where}{m}: {h['text']}")
            more = r.get("more") or []
            if more:
                lines.append(f"    나머지 {len(more)}곳(줄 번호와 걸린 말):")
                for k in range(0, len(more), 6):
                    lines.append("      " + ", ".join(
                        (f"L{h['line']}" if h["line"] else "fact sheet") + (f" «{h['match']}»" if h["match"] else "")
                        for h in more[k:k + 6]))
    return "\n".join(lines)


# ---------------------------------------------------------------- 짧은 글 모드

def short_profile(thresholds, patterns_spec):
    """thresholds.json의 short 프로필을 적용한 (기준치, 패턴) 사본을 돌려준다.
    drop의 항목이 "."으로 끝나면 그 접두어로 시작하는 metric을 모두 뺀다."""
    prof = thresholds.get("short") or {}
    drops = prof.get("drop") or []

    def dropped(mid):
        return any(mid.startswith(d) if d.endswith(".") else mid == d for d in drops)
    th = dict(thresholds)
    th["metrics"] = {mid: spec for mid, spec in thresholds["metrics"].items() if not dropped(mid)}
    # 1,000자당 비율은 짧은 글에서 판정하지 않으므로(min_chars) 정한 항목은 개수로 본다
    for mid, (pass_max, warn_max) in (prof.get("count") or {}).items():
        if mid in th["metrics"]:
            spec = th["metrics"][mid]
            title = re.sub(r"\(1,000자당\)", "", spec.get("title") or mid).strip()
            th["metrics"][mid] = {"kind": "upper", "pass_max": pass_max, "warn_max": warn_max, "count": True,
                                  "title": f"{title} (짧은 글: 개수)",
                                  **({"hint": spec["hint"]} if spec.get("hint") else {})}
    if "max_warn" in prof:
        th["max_warn"] = prof["max_warn"]
    th["allow_imperative"] = bool(prof.get("allow_imperative"))
    th["allow_inga_question"] = bool(prof.get("allow_inga_question"))
    th["poisson_floor"] = prof.get("poisson_floor", 0)
    spec = json.loads(json.dumps(patterns_spec))
    for pid, allowed in (prof.get("allow_patterns") or {}).items():
        if pid in spec["patterns"]:
            spec["patterns"][pid]["regex"] = [r for r in spec["patterns"][pid]["regex"] if r not in allowed]
    return th, spec


FENCED_BLOCK_RE = re.compile(r"^ {0,3}(`{3,}|~{3,})[^\n]*\n(.*?)^ {0,3}\1[ \t]*$", re.M | re.S)
INLINE_CODE_RE = re.compile(r"(`+)(?!`)(.+?)(?<!`)\1(?!`)")
URL_RE = re.compile(r"https?://[^\s)>\]`\"'<]+")
SLACK_TOKEN_RE = re.compile(r"<[@#!][^>\s]+>|\{[A-Za-z_]+(?::[^}\s]+)?\}")
NUMBER_RE = re.compile(r"(?<![\w.])\d+(?:[.,]\d+)*")
LIST_LINE_RE = re.compile(r"^[ \t]*(?:[-*+]|\d{1,3}[.)])[ \t]+\S")
HEADING_LINE_RE = re.compile(r"^ {0,3}#{1,6}[ \t]+\S")


def _outside_fences(text):
    """코드 블록을 지운 본문과 코드 블록 내용 목록."""
    blocks = [m.group(2) for m in FENCED_BLOCK_RE.finditer(text)]
    return FENCED_BLOCK_RE.sub("\n", text), blocks


def _structure(text):
    body, blocks = _outside_fences(text)
    spans = [m.group(2) for m in INLINE_CODE_RE.finditer(body)]
    no_code = INLINE_CODE_RE.sub(" ", body)
    urls = URL_RE.findall(no_code)
    tokens = SLACK_TOKEN_RE.findall(no_code)
    plain = SLACK_TOKEN_RE.sub(" ", URL_RE.sub(" ", no_code))
    lines = body.split("\n")
    return {"blocks": blocks, "spans": spans, "urls": urls, "tokens": tokens,
            "numbers": NUMBER_RE.findall(plain),
            "list_items": sum(1 for line in lines if LIST_LINE_RE.match(line)),
            "headings": sum(1 for line in lines if HEADING_LINE_RE.match(line))}


def _missing(src_items, out_items):
    """원문에 있는데 결과에 없는(또는 모자란) 항목."""
    left = list(out_items)
    out = []
    for item in src_items:
        if item in left:
            left.remove(item)
        else:
            out.append(item)
    return out


def _term_targets(terms):
    """용어표: {"영어": "한국어"} 또는 [{"en": ..., "ko": ...}] 목록."""
    if isinstance(terms, dict):
        return [(str(k), str(v)) for k, v in terms.items()]
    return [(str(t.get("en")), str(t.get("ko"))) for t in terms or [] if isinstance(t, dict)]


def fidelity_metrics(source_text, text, terms=None):
    """짧은 글 모드의 원문 대조(F 항목). 값은 어긋난 개수다."""
    src, out = _structure(normalize_text(source_text)), _structure(text)

    def hits(items):
        return [{"line": 0, "text": str(i)[:160]} for i in items]
    m = {}
    altered = _missing(src["blocks"], out["blocks"])
    m["F1.code_blocks"] = {"value": len(altered), "hits": hits(b.strip().split("\n")[0] for b in altered)}
    spans = _missing(src["spans"], out["spans"])
    m["F2.inline_code"] = {"value": len(spans), "hits": hits(spans)}
    urls = _missing(src["urls"], out["urls"])
    m["F3.urls"] = {"value": len(urls), "hits": hits(urls)}
    tokens = _missing(src["tokens"], out["tokens"])
    m["F4.slack_tokens"] = {"value": len(tokens), "hits": hits(tokens)}
    numbers = _missing(sorted(set(src["numbers"])), sorted(set(out["numbers"])))
    m["F5.numbers"] = {"value": len(numbers), "hits": hits(numbers)}
    diff = abs(src["list_items"] - out["list_items"])
    m["F6.list_items"] = {"value": diff, "hits": hits([f"원문 {src['list_items']}개, 결과 {out['list_items']}개"])
                          if diff else []}
    diff = abs(src["headings"] - out["headings"])
    m["F7.headings"] = {"value": diff, "hits": hits([f"원문 {src['headings']}개, 결과 {out['headings']}개"])
                        if diff else []}
    wrong = []
    if terms:
        # 코드 블록과 인라인 코드는 원문 그대로 두는 것이라 용어를 찾지 않는다. 대문자가 있는 표기(버튼 이름
        # "Keep")는 쓴 그대로 찾고, 모두 소문자인 표기("blocked")는 대소문자를 가리지 않는다.
        prose = INLINE_CODE_RE.sub(" ", FENCED_BLOCK_RE.sub(" ", normalize_text(source_text)))
        for en, ko in _term_targets(terms):
            if not (en and ko):
                continue
            flags = 0 if en != en.lower() else re.I
            if re.search(r"(?<![A-Za-z])" + re.escape(en) + r"(?![A-Za-z])", prose, flags) and ko not in text:
                wrong.append(f"{en} → {ko}")
    m["F8.terms"] = {"value": len(wrong), "hits": hits(wrong)}
    return m


def run(path, tone="auto", facts=None, thresholds_path=None, as_json=False, show_all=False, max_hits=5,
        short=False, source=None, terms=None):
    text = read_text(path)
    facts_text = read_text(facts) if facts else None
    thresholds = load_json(thresholds_path or THRESHOLDS_PATH)
    patterns_spec = load_json(PATTERNS_PATH)
    if short:
        thresholds, patterns_spec = short_profile(thresholds, patterns_spec)
    analysis = analyze(text, patterns_spec=patterns_spec, facts_text=facts_text)
    if short and source:
        analysis["metrics"].update(fidelity_metrics(read_text(source), text,
                                                    load_json(terms) if terms else None))
    if tone == "auto":
        tone = detect_tone(analysis)
    ev = evaluate(analysis, thresholds, tone, max_hits=-1 if as_json else max_hits, patterns_spec=patterns_spec)
    if as_json:
        out = {"schema": LINT_SCHEMA, "file": path, "tone": tone, "stats": analysis["stats"],
               "endings": analysis["endings"], "results": ev["results"], "summary": ev["summary"]}
        return json.dumps(out, ensure_ascii=False, indent=1), ev["summary"]["verdict"]
    return render_text(path, tone, analysis, ev, show_all), ev["summary"]["verdict"]


def main(argv=None):
    setup_stdio()
    ap = argparse.ArgumentParser(description="techblog 한국어 문체 lint")
    ap.add_argument("article")
    ap.add_argument("--tone", choices=("default", "casual", "auto"), default="auto")
    ap.add_argument("--facts", help="fact sheet 경로(A15 수치 대조)")
    ap.add_argument("--thresholds", help="기준치 JSON 경로(기본: scripts/thresholds.json)")
    ap.add_argument("--json", action="store_true", help="JSON으로 출력")
    ap.add_argument("--all", action="store_true", help="PASS 항목도 출력")
    ap.add_argument("--max-hits", type=int, default=5)
    ap.add_argument("--short", action="store_true", help="짧은 글 모드(thresholds.json의 short 프로필)")
    ap.add_argument("--source", help="짧은 글 모드: 영어 원문 경로(F 항목 대조)")
    ap.add_argument("--terms", help="짧은 글 모드: 용어표 JSON 경로({\"영어\": \"한국어\"})")
    try:
        args = ap.parse_args(argv)
    except SystemExit as e:
        return 2 if e.code else 0
    if (args.source or args.terms) and not args.short:
        print("--source와 --terms는 --short와 함께 씁니다", file=sys.stderr)
        return 2
    for p in [args.article] + [x for x in (args.facts, args.source, args.terms) if x]:
        if not os.path.isfile(p):
            print(f"파일이 없습니다: {p}", file=sys.stderr)
            return 2
    try:
        out, verdict = run(args.article, args.tone, args.facts, args.thresholds, args.json, args.all, args.max_hits,
                           short=args.short, source=args.source, terms=args.terms)
    except (OSError, ValueError, KeyError) as e:
        print(f"lint 실행 오류: {e}", file=sys.stderr)
        return 2
    print(out)
    return 0 if verdict == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
