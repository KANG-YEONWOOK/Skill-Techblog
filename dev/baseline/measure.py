#!/usr/bin/env python3
"""토스·카카오·당근 기술 블로그 글을 모아 lint_ko.analyze()로 측정한다.

원문은 --cache 폴더에만 저장하고 저장소에는 커밋하지 않는다. 저장소에는 URL 목록(urls.json)과
측정값(stats.json)만 남긴다.

사용법
  python dev/baseline/measure.py collect --cache DIR
  python dev/baseline/measure.py measure --cache DIR [--out dev/baseline/stats.json] [--urls dev/baseline/urls.json]
"""

import argparse
import hashlib
import html
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from email.utils import parsedate_to_datetime
from html.parser import HTMLParser

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(ROOT, "skills", "techblog", "scripts"))
import lint_ko as L  # noqa: E402

UA = {"User-Agent": "Mozilla/5.0 (techblog baseline measurement; github.com/KANG-YEONWOOK/Skill-Techblog)"}
CUTOFF = "2022-12-01"          # ChatGPT 공개(2022-11-30) 이전 글
CASUAL_END = "2024-07-01"      # 해요체 그룹은 이전 글이 부족해서 2024-06-30까지 넓힌다
DRIFT_START = "2025-01-01"
DAANGN_TAGS = [
    "backend", "frontend", "android", "ios", "data", "machine-learning", "mlops", "kubernetes", "devops",
    "sre", "infrastructure", "search", "recommendation-system", "ai", "llm", "react", "kotlin", "swift",
    "flutter", "golang", "go", "database", "mysql", "kafka", "aws", "platform", "web", "javascript",
    "typescript", "data-engineering", "analytics", "security", "observability", "monitoring", "spring",
    "nodejs", "graphql", "microservices", "architecture", "testing", "design-system", "data-science",
    "ab-testing", "experiment", "elasticsearch", "redis", "mongodb", "cloud", "network", "performance",
    "engineering", "software-development", "programming", "development", "tech", "daangn", "karrot",
]
NON_TECH_RE = re.compile(r"(채용|모집|인터뷰|Ka-reer|ka-reer|컨퍼런스|행사|밋업|meetup|SLASH|모닥불|"
                         r"합류|입사|신입|인턴십|career|hiring|recruit|팀을 소개|팀 소개|소개합니다|웨비나|"
                         r"이벤트|챌린지|해커톤|발표\s*영상|세션\s*영상|문화)", re.I)
KAKAO_SKIP_TAGS = ("career", "recruit", "new-krew", "krew", "event", "conference", "if-kakao", "ifkakao",
                   "culture", "interview", "hiring", "채용", "행사", "인터뷰", "문화")


# ---------------------------------------------------------------- HTML → markdown

class MDConverter(HTMLParser):
    """본문 HTML을 lint_ko가 읽는 markdown으로 바꾼다. bold, 헤딩, 목록, 인용, 코드, 표를 보존한다."""
    SKIP = {"style", "script", "noscript", "svg", "figcaption", "button", "nav", "footer", "iframe",
            "select", "option", "template", "header"}
    BLOCK = {"p", "div", "section", "h1", "h2", "h3", "h4", "h5", "h6", "li", "pre", "blockquote",
             "table", "tr", "figure", "ul", "ol", "dl", "dt", "dd", "hr", "article", "aside"}

    def __init__(self, skip_header=True):
        super().__init__(convert_charrefs=True)
        self.blocks = []
        self.buf = []
        self.skip = 0
        self.lists = []
        self.ctx = []          # 열린 블록 태그
        self.pre = 0
        self.bq = 0
        self.row = None
        self.rows = None
        self.cell = None
        if not skip_header:
            self.SKIP = self.SKIP - {"header"}

    def _kind(self):
        for t in reversed(self.ctx):
            if t in ("h1", "h2", "h3", "h4", "h5", "h6", "li", "dt", "dd"):
                return t
        return "p"

    def flush(self):
        if self.pre:
            return
        text = "".join(self.buf)
        self.buf = []
        text = re.sub(r"\s+", " ", text).strip()
        text = re.sub(r"\*\*\s*\*\*", "", text)
        if not text or text in ("**",):
            return
        kind = self._kind()
        prefix = "> " if self.bq else ""
        if kind.startswith("h"):
            level = int(kind[1])
            self.blocks.append("#" * level + " " + text.replace("**", ""))
        elif kind == "li":
            depth = max(0, len(self.lists) - 1)
            marker = "1." if self.lists and self.lists[-1] == "ol" else "-"
            self.blocks.append(prefix + "  " * depth + marker + " " + text)
        else:
            self.blocks.append(prefix + text)

    def handle_starttag(self, tag, attrs):
        if tag in self.SKIP:
            self.skip += 1
            return
        if self.skip:
            return
        if self.rows is not None and tag in ("td", "th"):
            self.cell = []
            return
        if self.rows is not None and tag == "tr":
            self.row = []
            return
        if tag == "table":
            self.flush()
            self.rows = []
            return
        if tag == "pre":
            self.flush()
            self.pre += 1
            self.buf = []
            return
        if self.pre:
            return
        if tag in self.BLOCK:
            self.flush()
            if tag in ("ul", "ol"):
                self.lists.append(tag)
            elif tag == "blockquote":
                self.bq += 1
            elif tag != "hr":
                self.ctx.append(tag)
            return
        if tag in ("strong", "b"):
            self._add("**")
        elif tag == "code":
            self._add("`")
        elif tag == "br":
            self._add(" ")
        elif tag == "img":
            pass

    def handle_endtag(self, tag):
        if tag in self.SKIP:
            self.skip = max(0, self.skip - 1)
            return
        if self.skip:
            return
        if self.rows is not None:
            if tag in ("td", "th") and self.cell is not None and self.row is not None:
                self.row.append(re.sub(r"\s+", " ", "".join(self.cell)).strip().replace("|", "/"))
                self.cell = None
                return
            if tag == "tr" and self.row is not None:
                self.rows.append(self.row)
                self.row = None
                return
            if tag == "table":
                if self.rows:
                    width = max(len(r) for r in self.rows)
                    lines = ["| " + " | ".join(r + [""] * (width - len(r))) + " |" for r in self.rows]
                    lines.insert(1, "|" + "---|" * width)
                    self.blocks.append("\n".join(lines))
                self.rows = None
                return
            return
        if tag == "pre":
            self.pre = max(0, self.pre - 1)
            code = "".join(self.buf).strip("\n")
            self.buf = []
            self.blocks.append("```\n" + code + "\n```")
            return
        if self.pre:
            return
        if tag in self.BLOCK:
            self.flush()
            if tag in ("ul", "ol"):
                if self.lists:
                    self.lists.pop()
            elif tag == "blockquote":
                self.bq = max(0, self.bq - 1)
            elif tag != "hr" and tag in self.ctx:
                while self.ctx and self.ctx.pop() != tag:
                    pass
            return
        if tag in ("strong", "b"):
            self._add("**")
        elif tag == "code":
            self._add("`")

    def _add(self, s):
        if self.cell is not None:
            self.cell.append(s.replace("**", "").replace("`", ""))
        else:
            self.buf.append(s)

    def handle_data(self, data):
        if self.skip:
            return
        if self.cell is not None:
            self.cell.append(data)
            return
        self.buf.append(data)

    def result(self):
        self.flush()
        return "\n\n".join(self.blocks) + "\n"


TAIL_MARKERS = re.compile(r"(님의 다른 글|재미있게 읽으셨나요|좋았던 점, 아쉬웠던 점|함께 읽으면 좋은 글|was originally published in)")


def trim_tail(md, cta=None):
    """본문 뒤에 붙는 채용 버튼, 저자의 다른 글 목록을 잘라 낸다."""
    out = []
    for ln in md.split("\n"):
        s = ln.strip().lstrip("#").strip()
        if TAIL_MARKERS.search(s):
            break
        if cta and s == cta.strip():
            continue
        out.append(ln)
    return "\n".join(out).rstrip() + "\n"


def html_to_md(fragment, title=None, cta=None):
    conv = MDConverter()
    conv.feed(fragment)
    body = conv.result()
    # 태그 경계에서 사라진 문장 사이 공백을 되살린다: "있습니다.`code`" → "있습니다. `code`"
    body = re.sub(r"([다요죠][.!?])(?=[`가-힣A-Za-z\"“])", r"\1 ", body)
    body = trim_tail(body, cta)
    if title:
        body = "# " + title.strip() + "\n\n" + body
    return body


# ---------------------------------------------------------------- 수집

def fetch(url, retries=2):
    for attempt in range(retries + 1):
        try:
            req = urllib.request.Request(url, headers=UA)
            with urllib.request.urlopen(req, timeout=40) as r:
                return r.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as e:
            if e.code in (404, 403, 410):
                return None
            time.sleep(3 * (attempt + 1))
        except Exception:
            time.sleep(3 * (attempt + 1))
    return None


def collect_toss(cache, meta):
    lst = []
    page = 1
    while True:
        raw = fetch(f"https://api-public.toss.im/api-public/v3/ipd-thor/api/v1/workspaces/15/posts?page={page}&size=100")
        if not raw:
            break
        d = json.loads(raw)["success"]
        lst += d["results"]
        if not d.get("next"):
            break
        page += 1
        time.sleep(1)
    for p in lst:
        if p.get("category") != "Engineering":
            continue
        date = (p.get("publishedTime") or "")[:10]
        if not date or (CASUAL_END <= date < DRIFT_START):
            continue
        key = p["key"]
        aid = f"toss-{key}"
        url = f"https://toss.tech/article/{key}"
        editor = (p.get("editor") or {}).get("name") if isinstance(p.get("editor"), dict) else None
        entry = {"id": aid, "site": "toss", "url": url, "date": date, "title": p.get("title", ""),
                 "author": editor or "", "tags": [c.get("name") for c in p.get("categories") or []]}
        path = os.path.join(cache, "md", aid + ".md")
        if not os.path.exists(path):
            page_html = fetch(url)
            time.sleep(1)
            if not page_html:
                entry["error"] = "fetch"
                meta[aid] = entry
                continue
            i = page_html.find("<article")
            j = page_html.find("</article>", i)
            frag = page_html[i:j] if i >= 0 and j > i else ""
            cta = (p.get("bottomButtonConfig") or {}).get("ctaName") or None
            md = html_to_md(frag, entry["title"], cta)
            with open(path, "w", encoding="utf-8") as f:
                f.write(md)
        meta[aid] = entry


def collect_kakao(cache, meta, start=380, end=845):
    for pid in range(start, end + 1):
        aid = f"kakao-{pid}"
        path = os.path.join(cache, "md", aid + ".md")
        if aid in meta and os.path.exists(path):
            continue
        raw = fetch(f"https://tech.kakao.com/api/v1/posts/{pid}")
        time.sleep(1)
        if not raw:
            continue
        try:
            d = json.loads(raw)
        except ValueError:
            continue
        rd = (d.get("releaseDate") or "").replace(".", "-")[:10]
        tags = [t.get("name", "") for t in d.get("tags") or []]
        authors = [a.get("name", "") for a in d.get("authors") or []]
        cats = [c.get("code", "") for c in d.get("categories") or []]
        entry = {"id": aid, "site": "kakao", "url": f"https://tech.kakao.com/posts/{pid}", "date": rd,
                 "title": d.get("title", ""), "author": ",".join(authors), "tags": tags + cats}
        md = html_to_md(d.get("content") or "", entry["title"])
        with open(path, "w", encoding="utf-8") as f:
            f.write(md)
        meta[aid] = entry


def collect_daangn(cache, meta):
    seen = set()
    for tag in DAANGN_TAGS:
        raw = fetch(f"https://medium.com/feed/daangn/tagged/{tag}")
        time.sleep(1)
        if not raw:
            continue
        for it in re.findall(r"<item>(.*?)</item>", raw, re.S):
            link = re.search(r"<link>(.*?)</link>", it)
            guid = re.search(r"<guid[^>]*>(.*?)</guid>", it)
            pid = (guid.group(1) if guid else link.group(1)).rstrip("/").split("/")[-1]
            pid = re.sub(r"[^0-9a-zA-Z]", "", pid)[-12:]
            aid = f"daangn-{pid}"
            if aid in seen:
                continue
            seen.add(aid)
            title = re.search(r"<title><!\[CDATA\[(.*?)\]\]></title>", it, re.S)
            pub = re.search(r"<pubDate>(.*?)</pubDate>", it)
            creator = re.search(r"<dc:creator><!\[CDATA\[(.*?)\]\]></dc:creator>", it)
            cats = re.findall(r"<category><!\[CDATA\[(.*?)\]\]></category>", it)
            content = re.search(r"<content:encoded><!\[CDATA\[(.*?)\]\]></content:encoded>", it, re.S)
            date = parsedate_to_datetime(pub.group(1)).strftime("%Y-%m-%d") if pub else ""
            entry = {"id": aid, "site": "daangn", "url": (link.group(1) if link else "").split("?")[0],
                     "date": date, "title": html.unescape(title.group(1)) if title else "",
                     "author": creator.group(1) if creator else "", "tags": cats}
            path = os.path.join(cache, "md", aid + ".md")
            if content and not os.path.exists(path):
                with open(path, "w", encoding="utf-8") as f:
                    f.write(html_to_md(content.group(1), entry["title"]))
            meta[aid] = entry


def cmd_collect(args):
    os.makedirs(os.path.join(args.cache, "md"), exist_ok=True)
    meta_path = os.path.join(args.cache, "meta.json")
    meta = json.load(open(meta_path, encoding="utf-8")) if os.path.exists(meta_path) else {}
    for name, fn in (("daangn", collect_daangn), ("toss", collect_toss), ("kakao", collect_kakao)):
        if args.only and name not in args.only:
            continue
        print(f"[collect] {name} ...", flush=True)
        fn(args.cache, meta)
        with open(meta_path, "w", encoding="utf-8") as f:
            json.dump(meta, f, ensure_ascii=False, indent=1)
        print(f"[collect] {name} done, total {len(meta)}", flush=True)


# ---------------------------------------------------------------- 측정

def tone_group(analysis):
    c = analysis["endings"]["class"]
    hap = c.get("HAPNIDA", 0)
    hae = c.get("HAEYO", 0) + c.get("Q_KKAYO", 0) * 0  # ~할까요?는 양쪽에서 쓰여서 판정에서 뺀다
    pred = hap + hae + c.get("HAERA", 0)
    if pred == 0:
        return "unknown", 0.0
    if hap / pred >= 0.9:
        return "default", round(hap / pred, 3)
    if hae / pred >= 0.9:
        return "casual", round(hae / pred, 3)
    return "mixed", round(max(hap, hae) / pred, 3)


def period(date):
    if date < CUTOFF:
        return "pre2023"
    if date < CASUAL_END:
        return "2023-2024H1"
    if date >= DRIFT_START:
        return "drift"
    return "gap"


def holdout(aid):
    return int(hashlib.sha1(aid.encode()).hexdigest(), 16) % 5 == 0  # 20%


def is_tech(entry):
    if NON_TECH_RE.search(entry.get("title", "")):
        return False
    tags = " ".join(entry.get("tags") or []).lower()
    if entry["site"] == "kakao" and any(t in tags for t in KAKAO_SKIP_TAGS):
        return False
    return True


def cmd_measure(args):
    meta = json.load(open(os.path.join(args.cache, "meta.json"), encoding="utf-8"))
    patterns = L.load_json(L.PATTERNS_PATH)
    rows = []
    per_author = {}
    for aid, e in sorted(meta.items(), key=lambda kv: kv[1].get("date", "")):
        rec = {k: e.get(k) for k in ("id", "site", "url", "date", "title", "author")}
        path = os.path.join(args.cache, "md", aid + ".md")
        if e.get("error") or not os.path.exists(path):
            rec.pop("author", None)
            rec.update(included=False, reason="본문 없음")
            rows.append(rec)
            continue
        text = L.read_text(path)
        a = L.analyze(text, patterns)
        st = a["stats"]
        grp, share = tone_group(a)
        rec.update(chars=st["chars"], sentences=st["sentences"], tone=grp, tone_share=share,
                   period=period(e.get("date") or ""))
        reason = None
        if not is_tech(e):
            reason = "기술 글 아님(채용·행사·인터뷰·팀 소개)"
        elif len(re.findall(r"[가-힣]", text)) < 300:
            reason = "본문 없음(영상·발표 요약, 짧은 공지)"
        elif len(re.findall(r"[가-힣]", text)) < 1000:
            reason = "영어 글이거나 한국어 본문 1,000자 미만"
        elif st["chars"] < 1500 or st["sentences"] < 30:
            reason = "본문 1,500자·30문장 미만"
        elif grp in ("mixed", "unknown"):
            reason = "어투 혼용(한쪽 어투 90% 미만)"
        elif rec["period"] == "gap":
            reason = "측정 기간 밖(2024-07~2024-12)"
        elif grp == "default" and rec["period"] == "2023-2024H1":
            reason = "합니다체 그룹은 2022-11-30 이전 글만 씀"
        if reason is None:
            key = (grp, rec["period"] == "drift", (e.get("author") or "").split(",")[0])
            per_author[key] = per_author.get(key, 0) + 1
            if key[2] and per_author[key] > 2:
                reason = "저자당 2편 초과"
        if reason:
            rec.pop("author", None)
            rec.update(included=False, reason=reason)
            rows.append(rec)
            continue
        rec.pop("author", None)  # 저자 이름은 저장소에 남기지 않는다
        ev_metrics = dict(a["metrics"])
        ev_metrics.update(L.tone_metrics(a, grp))
        rec.update(included=True, group=("drift-" + grp) if rec["period"] == "drift" else grp,
                   holdout=holdout(aid),
                   metrics={k: v["value"] for k, v in ev_metrics.items()},
                   endings=a["endings"]["bucket"])
        rows.append(rec)
    inc = [r for r in rows if r.get("included")]
    summary = {}
    for r in inc:
        summary.setdefault(r["group"], {"n": 0, "holdout": 0, "sites": {}})
        g = summary[r["group"]]
        g["n"] += 1
        g["holdout"] += int(r["holdout"])
        g["sites"][r["site"]] = g["sites"].get(r["site"], 0) + 1
    out = {"schema": 1, "generated_at": time.strftime("%Y-%m-%d"), "lint_schema": L.LINT_SCHEMA,
           "groups": summary, "articles": inc}
    with open(args.out, "w", encoding="utf-8", newline="\n") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    urls = [{k: r.get(k) for k in ("id", "site", "url", "date", "title", "group", "included", "reason", "holdout",
                                    "tone", "tone_share", "chars")} for r in rows]
    with open(args.urls, "w", encoding="utf-8", newline="\n") as f:
        json.dump(urls, f, ensure_ascii=False, indent=1)
    print(json.dumps(summary, ensure_ascii=False, indent=1))
    reasons = {}
    for r in rows:
        if not r.get("included"):
            reasons[r["reason"]] = reasons.get(r["reason"], 0) + 1
    print("제외 사유:", json.dumps(reasons, ensure_ascii=False))


def main():
    L.setup_stdio()
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("collect")
    c.add_argument("--cache", required=True)
    c.add_argument("--only", nargs="*")
    m = sub.add_parser("measure")
    m.add_argument("--cache", required=True)
    m.add_argument("--out", default=os.path.join(ROOT, "dev", "baseline", "stats.json"))
    m.add_argument("--urls", default=os.path.join(ROOT, "dev", "baseline", "urls.json"))
    args = ap.parse_args()
    {"collect": cmd_collect, "measure": cmd_measure}[args.cmd](args)


if __name__ == "__main__":
    main()
