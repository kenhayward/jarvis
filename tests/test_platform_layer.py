"""The platform layer: what this machine can do, and what that withdraws.

On macOS every capability is declared, so nothing is ever withdrawn here and
the machinery would go completely unexercised on the machine it was written
on. That is what `fake_host` is for — the first proof that a tool can be
taken away cleanly must not arrive on Windows, on the day the whole port
depends on it.
"""

import importlib

import pytest
from fastapi.testclient import TestClient

import brain
import jarvis_mcp
import jarvis_platform as jp
from jarvis_platform.base import TOOL_CAPABILITIES
from jarvis_platform.fake import fake_host


@pytest.fixture
def as_host(monkeypatch):
    """Run the rest of the test as if this were a different machine."""
    def _use(host):
        monkeypatch.setattr(jp, "_HOST", host)
        return host
    return _use


# --- the macOS baseline: nothing changes ----------------------------------

def test_macos_declares_every_capability_so_nothing_is_withdrawn():
    """The acceptance criterion for the whole refactor: on a Mac, this
    layer is invisible."""
    from jarvis_platform.macos import MACOS
    assert MACOS.capabilities == jp.ALL_CAPABILITIES
    assert MACOS.withdrawn_tools() == frozenset()
    assert MACOS.filter_tools(sorted(TOOL_CAPABILITIES)) == sorted(TOOL_CAPABILITIES)


def test_an_unknown_platform_declares_nothing_rather_than_guessing():
    """JARVIS still starts — the portable two thirds of him work — but he
    claims nothing he has not been shown to do."""
    host = jp.Host(name="plan9", capabilities=frozenset())
    assert host.withdrawn_tools() == frozenset(TOOL_CAPABILITIES)
    assert host.allows_tool("spawn_run") is True     # portable, still offered


# --- withdrawal ------------------------------------------------------------

def test_a_portable_tool_is_never_withdrawn():
    """Portable is the default, so a new tool has to opt IN to being
    platform-bound. Forgetting to list one leaves it working everywhere
    rather than silently dead on the platform nobody tested."""
    barren = fake_host(capabilities=frozenset())
    for tool in ("spawn_run", "remember", "read_file", "list_sessions",
                 "usage_status", "read_page"):
        assert barren.allows_tool(tool) is True, tool


def test_losing_one_capability_withdraws_exactly_its_tools():
    host = fake_host(without={jp.CAP_TERMINAL})
    assert host.withdrawn_tools() == {"open_in_terminal", "run_command"}
    assert host.allows_tool("open_in_browser") is True


def test_every_capability_gated_tool_is_a_tool_that_exists(as_host):
    """A typo in TOOL_CAPABILITIES withdraws nothing and says nothing.

    Checked against the server's own registry rather than a second list, so
    renaming a tool and forgetting the mapping fails here.
    """
    import server
    for name in TOOL_CAPABILITIES:
        assert name in server.TOOL_HANDLERS, f"{name} is not a registered tool"


# --- consumer 1: the brain's --tools allowlist -----------------------------

def test_granted_tools_drops_what_the_platform_cannot_do(as_host):
    as_host(fake_host(without={jp.CAP_SCREEN_CAPTURE, jp.CAP_DIALOG_KEY}))
    granted = brain.granted_tools([])
    assert "mcp__jarvis__look_at_screen" not in granted
    assert "mcp__jarvis__answer_dialog" not in granted
    assert "mcp__jarvis__what_is_on_screen" in granted     # window list survives
    assert "mcp__jarvis__spawn_run" in granted


def test_granted_tools_never_withdraws_what_is_not_ours(as_host):
    """The CLI's own tools and a user's declared server are not JARVIS's to
    withdraw on platform grounds."""
    as_host(fake_host(capabilities=frozenset()))
    granted = brain.granted_tools(["notion"])
    assert "WebSearch" in granted and "WebFetch" in granted
    assert "mcp__notion" in granted


# --- consumer 2: the MCP child's tools/list --------------------------------

def test_the_mcp_child_offers_everything_when_nothing_is_disabled(monkeypatch):
    monkeypatch.delenv("JARVIS_DISABLED_TOOLS", raising=False)
    assert jarvis_mcp.offered_tools() is jarvis_mcp.TOOL_SPECS


def test_the_mcp_child_drops_disabled_tools_from_its_schema(monkeypatch):
    """A withdrawn tool costs no schema on any turn — which is the whole
    reason withdrawal beats a handler that answers 'not supported'."""
    monkeypatch.setenv("JARVIS_DISABLED_TOOLS", "answer_dialog, look_at_screen")
    offered = {spec["name"] for spec in jarvis_mcp.offered_tools()}
    assert "answer_dialog" not in offered and "look_at_screen" not in offered
    assert "spawn_run" in offered


def test_the_mcp_child_ignores_a_blank_or_padded_variable(monkeypatch):
    monkeypatch.setenv("JARVIS_DISABLED_TOOLS", " , ,")
    assert jarvis_mcp.disabled_tools() == set()


# --- consumer 3: the generated mcp.json ------------------------------------

def test_mcp_config_says_nothing_when_the_platform_can_do_everything(
        monkeypatch, tmp_path):
    monkeypatch.setenv("JARVIS_DATA_DIR", str(tmp_path))
    import server
    importlib.reload(server)
    import json
    home = server.data_paths.brain_home()
    home.mkdir(parents=True, exist_ok=True)
    path = server._write_mcp_config(home)
    env = json.loads(path.read_text())["mcpServers"]["jarvis"]["env"]
    assert "JARVIS_DISABLED_TOOLS" not in env


def test_mcp_config_carries_the_withdrawn_list_to_the_child(
        monkeypatch, tmp_path, as_host):
    monkeypatch.setenv("JARVIS_DATA_DIR", str(tmp_path))
    import server
    importlib.reload(server)
    as_host(fake_host(without={jp.CAP_DIALOG_KEY}))
    import json
    home = server.data_paths.brain_home()
    home.mkdir(parents=True, exist_ok=True)
    path = server._write_mcp_config(home)
    env = json.loads(path.read_text())["mcpServers"]["jarvis"]["env"]
    assert env["JARVIS_DISABLED_TOOLS"] == "answer_dialog"


# --- consumer 4: the dispatch gate -----------------------------------------

def test_a_withdrawn_tool_is_refused_at_the_endpoint(monkeypatch, tmp_path,
                                                     as_host):
    """Belt and braces behind the two lists above: a brain older than the
    current capability set, or something calling /internal/tool directly,
    still cannot reach a handler this machine cannot honour."""
    monkeypatch.setenv("JARVIS_DATA_DIR", str(tmp_path))
    import server
    importlib.reload(server)
    token = server.data_paths.ensure_tool_token()
    as_host(fake_host(without={jp.CAP_WINDOW_LIST}))

    with TestClient(server.app,
                    headers={"Origin": "http://localhost:5173"}) as c:
        r = c.post("/internal/tool",
                   json={"tool": "what_is_on_screen", "arguments": {}},
                   headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200
    assert r.json()["ok"] is False
    assert "unknown tool" in r.json()["text"].lower()


# --- consumer 5: preflight -------------------------------------------------

@pytest.mark.asyncio
async def test_preflight_skips_checks_for_capabilities_this_platform_lacks(
        as_host, monkeypatch):
    """A permission check for a permission the platform does not have is a
    category error, not a warning — and a check that warns forever on a
    healthy machine teaches people to ignore the preflight."""
    import preflight
    as_host(fake_host(without={jp.CAP_DIALOG_KEY, jp.CAP_SCREEN_CAPTURE}))

    async def _fake_subprocess(*args, **kwargs):
        return 0, "", ""
    monkeypatch.setattr(preflight, "_run_subprocess", _fake_subprocess)

    checks = await preflight.run_checks(timeout=0.5)
    names = {c.name for c in checks}
    assert "accessibility" not in names
    assert "screen_recording" not in names
    assert "claude_cli" in names          # unconditional checks still run


@pytest.mark.asyncio
async def test_preflight_runs_every_check_on_a_complete_host(as_host, monkeypatch):
    import preflight
    as_host(fake_host())

    async def _fake_subprocess(*args, **kwargs):
        return 0, "", ""
    monkeypatch.setattr(preflight, "_run_subprocess", _fake_subprocess)

    names = {c.name for c in await preflight.run_checks(timeout=0.5)}
    assert {"accessibility", "screen_recording"} <= names


# --- the sub-interfaces ----------------------------------------------------

def test_the_macos_host_carries_the_real_notifications_module():
    from jarvis_platform.macos import MACOS, notifications
    assert MACOS.notifications is notifications


@pytest.mark.asyncio
async def test_a_host_without_notifications_declines_rather_than_raising():
    """The announcement path calls this when nothing is listening on the
    voice channel and must never be broken by it — so an unbuilt platform
    answers "nobody was told", which is true, instead of throwing into the
    watcher."""
    host = jp.Host(name="plan9", capabilities=frozenset())
    assert host.notifications.available() is False
    assert await host.notifications.notify("t", "m", subtitle="s") is False
