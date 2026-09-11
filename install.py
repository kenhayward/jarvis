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

# The one definition of a .env line -- the server's own, not a copy.
from env_file import parse_env_lines

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


REQUIREMENTS = ("requirements.txt", "requirements-piper.txt", "requirements-stt.txt")


def venv_python(root: Path) -> Path | None:
    """The venv's interpreter under EITHER platform's name -- both tried,
    never chosen by platform (electron/python.js follows the same rule)."""
    for rel in (Path(".venv", "Scripts", "python.exe"), Path(".venv", "bin", "python")):
        candidate = root / rel
        if candidate.is_file():
            return candidate
    return None


def _digest(files: list[Path]) -> str:
    h = hashlib.sha256()
    for f in files:
        h.update(f.name.encode("utf-8") + b"\0" + f.read_bytes() + b"\0")
    return h.hexdigest()


def _is_current(target: Path, digest: str) -> bool:
    """Whether `target` was last built from inputs with this digest. The stamp
    lives INSIDE the thing it describes: delete the venv, or node_modules, and
    the stamp goes with it rather than vouching for something that is gone."""
    try:
        return (target / STAMP).read_text(encoding="utf-8").strip() == digest
    except OSError:
        return False


def _stamp(target: Path, digest: str) -> None:
    target.mkdir(parents=True, exist_ok=True)
    (target / STAMP).write_text(digest + "\n", encoding="utf-8")


def venv(ctx: Context) -> str:
    found = venv_python(ctx.root)
    if found is None:
        argv = [ctx.python, "-m", "venv", str(ctx.root / ".venv")]
        must(run(argv, cwd=ctx.root), argv, "could not create .venv")
        found = venv_python(ctx.root)
        if found is None:
            raise StepFailed("created .venv, but found no interpreter inside it")
        return f"created .venv ({found})"
    argv = [str(found), "-c", "import sys; print('%d.%d' % sys.version_info[:2])"]
    said = must(run(argv), argv, "the existing .venv's Python would not run").stdout.strip()
    got = _version(said)
    if got is None or got[:2] < MIN_PYTHON:
        raise StepFailed(f"the existing .venv is Python {said or 'unknown'}; JARVIS needs "
                         f"3.11 or newer. Delete .venv and run install.py again.")
    return f"skipped: .venv already exists (Python {said})"


def python_packages(ctx: Context) -> str:
    """All three requirements files: the voice and the ear are optional for a
    Chrome JARVIS, but the desktop application is what this sets up."""
    exe = venv_python(ctx.root)
    digest = _digest([ctx.root / name for name in REQUIREMENTS])
    target = ctx.root / ".venv"
    if _is_current(target, digest):
        return "skipped: requirements unchanged since the last install"
    argv = [str(exe), "-m", "pip", "install"]
    for name in REQUIREMENTS:
        argv += ["-r", name]
    must(run(argv, cwd=ctx.root), argv, "pip could not install the requirements")
    _stamp(target, digest)
    return "installed " + ", ".join(REQUIREMENTS)


def playwright(ctx: Context) -> str:
    """Always run: Playwright's own installer skips a browser it already has,
    which beats guessing where it keeps them (PLAYWRIGHT_BROWSERS_PATH moves
    them). The fresh-clone run in Task 12 times it."""
    argv = [str(venv_python(ctx.root)), "-m", "playwright", "install", "chromium"]
    must(run(argv, cwd=ctx.root), argv, "Playwright could not install Chromium")
    return "Chromium ready"


ENV_BLOCK_HEAD = "# --- added by install.py: what the desktop application needs on this machine ---"


def env_path(ctx: Context) -> Path:
    """JARVIS_ENV_FILE if set, else the repository's .env -- the server's rule."""
    override = ctx.env.get("JARVIS_ENV_FILE", "").strip()
    return Path(override) if override else ctx.root / ".env"


def _merge_env(process: dict[str, str], dotenv_text: str) -> dict[str, str]:
    """server.py's loader: `os.environ.setdefault` per line, so the process
    environment wins and, within the file, the first occurrence does."""
    merged = dict(process)
    for key, value in parse_env_lines(dotenv_text):
        merged.setdefault(key, value)
    return merged


def effective_env(ctx: Context) -> dict[str, str]:
    """The environment the SERVER will run with."""
    path = env_path(ctx)
    text = path.read_text(encoding="utf-8") if path.exists() else ""
    return _merge_env(ctx.env, text)


def env_problems(env: dict[str, str], have_say: bool) -> list[str]:
    """What in this configuration leaves the desktop application deaf or mute
    here, each with the line that fixes it."""
    out = []
    stt = (env.get("JARVIS_STT_BACKEND") or "browser").strip().lower()
    if stt != "whisper":
        out.append(f"JARVIS_STT_BACKEND is {stt!r}: the desktop application will hear "
                   f"nothing (Electron has no speech service). Add: JARVIS_STT_BACKEND=whisper")
    tts = (env.get("JARVIS_TTS_BACKEND") or "say").strip().lower()
    if tts == "fish" and not env.get("FISH_API_KEY", "").strip():
        tts = "say"                     # tts.py falls back to `say` without a key
    if tts not in ("piper", "fish") and not have_say:
        out.append(f"JARVIS_TTS_BACKEND is {tts!r} and there is no `say` on this machine: "
                   f"JARVIS will not speak. Add: JARVIS_TTS_BACKEND=piper")
    return out


def dotenv(ctx: Context) -> str:
    """Create a missing .env; NEVER modify an existing one. A program that
    rewrites configuration behind you is harder to trust than one that
    explains (phase 5's rule)."""
    path = env_path(ctx)
    have_say = which("say") is not None
    if path.exists():
        problems = env_problems(effective_env(ctx), have_say)
        if not problems:
            return f"kept {path}; nothing in it stops the application hearing or speaking"
        return f"kept {path} unchanged -- but:\n" + "\n".join(f"  {p}" for p in problems)
    block = ["", ENV_BLOCK_HEAD,
             "# Electron has no speech service: the browser's recogniser hears nothing there.",
             "JARVIS_STT_BACKEND=whisper"]
    if not have_say:
        block += ["# There is no `say` on this machine, so the default voice would be silence.",
                  "JARVIS_TTS_BACKEND=piper"]
    example = (ctx.root / ".env.example").read_text(encoding="utf-8")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(example.rstrip("\n") + "\n" + "\n".join(block) + "\n", encoding="utf-8")
    # Judged as the server will read it: the FIRST occurrence of a key wins,
    # and the block is appended -- a live line in the example would override
    # it and leave a .env that looks right and is deaf.
    still = env_problems(effective_env(ctx), have_say)
    if still:
        raise StepFailed(f"created {path}, but a line in .env.example overrides what it "
                         f"added:\n  " + "\n  ".join(still))
    added = [line for line in block if line and not line.startswith("#")]
    return f"created {path} from .env.example, adding " + ", ".join(added)


# Asked of JARVIS itself, through the venv: "present" means what the server
# will find, not what this script believes. One JSON line, printed last, so
# anything a module logs at import time cannot be mistaken for the answer.
PROBE_MODELS = (
    "import json, data_paths, stt, tts\n"
    "print(json.dumps({'voice': tts.resolve_piper_voice(),"
    " 'voice_present': tts.piper_model_path() is not None,"
    " 'voices_dir': str(data_paths.voices_dir()),"
    " 'stt_model': stt.resolve_model(),"
    " 'stt_present': stt.model_is_cached()}))"
)
# The model name arrives as an ARGUMENT, never spliced into the code.
FETCH_WHISPER = (
    "import sys\n"
    "from faster_whisper import WhisperModel\n"
    "WhisperModel(sys.argv[1], device='cpu', compute_type='int8')"
)


def _probe_models(ctx: Context, exe: Path, env: dict[str, str]) -> dict:
    argv = [str(exe), "-c", PROBE_MODELS]
    result = must(run(argv, cwd=ctx.root, env=env), argv,
                  "could not ask JARVIS which models it will load")
    return json.loads(result.stdout.strip().splitlines()[-1])


def models(ctx: Context) -> str:
    exe = venv_python(ctx.root)
    env = effective_env(ctx)
    found = _probe_models(ctx, exe, env)
    fetched = []
    if not found["voice_present"]:
        voice = found["voice"]
        if "/" in voice or "\\" in voice or voice.endswith(".onnx"):
            raise StepFailed(f"JARVIS_PIPER_VOICE names a file that does not exist: {voice}")
        Path(found["voices_dir"]).mkdir(parents=True, exist_ok=True)
        argv = [str(exe), "-m", "piper.download_voices", "--download-dir",
                found["voices_dir"], voice]
        must(run(argv, cwd=ctx.root, env=env), argv, f"could not download the piper voice {voice}")
        fetched.append(f"voice {voice}")
    if not found["stt_present"]:
        argv = [str(exe), "-c", FETCH_WHISPER, found["stt_model"]]
        must(run(argv, cwd=ctx.root, env=env), argv,
             f"could not fetch the whisper model {found['stt_model']}")
        fetched.append(f"whisper {found['stt_model']}")
    if not fetched:
        return f"skipped: voice {found['voice']} and whisper {found['stt_model']} already present"
    again = _probe_models(ctx, exe, env)
    missing = [name for name, key in (("the voice", "voice_present"), ("the whisper model", "stt_present"))
               if not again[key]]
    if missing:
        raise StepFailed("downloaded, but JARVIS still cannot find " + " or ".join(missing))
    return "downloaded " + ", ".join(fetched)


# What npm reports when Windows will not let it delete a file that is in use.
# Measured 2026-09-11 with the application running from this checkout: `npm
# ci` in electron/ failed with EPERM (syscall unlink, errno -4048) on a DLL in
# node_modules/electron/dist -- AFTER deleting whatever it could, so the tree
# is left broken until npm ci runs again with JARVIS quit. EBUSY is the other
# code Windows gives for the same condition.
BUSY_MARKERS = ("EBUSY", "EPERM")


def _npm_ci(ctx: Context, where: Path) -> bool:
    """`npm ci` by the lockfile, skipped when the lockfile is what the last
    successful install used. Returns whether it installed."""
    digest = _digest([where / "package-lock.json"])
    modules = where / "node_modules"
    if _is_current(modules, digest):
        return False
    argv = [ctx.tools["npm"], "ci"]
    result = run(argv, cwd=where)
    if result.returncode != 0:
        if any(marker in result.output for marker in BUSY_MARKERS):
            raise StepFailed(f"npm could not replace {where.name}/node_modules -- something in it "
                             f"is in use. If JARVIS is running, quit it from the tray and run "
                             f"install.py again.", [str(a) for a in argv], result.output)
        raise StepFailed(f"npm ci failed in {where.name}/", [str(a) for a in argv], result.output)
    _stamp(modules, digest)
    return True


def frontend(ctx: Context) -> str:
    """The application loads the page the server serves out of frontend/dist.
    The build always runs: a pull can change the source without the lockfile."""
    where = ctx.root / "frontend"
    installed = _npm_ci(ctx, where)
    argv = [ctx.tools["npm"], "run", "build"]
    must(run(argv, cwd=where), argv, "the frontend build failed")
    return ("installed dependencies and " if installed else "dependencies unchanged; ") + "built frontend/dist"


def electron_exe(root: Path) -> Path | None:
    """The unpacked Electron binary, found the way Electron finds it: through
    the path.txt its installer writes (electron/index.js)."""
    package = root / "electron" / "node_modules" / "electron"
    try:
        relative = (package / "path.txt").read_text(encoding="utf-8").strip()
    except OSError:
        return None
    exe = package / "dist" / relative
    return exe if relative and exe.exists() else None


def electron(ctx: Context) -> str:
    """`npm ci` does not unpack the binary (found in phase 5); install.js does."""
    where = ctx.root / "electron"
    installed = _npm_ci(ctx, where)
    unpacked = False
    if electron_exe(ctx.root) is None:
        argv = [ctx.tools["node"], str(Path("node_modules", "electron", "install.js"))]
        must(run(argv, cwd=where), argv, "could not unpack the Electron binary")
        if electron_exe(ctx.root) is None:
            raise StepFailed("Electron's installer ran but left no binary")
        unpacked = True
    parts = ["installed dependencies" if installed else "dependencies unchanged",
             "unpacked the binary" if unpacked else "binary present"]
    return "; ".join(parts)


# Every path arrives as an environment variable. None is ever part of this
# text: phase 3 found a launcher whose quoting had never worked, because a
# shell re-parsed a path it was handed inside a command line.
SHORTCUT_PS1 = (
    "$ErrorActionPreference = 'Stop'\n"
    "$s = (New-Object -ComObject WScript.Shell).CreateShortcut($env:JARVIS_LNK)\n"
    "$s.TargetPath = $env:JARVIS_TARGET\n"
    "$s.Arguments = '\"' + $env:JARVIS_APP + '\"'\n"
    "$s.WorkingDirectory = $env:JARVIS_APP\n"
    "$s.IconLocation = $env:JARVIS_ICON\n"
    "$s.Description = 'JARVIS'\n"
    "$s.Save()\n"
)


def start_menu(ctx: Context) -> Path | None:
    """The per-user Start-menu Programs folder, if this machine has one --
    asked of the machine rather than of its operating system's name."""
    appdata = ctx.env.get("APPDATA", "").strip()
    if not appdata:
        return None
    programs = Path(appdata) / "Microsoft" / "Windows" / "Start Menu" / "Programs"
    return programs if programs.is_dir() else None


def shortcut(ctx: Context) -> str:
    """Rewritten on every run, so a moved checkout is mended the way it was
    installed. macOS: prints the launch command -- a Mac .app is out of scope."""
    app_dir = ctx.root / "electron"
    programs = start_menu(ctx)
    if programs is None:
        return f"no Start menu here; launch JARVIS with:  cd \"{app_dir}\" && npm start"
    exe = electron_exe(ctx.root)
    if exe is None:
        raise StepFailed("no Electron binary to point the shortcut at")
    powershell = which("powershell")
    if not powershell:
        raise StepFailed("no `powershell` on PATH to write the Start-menu shortcut with")
    link = programs / "JARVIS.lnk"
    env = dict(ctx.env, JARVIS_LNK=str(link), JARVIS_TARGET=str(exe),
               JARVIS_APP=str(app_dir), JARVIS_ICON=str(app_dir / "jarvis.ico"))
    argv = [powershell, "-NoProfile", "-NonInteractive", "-Command", SHORTCUT_PS1]
    must(run(argv, env=env), argv, "PowerShell could not write the shortcut")
    return f"wrote {link}"


PREFLIGHT = (
    "import asyncio, json, preflight\n"
    "found = asyncio.run(preflight.run_checks())\n"
    "print(json.dumps([{'name': c.name, 'status': c.status, 'message': c.message,"
    " 'remedy': c.remedy} for c in found]))"
)


def checks(ctx: Context) -> str:
    """JARVIS's own first-run checks, through the venv with the server's
    environment. Reported, never a stop: this is the last step, and the most
    likely finding -- Claude Code not logged in -- is Ken's to fix."""
    argv = [str(venv_python(ctx.root)), "-c", PREFLIGHT]
    result = must(run(argv, cwd=ctx.root, env=effective_env(ctx)), argv, "preflight did not run")
    found = json.loads(result.stdout.strip().splitlines()[-1])
    lines = []
    for c in found:
        lines.append(f"  {c['status']} {c['name']}: {c['message']}")
        if c.get("remedy"):
            lines.append(f"       -> {c['remedy']}")
    bad = sum(1 for c in found if c["status"] != "ok")
    head = "all checks passed" if not bad else f"{bad} check(s) need attention"
    return head + "\n" + "\n".join(lines)


STEPS = [
    ("prerequisites", prerequisites),
    ("venv", venv),
    ("Python packages", python_packages),
    ("Playwright Chromium", playwright),
    (".env", dotenv),
    ("models", models),
    ("frontend", frontend),
    ("Electron", electron),
    ("Start-menu shortcut", shortcut),
    ("preflight", checks),
]


def main(*, root: Path = REPO, env: dict | None = None) -> int:
    try:
        sys.stdout.reconfigure(errors="replace")     # a tool's output may hold anything
    except AttributeError:
        pass
    ctx = Context(root=root, env=dict(os.environ if env is None else env))
    for number, (name, step) in enumerate(STEPS, 1):
        print(f"[{number}/{len(STEPS)}] {name}", flush=True)
        try:
            status = step(ctx)
        except StepFailed as failure:
            print(f"      FAILED: {failure.message}")
            if failure.command:
                print("      command: " + " ".join(failure.command))
            for line in failure.output.strip().splitlines()[-20:]:
                print("      | " + line)
            print("Stopped. Fix that and run install.py again -- finished steps are skipped.")
            return 1
        for line in status.splitlines():
            print("      " + line, flush=True)
    print("Done. Start JARVIS from the Start menu (or as step 9 said); "
          "run install.py again after every git pull.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
