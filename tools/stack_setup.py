#!/usr/bin/env python3
"""First-run and recurring setup for a machine using this stack.

    stack_setup.py clients                 which agents are installed (JSON)
    stack_setup.py memory-hub [--create]   verify 2FA, find/create the private memory hub,
                                           clone or fast-forward it, and tell every installed
                                           agent where it is
    stack_setup.py review-routes [--current AGENT]
                                           which PR review routes this machine can run
    stack_setup.py update-check [--force] [--mark-applied [SHA]]
                                           rate-limited check for a newer stack `main`

Works with any subset of Codex, Claude, Gemini, and OpenCode: absent agents are skipped. Machine
state lives in `$XDG_STATE_HOME/caphe/` (default `~/.local/state/caphe/`), never in Git.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Callable

Runner = Callable[[list[str]], "tuple[int, str]"]

STACK_REPO = os.environ.get("CAPHE_STACK_REPO", "https://github.com/CaullenOmdahl/CaPhe-Agentic-Stack.git")
HUB_NAME = "agent-memory"
BEGIN = "<!-- CAPHE:MEMORY-HUB:BEGIN -->"
END = "<!-- CAPHE:MEMORY-HUB:END -->"


class SetupError(RuntimeError):
    pass


def default_runner(cmd: list[str]) -> tuple[int, str]:
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return 127, str(exc)
    return out.returncode, (out.stdout or "") + (out.stderr if out.returncode else "")


def home() -> Path:
    return Path.home()


def state_dir() -> Path:
    return Path(os.environ.get("XDG_STATE_HOME", home() / ".local" / "state")) / "caphe"


# ------------------------------------------------------------------ clients


def client_table() -> dict[str, dict[str, Path | str]]:
    h = home()
    return {
        "codex": {"cmd": "codex", "config": h / ".codex", "entry": h / ".codex" / "AGENTS.md"},
        "claude": {"cmd": "claude", "config": h / ".claude", "entry": h / ".claude" / "CLAUDE.md"},
        "gemini": {"cmd": "gemini", "config": h / ".gemini", "entry": h / ".gemini" / "GEMINI.md"},
        "opencode": {"cmd": "opencode", "config": h / ".config" / "opencode",
                     "entry": h / ".config" / "opencode" / "AGENTS.md",
                     "json": h / ".config" / "opencode" / "opencode.json"},
    }


def detect_clients(which: Callable[[str], str | None] | None = None) -> dict[str, dict[str, str]]:
    """Installed agents: the CLI is on PATH or its config directory exists."""
    which = which or shutil.which
    found = {}
    for name, info in client_table().items():
        binary = which(str(info["cmd"]))
        if binary or Path(info["config"]).is_dir():
            found[name] = {"binary": binary or "", "config": str(info["config"]), "entry": str(info["entry"])}
    return found


def memory_block(client: str, hub: Path, runtime: Path | None) -> str:
    lines = [
        BEGIN,
        "## Shared project memory",
        "",
        "Project memory is Git-stored and shared by every agent. At the start of project work run",
        "`caphe-memory list`; to look something up, run `caphe-memory search <terms>`, which searches",
        "this repository, enclosing parent repositories, and the hub together. Follow the",
        "`project-memory` skill.",
        f"Owner memory hub: `{hub}` (global index: `{hub / 'global' / 'MEMORY.md'}`).",
    ]
    if client == "claude":
        lines += ["", f"@{hub / 'global' / 'MEMORY.md'}"]
    if runtime:
        lines += ["", "Stack freshness: at session start run",
                  f"`python3 {runtime / 'tools' / 'stack_setup.py'} update-check` (rate-limited)."]
    return "\n".join(lines + [END])


def upsert_block(path: Path, block: str) -> bool:
    """Insert or replace the marked block; returns True when the file changed."""
    text = path.read_text(encoding="utf-8") if path.is_file() else ""
    if BEGIN in text and END in text:
        start, stop = text.index(BEGIN), text.index(END) + len(END)
        new = text[:start] + block + text[stop:]
    else:
        new = (text.rstrip("\n") + "\n\n" if text.strip() else "") + block + "\n"
    if new == text:
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(new, encoding="utf-8")
    return True


def add_opencode_instruction(config: Path, entry: str) -> str:
    """Add ENTRY to opencode.json `instructions`; JSONC with comments is reported, not rewritten."""
    if not config.is_file():
        return "absent"
    try:
        data = json.loads(config.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return "manual: opencode config is not plain JSON"
    before = json.dumps(data, sort_keys=True)
    instructions = data.get("instructions", [])
    if isinstance(instructions, str):
        instructions = [instructions]
    elif not isinstance(instructions, list):
        instructions = []
    data["instructions"] = instructions
    if entry not in instructions:
        instructions.append(entry)
    # Memory stores sit outside the working directory (parent repositories, the hub); let agents
    # read them without an interactive prompt that stalls unattended runs. Nothing else is widened.
    hub = str(Path(entry).parents[1])
    permission = data.setdefault("permission", {})
    rules = permission.get("external_directory")
    if not isinstance(rules, dict):
        rules = {"*": rules} if isinstance(rules, str) else {}
    rules.setdefault(f"{hub}/*", "allow")
    rules.setdefault("*/.agent/memory/*", "allow")
    permission["external_directory"] = rules
    if json.dumps(data, sort_keys=True) == before:
        return "present"
    tmp = config.with_suffix(".json.caphe-tmp")
    tmp.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, config)
    return "added"


def wire_clients(clients: dict[str, dict[str, str]], hub: Path, runtime: Path | None) -> dict[str, str]:
    results = {}
    table = client_table()
    for name in clients:
        changed = upsert_block(Path(table[name]["entry"]), memory_block(name, hub, runtime))
        results[name] = "updated" if changed else "current"
        if name == "opencode":
            results[name] += "; instructions " + add_opencode_instruction(
                Path(table[name]["json"]), str(hub / "global" / "MEMORY.md"))
    return results


# ------------------------------------------------------------------ memory hub


def verify_account(run: Runner, allow_unverified_2fa: bool) -> str:
    rc, out = run(["gh", "api", "user"])
    if rc != 0:
        raise SetupError("GitHub CLI is not authenticated; run `gh auth login` first")
    user = json.loads(out)
    tfa = user.get("two_factor_authentication")
    if tfa is False:
        raise SetupError("enable two-factor authentication on the GitHub account before storing memory")
    if tfa is None and not allow_unverified_2fa:
        raise SetupError("could not verify two-factor authentication (token lacks `user` scope); "
                         "confirm it is on, then rerun with --allow-unverified-2fa")
    return user["login"]


def hub_visibility(run: Runner, repo: str) -> str | None:
    rc, out = run(["gh", "repo", "view", repo, "--json", "visibility", "-q", ".visibility"])
    return out.strip().upper() if rc == 0 else None


SCAFFOLD = {
    "README.md": "# Agent memory hub\n\nPrivate. Owner-wide and non-repository project memory shared by every\n"
                 "agent. See the stack's `project-memory` skill.\n",
    "projects.json": json.dumps({"paths": {}, "subject_overrides": []}, indent=2) + "\n",
    "global/MEMORY.md": "# Memory Index\n\n<!-- Generated by `caphe-memory index`; edit the memory files, not this index. -->\n",
    "projects/.gitkeep": "",
}


def scaffold(dest: Path) -> list[str]:
    written = []
    for rel, text in SCAFFOLD.items():
        path = dest / rel
        if not path.exists():
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8")
            written.append(rel)
    return written


def ensure_hub(run: Runner, dest: Path, name: str, owner: str | None, create: bool,
               allow_unverified_2fa: bool = False) -> dict[str, str]:
    login = verify_account(run, allow_unverified_2fa)
    repo = f"{owner or login}/{name}"
    visibility = hub_visibility(run, repo)
    created = False
    if visibility is None:
        if not create:
            raise SetupError(f"no memory hub at {repo}; create a PRIVATE repository for it "
                             f"(rerun with --create once the owner agrees)")
        rc, out = run(["gh", "repo", "create", repo, "--private",
                       "--description", "Private agent memory hub"])
        if rc != 0:
            raise SetupError(f"could not create {repo}: {out.strip()}")
        visibility, created = hub_visibility(run, repo), True
    if visibility != "PRIVATE":
        raise SetupError(f"{repo} is {visibility or 'unknown'}; the memory hub must be PRIVATE")
    if (dest / ".git").exists():
        rc, url = run(["git", "-C", str(dest), "remote", "get-url", "origin"])
        if rc != 0 or not url.strip().rstrip("/").removesuffix(".git").endswith(repo):
            raise SetupError(f"{dest} exists but is not a clone of {repo}")
        rc, out = run(["git", "-C", str(dest), "pull", "--ff-only", "-q"])
        action = "fast-forwarded" if rc == 0 else f"pull failed: {out.strip()}"
    else:
        if dest.exists() and any(dest.iterdir()):
            raise SetupError(f"{dest} exists and is not empty; move it aside first")
        rc, out = run(["gh", "repo", "clone", repo, str(dest)])
        if rc != 0:
            raise SetupError(f"clone failed: {out.strip()}")
        action = "cloned"
    added = scaffold(dest)
    if added:  # a new or hand-made empty hub: publish the scaffold so other machines get it
        for cmd in (["git", "-C", str(dest), "add", "-A"],
                    ["git", "-C", str(dest), "commit", "-qm", "Scaffold agent memory hub"],
                    ["git", "-C", str(dest), "push", "-q", "-u", "origin", "HEAD"]):
            rc, out = run(cmd)
            if rc != 0:
                raise SetupError(f"{' '.join(cmd[3:5])} failed: {out.strip()}")
    return {"repo": repo, "path": str(dest), "action": ("created and " if created else "") + action,
            "scaffolded": ", ".join(added) or "none"}


# ------------------------------------------------------------------ review routes

# Local command-line reviewers, their model family, and the review-models.conf key holding
# the pinned review model. Invocations live in the `second-opinion` skill.
REVIEWERS = (
    ("claude", "claude", "anthropic", "STRICT_CONFER_CLAUDE_MODEL"),
    ("agy", "agy", "google", "STRICT_CONFER_AGY_MODEL"),
    ("codex", "codex", "openai", "STRICT_CONFER_CODEX_MODEL"),
    ("opencode", "opencode", "configured-provider", "STRICT_CONFER_OPENCODE_MODEL"),
)
FAMILY = {name: family for name, _, family, _ in REVIEWERS}


def review_models() -> dict[str, str]:
    conf = home() / ".config" / "caphe" / "review-models.conf"
    models = {}
    if conf.is_file():
        for line in conf.read_text().splitlines():
            key, sep, value = line.partition("=")
            if sep and value.strip():
                models[key.strip()] = value.strip()
    return models


def review_routes(run: Runner, which: Callable[[str], str | None] | None = None,
                  current: str | None = None) -> dict:
    """Remote (GitHub) and local CLI review routes available on this machine.

    A local reviewer is independent only when its model family differs from the current agent's.
    OpenCode's family depends on its configured provider, so it is independent of any agent whose
    family differs from that provider's; the caller must confirm which provider it uses.
    """
    which = which or shutil.which
    models = review_models()
    local = []
    for name, cmd, family, key in REVIEWERS:
        binary = which(cmd)
        if not binary:
            continue
        rc, out = run([binary, "--version"])
        local.append({
            "reviewer": name, "binary": binary, "family": family,
            "version": out.strip().splitlines()[0] if rc == 0 and out.strip() else "unknown",
            "model": models.get(key),
            "independent": current is None or FAMILY.get(current) != family,
        })
    gh = which("gh")
    authed = bool(gh) and run(["gh", "auth", "status"])[0] == 0
    return {
        "current": current,
        "remote": {"gh_authenticated": authed,
                   "note": "remote PR reviewers are selected per docs/review-workflow.md"},
        "local": local,
        "guide": "skills/second-opinion/SKILL.md",
    }


# ------------------------------------------------------------------ update check


def load_state() -> dict:
    path = state_dir() / "update-check.json"
    try:
        return json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return {}


def save_state(state: dict) -> None:
    path = state_dir() / "update-check.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, indent=2) + "\n")
    os.replace(tmp, path)


def update_check(run: Runner, now: dt.datetime, interval: dt.timedelta, force: bool) -> dict:
    state = load_state()
    last = state.get("last_check")
    if not force and last and now - dt.datetime.fromisoformat(last) < interval:
        state["checked"] = False
    else:
        rc, out = run(["git", "ls-remote", STACK_REPO, "refs/heads/main"])
        if rc != 0 or not out.strip():
            raise SetupError("could not reach the stack repository; will retry next session")
        state.update(last_check=now.isoformat(timespec="seconds"), remote_main=out.split()[0])
        state.pop("checked", None)
        save_state(state)
        state["checked"] = True
    applied, remote = state.get("applied"), state.get("remote_main")
    state["update_available"] = bool(remote) and remote != applied
    return state


def mark_applied(sha: str | None) -> dict:
    state = load_state()
    state["applied"] = sha or state.get("remote_main")
    if not state["applied"]:
        raise SetupError("nothing to mark: run update-check first or pass a SHA")
    save_state(state)
    return state


# ------------------------------------------------------------------ CLI


def main(argv: list[str] | None = None, run: Runner = default_runner) -> int:
    parser = argparse.ArgumentParser(prog="stack_setup.py", description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("clients")
    p = sub.add_parser("memory-hub")
    p.add_argument("--create", action="store_true")
    p.add_argument("--owner")
    p.add_argument("--name", default=HUB_NAME)
    p.add_argument("--dest", default=str(home() / HUB_NAME))
    p.add_argument("--runtime", default=str(Path(__file__).resolve().parents[1]))
    p.add_argument("--allow-unverified-2fa", action="store_true")
    p = sub.add_parser("review-routes")
    p.add_argument("--current", choices=sorted(FAMILY), help="the agent asking, to judge independence")
    p = sub.add_parser("update-check")
    p.add_argument("--force", action="store_true")
    p.add_argument("--interval-days", type=float, default=2.0)
    p.add_argument("--mark-applied", nargs="?", const="", metavar="SHA")
    args = parser.parse_args(argv)
    try:
        if args.cmd == "clients":
            result: dict = detect_clients()
        elif args.cmd == "memory-hub":
            dest = Path(args.dest).expanduser().resolve()
            result = ensure_hub(run, dest, args.name, args.owner, args.create, args.allow_unverified_2fa)
            result["clients"] = wire_clients(detect_clients(), dest, Path(args.runtime))
        elif args.cmd == "review-routes":
            result = review_routes(run, current=args.current)
        elif args.mark_applied is not None:
            result = mark_applied(args.mark_applied or None)
        else:
            result = update_check(run, dt.datetime.now(dt.timezone.utc),
                                  dt.timedelta(days=args.interval_days), args.force)
    except SetupError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
