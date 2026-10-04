#!/usr/bin/env python3
"""techblog lint: 한국어 기술 블로그 글에서 rubric의 자동 측정 항목(G, A)을 센다.

사용법
  python lint_ko.py ARTICLE.md [--tone default|casual|auto] [--facts FACTS.md]
                    [--thresholds PATH] [--json] [--all] [--max-hits N]

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
    """마침표·물음표·느낌표 뒤 공백을 경계로 나눈다. 괄호·따옴표 안과 숫자(3.5)·약어(e.g.)는 나누지 않는다."""
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
DASH_RE = re.compile(r"[가-힣][^—―–\n]{0,15}?(?:[—―]|\s–\s)[^—―–\n]{0,15}?[가-힣]")
LABEL_DASH_RE = re.compile(r"^(?:[-*+]\s|\d+[.)]\s)?([^—―–]{1,20}?)\s[—―–]\s")
LABEL_PARTICLE_RE = re.compile(r"(은|는|이|가|을|를|에|의|로|와|과|도|만|면|고|서)$")
REF_HEADING_RE = re.compile(r"(참고|references?|출처|각주|reference|읽을\s*거리)", re.I)
QUESTION_HEADING_RE = re.compile(r"(\?|을까|를까|할까|일까|될까|볼까|까요|나요|는가|인가)$")


class Sentence:
    __slots__ = ("text", "masked", "kind", "block", "para", "line", "first", "last",
                 "word", "cls", "bucket", "question")


def _compile_patterns(spec):
    compiled = {}
    for pid, p in spec["patterns"].items():
        compiled[pid] = {
            "title": p.get("title", pid),
            "scope": p.get("scope", "sentence"),
            "max_len": p.get("max_len"),
            "hint": p.get("hint", ""),
            "regex": [re.compile(r) for r in p["regex"]],
        }
    return compiled


def _hit(sent, match=None):
    h = {"line": sent.line, "text": sent.text[:160]}
    if match is not None:
        h["match"] = match
    return h


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
    dash_hits = []
    emoji_hits = []
    semicolon_hits = []

    for bi, b in enumerate(blocks):
        if b.type == "heading":
            clean, bcount, _ = clean_inline(b.text)
            headings.append({"level": b.level, "text": clean, "line": b.line})
            in_refs = bool(REF_HEADING_RE.search(clean)) and b.level >= 2
            if EMOJI_RE.search(clean):
                emoji_hits.append({"line": b.line, "text": clean[:160]})
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
        if not in_refs:
            for m in DASH_RE.finditer(mask_quotes(clean)):
                lm = LABEL_DASH_RE.match(clean)
                if lm and m.start() <= len(lm.group(0)) and not LABEL_PARTICLE_RE.search(lm.group(1).strip()):
                    continue  # "1단계 — 설정" 같은 라벨 구분자
                dash_hits.append({"line": b.line, "text": clean[:160], "match": m.group(0)})
                break
            if ";" in PH_RE.sub("", clean):
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

    # 패턴 기반 metric
    for pid, p in patterns.items():
        hits = []
        if p["scope"] == "para_last":
            pool = [ps[-1] for ps in para_sents if ps]
        else:
            pool = body
        for s in pool:
            if p["max_len"] and len(s.text) > p["max_len"]:
                continue
            target = s.masked.lstrip()
            for rx in p["regex"]:
                m = rx.search(target)
                if m:
                    hits.append(_hit(s, m.group(0)))
                    break
        metrics[pid] = {"value": len(hits), "hits": hits}

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
    put("G6.emdash", len(dash_hits), dash_hits)
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

    # A4 문단 끝 요약·교훈 합계
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

    # A15 fact sheet에 없는 수치
    if facts_text is not None:
        known = number_set(facts_text)
        unknown = []
        for s in sentences:
            for key, raw in extract_numbers(s.text):
                if key not in known:
                    unknown.append(_hit(s, raw))
        for h in headings:
            for key, raw in extract_numbers(h["text"]):
                if key not in known:
                    unknown.append({"line": h["line"], "text": h["text"][:160], "match": raw})
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


def tone_metrics(analysis, tone):
    """G4 어투 혼용과 Casual 허용 변형 비율."""
    off = []
    banned = []
    for s in analysis["_sentences"]:
        if s.cls in ("NOUN", "OTHER"):
            continue
        if s.word.endswith(BANNED_ENDINGS) and tone == "casual":
            banned.append(_hit(s, s.word))
            continue
        ok = {"default": ("HAPNIDA", "Q_KKAYO"), "casual": ("HAEYO", "Q_KKAYO")}[tone]
        if s.cls == "NOMINAL" and s.kind != "paragraph":
            continue
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
    if kind == "gate":
        return ("GATE" if value > 0 else "PASS"), {"max": 0}
    if kind == "poisson":
        lam = spec["rate_per_1k"] * chars / 1000.0
        p = poisson_ppf(spec.get("pass_q", 0.9), lam)
        w = poisson_ppf(spec.get("warn_q", 0.975), lam)
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
    metrics.update(tone_metrics(analysis, tone))
    chars = analysis["stats"]["chars"]
    results = []
    for mid, spec in thresholds["metrics"].items():
        if mid not in metrics:
            continue
        if spec.get("tone") and spec["tone"] != tone:
            continue
        if "by_tone" in spec:
            spec = dict(spec, **spec["by_tone"].get(tone, {}))
        m = metrics[mid]
        status, lim = judge(m["value"], spec, chars)
        if spec.get("min_chars") and chars < spec["min_chars"] and status not in ("GATE",):
            status, lim = "INFO", {"note": f"본문 {spec['min_chars']}자 미만이라 판정하지 않음"}
        base_id = mid[:-len("_per_1k")] if mid.endswith("_per_1k") else mid
        title = spec.get("title") or pmeta.get(base_id, {}).get("title", mid)
        hint = spec.get("hint") or pmeta.get(base_id, {}).get("hint", "")
        r = {"id": mid, "title": title, "value": m["value"], "status": status, "limit": lim}
        if m.get("extra"):
            r["extra"] = m["extra"]
        if status not in ("PASS", "INFO") or max_hits < 0:
            r["hits"] = m["hits"][:max_hits] if max_hits >= 0 else m["hits"]
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

STATUS_ORDER = {"GATE": 0, "FAIL": 1, "WARN": 2, "PASS": 3, "INFO": 4}


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
        f"techblog lint | {os.path.basename(path)} | tone={tone} | {st['chars']:,}자 · {st['sentences']}문장 · {st['paragraphs']}문단 · 헤딩 {st['headings']}개",
        f"판정: {sm['verdict']} (Gate 위반 {sm['gate_fail']}, FAIL {sm['fail']}, WARN {sm['warn']})",
    ]
    for r in sorted(ev["results"], key=lambda r: STATUS_ORDER[r["status"]]):
        if r["status"] in ("PASS", "INFO") and not show_all:
            continue
        lines.append(f"[{r['status']}] {r['id']} {r['title']}: {r['value']} ({_fmt_limit(r['limit'])})")
        if r.get("hint"):
            lines.append(f"    고치는 방향: {r['hint']}")
        for h in r.get("hits", []):
            m = f" «{h['match']}»" if h.get("match") else ""
            lines.append(f"    L{h['line']}{m}: {h['text']}")
    return "\n".join(lines)


def run(path, tone="auto", facts=None, thresholds_path=None, as_json=False, show_all=False, max_hits=5):
    text = read_text(path)
    facts_text = read_text(facts) if facts else None
    analysis = analyze(text, facts_text=facts_text)
    if tone == "auto":
        tone = detect_tone(analysis)
    thresholds = load_json(thresholds_path or THRESHOLDS_PATH)
    ev = evaluate(analysis, thresholds, tone, max_hits=-1 if as_json else max_hits)
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
    try:
        args = ap.parse_args(argv)
    except SystemExit as e:
        return 2 if e.code else 0
    for p in [args.article] + ([args.facts] if args.facts else []):
        if not os.path.isfile(p):
            print(f"파일이 없습니다: {p}", file=sys.stderr)
            return 2
    try:
        out, verdict = run(args.article, args.tone, args.facts, args.thresholds, args.json, args.all, args.max_hits)
    except (OSError, ValueError, KeyError) as e:
        print(f"lint 실행 오류: {e}", file=sys.stderr)
        return 2
    print(out)
    return 0 if verdict == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
