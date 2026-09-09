"""Tests for preflight.py -- first-run environment checks.

NO TEST IN THIS FILE MAY INVOKE THE REAL `claude` BINARY, THE REAL
`osascript`, OR READ THE DEVELOPER'S REAL ~/.claude/settings.json.

Every subprocess call goes through the single seam `preflight._run_subprocess`
(the pattern `dialog.py` uses for `_osascript`), so tests monkeypatch that one
function rather than `asyncio.create_subprocess_exec` per call site. The
settings-file check goes through `preflight._settings_path`, which tests
point at a tmp_path fixture instead of the real home directory.
"""

import asyncio
import json
import time

import pytest

import jarvis_platform.macos.screen
import preflight
from preflight import Check, STATUS_FAIL, STATUS_OK, STATUS_WARN


def _fake_run_subprocess(responses):
    """Build a fake `_run_subprocess` keyed by (args tuple) -> (rc, stdout, stderr).

    Matching is by the first two positional args (e.g. ("claude", "--version")
    or ("osascript", "-e")) so callers don't need to know exact remaining
    arguments (like the literal AppleScript source). Accepts (and ignores)
    the `env` kwarg that `claude_login` now passes.
    """
    async def fake(*args, timeout, env=None):
        key = tuple(args[:2])
        if key in responses:
            return responses[key]
        raise AssertionError(f"unexpected subprocess call: {args}")
    return fake


# --- claude_cli: PATH + version -------------------------------------------

@pytest.mark.asyncio
async def test_claude_missing_from_path(monkeypatch):
    monkeypatch.setattr(preflight.shutil, "which", lambda name: None)
    check = await preflight._check_claude_cli()
    assert check.status == STATUS_FAIL
    assert "PATH" in check.message
    assert check.remedy


@pytest.mark.asyncio
async def test_claude_present_but_too_old(monkeypatch):
    monkeypatch.setattr(preflight.shutil, "which", lambda name: "/usr/local/bin/claude")
    monkeypatch.setattr(
        preflight, "_run_subprocess",
        _fake_run_subprocess({("/usr/local/bin/claude", "--version"): (0, "2.1.9 (Claude Code)\n", "")}),
    )
    check = await preflight._check_claude_cli()
    assert check.status == STATUS_FAIL
    assert "2.1.9" in check.message
    assert check.remedy


@pytest.mark.asyncio
async def test_claude_present_and_new_enough(monkeypatch):
    monkeypatch.setattr(preflight.shutil, "which", lambda name: "/usr/local/bin/claude")
    monkeypatch.setattr(
        preflight, "_run_subprocess",
        _fake_run_subprocess({("/usr/local/bin/claude", "--version"): (0, "2.1.258 (Claude Code)\n", "")}),
    )
    check = await preflight._check_claude_cli()
    assert check.status == STATUS_OK
    assert check.remedy is None


@pytest.mark.asyncio
async def test_claude_exactly_at_minimum_version_is_ok(monkeypatch):
    monkeypatch.setattr(preflight.shutil, "which", lambda name: "/usr/local/bin/claude")
    monkeypatch.setattr(
        preflight, "_run_subprocess",
        _fake_run_subprocess({("/usr/local/bin/claude", "--version"): (0, "2.1.224\n", "")}),
    )
    check = await preflight._check_claude_cli()
    assert check.status == STATUS_OK


def test_version_comparison_is_numeric_not_lexicographic():
    """The whole point of parsing into a tuple of ints: '2.1.9' < '2.1.224'
    numerically even though it is greater lexicographically as a string."""
    assert preflight._parse_version("2.1.9") < preflight.MIN_CLAUDE_VERSION
    assert preflight._parse_version("2.1.224") == preflight.MIN_CLAUDE_VERSION
    assert preflight._parse_version("2.1.258") > preflight.MIN_CLAUDE_VERSION
    assert "2.1.9" > "2.1.224"  # the naive (wrong) string comparison, for contrast


@pytest.mark.asyncio
async def test_claude_version_unparseable_output_is_warn(monkeypatch):
    monkeypatch.setattr(preflight.shutil, "which", lambda name: "/usr/local/bin/claude")
    monkeypatch.setattr(
        preflight, "_run_subprocess",
        _fake_run_subprocess({("/usr/local/bin/claude", "--version"): (0, "garbage\n", "")}),
    )
    check = await preflight._check_claude_cli()
    assert check.status == STATUS_WARN


# --- claude_login -----------------------------------------------------------

def _fake_child_env(monkeypatch, config_dir):
    """Point claude_login's `claude_env.child_env()` call at a fixed,
    test-controlled environment instead of this process's real one, so
    results (and the config dir named in messages) are deterministic."""
    monkeypatch.setattr(
        preflight.claude_env, "child_env",
        lambda: {"CLAUDE_CONFIG_DIR": str(config_dir)},
    )


@pytest.mark.asyncio
async def test_claude_not_logged_in(monkeypatch, tmp_path):
    monkeypatch.setattr(preflight.shutil, "which", lambda name: "/usr/local/bin/claude")
    _fake_child_env(monkeypatch, tmp_path / ".claude")
    body = json.dumps({"loggedIn": False})
    monkeypatch.setattr(
        preflight, "_run_subprocess",
        _fake_run_subprocess({("/usr/local/bin/claude", "auth"): (0, body, "")}),
    )
    check = await preflight._check_claude_login()
    assert check.status == STATUS_FAIL
    assert "not logged in" in check.message
    assert check.remedy


@pytest.mark.asyncio
async def test_claude_logged_in(monkeypatch, tmp_path):
    monkeypatch.setattr(preflight.shutil, "which", lambda name: "/usr/local/bin/claude")
    _fake_child_env(monkeypatch, tmp_path / ".claude")
    body = json.dumps({"loggedIn": True, "email": "you@example.com"})
    monkeypatch.setattr(
        preflight, "_run_subprocess",
        _fake_run_subprocess({("/usr/local/bin/claude", "auth"): (0, body, "")}),
    )
    check = await preflight._check_claude_login()
    assert check.status == STATUS_OK
    assert check.remedy is None
    assert "you@example.com" in check.message


@pytest.mark.asyncio
async def test_claude_login_check_without_claude_on_path(monkeypatch):
    monkeypatch.setattr(preflight.shutil, "which", lambda name: None)
    check = await preflight._check_claude_login()
    assert check.status == STATUS_WARN
    assert check.remedy


@pytest.mark.asyncio
async def test_claude_login_nonzero_exit_is_fail(monkeypatch, tmp_path):
    monkeypatch.setattr(preflight.shutil, "which", lambda name: "/usr/local/bin/claude")
    _fake_child_env(monkeypatch, tmp_path / ".claude")
    monkeypatch.setattr(
        preflight, "_run_subprocess",
        _fake_run_subprocess({("/usr/local/bin/claude", "auth"): (1, "", "not logged in at all")}),
    )
    check = await preflight._check_claude_login()
    assert check.status == STATUS_FAIL


@pytest.mark.asyncio
async def test_claude_login_malformed_json_is_warn(monkeypatch, tmp_path):
    monkeypatch.setattr(preflight.shutil, "which", lambda name: "/usr/local/bin/claude")
    _fake_child_env(monkeypatch, tmp_path / ".claude")
    monkeypatch.setattr(
        preflight, "_run_subprocess",
        _fake_run_subprocess({("/usr/local/bin/claude", "auth"): (0, "not json{{{", "")}),
    )
    check = await preflight._check_claude_login()
    assert check.status == STATUS_WARN


@pytest.mark.asyncio
async def test_claude_login_names_the_config_dir(monkeypatch, tmp_path):
    """A mismatched CLAUDE_CONFIG_DIR must be visible at a glance in the result."""
    monkeypatch.setattr(preflight.shutil, "which", lambda name: "/usr/local/bin/claude")
    config_dir = tmp_path / "some-other-config-dir"
    _fake_child_env(monkeypatch, config_dir)
    body = json.dumps({"loggedIn": True, "email": "you@example.com"})
    monkeypatch.setattr(
        preflight, "_run_subprocess",
        _fake_run_subprocess({("/usr/local/bin/claude", "auth"): (0, body, "")}),
    )
    check = await preflight._check_claude_login()
    assert str(config_dir) in check.message


@pytest.mark.asyncio
async def test_claude_login_expired_oauth_session_is_fail_not_ok(monkeypatch, tmp_path):
    """The real incident: `claude auth status` reports loggedIn: true, but the
    stored OAuth refresh token has already expired -- a real turn would fail
    with 'OAuth session expired and could not be refreshed'. A status probe
    alone can't see this; the check must go further and catch it."""
    monkeypatch.setattr(preflight.shutil, "which",
                        lambda name: {"claude": "/usr/local/bin/claude", "security": "/usr/bin/security"}.get(name))
    monkeypatch.setattr(preflight.sys, "platform", "darwin")
    config_dir = tmp_path / ".claude"
    _fake_child_env(monkeypatch, config_dir)
    status_body = json.dumps({"loggedIn": True, "authMethod": "claude.ai", "email": "you@example.com"})
    expired_at_ms = (time.time() - 3600) * 1000  # expired an hour ago
    keychain_body = json.dumps({"claudeAiOauth": {"refreshTokenExpiresAt": expired_at_ms}})
    monkeypatch.setattr(
        preflight, "_run_subprocess",
        _fake_run_subprocess({
            ("/usr/local/bin/claude", "auth"): (0, status_body, ""),
            ("security", "find-generic-password"): (0, keychain_body, ""),
        }),
    )
    check = await preflight._check_claude_login()
    assert check.status == STATUS_FAIL
    assert "expired" in check.message.lower()
    assert check.remedy


@pytest.mark.asyncio
async def test_claude_login_valid_oauth_session_is_ok(monkeypatch, tmp_path):
    monkeypatch.setattr(preflight.shutil, "which",
                        lambda name: {"claude": "/usr/local/bin/claude", "security": "/usr/bin/security"}.get(name))
    monkeypatch.setattr(preflight.sys, "platform", "darwin")
    config_dir = tmp_path / ".claude"
    _fake_child_env(monkeypatch, config_dir)
    status_body = json.dumps({"loggedIn": True, "authMethod": "claude.ai", "email": "you@example.com"})
    future_at_ms = (time.time() + 3600 * 24 * 30) * 1000  # valid for another 30 days
    keychain_body = json.dumps({"claudeAiOauth": {"refreshTokenExpiresAt": future_at_ms}})
    monkeypatch.setattr(
        preflight, "_run_subprocess",
        _fake_run_subprocess({
            ("/usr/local/bin/claude", "auth"): (0, status_body, ""),
            ("security", "find-generic-password"): (0, keychain_body, ""),
        }),
    )
    check = await preflight._check_claude_login()
    assert check.status == STATUS_OK
    assert check.remedy is None


@pytest.mark.asyncio
async def test_claude_login_oauth_probe_unavailable_stays_ok_but_says_so(monkeypatch, tmp_path):
    """When the secondary Keychain probe can't be attempted (not macOS here),
    the check must not silently claim more certainty than it has."""
    monkeypatch.setattr(preflight.shutil, "which", lambda name: "/usr/local/bin/claude")
    monkeypatch.setattr(preflight.sys, "platform", "linux")
    config_dir = tmp_path / ".claude"
    _fake_child_env(monkeypatch, config_dir)
    status_body = json.dumps({"loggedIn": True, "authMethod": "claude.ai", "email": "you@example.com"})
    monkeypatch.setattr(
        preflight, "_run_subprocess",
        _fake_run_subprocess({("/usr/local/bin/claude", "auth"): (0, status_body, "")}),
    )
    check = await preflight._check_claude_login()
    assert check.status == STATUS_OK
    assert "could not independently verify" in check.message.lower()


@pytest.mark.asyncio
async def test_claude_login_keychain_probe_never_raises_on_garbage(monkeypatch, tmp_path):
    monkeypatch.setattr(preflight.shutil, "which",
                        lambda name: {"claude": "/usr/local/bin/claude", "security": "/usr/bin/security"}.get(name))
    monkeypatch.setattr(preflight.sys, "platform", "darwin")
    config_dir = tmp_path / ".claude"
    _fake_child_env(monkeypatch, config_dir)
    status_body = json.dumps({"loggedIn": True, "authMethod": "claude.ai", "email": "you@example.com"})
    monkeypatch.setattr(
        preflight, "_run_subprocess",
        _fake_run_subprocess({
            ("/usr/local/bin/claude", "auth"): (0, status_body, ""),
            ("security", "find-generic-password"): (0, "not json at all {{{", ""),
        }),
    )
    check = await preflight._check_claude_login()  # must not raise
    assert check.status == STATUS_OK
    assert "could not independently verify" in check.message.lower()


# --- accessibility -----------------------------------------------------------

@pytest.mark.asyncio
async def test_accessibility_granted(monkeypatch):
    monkeypatch.setattr(preflight.sys, "platform", "darwin")
    monkeypatch.setattr(preflight.shutil, "which", lambda name: "/usr/bin/osascript")
    monkeypatch.setattr(
        preflight, "_run_subprocess",
        _fake_run_subprocess({("osascript", "-e"): (0, "window 1\n", "")}),
    )
    check = await preflight._check_accessibility()
    assert check.status == STATUS_OK


@pytest.mark.asyncio
async def test_accessibility_not_granted(monkeypatch):
    monkeypatch.setattr(preflight.sys, "platform", "darwin")
    monkeypatch.setattr(preflight.shutil, "which", lambda name: "/usr/bin/osascript")
    err = '65:69: execution error: System Events got an error: osascript is not allowed assistive access. (-1728)'
    monkeypatch.setattr(
        preflight, "_run_subprocess",
        _fake_run_subprocess({("osascript", "-e"): (1, "", err)}),
    )
    check = await preflight._check_accessibility()
    assert check.status == STATUS_FAIL
    assert check.remedy
    assert "Accessibility" in check.remedy


@pytest.mark.asyncio
async def test_accessibility_unknown_error_is_warn_not_ok(monkeypatch):
    monkeypatch.setattr(preflight.sys, "platform", "darwin")
    monkeypatch.setattr(preflight.shutil, "which", lambda name: "/usr/bin/osascript")
    monkeypatch.setattr(
        preflight, "_run_subprocess",
        _fake_run_subprocess({("osascript", "-e"): (1, "", "some other applescript error")}),
    )
    check = await preflight._check_accessibility()
    assert check.status == STATUS_WARN


@pytest.mark.asyncio
async def test_accessibility_skipped_off_darwin(monkeypatch):
    monkeypatch.setattr(preflight.sys, "platform", "linux")
    check = await preflight._check_accessibility()
    assert check.status == STATUS_WARN


# --- Screen Recording ----------------------------------------------------------
#
# The same lesson as Accessibility, one permission along: macOS attributes it
# to the app that LAUNCHED JARVIS, not to python. And unlike Accessibility it
# fails silently -- `screencapture` exits 0 and hands back a black frame -- so
# it is worth saying at startup rather than at the moment he asks.

# `_check_screen_recording_sync` is capability-gated in production
# (`preflight._CHECK_CAPABILITIES`), and on a platform that does not declare
# CAP_SCREEN_CAPTURE it answers `warn` — "this machine has no such
# permission to check" — whatever the screen module is patched to say. The
# ones below assert what the check does when the host HAS the capability, so
# they are gated on the same condition production uses rather than on
# `sys.platform` — they follow the capability if it ever moves.
_needs_screen_capture = pytest.mark.skipif(
    not jarvis_platform.can(jarvis_platform.CAP_SCREEN_CAPTURE),
    reason="no CAP_SCREEN_CAPTURE here; the check is withdrawn, not failing")


# THIS HOST's screen module, never `jarvis_platform.macos.screen` by name.
#
# These tests named the macOS module and were invisible off macOS only
# because the skip above hid them -- CAP_SCREEN_CAPTURE was macOS-only, so
# they never ran anywhere the patch would have missed. Windows declaring the
# capability un-hid them, and they failed at once: the check reads
# `current().screen`, which is the Windows module, and the patch was landing
# on one nothing calls. The same shape as the launcher fixtures, exposed by
# a capability moving rather than by a platform moving.
def _this_hosts_screen():
    return jarvis_platform.current().screen


@_needs_screen_capture
def test_screen_recording_granted(monkeypatch):
    monkeypatch.setattr(_this_hosts_screen(), "permission_granted", lambda: True)
    check = preflight._check_screen_recording_sync()
    assert check.status == STATUS_OK
    assert check.remedy is None


@_needs_screen_capture
def test_a_refusal_carries_this_hosts_own_remedy(monkeypatch):
    """The check does not know which platform it is on, and must not: the
    words come from `screen.CAPTURE_GATE`, which is the host's own
    statement of what its gate is and how to open it."""
    screen = _this_hosts_screen()
    monkeypatch.setattr(screen, "permission_granted", lambda: False)
    check = preflight._check_screen_recording_sync()
    assert check.remedy == screen.CAPTURE_GATE.remedy
    assert screen.CAPTURE_GATE.name in check.message


def test_a_gate_the_user_never_granted_fails_and_a_default_off_one_warns():
    """The status is not a constant, and the difference is whether JARVIS
    SPEAKS at startup: `_run_preflight` says fails out loud and only logs
    warns.

    macOS: the user granted Screen Recording once and something took it
    away. That is news, and worth hearing.

    A host whose gate is a JARVIS setting that ships OFF: off is the resting
    state the project chose, and announcing it at every boot would be
    nagging the user about a decision they have not made yet.

    Asserted against BOTH hosts' gates from wherever this runs, rather than
    against the one underfoot, so neither half can rot unnoticed on the
    platform that cannot run the other.
    """
    from jarvis_platform.macos import screen as macos_screen
    from jarvis_platform.windows import screen as windows_screen
    assert macos_screen.CAPTURE_GATE.off_by_default is False
    assert windows_screen.CAPTURE_GATE.off_by_default is True


def test_the_macos_remedy_still_names_the_launching_app():
    """The lesson that remedy exists to carry, pinned where it now lives.

    macOS attributes the permission to the app that LAUNCHED JARVIS, not to
    python or screencapture, and a user who does not know that will grant it
    to the wrong thing and see no change. Checked against the constant so it
    holds when this suite runs on Windows too.
    """
    from jarvis_platform.macos import screen as macos_screen
    remedy = macos_screen.CAPTURE_GATE.remedy
    assert "Screen Recording" in remedy
    assert "launched" in remedy.lower()
    assert "RESTART" in remedy


def test_the_windows_remedy_names_the_setting_and_not_a_system_pane():
    """Windows asks nobody, so there is no pane to send anyone to. The
    remedy has to name the switch instead -- and say that it takes effect
    without a restart, which is the part that differs from macOS."""
    from jarvis_platform.windows import screen as windows_screen
    remedy = windows_screen.CAPTURE_GATE.remedy
    assert windows_screen.CAPTURE_ENV in remedy
    assert "System Settings" not in remedy
    assert "no restart" in remedy.lower()


@_needs_screen_capture
def test_screen_recording_undeterminable_is_warn_not_fail(monkeypatch):
    """None means the probe could not run. Reporting that as a missing
    permission would send the user to a settings pane over nothing."""
    monkeypatch.setattr(_this_hosts_screen(), "permission_granted", lambda: None)
    check = preflight._check_screen_recording_sync()
    assert check.status == STATUS_WARN


@_needs_screen_capture
def test_screen_recording_check_never_raises(monkeypatch):
    def boom():
        raise RuntimeError("CoreGraphics went sideways")

    monkeypatch.setattr(_this_hosts_screen(), "permission_granted", boom)
    check = preflight._check_screen_recording_sync()
    assert check.status == STATUS_WARN


@_needs_screen_capture
def test_the_startup_check_never_takes_a_picture(monkeypatch):
    """Preflight asks the OS a question. It does NOT capture the screen to
    find out -- that would be a screenshot the user never asked for, at every
    boot."""
    screen = _this_hosts_screen()
    monkeypatch.setattr(screen, "permission_granted", lambda: True)

    def forbidden(*a, **k):
        raise AssertionError("preflight captured the screen")

    monkeypatch.setattr(screen, "capture", forbidden)
    assert preflight._check_screen_recording_sync().status == STATUS_OK


# --- the voice ----------------------------------------------------------------
#
# "No FISH_API_KEY" stopped meaning "no voice" when `say` became the default
# backend, and a preflight that fails over a key the machine does not need is
# a preflight people learn to ignore.

_VOICES = ("Daniel              en_GB    # Hello! My name is Daniel.\n"
           "Reed (English (UK)) en_GB    # Hello! My name is Reed.\n"
           "Majed               ar_001   # a numeric region subtag\n")


def _say_listing(monkeypatch, listing=_VOICES, rc=0):
    async def fake(*args, timeout=0.0, env=None):
        assert args[0] == "say", "the voice list comes from `say`, not another binary"
        return rc, listing, ""
    monkeypatch.setattr(preflight, "_run_subprocess", fake)


@pytest.mark.asyncio
async def test_voice_ok_when_the_local_voice_is_installed(monkeypatch):
    monkeypatch.delenv("JARVIS_TTS_BACKEND", raising=False)
    monkeypatch.setenv("JARVIS_TTS_VOICE", "Reed (English (UK))")
    monkeypatch.setattr(preflight.shutil, "which", lambda name: "/usr/bin/say")
    _say_listing(monkeypatch)
    check = await preflight._check_voice(timeout=1.0)
    assert check.status == STATUS_OK and check.remedy is None


@pytest.mark.asyncio
async def test_a_voice_that_is_not_installed_is_a_warning_not_silence(monkeypatch):
    """`say -v Bogus` exits 0 and uses the system default (measured), so a typo
    costs the British butler and reports nothing on its own."""
    monkeypatch.delenv("JARVIS_TTS_BACKEND", raising=False)
    monkeypatch.setenv("JARVIS_TTS_VOICE", "Danielle")
    monkeypatch.setattr(preflight.shutil, "which", lambda name: "/usr/bin/say")
    _say_listing(monkeypatch)
    check = await preflight._check_voice(timeout=1.0)
    assert check.status == STATUS_WARN and "Danielle" in check.message and check.remedy


@pytest.mark.asyncio
async def test_no_say_binary_is_a_failure(monkeypatch):
    monkeypatch.delenv("JARVIS_TTS_BACKEND", raising=False)
    monkeypatch.setattr(preflight.shutil, "which", lambda name: None)
    check = await preflight._check_voice(timeout=1.0)
    assert check.status == STATUS_FAIL and "say" in check.message


@pytest.mark.asyncio
async def test_the_piper_backend_reports_its_own_two_failures(monkeypatch, tmp_path):
    """An optional dependency and a 63 MB download are different problems with
    different commands, and a preflight that says "no voice" for both sends
    the user to the wrong one."""
    import tts
    monkeypatch.setenv("JARVIS_TTS_BACKEND", "piper")
    monkeypatch.setenv("JARVIS_DATA_DIR", str(tmp_path))
    monkeypatch.delenv("JARVIS_PIPER_VOICE", raising=False)

    monkeypatch.setattr(tts, "piper_bin", lambda: None)
    check = await preflight._check_voice(timeout=1.0)
    assert check.status == STATUS_FAIL
    assert "requirements-piper.txt" in (check.remedy or ""), "the remedy is the install"

    monkeypatch.setattr(tts, "piper_bin", lambda: "/opt/piper")
    check = await preflight._check_voice(timeout=1.0)
    assert check.status == STATUS_FAIL and "download_voices" in (check.remedy or "")

    voices = tmp_path / "voices"
    voices.mkdir()
    (voices / f"{tts.DEFAULT_PIPER_VOICE}.onnx").write_bytes(b"onnx")
    check = await preflight._check_voice(timeout=1.0)
    assert check.status == STATUS_OK and tts.DEFAULT_PIPER_VOICE in check.message


def test_the_spoken_summary_tells_piper_s_two_failures_apart():
    missing_binary = Check(name="voice", status=STATUS_FAIL,
                           message="JARVIS_TTS_BACKEND=piper but `piper` was not found.")
    missing_voice = Check(name="voice", status=STATUS_FAIL,
                          message="piper voice 'en_GB-alan-medium' is not installed in /x/voices.")
    assert "piper isn't installed" in preflight.spoken_summary([missing_binary])
    assert "voice isn't downloaded" in preflight.spoken_summary([missing_voice])


@pytest.mark.asyncio
async def test_the_fish_backend_still_needs_its_key(monkeypatch):
    monkeypatch.setenv("JARVIS_TTS_BACKEND", "fish")
    monkeypatch.setenv("FISH_API_KEY", "sk-fish-abc123")
    assert (await preflight._check_voice(timeout=1.0)).status == STATUS_OK

    monkeypatch.delenv("FISH_API_KEY", raising=False)
    check = await preflight._check_voice(timeout=1.0)
    assert check.status == STATUS_FAIL and check.remedy


@pytest.mark.asyncio
async def test_a_missing_fish_key_is_not_a_failure_on_the_local_backend(monkeypatch):
    monkeypatch.delenv("JARVIS_TTS_BACKEND", raising=False)
    monkeypatch.delenv("FISH_API_KEY", raising=False)
    monkeypatch.delenv("JARVIS_TTS_VOICE", raising=False)
    monkeypatch.setattr(preflight.shutil, "which", lambda name: "/usr/bin/say")
    _say_listing(monkeypatch)
    assert (await preflight._check_voice(timeout=1.0)).status == STATUS_OK


# --- leftover ANTHROPIC_* ------------------------------------------------------

def test_leftover_anthropic_key_warns(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-abc123")
    monkeypatch.delenv("ANTHROPIC_WORKSPACE_ID", raising=False)
    check = preflight._check_anthropic_key_leftover_sync()
    assert check.status == STATUS_WARN
    assert "ANTHROPIC_API_KEY" in check.message
    assert check.remedy


def test_no_anthropic_key_is_ok(monkeypatch):
    for key in list(preflight.os.environ):
        if key.startswith("ANTHROPIC_"):
            monkeypatch.delenv(key, raising=False)
    check = preflight._check_anthropic_key_leftover_sync()
    assert check.status == STATUS_OK
    assert check.remedy is None


# --- crossSessionInbound --------------------------------------------------------

def test_cross_session_inbound_missing_settings_file(monkeypatch, tmp_path):
    monkeypatch.setattr(preflight, "_settings_path", lambda: tmp_path / "does-not-exist.json")
    check = preflight._check_cross_session_inbound_sync()
    assert check.status == STATUS_WARN
    assert "No settings file" in check.message


def test_cross_session_inbound_malformed_json(monkeypatch, tmp_path):
    p = tmp_path / "settings.json"
    p.write_text("{ not valid json ][")
    monkeypatch.setattr(preflight, "_settings_path", lambda: p)
    check = preflight._check_cross_session_inbound_sync()
    assert check.status == STATUS_WARN
    assert "Could not read/parse" in check.message


def test_cross_session_inbound_absent_key(monkeypatch, tmp_path):
    p = tmp_path / "settings.json"
    p.write_text(json.dumps({"model": "sonnet"}))
    monkeypatch.setattr(preflight, "_settings_path", lambda: p)
    check = preflight._check_cross_session_inbound_sync()
    assert check.status == STATUS_WARN
    assert "not set" in check.message
    # Read-only: the check must never have written to the file.
    assert json.loads(p.read_text(encoding="utf-8")) == {"model": "sonnet"}


def test_cross_session_inbound_set_to_accept(monkeypatch, tmp_path):
    p = tmp_path / "settings.json"
    p.write_text(json.dumps({"crossSessionInbound": "accept"}))
    monkeypatch.setattr(preflight, "_settings_path", lambda: p)
    check = preflight._check_cross_session_inbound_sync()
    assert check.status == STATUS_OK
    assert check.remedy is None


def test_cross_session_inbound_set_to_something_else(monkeypatch, tmp_path):
    p = tmp_path / "settings.json"
    p.write_text(json.dumps({"crossSessionInbound": "deny"}))
    monkeypatch.setattr(preflight, "_settings_path", lambda: p)
    check = preflight._check_cross_session_inbound_sync()
    assert check.status == STATUS_WARN
    assert "'deny'" in check.message or '"deny"' in check.message


def test_cross_session_inbound_never_writes_when_file_missing(monkeypatch, tmp_path):
    target = tmp_path / "does-not-exist.json"
    monkeypatch.setattr(preflight, "_settings_path", lambda: target)
    preflight._check_cross_session_inbound_sync()
    assert not target.exists()


# --- run_checks(): timeouts, internal exceptions, concurrency -----------------

@pytest.mark.asyncio
async def test_a_hung_check_times_out_as_warn(monkeypatch):
    async def hang(*, timeout):
        await asyncio.sleep(999)
        return Check(name="claude_cli", status=STATUS_OK, message="unreachable")

    monkeypatch.setattr(preflight, "_ASYNC_CHECKS", (hang,))
    monkeypatch.setattr(preflight, "_SYNC_CHECKS", ())

    results = await preflight.run_checks(timeout=0.05)
    assert len(results) == 1
    assert results[0].status == STATUS_WARN
    assert "timed out" in results[0].message


@pytest.mark.asyncio
async def test_a_raising_check_becomes_warn_not_an_exception(monkeypatch):
    def explode():
        raise RuntimeError("disk on fire")

    monkeypatch.setattr(preflight, "_ASYNC_CHECKS", ())
    monkeypatch.setattr(preflight, "_SYNC_CHECKS", (explode,))

    results = await preflight.run_checks(timeout=1.0)
    assert len(results) == 1
    assert results[0].status == STATUS_WARN
    assert "disk on fire" in results[0].message


@pytest.mark.asyncio
async def test_run_checks_never_raises_even_with_a_broken_check(monkeypatch):
    def explode():
        raise ValueError("boom")

    monkeypatch.setattr(preflight, "_SYNC_CHECKS", (explode,))
    # Should not raise.
    results = await preflight.run_checks(timeout=1.0)
    assert isinstance(results, list)


@pytest.mark.asyncio
async def test_run_checks_runs_all_registered_checks(monkeypatch):
    monkeypatch.setattr(preflight.shutil, "which", lambda name: None)  # claude missing -> fast fail
    monkeypatch.setattr(preflight.sys, "platform", "linux")  # accessibility skipped -> fast warn
    monkeypatch.delenv("FISH_API_KEY", raising=False)
    monkeypatch.setattr(preflight, "_settings_path", lambda: preflight.Path("/nonexistent/settings.json"))

    results = await preflight.run_checks(timeout=1.0)
    names = {c.name for c in results}
    # Two of these are capability-gated, and where the platform withdraws
    # them they are not merely skipped, they are ABSENT from the run --
    # `preflight._applies_here` never calls them. So the expected set is
    # built the same way production builds the run, rather than pinning a
    # complete host and calling every other one a failure.
    expected = {"claude_cli", "claude_login", "voice",
                "anthropic_key_leftover", "cross_session_inbound"}
    if jarvis_platform.can(jarvis_platform.CAP_DIALOG_KEY):
        expected.add("accessibility")
    if jarvis_platform.can(jarvis_platform.CAP_SCREEN_CAPTURE):
        expected.add("screen_recording")
    assert names == expected


# --- spoken_summary -------------------------------------------------------------

def test_spoken_summary_empty_when_all_ok():
    checks = [
        Check(name="claude_cli", status=STATUS_OK, message="ok"),
        Check(name="voice", status=STATUS_OK, message="ok"),
    ]
    assert preflight.spoken_summary(checks) == ""


def test_spoken_summary_never_says_all_checks_passed():
    checks = [Check(name="claude_cli", status=STATUS_OK, message="ok")]
    summary = preflight.spoken_summary(checks)
    assert summary == ""
    assert "all checks passed" not in summary.lower()


def test_spoken_summary_names_a_single_failure():
    checks = [
        Check(name="claude_cli", status=STATUS_OK, message="ok"),
        Check(name="claude_login", status=STATUS_FAIL, message="Claude Code is not logged in."),
    ]
    summary = preflight.spoken_summary(checks)
    assert "One thing needs attention" in summary
    assert "isn't logged in" in summary
    assert "claude_cli" not in summary  # only the failing check is named


def test_spoken_summary_says_screen_recording_in_words_a_person_would_use():
    """The spoken phrase names THIS host's gate.

    It said "Screen Recording permission" flat, which is right on a Mac and
    names a permission that does not exist on Windows -- where the gate is
    JARVIS's own switch. `screen_recording` stays the check's id and must
    never be what the user hears either way.
    """
    gate = jarvis_platform.current().screen.CAPTURE_GATE
    checks = [Check(name="screen_recording", status=STATUS_FAIL,
                    message=f"JARVIS has not been granted {gate.name}.")]
    summary = preflight.spoken_summary(checks)
    assert f"{gate.name} permission" in summary
    assert "screen_recording" not in summary


def test_spoken_summary_names_two_failures_and_matches_the_example():
    checks = [
        Check(name="claude_login", status=STATUS_FAIL, message="Claude Code is not logged in."),
        Check(name="voice", status=STATUS_FAIL,
              message="JARVIS_TTS_BACKEND=fish but FISH_API_KEY is not set."),
    ]
    summary = preflight.spoken_summary(checks)
    assert summary == (
        "Two things need attention, sir: Claude Code isn't logged in, "
        "and I have no Fish Audio key."
    )


def test_spoken_summary_names_only_the_failures_among_a_mix():
    checks = [
        Check(name="claude_cli", status=STATUS_OK, message="ok"),
        Check(name="claude_login", status=STATUS_OK, message="ok"),
        Check(name="accessibility", status=STATUS_FAIL,
              message="osascript is not granted Accessibility (assistive access); answer_dialog's keystroke will fail."),
        Check(name="cross_session_inbound", status=STATUS_WARN, message="crossSessionInbound is not set"),
        Check(name="anthropic_key_leftover", status=STATUS_WARN, message="ANTHROPIC_API_KEY set"),
    ]
    summary = preflight.spoken_summary(checks)
    assert summary.startswith("3 things need attention, sir:")
    assert "Accessibility permission" in summary
    assert "cross-session steering" in summary
    assert "leftover Anthropic API key" in summary


def test_spoken_summary_warn_counts_as_something_wrong():
    checks = [Check(name="cross_session_inbound", status=STATUS_WARN, message="crossSessionInbound is not set")]
    summary = preflight.spoken_summary(checks)
    assert summary != ""
    assert "One thing needs attention" in summary
