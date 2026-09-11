"""Set up JARVIS from this git checkout, or bring a set-up checkout up to date.

    py install.py          Windows
    python3 install.py     macOS (UNVERIFIED until run on the Mac)

Run it again after every `git pull`: each step checks before it acts, so a run
with nothing to do takes seconds. The design is docs/plans/phase-6-install.md.

Standard library only -- this runs before the venv it creates exists.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

REPO = Path(__file__).resolve().parent
MIN_PYTHON = (3, 11)
# Electron 44's own floor -- its package.json `engines`, and its downloader's.
# Vite accepts older, so Electron is what sets it.
MIN_NODE = (22, 12, 0)
STAMP = ".jarvis-install-stamp"


class StepFailed(Exception):
    """A step that could not finish. The run stops here: carrying on past a
    failure leaves a checkout that looks installed and is not."""

    def __init__(self, message: str, command: list[str] | None = None, output: str = ""):
        super().__init__(message)
        self.message = message
        self.command = command
        self.output = output


@dataclass
class Result:
    returncode: int
    stdout: str
    stderr: str

    @property
    def output(self) -> str:
        return self.stdout + self.stderr


def run(argv: list, *, cwd: Path | None = None, env: dict | None = None) -> Result:
    """The ONE place this script starts a program. The tests replace it.

    `argv[0]` is always a full path from `which`, never a bare name: on
    Windows `npm` is `npm.cmd`, and CreateProcess will not find a bare `npm`.
    """
    proc = subprocess.run([str(a) for a in argv], cwd=cwd, env=env,
                          capture_output=True, text=True,
                          encoding="utf-8", errors="replace")
    return Result(proc.returncode, proc.stdout or "", proc.stderr or "")


def which(name: str) -> str | None:
    """The ONE place this script looks a program up. The tests replace it."""
    return shutil.which(name)


def must(result: Result, argv: list, what: str) -> Result:
    if result.returncode != 0:
        raise StepFailed(what, [str(a) for a in argv], result.output)
    return result


@dataclass
class Context:
    root: Path
    env: dict[str, str]
    python: str = sys.executable
    version: tuple = tuple(sys.version_info[:3])
    tools: dict[str, str] = field(default_factory=dict)


def _version(text: str) -> tuple[int, ...] | None:
    m = re.search(r"(\d+)\.(\d+)(?:\.(\d+))?", text)
    if not m:
        return None
    return tuple(int(x) for x in m.groups() if x is not None)


def _install_hint(what: str) -> str:
    """How to get `what` here -- by the package manager this machine HAS,
    not by the name of its operating system."""
    if what == "claude":
        return "npm install -g @anthropic-ai/claude-code, then run `claude` once to log in"
    if which("winget"):
        return {"python": "winget install Python.Python.3.13",
                "node": "winget install OpenJS.NodeJS.LTS",
                "git": "winget install Git.Git"}[what]
    if which("brew"):
        return {"python": "brew install python@3.13",
                "node": "brew install node",
                "git": "brew install git"}[what]
    return f"install {what} and make sure it is on PATH"


def prerequisites(ctx: Context) -> str:
    """Checked, never installed. Python, Node and npm stop the run; git and
    claude are notes, because nothing this script installs needs them -- git
    is for the next `git pull`, and preflight judges Claude Code at the end."""
    if tuple(ctx.version[:2]) < MIN_PYTHON:
        raise StepFailed(
            f"this is Python {ctx.version[0]}.{ctx.version[1]}; JARVIS needs 3.11 or "
            f"newer. Get one ({_install_hint('python')}) and run install.py with it.")
    for name in ("node", "npm"):
        found = which(name)
        if not found:
            raise StepFailed(f"no `{name}` on PATH. JARVIS needs Node 22.12 or newer: "
                             f"{_install_hint('node')}")
        ctx.tools[name] = found
    argv = [ctx.tools["node"], "--version"]
    said = must(run(argv), argv, "node would not report its version").stdout.strip()
    got = _version(said)
    if got is None or got < MIN_NODE:
        raise StepFailed(f"node is {said or 'unknown'}; Electron 44 needs 22.12 or newer. "
                         f"{_install_hint('node')}")
    lines = [f"Python {'.'.join(map(str, ctx.version))}, node {said}"]
    for name in ("git", "claude"):
        found = which(name)
        if found:
            ctx.tools[name] = found
        else:
            lines.append(f"note: no `{name}` on PATH -- {_install_hint(name)}")
    return "\n".join(lines)
