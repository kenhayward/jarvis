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
