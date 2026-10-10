#!/usr/bin/env python3
"""Run a real Codex smoke case in an isolated installation (Python 3.8+, stdlib).

Uses the existing Codex login, but keeps config, plugin cache, and output in --work.
Does not install into the user's skill folders or modify the original login/config.
Model calls consume the signed-in account's usage. Never run as a unit test.
"""

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import signal
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
CASES = ("default", "casual", "retone-casual", "retone-default", "url", "pdf", "cleanup")
WORK_SUFFIXES = (".facts.md", ".draft.md", ".unrevised.md", ".repeats.md")


def note_text():
    prompt = (ROOT / "evals/note-default/prompt.md").read_text(encoding="utf-8")
    return "# Migrating" + prompt.split("\n# Migrating", 1)[1]


def prepare_case(project, case, source=None, skill_mention="$techblog"):
    """Return the user prompt and source paths whose contents must stay unchanged."""
    keep = "" if case == "cleanup" or case.startswith("retone-") else " --keep-work"
    tone = "casual" if case in ("casual", "retone-casual") else "default"
    prefix = "{} {} -o article.md{}".format(skill_mention, tone, keep)
    if case.startswith("retone-"):
        example = "paged-attention.{}.md".format("default" if tone == "casual" else "casual")
        original = Path(source) if source else ROOT / "examples" / example
        dest = project / "input.md"
        shutil.copyfile(original, dest)
        return prefix + " --retone input.md", [dest]
    if case == "pdf":
        if not source:
            raise ValueError("--source <local.pdf> is required for the pdf case")
        dest = project / "input.pdf"
        shutil.copyfile(source, dest)
        return prefix + " input.pdf", [dest]
    if case == "url":
        return prefix + " " + (source or "https://peps.python.org/pep-0659/"), []
    if case == "casual":
        return prefix + "\n\n" + note_text(), []
    dest = project / "input.md"
    dest.write_text(note_text(), encoding="utf-8")
    return prefix + " input.md", [dest]


def stage_package(destination):
    destination.mkdir()
    for name in ("plugin.json", ".codex-plugin", ".claude-plugin", ".agents", "skills", "LICENSE"):
        src = ROOT / name
        if src.is_dir():
            shutil.copytree(src, destination / name, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
        else:
            shutil.copyfile(src, destination / name)


def run_logged(cmd, cwd, env, log, timeout, prompt=None):
    started = time.monotonic()
    with log.open("w", encoding="utf-8") as out, log.with_suffix(".err").open("w", encoding="utf-8") as err:
        proc = subprocess.Popen(cmd, cwd=str(cwd), env=env, stdin=subprocess.PIPE,
                                stdout=out, stderr=err, text=True, encoding="utf-8",
                                start_new_session=os.name != "nt")
        try:
            proc.communicate(prompt, timeout=timeout)
            code = proc.returncode
        except subprocess.TimeoutExpired:
            if os.name == "nt":
                proc.kill()
            else:
                os.killpg(proc.pid, signal.SIGTERM)
            try:
                proc.communicate(timeout=10)
            except subprocess.TimeoutExpired:
                if os.name == "nt":
                    proc.kill()
                else:
                    os.killpg(proc.pid, signal.SIGKILL)
                proc.communicate()
            code = "timeout"
    return {"exit": code, "seconds": round(time.monotonic() - started, 1)}


def command_events(path):
    """Codex exec JSONL emits command items; prefer completed items to avoid duplicates."""
    commands = []
    with path.open(encoding="utf-8") as stream:
        for line in stream:
            try:
                event = json.loads(line)
            except ValueError:
                continue
            item = event.get("item", {})
            if event.get("type") == "item.completed" and item.get("type") == "command_execution":
                commands.append({"command": item.get("command", ""), "exit_code": item.get("exit_code")})
    return commands


def skill_load_errors(log, stderr):
    """Read runtime diagnostics, not quoted warnings in prompts or agent messages.

    Codex 0.162.1 emits non-fatal warnings as item.completed / error in JSONL.
    A successful process or article therefore does not prove an intact skill load.
    """
    messages = []
    for line in log.read_text(encoding="utf-8").splitlines():
        try:
            event = json.loads(line)
        except ValueError:
            continue
        item = event.get("item", {})
        if event.get("type") == "item.completed" and item.get("type") == "error":
            messages.append(item.get("message", ""))
        elif event.get("type") in ("error", "warning"):
            messages.append(event.get("message", ""))
    if stderr.is_file():
        messages.extend(stderr.read_text(encoding="utf-8").splitlines())
    pattern = re.compile(r"Skill `[^`]+` exceeded the main prompt context limit and was truncated\."
                         r"|Failed to load skill[^\r\n]*")
    return list(dict.fromkeys(match.group(0) for message in messages
                             for match in pattern.finditer(message)))


def installed_skill(project, profile, installation):
    if installation == "direct":
        path = project / ".agents/skills/techblog/SKILL.md"
        if not path.is_file():
            raise RuntimeError("Direct skill was not installed")
        return path
    candidates = list((profile / "plugins/cache/skill-techblog").rglob("skills/techblog/SKILL.md"))
    if len(candidates) != 1:
        raise RuntimeError("Expected one installed plugin skill, found {}".format(len(candidates)))
    return candidates[0]


def link_auth(auth, destination):
    """Reference existing auth without copying its contents into test artifacts."""
    try:
        destination.symlink_to(auth.resolve())
        return "symlink"
    except OSError as error:
        if getattr(error, "winerror", None) != 1314:
            raise
        # Windows can deny symlinks to non-admin users. A same-volume hard link
        # needs no elevation and is removed by the same finally block below.
        os.link(str(auth.resolve()), str(destination))
        return "hardlink"


def command_basename(word):
    return word.replace("\\", "/").rsplit("/", 1)[-1]


def checker_invocations(command):
    """Extract Python checker calls, excluding commands that merely read script files."""
    try:
        words = shlex.split(command)
        if words and command_basename(words[0]).lower() in (
                "sh", "bash", "zsh", "powershell", "powershell.exe", "pwsh", "pwsh.exe"):
            for i, word in enumerate(words[1:], 1):
                if word.lower() in ("-c", "-lc", "-command") and i + 1 < len(words):
                    return checker_invocations(" ".join(words[i + 1:]))
        lexer = shlex.shlex(command, posix=True, punctuation_chars=";&|")
        lexer.whitespace_split = True
        words = list(lexer)
    except ValueError:
        return []
    calls = []
    for i, word in enumerate(words[1:], 1):
        name = command_basename(word)
        if name in ("lint_ko.py", "revise_ko.py", "tone_check.py") and re.fullmatch(
                r"python(?:\d+(?:\.\d+)*)?(?:\.exe)?", command_basename(words[i - 1])):
            calls.append({"script": name, "action": words[i + 1] if i + 1 < len(words) else ""})
    return calls


def inspect_output(project, case, commands, hashes):
    """Re-run the deterministic checkers; leave semantic source review to the reviewer."""
    scripts = ROOT / "skills/techblog/scripts"
    sys.path.insert(0, str(scripts))
    import lint_ko as lint
    import revise_ko as revise
    import tone_check as tone_check

    result = {"source_unchanged": all(Path(p).is_file() and hashlib.sha256(Path(p).read_bytes()).hexdigest() == h
                                      for p, h in hashes.items())}
    article = project / "article.md"
    result["article_exists"] = article.is_file() and article.stat().st_size > 0
    if not result["article_exists"]:
        return result
    tone = "casual" if case in ("casual", "retone-casual") else "default"
    facts = project / "article.facts.md"
    cmd = [sys.executable, str(scripts / "lint_ko.py"), str(article), "--tone", tone, "--json"]
    if facts.is_file():
        cmd.extend(["--facts", str(facts)])
    checked = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8")
    result["lint"] = json.loads(checked.stdout)
    if case.startswith("retone-") or case == "casual":
        original = project / ("input.md" if case.startswith("retone-") else "article.draft.md")
        if original.exists():
            default, casual = (original, article) if tone == "casual" else (article, original)
            result["tone"] = tone_check.check(lint.read_text(str(default)), lint.read_text(str(casual)))
    snapshot = project / "article.unrevised.md"
    target = project / ("article.draft.md" if tone == "casual" else "article.md")
    if snapshot.exists() and target.exists():
        result["revision"] = revise.compare(lint.read_text(str(snapshot)), lint.read_text(str(target)),
                                              lint.read_text(str(facts)) if facts.exists() else None)
    present = [s for s in WORK_SUFFIXES if (project / ("article" + s)).exists()]
    result["work_files"] = present
    result["work_files_ok"] = (not present if case == "cleanup" or case.startswith("retone-") else
                               all(s in present for s in WORK_SUFFIXES if s != ".draft.md" or tone == "casual"))
    result["checker_commands"] = [c for c in commands if checker_invocations(c["command"])]
    successful = [call for c in commands if c.get("exit_code") == 0
                  for call in checker_invocations(c["command"])]
    required = [("lint_ko.py", None)]
    if case.startswith("retone-") or case == "casual":
        required.append(("tone_check.py", None))
    if not case.startswith("retone-"):
        required.extend([("revise_ko.py", "start"), ("revise_ko.py", "check")])
    if case == "cleanup":
        required.append(("tone_check.py", "--cleanup"))
    result["checkers_ran"] = all(any(c["script"] == name and (action is None or c["action"] == action)
                                      for c in successful) for name, action in required)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--installation", choices=("direct", "plugin"), required=True)
    parser.add_argument("--case", choices=CASES, required=True)
    parser.add_argument("--work", type=Path, required=True, help="New directory; existing paths are never overwritten")
    parser.add_argument("--source", help="PDF file, retone article, or public URL override")
    parser.add_argument("--timeout", type=int, default=1800)
    parser.add_argument("--direct-revision", action="store_true", help="Request revision without delegating to a subagent")
    parser.add_argument("--windows-sandbox", choices=("mxc", "elevated", "unelevated"),
                        help="Native Windows sandbox implementation; workspace-write permissions stay enabled")
    args = parser.parse_args()
    codex = shutil.which("codex")
    if not codex:
        parser.error("codex is not installed")
    if args.work.exists():
        parser.error("--work must be a new directory")
    if args.case == "pdf" and not args.source:
        parser.error("pdf requires --source")
    work = args.work.resolve()
    project = work / "작업 폴더"
    profile = work / "codex-profile"
    project.mkdir(parents=True)
    profile.mkdir()
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    auth = Path(env.get("CODEX_HOME", str(Path.home() / ".codex"))) / "auth.json"
    env["CODEX_HOME"] = str(profile)
    try:
        auth_link_kind = link_auth(auth, profile / "auth.json") if auth.exists() else None
        if args.installation == "direct":
            shutil.copytree(ROOT / "skills/techblog", project / ".agents/skills/techblog",
                            ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
        else:
            package = work / "package"
            stage_package(package)
            for label, command in (
                ("marketplace", [codex, "plugin", "marketplace", "add", str(package), "--json"]),
                ("install", [codex, "plugin", "add", "techblog@skill-techblog", "--json"]),
            ):
                outcome = run_logged(command, project, env, work / (label + ".jsonl"), 120)
                if outcome["exit"] != 0:
                    raise RuntimeError("{} failed; see {}".format(label, work / (label + ".err")))
        skill = installed_skill(project, profile, args.installation).resolve()
        skill_name = "techblog:techblog" if args.installation == "plugin" else "techblog"
        # A linked mention selects the installed skill by path before model inference.
        mention = "[${}]({})".format(skill_name, skill.as_posix())
        prompt, originals = prepare_case(project, args.case, args.source, mention)
        if args.direct_revision:
            prompt += "\n이번 실행에서는 subagent를 사용하지 말고 runtime.md의 직접 후처리 절차를 수행해줘."
        hashes = {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in originals}
        (work / "prompt.txt").write_text(prompt, encoding="utf-8")
        cmd = [codex, "--no-daemon", "-a", "never", "--search", "exec", "--sandbox", "workspace-write",
               "--skip-git-repo-check", "--ephemeral", "--json", "-C", str(project), "-"]
        if args.windows_sandbox:
            cmd[1:1] = ["-c", "windows.sandbox=" + args.windows_sandbox]
        print("Running {} / {} in {}".format(args.installation, args.case, work), flush=True)
        outcome = run_logged(cmd, project, env, work / "run.jsonl", args.timeout, prompt)
        meta = dict(outcome, installation=args.installation, case=args.case,
                    direct_revision=args.direct_revision, auth_link_kind=auth_link_kind,
                    codex_version=subprocess.check_output([codex, "--version"], text=True, encoding="utf-8").strip(),
                    command=cmd, source_hashes=hashes, skill_name=skill_name, skill_path=str(skill),
                    skill_bytes=skill.stat().st_size,
                    skill_sha256=hashlib.sha256(skill.read_bytes()).hexdigest())
        (work / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
        evaluation = inspect_output(project, args.case, command_events(work / "run.jsonl"), hashes)
        evaluation["skill_load_errors"] = skill_load_errors(work / "run.jsonl", work / "run.err")
        (work / "eval.json").write_text(json.dumps(evaluation, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps({"run": outcome, "article": evaluation["article_exists"],
                          "lint": evaluation.get("lint", {}).get("summary"),
                          "source_unchanged": evaluation["source_unchanged"],
                          "skill_load_errors": evaluation["skill_load_errors"],
                          "work_files_ok": evaluation.get("work_files_ok")}, ensure_ascii=False))
        # Quality findings remain in eval.json; a successful process alone is not a passing case.
        ok = outcome["exit"] == 0 and evaluation["article_exists"] and evaluation["source_unchanged"]
        ok = ok and not evaluation["skill_load_errors"]
        ok = ok and evaluation.get("work_files_ok", False)
        ok = ok and evaluation.get("checkers_ran", False)
        ok = ok and not evaluation.get("revision", {}).get("must_fix", False)
        if evaluation.get("tone"):
            ok = ok and not any(i["level"] == "FAIL" for i in evaluation["tone"]["issues"])
        if not args.case.startswith("retone-"):
            summary = evaluation.get("lint", {}).get("summary", {})
            ok = ok and summary.get("gate_fail") == 0 and summary.get("fail") == 0
        return 0 if ok else 1
    finally:
        # Leave reports and installed files for inspection, but no link to the user's login.
        (profile / "auth.json").unlink(missing_ok=True)


if __name__ == "__main__":
    sys.exit(main())
