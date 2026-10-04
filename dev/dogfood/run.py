#!/usr/bin/env python3
"""설치된 techblog 스킬을 headless Claude Code(`claude -p`)로 실행해 dogfooding 결과를 모은다.

- 사용자 ~/.claude/CLAUDE.md와 auto memory를 끄고 실행한다(CLAUDE_CODE_DISABLE_CLAUDE_MDS=1).
  그래야 다른 사용자가 스킬만 설치했을 때와 같은 조건이 된다.
- 자료 파일은 실행 폴더에 복사한다. 원본 폴더를 --add-dir로 열지 않는다.
- 결과: <work>/<iter>/<case>/ 아래 article.md, 작업 파일, run.jsonl(stream-json), run.err, meta.json

사용법
  python dev/dogfood/run.py --cases dev/dogfood/cases.json --iter iter-1 [--only A B] [--jobs 2]
"""

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DEFAULT_WORK = os.path.join(os.environ.get("TEMP", "/tmp"), "techblog-work", "dogfood")
BASELINE_PROMPT = ("{src} 자료의 핵심 내용을 한국어 기술 블로그 아티클로 정리해서 article.md 파일로 저장해줘. "
                   "어투는 {tone_ko}로 써줘.")


def build(case, run_dir):
    """케이스 설정으로 프롬프트와 추가 CLI 인자를 만든다."""
    src = case.get("source")
    if src and not src.startswith(("http://", "https://")):
        src = src.replace("{work}", os.path.dirname(os.path.dirname(os.path.dirname(run_dir)))).replace("{root}", ROOT)
        if not os.path.isabs(src):
            src = os.path.join(ROOT, src)
    src_arg = src
    if src and not src.startswith(("http://", "https://")):
        name = "input" + os.path.splitext(src)[1]
        shutil.copyfile(src, os.path.join(run_dir, name))
        src_arg = "./" + name
    tone = case.get("tone", "default")
    extra = []
    if case.get("mode") == "baseline":
        prompt = BASELINE_PROMPT.format(src=src_arg, tone_ko="해요체" if tone == "casual" else "합니다체")
        extra.append("--disable-slash-commands")
    elif case.get("mode") == "retone":
        prompt = f"/techblog {tone} --retone {src_arg} -o article.md"
    elif case.get("mode") == "pasted":
        with open(src, encoding="utf-8-sig") as f:
            text = f.read()
        prompt = f"/techblog {tone} -o article.md --keep-work\n\n{text}"
        os.remove(os.path.join(run_dir, "input" + os.path.splitext(src)[1]))
    else:
        prompt = f"/techblog {tone} {src_arg} -o article.md --keep-work"
    return prompt, extra


def run_case(case, iter_dir, model, effort, budget, timeout):
    run_dir = os.path.join(iter_dir, case["name"])
    if os.path.isdir(run_dir):
        shutil.rmtree(run_dir)
    os.makedirs(run_dir)
    prompt, extra = build(case, run_dir)
    cmd = [shutil.which("claude") or "claude", "-p", prompt,
           "--model", case.get("model", model), "--effort", case.get("effort", effort),
           "--output-format", "stream-json", "--verbose", "--no-session-persistence", "--strict-mcp-config",
           "--permission-mode", "acceptEdits", "--max-budget-usd", str(budget)] + extra
    env = dict(os.environ)
    env.update({"CLAUDE_CODE_DISABLE_CLAUDE_MDS": "1", "CLAUDE_CODE_DISABLE_AUTO_MEMORY": "1"})
    env.pop("PYTHONUTF8", None)
    t0 = time.time()
    with open(os.path.join(run_dir, "run.jsonl"), "wb") as out, open(os.path.join(run_dir, "run.err"), "wb") as err:
        try:
            p = subprocess.run(cmd, cwd=run_dir, env=env, stdin=subprocess.DEVNULL, stdout=out, stderr=err,
                               timeout=timeout)
            code = p.returncode
        except subprocess.TimeoutExpired:
            code = "timeout"
    meta = {"case": case, "prompt": prompt, "cmd": cmd[3:], "exit": code, "seconds": round(time.time() - t0),
            "claude_version": subprocess.run([cmd[0], "--version"], capture_output=True, text=True).stdout.strip()}
    with open(os.path.join(run_dir, "meta.json"), "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=1)
    print(f"[{case['name']}] exit={code} {meta['seconds']}s", flush=True)
    return meta


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except AttributeError:
        pass
    ap = argparse.ArgumentParser()
    ap.add_argument("--cases", default=os.path.join(ROOT, "dev", "dogfood", "cases.json"))
    ap.add_argument("--iter", required=True)
    ap.add_argument("--only", nargs="*")
    ap.add_argument("--work", default=DEFAULT_WORK)
    ap.add_argument("--jobs", type=int, default=2)
    ap.add_argument("--model", default="opus")
    ap.add_argument("--effort", default="xhigh")
    ap.add_argument("--budget", type=float, default=8.0)
    ap.add_argument("--timeout", type=int, default=45 * 60)
    args = ap.parse_args()
    with open(args.cases, encoding="utf-8") as f:
        cases = json.load(f)["cases"]
    if args.only:
        cases = [c for c in cases if c["name"] in args.only]
    iter_dir = os.path.join(args.work, args.iter)
    os.makedirs(iter_dir, exist_ok=True)
    with ThreadPoolExecutor(max_workers=args.jobs) as ex:
        list(ex.map(lambda c: run_case(c, iter_dir, args.model, args.effort, args.budget, args.timeout), cases))


if __name__ == "__main__":
    main()
