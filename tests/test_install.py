"""install.py: every step's decision, with nothing actually installed.

`install.run` is the one place the script starts a program and `install.which`
the one place it looks one up; the fixtures replace both, so these tests run
on either CI platform without pip, npm, PowerShell or a network.
"""
import ast
import sys
from pathlib import Path

import pytest

import install


class Recorder:
    """Stands in for `install.run`: records every call, answers by rule.

    `reply(match, result, effect=None)`: the first rule whose `match(argv)` is
    true answers. `result` may be a list, consumed one per call (the last one
    repeats); `effect(argv, cwd, env)` runs first, to create the files a real
    command would have left behind.
    """

    def __init__(self):
        self.calls = []
        self._rules = []

    def reply(self, match, result, effect=None):
        results = list(result) if isinstance(result, list) else [result]
        self._rules.append((match, results, effect))

    def __call__(self, argv, *, cwd=None, env=None):
        argv = [str(a) for a in argv]
        self.calls.append({"argv": argv, "cwd": cwd, "env": env})
        for match, results, effect in self._rules:
            if match(argv):
                if effect:
                    effect(argv, cwd, env)
                return results.pop(0) if len(results) > 1 else results[0]
        return install.Result(0, "", "")

    def argvs(self):
        return [c["argv"] for c in self.calls]


def ok(stdout=""):
    return install.Result(0, stdout, "")


@pytest.fixture
def rec(monkeypatch):
    r = Recorder()
    monkeypatch.setattr(install, "run", r)
    return r


@pytest.fixture
def tools(monkeypatch):
    """What `which` finds. Deliberately Windows-shaped: npm is npm.cmd."""
    found = {"node": "/fake/bin/node", "npm": "/fake/bin/npm.cmd",
             "git": "/fake/bin/git", "claude": "/fake/bin/claude"}
    monkeypatch.setattr(install, "which", lambda name: found.get(name))
    return found


def make_ctx(root, **kw):
    kw.setdefault("env", {})
    kw.setdefault("version", (3, 13, 0))
    kw.setdefault("python", "/fake/python3")
    return install.Context(root=root, **kw)


def node_says(version):
    return lambda argv: argv[-1] == "--version", ok(version)


# --- the spine ------------------------------------------------------------

def test_install_py_needs_nothing_but_the_standard_library():
    """It runs before the venv it creates exists."""
    for name in ("install.py", "env_file.py"):
        tree = ast.parse((Path(install.__file__).parent / name).read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                mods = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom) and node.level == 0:
                mods = [node.module]
            else:
                continue
            for mod in mods:
                top = mod.split(".")[0]
                assert top in sys.stdlib_module_names or top in ("env_file", "__future__"), \
                    f"{name} imports {mod}, which the fresh machine will not have"


def test_run_keeps_stdout_apart_from_stderr():
    r = install.run([sys.executable, "-c",
                     "import sys; print('out'); print('err', file=sys.stderr)"])
    assert r.returncode == 0 and r.stdout.strip() == "out"
    assert "out" in r.output and "err" in r.output


def test_must_turns_a_failed_command_into_a_stop_that_carries_it():
    with pytest.raises(install.StepFailed) as e:
        install.must(install.Result(2, "", "boom"), ["/x/tool", "arg"], "tool failed")
    assert e.value.command == ["/x/tool", "arg"] and "boom" in e.value.output


# --- prerequisites -----------------------------------------------------------

def test_an_old_python_stops_before_anything_is_touched(tmp_path, rec, tools):
    with pytest.raises(install.StepFailed, match="3.11"):
        install.prerequisites(make_ctx(tmp_path, version=(3, 10, 9)))
    assert rec.calls == []


def test_a_missing_node_stops_with_a_hint(tmp_path, rec, tools):
    del tools["node"]
    with pytest.raises(install.StepFailed, match="Node 22.12"):
        install.prerequisites(make_ctx(tmp_path))


def test_node_older_than_electrons_floor_is_refused(tmp_path, rec, tools):
    rec.reply(*node_says("v22.11.0\n"))
    with pytest.raises(install.StepFailed, match="22.12"):
        install.prerequisites(make_ctx(tmp_path))


def test_programs_are_run_by_the_path_which_found(tmp_path, rec, tools):
    """On Windows npm is npm.cmd, and CreateProcess cannot find a bare `npm`:
    the extension bug this port has met three times. So nothing is ever run
    by its bare name."""
    rec.reply(*node_says("v24.16.0\n"))
    ctx = make_ctx(tmp_path)
    install.prerequisites(ctx)
    assert rec.argvs() == [[tools["node"], "--version"]]
    assert ctx.tools["npm"] == tools["npm"] and ctx.tools["node"] == tools["node"]


def test_no_claude_or_git_is_a_note_not_a_stop(tmp_path, rec, tools):
    del tools["claude"], tools["git"]
    rec.reply(*node_says("v24.16.0\n"))
    status = install.prerequisites(make_ctx(tmp_path))
    assert "no `claude`" in status and "@anthropic-ai/claude-code" in status
    assert "no `git`" in status


def test_the_hint_follows_the_package_manager_the_machine_has(monkeypatch):
    monkeypatch.setattr(install, "which", lambda n: "/x/winget" if n == "winget" else None)
    assert install._install_hint("node") == "winget install OpenJS.NodeJS.LTS"
    monkeypatch.setattr(install, "which", lambda n: "/x/brew" if n == "brew" else None)
    assert install._install_hint("node") == "brew install node"
    monkeypatch.setattr(install, "which", lambda n: None)
    assert "PATH" in install._install_hint("node")


# --- the venv ----------------------------------------------------------------

def fake_venv(root, name=("Scripts", "python.exe")):
    exe = root / ".venv" / Path(*name)
    exe.parent.mkdir(parents=True, exist_ok=True)
    exe.write_text("")
    return exe


def says_python(version):
    return lambda argv: argv[1:2] == ["-c"] and "version_info" in argv[2], ok(version)


def test_a_missing_venv_is_created_from_the_running_interpreter(tmp_path, rec):
    rec.reply(lambda a: a[1:3] == ["-m", "venv"], ok(),
              effect=lambda *_: fake_venv(tmp_path))
    status = install.venv(make_ctx(tmp_path))
    assert rec.argvs()[0] == ["/fake/python3", "-m", "venv", str(tmp_path / ".venv")]
    assert status.startswith("created")


def test_an_existing_venv_is_kept(tmp_path, rec):
    fake_venv(tmp_path)
    rec.reply(*says_python("3.13\n"))
    status = install.venv(make_ctx(tmp_path))
    assert not any(a[1:3] == ["-m", "venv"] for a in rec.argvs())
    assert status.startswith("skipped")


def test_a_venv_too_old_for_jarvis_is_refused_not_used(tmp_path, rec):
    fake_venv(tmp_path)
    rec.reply(*says_python("3.10\n"))
    with pytest.raises(install.StepFailed, match="Delete .venv"):
        install.venv(make_ctx(tmp_path))


def test_the_venv_interpreter_is_found_under_either_platforms_name(tmp_path):
    exe = fake_venv(tmp_path, ("bin", "python"))
    assert install.venv_python(tmp_path) == exe


# --- Python packages ---------------------------------------------------------

def fake_requirements(root):
    for name in install.REQUIREMENTS:
        (root / name).write_text(f"# {name}\n")


def is_pip(argv):
    return argv[1:4] == ["-m", "pip", "install"]


def test_packages_install_all_three_files_through_the_venv(tmp_path, rec):
    exe = fake_venv(tmp_path)
    fake_requirements(tmp_path)
    install.python_packages(make_ctx(tmp_path))
    (argv,) = [a for a in rec.argvs() if is_pip(a)]
    assert argv[0] == str(exe)
    assert argv[4:] == ["-r", "requirements.txt", "-r", "requirements-piper.txt",
                        "-r", "requirements-stt.txt"]


def test_unchanged_requirements_are_not_reinstalled(tmp_path, rec):
    fake_venv(tmp_path)
    fake_requirements(tmp_path)
    install.python_packages(make_ctx(tmp_path))
    status = install.python_packages(make_ctx(tmp_path))
    assert sum(is_pip(a) for a in rec.argvs()) == 1
    assert status.startswith("skipped")


def test_a_changed_requirements_file_reinstalls(tmp_path, rec):
    fake_venv(tmp_path)
    fake_requirements(tmp_path)
    install.python_packages(make_ctx(tmp_path))
    (tmp_path / "requirements-stt.txt").write_text("faster-whisper==9\n")
    install.python_packages(make_ctx(tmp_path))
    assert sum(is_pip(a) for a in rec.argvs()) == 2


def test_the_stamp_lives_inside_the_venv_so_deleting_it_forgets_it(tmp_path, rec):
    fake_venv(tmp_path)
    fake_requirements(tmp_path)
    install.python_packages(make_ctx(tmp_path))
    assert (tmp_path / ".venv" / install.STAMP).is_file()


def test_a_failed_pip_stops_and_stamps_nothing(tmp_path, rec):
    fake_venv(tmp_path)
    fake_requirements(tmp_path)
    rec.reply(is_pip, install.Result(1, "", "No matching distribution"))
    with pytest.raises(install.StepFailed):
        install.python_packages(make_ctx(tmp_path))
    assert not (tmp_path / ".venv" / install.STAMP).exists()


# --- Playwright --------------------------------------------------------------

def test_playwright_installs_chromium_through_the_venv(tmp_path, rec):
    exe = fake_venv(tmp_path)
    install.playwright(make_ctx(tmp_path))
    assert rec.argvs() == [[str(exe), "-m", "playwright", "install", "chromium"]]


# --- .env --------------------------------------------------------------------

EXAMPLE = "# JARVIS configuration\n# JARVIS_TTS_BACKEND=say\nUSER_NAME=\n"


def with_example(root):
    (root / ".env.example").write_text(EXAMPLE)
    return root


def say_is(present, monkeypatch):
    monkeypatch.setattr(install, "which", lambda n: "/usr/bin/say" if (n == "say" and present) else None)


def test_a_missing_env_is_made_from_the_example_with_the_ear_the_app_needs(tmp_path, monkeypatch):
    say_is(True, monkeypatch)
    install.dotenv(make_ctx(with_example(tmp_path)))
    text = (tmp_path / ".env").read_text()
    assert text.startswith(EXAMPLE)
    assert "\nJARVIS_STT_BACKEND=whisper\n" in text
    assert "\nJARVIS_TTS_BACKEND=piper\n" not in text, "say exists here; the default voice works"


def test_without_say_the_new_env_names_a_voice_that_exists(tmp_path, monkeypatch):
    say_is(False, monkeypatch)
    install.dotenv(make_ctx(with_example(tmp_path)))
    assert "\nJARVIS_TTS_BACKEND=piper\n" in (tmp_path / ".env").read_text()


def test_jarvis_env_file_decides_which_file(tmp_path, monkeypatch):
    say_is(True, monkeypatch)
    elsewhere = tmp_path / "elsewhere" / ".env"
    install.dotenv(make_ctx(with_example(tmp_path), env={"JARVIS_ENV_FILE": str(elsewhere)}))
    assert elsewhere.exists() and not (tmp_path / ".env").exists()


def test_an_existing_env_is_never_changed_only_diagnosed(tmp_path, monkeypatch):
    say_is(False, monkeypatch)
    original = b"JARVIS_STT_BACKEND=browser\r\n# mine\r\n"
    (with_example(tmp_path) / ".env").write_bytes(original)
    status = install.dotenv(make_ctx(tmp_path))
    assert (tmp_path / ".env").read_bytes() == original
    assert "hear nothing" in status and "JARVIS_STT_BACKEND=whisper" in status
    assert "will not speak" in status and "JARVIS_TTS_BACKEND=piper" in status


def test_a_good_existing_env_is_reported_as_fine(tmp_path, monkeypatch):
    say_is(False, monkeypatch)
    (with_example(tmp_path) / ".env").write_text(
        "JARVIS_STT_BACKEND=whisper\nJARVIS_TTS_BACKEND=piper\n")
    assert "nothing in it" in install.dotenv(make_ctx(tmp_path))


def test_the_effective_env_is_the_servers_process_first_then_first_line():
    """server.py loads .env with os.environ.setdefault per line: the process
    environment wins, and within the file the FIRST occurrence does."""
    ctx = make_ctx(Path("."), env={"JARVIS_STT_BACKEND": "whisper"})
    lines = "JARVIS_STT_BACKEND=browser\nUSER_NAME=Ken\nUSER_NAME=Other\n"
    got = install._merge_env(ctx.env, lines)
    assert got["JARVIS_STT_BACKEND"] == "whisper" and got["USER_NAME"] == "Ken"


def test_a_created_env_that_an_example_line_would_override_is_a_stop(tmp_path, monkeypatch):
    """The server takes the FIRST occurrence of a key, and the block is
    appended. An example that ever grows a live `JARVIS_STT_BACKEND=browser`
    would win over it, and a freshly installed application would be deaf
    with a .env that looks right. So the created file is judged as the
    server will read it."""
    say_is(True, monkeypatch)
    (tmp_path / ".env.example").write_text("JARVIS_STT_BACKEND=browser\n")
    with pytest.raises(install.StepFailed, match="hear nothing"):
        install.dotenv(make_ctx(tmp_path))


def test_fish_without_a_key_on_a_machine_without_say_is_mute():
    problems = install.env_problems(
        {"JARVIS_STT_BACKEND": "whisper", "JARVIS_TTS_BACKEND": "fish"}, have_say=False)
    assert any("will not speak" in p for p in problems)


# --- models ------------------------------------------------------------------

import json as _json


def probe_says(**kw):
    # voices_dir is only ever created when the voice is missing; every test
    # that says so passes its own tmp directory.
    found = {"voice": "en_GB-alan-medium", "voice_present": True,
             "voices_dir": "/never-created", "stt_model": "base.en", "stt_present": True}
    found.update(kw)
    return ok("some import-time log line\n" + _json.dumps(found) + "\n")


def is_probe(argv):
    return argv[1:2] == ["-c"] and argv[2] == install.PROBE_MODELS


def test_models_already_present_download_nothing(tmp_path, rec):
    fake_venv(tmp_path)
    rec.reply(is_probe, probe_says())
    status = install.models(make_ctx(tmp_path))
    assert rec.argvs() == [[str(tmp_path / ".venv" / "Scripts" / "python.exe"), "-c", install.PROBE_MODELS]]
    assert status.startswith("skipped")


def test_a_missing_voice_is_downloaded_by_its_configured_name(tmp_path, rec):
    exe = fake_venv(tmp_path)
    rec.reply(is_probe, [probe_says(voice="en_US-amy-low", voice_present=False,
                                    voices_dir=str(tmp_path / "voices")),
                         probe_says(voice="en_US-amy-low")])
    install.models(make_ctx(tmp_path))
    assert [str(exe), "-m", "piper.download_voices", "--download-dir",
            str(tmp_path / "voices"), "en_US-amy-low"] in rec.argvs()


def test_a_missing_whisper_model_is_fetched_by_its_configured_name(tmp_path, rec):
    exe = fake_venv(tmp_path)
    rec.reply(is_probe, [probe_says(stt_model="small.en", stt_present=False),
                         probe_says(stt_model="small.en")])
    install.models(make_ctx(tmp_path))
    assert [str(exe), "-c", install.FETCH_WHISPER, "small.en"] in rec.argvs()


def test_a_voice_named_as_a_missing_file_is_a_stop_not_a_download(tmp_path, rec):
    fake_venv(tmp_path)
    rec.reply(is_probe, probe_says(voice="/models/mine.onnx", voice_present=False))
    with pytest.raises(install.StepFailed, match="does not exist"):
        install.models(make_ctx(tmp_path))
    assert not any("piper.download_voices" in a for a in rec.argvs())


def test_the_probe_runs_with_the_servers_environment(tmp_path, rec):
    fake_venv(tmp_path)
    (tmp_path / ".env").write_text("JARVIS_PIPER_VOICE=en_US-amy-low\n")
    rec.reply(is_probe, probe_says())
    install.models(make_ctx(tmp_path))
    assert rec.calls[0]["env"]["JARVIS_PIPER_VOICE"] == "en_US-amy-low"


def test_a_download_jarvis_still_cannot_find_is_a_stop(tmp_path, rec):
    fake_venv(tmp_path)
    # Still missing afterwards. A tmp voices_dir: the step creates it.
    rec.reply(is_probe, probe_says(voice_present=False, voices_dir=str(tmp_path / "voices")))
    with pytest.raises(install.StepFailed, match="still cannot find"):
        install.models(make_ctx(tmp_path))
