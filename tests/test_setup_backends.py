"""Unit tests for stays.mcp.setup.{claude,codex,chatgpt} backends."""

from __future__ import annotations

import json
import shutil
import subprocess

import pytest

from stays.mcp.setup import BACKENDS, SetupReport, canonical_server_block, resolve_stays_command
from stays.mcp.setup import chatgpt as chatgpt_backend
from stays.mcp.setup import claude as claude_backend
from stays.mcp.setup import codex as codex_backend


class TestCommon:
    def test_resolve_prefers_stays_binary(self, monkeypatch):
        monkeypatch.setattr(
            shutil,
            "which",
            lambda name: "/usr/local/bin/stays" if name == "stays" else None,
        )
        cmd, args = resolve_stays_command()
        assert cmd == "/usr/local/bin/stays"
        assert args == ["mcp"]

    def test_resolve_falls_back_to_python(self, monkeypatch):
        monkeypatch.setattr(shutil, "which", lambda name: None)
        cmd, args = resolve_stays_command()
        # cmd is the active interpreter path
        assert "python" in cmd.lower()
        assert args == ["-m", "stays.mcp._entry"]

    def test_canonical_server_block_shape(self, monkeypatch):
        monkeypatch.setattr(shutil, "which", lambda name: "/bin/stays" if name == "stays" else None)
        block = canonical_server_block()
        assert set(block.keys()) == {"command", "args"}
        assert block["command"] == "/bin/stays"


class TestClaude:
    def test_print_json_only(self):
        report = claude_backend.register(print_json_only=True)
        assert report.fallback_json is not None
        payload = json.loads(report.fallback_json)
        assert "mcpServers" in payload
        assert "stays" in payload["mcpServers"]

    def test_no_clients_detected_falls_back(self, monkeypatch, tmp_path):
        monkeypatch.setattr(shutil, "which", lambda name: None)
        monkeypatch.setattr(
            claude_backend,
            "claude_desktop_config_path",
            lambda: tmp_path / "nowhere" / "cfg.json",
        )
        report = claude_backend.register()
        assert report.fallback_json is not None
        assert any("No Claude client" in m for m in report.messages)

    def test_already_registered_no_replace_does_not_print_fallback(self, monkeypatch, tmp_path):
        """Regression: if clients ARE detected but already have `stays`
        registered, a no-op re-run must NOT print the 'No Claude client
        detected' JSON fallback — that message is reserved for the case
        when neither client is present at all.
        """

        def which(name):
            return {"claude": "/bin/claude", "stays": "/bin/stays"}.get(name)

        monkeypatch.setattr(shutil, "which", which)

        cfg = tmp_path / "claude_desktop_config.json"
        cfg.write_text(json.dumps({"mcpServers": {"stays": {"command": "/bin/stays", "args": ["mcp"]}}}))
        monkeypatch.setattr(claude_backend, "claude_desktop_config_path", lambda: cfg)

        # Claude Code reports `stays` already registered.
        monkeypatch.setattr(
            claude_backend.subprocess,
            "run",
            lambda argv, **kw: subprocess.CompletedProcess(argv, 0, stdout="", stderr=""),
        )
        monkeypatch.setattr(claude_backend.subprocess, "call", lambda argv: 0)

        report = claude_backend.register()
        assert report.fallback_json is None, (
            f"fallback_json should be None when clients are detected; got {report.fallback_json!r}"
        )
        assert not any("No Claude client" in m for m in report.messages)

    def test_already_registered_no_replace_skips_backup(self, monkeypatch, tmp_path):
        """Regression: a no-op re-run must not litter the config dir with
        empty backup files. Backups are only created when we're about to
        mutate or when we can't safely parse the existing file.
        """

        def which(name):
            return {"claude": "/bin/claude", "stays": "/bin/stays"}.get(name)

        monkeypatch.setattr(shutil, "which", which)
        cfg = tmp_path / "claude_desktop_config.json"
        cfg.write_text(json.dumps({"mcpServers": {"stays": {"command": "/bin/stays", "args": ["mcp"]}}}))
        monkeypatch.setattr(claude_backend, "claude_desktop_config_path", lambda: cfg)
        monkeypatch.setattr(
            claude_backend.subprocess,
            "run",
            lambda argv, **kw: subprocess.CompletedProcess(argv, 0, stdout="", stderr=""),
        )
        monkeypatch.setattr(claude_backend.subprocess, "call", lambda argv: 0)

        report = claude_backend.register()
        assert report.backup_path is None
        bak_files = list(cfg.parent.glob("*.bak-*"))
        assert not bak_files, f"No-op re-run should not create backups; found {bak_files}"

    def test_desktop_patch_preserves_existing(self, monkeypatch, tmp_path):
        monkeypatch.setattr(
            shutil,
            "which",
            lambda name: "/bin/stays" if name == "stays" else None,
        )
        cfg = tmp_path / "claude_desktop_config.json"
        cfg.parent.mkdir(parents=True, exist_ok=True)
        cfg.write_text(json.dumps({"mcpServers": {"other": {"command": "x"}}}))
        monkeypatch.setattr(claude_backend, "claude_desktop_config_path", lambda: cfg)
        report = claude_backend.register(force_desktop_only=True)
        assert report.claude_desktop_patched
        data = json.loads(cfg.read_text())
        assert "other" in data["mcpServers"]
        assert "stays" in data["mcpServers"]
        assert data["mcpServers"]["stays"]["command"] == "/bin/stays"

    def test_desktop_patch_writes_backup(self, monkeypatch, tmp_path):
        monkeypatch.setattr(shutil, "which", lambda name: "/bin/stays" if name == "stays" else None)
        cfg = tmp_path / "claude_desktop_config.json"
        cfg.parent.mkdir(parents=True, exist_ok=True)
        cfg.write_text(json.dumps({"mcpServers": {}}))
        monkeypatch.setattr(claude_backend, "claude_desktop_config_path", lambda: cfg)
        report = claude_backend.register(force_desktop_only=True)
        assert report.backup_path is not None
        assert report.backup_path.exists()

    def test_claude_code_detection_and_add(self, monkeypatch, tmp_path):
        def which(name):
            if name == "claude":
                return "/bin/claude"
            if name == "stays":
                return "/bin/stays"
            return None

        monkeypatch.setattr(shutil, "which", which)
        monkeypatch.setattr(
            claude_backend,
            "claude_desktop_config_path",
            lambda: tmp_path / "no_desktop" / "cfg.json",
        )
        run_calls = []

        def fake_run(argv, **kwargs):
            run_calls.append(argv)
            # `claude mcp get stays` probes existing registration — return
            # non-zero so the backend proceeds with `mcp add`.
            rc = 1 if "get" in argv else 0
            return subprocess.CompletedProcess(argv, rc, stdout="", stderr="")

        call_calls = []

        def fake_call(argv):
            call_calls.append(argv)
            return 0

        monkeypatch.setattr(claude_backend.subprocess, "run", fake_run)
        monkeypatch.setattr(claude_backend.subprocess, "call", fake_call)
        report = claude_backend.register()
        assert report.claude_code_registered
        # Pin the EXACT argv shape — `claude mcp add` requires options
        # before the server name, and the command goes after `--`:
        #   claude mcp add -s user stays -- /bin/stays mcp
        add_call = call_calls[-1]
        assert add_call == [
            "/bin/claude",
            "mcp",
            "add",
            "-s",
            "user",
            "stays",
            "--",
            "/bin/stays",
            "mcp",
        ]


class TestCodex:
    def test_no_binary_falls_back_to_toml(self, monkeypatch):
        monkeypatch.setattr(shutil, "which", lambda name: "/bin/stays" if name == "stays" else None)
        report = codex_backend.register()
        assert report.fallback_toml is not None
        assert "[mcp_servers.stays]" in report.fallback_toml
        assert "/bin/stays" in report.fallback_toml

    def test_print_toml_only(self, monkeypatch):
        monkeypatch.setattr(shutil, "which", lambda name: "/bin/stays" if name == "stays" else None)
        report = codex_backend.register(print_toml_only=True)
        assert report.fallback_toml is not None
        assert "command" in report.fallback_toml
        assert "args" in report.fallback_toml

    def test_add_invoked_when_not_registered(self, monkeypatch):
        def which(name):
            return {"codex": "/bin/codex", "stays": "/bin/stays"}.get(name)

        monkeypatch.setattr(shutil, "which", which)

        def fake_run(argv, **kwargs):
            # `codex mcp list --json` returns empty array
            return subprocess.CompletedProcess(argv, 0, stdout="[]", stderr="")

        add_calls = []

        def fake_call(argv):
            add_calls.append(argv)
            return 0

        monkeypatch.setattr(codex_backend.subprocess, "run", fake_run)
        monkeypatch.setattr(codex_backend.subprocess, "call", fake_call)

        report = codex_backend.register()
        assert report.registered
        assert add_calls, "codex mcp add should have been invoked"
        # Pin exact argv shape. Codex CLI: `codex mcp add NAME -- CMD ARGS...`.
        # No scope flag (Codex has no per-user/project scopes today).
        invoked = add_calls[-1]
        assert invoked == [
            "/bin/codex",
            "mcp",
            "add",
            "stays",
            "--",
            "/bin/stays",
            "mcp",
        ]

    def test_already_registered_no_replace(self, monkeypatch):
        def which(name):
            return {"codex": "/bin/codex", "stays": "/bin/stays"}.get(name)

        monkeypatch.setattr(shutil, "which", which)

        def fake_run(argv, **kwargs):
            return subprocess.CompletedProcess(
                argv,
                0,
                stdout='[{"name":"stays"}]',
                stderr="",
            )

        monkeypatch.setattr(codex_backend.subprocess, "run", fake_run)
        monkeypatch.setattr(codex_backend.subprocess, "call", lambda argv: 0)
        report = codex_backend.register()
        assert report.already_present
        assert not report.registered

    def test_replace_removes_then_adds(self, monkeypatch):
        def which(name):
            return {"codex": "/bin/codex", "stays": "/bin/stays"}.get(name)

        monkeypatch.setattr(shutil, "which", which)
        run_calls = []

        def fake_run(argv, **kwargs):
            run_calls.append(argv)
            return subprocess.CompletedProcess(
                argv,
                0,
                stdout='[{"name":"stays"}]',
                stderr="",
            )

        call_calls = []

        def fake_call(argv):
            call_calls.append(argv)
            return 0

        monkeypatch.setattr(codex_backend.subprocess, "run", fake_run)
        monkeypatch.setattr(codex_backend.subprocess, "call", fake_call)
        report = codex_backend.register(replace=True)
        assert report.registered
        # Pattern: `codex mcp list --json`, `codex mcp remove stays`, `codex mcp add ...`
        remove_invocations = [r for r in run_calls if "remove" in r]
        assert remove_invocations, "Should have run `codex mcp remove` before add"


class TestChatGPT:
    def test_instructions_include_developer_mode(self):
        out = chatgpt_backend.build()
        text = "\n".join(out.messages)
        assert "Developer Mode" in text

    def test_instructions_include_oauth_requirement(self):
        out = chatgpt_backend.build()
        text = "\n".join(out.messages)
        assert "OAuth 2.1" in text or "OAuth" in text

    def test_instructions_include_tunnel_options(self):
        out = chatgpt_backend.build()
        text = "\n".join(out.messages)
        assert "ngrok" in text
        assert "cloudflared" in text

    def test_settings_url_populated(self):
        out = chatgpt_backend.build()
        assert out.settings_url.startswith("https://chatgpt.com")

    def test_mentions_mcp_http_limitation(self):
        out = chatgpt_backend.build()
        text = "\n".join(out.messages)
        assert "stays mcp-http" in text
        assert "HTTP" in text  # mentions it's plain HTTP on 127.0.0.1


class TestClaudeDesktopEdgeCases:
    def test_desktop_config_paths_per_os(self, monkeypatch):
        """Cover lines 47-53: per-OS config paths."""
        darwin = claude_backend.claude_desktop_config_path("Darwin")
        linux = claude_backend.claude_desktop_config_path("Linux")
        windows = claude_backend.claude_desktop_config_path("Windows")
        other = claude_backend.claude_desktop_config_path("Plan9")

        assert "Library/Application Support/Claude" in str(darwin)
        assert ".config/Claude" in str(linux)
        assert "Claude" in str(windows)
        assert ".claude_desktop_config.json" in str(other)

    def test_desktop_patch_fresh_no_existing_file(self, monkeypatch, tmp_path):
        """Cover lines 114-115: data = {} when file doesn't exist."""
        monkeypatch.setattr(shutil, "which", lambda name: "/bin/stays" if name == "stays" else None)
        cfg = tmp_path / "Claude" / "claude_desktop_config.json"
        monkeypatch.setattr(claude_backend, "claude_desktop_config_path", lambda: cfg)
        # Parent dir is created by the backend; file does NOT exist.
        cfg.parent.mkdir(parents=True, exist_ok=True)
        report = claude_backend.register(force_desktop_only=True)
        assert report.claude_desktop_patched
        assert report.backup_path is None  # no backup needed for fresh file
        data = json.loads(cfg.read_text())
        assert "stays" in data["mcpServers"]

    def test_desktop_patch_replace_existing_stays(self, monkeypatch, tmp_path):
        """Cover line 129->135: replace=True path overwrites existing."""
        monkeypatch.setattr(shutil, "which", lambda name: "/new/stays" if name == "stays" else None)
        cfg = tmp_path / "claude_desktop_config.json"
        cfg.write_text(json.dumps({"mcpServers": {"stays": {"command": "/old/stays", "args": ["mcp"]}}}))
        monkeypatch.setattr(claude_backend, "claude_desktop_config_path", lambda: cfg)
        report = claude_backend.register(force_desktop_only=True, replace=True)
        assert report.claude_desktop_patched
        data = json.loads(cfg.read_text())
        assert data["mcpServers"]["stays"]["command"] == "/new/stays"

    def test_desktop_patch_existing_stays_no_replace_skips(self, monkeypatch, tmp_path):
        """Cover lines 128-132: already-present no-replace path."""
        monkeypatch.setattr(shutil, "which", lambda name: "/old/stays" if name == "stays" else None)
        cfg = tmp_path / "claude_desktop_config.json"
        cfg.write_text(json.dumps({"mcpServers": {"stays": {"command": "/old/stays"}}}))
        monkeypatch.setattr(claude_backend, "claude_desktop_config_path", lambda: cfg)
        report = claude_backend.register(force_desktop_only=True)
        assert not report.claude_desktop_patched  # skipped
        assert any("already" in m for m in report.messages)

    def test_desktop_patch_malformed_json_raises(self, monkeypatch, tmp_path):
        """Cover lines 110-113: MalformedDesktopConfigError on bad JSON."""
        monkeypatch.setattr(shutil, "which", lambda name: "/bin/stays" if name == "stays" else None)
        cfg = tmp_path / "claude_desktop_config.json"
        cfg.write_text("not json {{{")
        monkeypatch.setattr(claude_backend, "claude_desktop_config_path", lambda: cfg)
        with pytest.raises(claude_backend.MalformedDesktopConfigError):
            claude_backend.register(force_desktop_only=True)

    def test_desktop_patch_non_dict_toplevel_raises(self, monkeypatch, tmp_path):
        """Cover lines 117-120: MalformedDesktopConfigError on non-object toplevel."""
        monkeypatch.setattr(shutil, "which", lambda name: "/bin/stays" if name == "stays" else None)
        cfg = tmp_path / "claude_desktop_config.json"
        cfg.write_text(json.dumps(["not", "a", "dict"]))
        monkeypatch.setattr(claude_backend, "claude_desktop_config_path", lambda: cfg)
        with pytest.raises(claude_backend.MalformedDesktopConfigError):
            claude_backend.register(force_desktop_only=True)

    def test_claude_code_already_registered_no_replace(self, monkeypatch, tmp_path):
        """Cover lines 74-79: already-registered + no-replace skips."""

        def which(name):
            return {"claude": "/bin/claude", "stays": "/bin/stays"}.get(name)

        monkeypatch.setattr(shutil, "which", which)
        monkeypatch.setattr(claude_backend, "claude_desktop_config_path", lambda: tmp_path / "nope" / "cfg.json")

        # `claude mcp get stays` returns 0 -> already registered
        monkeypatch.setattr(
            claude_backend.subprocess,
            "run",
            lambda argv, **kw: subprocess.CompletedProcess(argv, 0, stdout="", stderr=""),
        )
        monkeypatch.setattr(claude_backend.subprocess, "call", lambda argv: 0)
        report = claude_backend.register()
        assert not report.claude_code_registered  # skipped
        assert any("already" in m for m in report.messages)


class TestCodexEdgeCases:
    def test_is_registered_nonzero_returncode_returns_false(self, monkeypatch):
        """Cover line 55: codex mcp list --json fails -> not registered."""

        def which(name):
            return {"codex": "/bin/codex", "stays": "/bin/stays"}.get(name)

        monkeypatch.setattr(shutil, "which", which)
        monkeypatch.setattr(
            codex_backend.subprocess,
            "run",
            lambda argv, **kw: subprocess.CompletedProcess(argv, 1, stdout="", stderr="err"),
        )
        monkeypatch.setattr(codex_backend.subprocess, "call", lambda argv: 0)
        report = codex_backend.register()
        # Non-zero returncode -> not registered -> proceeds to add
        assert report.registered

    def test_is_registered_invalid_json_returns_false(self, monkeypatch):
        """Cover lines 58-59: non-JSON list output -> not registered."""

        def which(name):
            return {"codex": "/bin/codex", "stays": "/bin/stays"}.get(name)

        monkeypatch.setattr(shutil, "which", which)
        monkeypatch.setattr(
            codex_backend.subprocess,
            "run",
            lambda argv, **kw: subprocess.CompletedProcess(argv, 0, stdout="not json", stderr=""),
        )
        monkeypatch.setattr(codex_backend.subprocess, "call", lambda argv: 0)
        report = codex_backend.register()
        assert report.registered

    def test_is_registered_dict_format(self, monkeypatch):
        """Cover lines 60-61: codex returns a dict (name -> config)."""

        def which(name):
            return {"codex": "/bin/codex", "stays": "/bin/stays"}.get(name)

        monkeypatch.setattr(shutil, "which", which)
        monkeypatch.setattr(
            codex_backend.subprocess,
            "run",
            lambda argv, **kw: subprocess.CompletedProcess(
                argv,
                0,
                stdout='{"stays": {"command": "x"}}',
                stderr="",
            ),
        )
        monkeypatch.setattr(codex_backend.subprocess, "call", lambda argv: 0)
        report = codex_backend.register()
        assert report.already_present

    def test_is_registered_unexpected_shape_returns_false(self, monkeypatch):
        """Cover line 66: codex returns neither dict nor list."""

        def which(name):
            return {"codex": "/bin/codex", "stays": "/bin/stays"}.get(name)

        monkeypatch.setattr(shutil, "which", which)
        monkeypatch.setattr(
            codex_backend.subprocess,
            "run",
            lambda argv, **kw: subprocess.CompletedProcess(argv, 0, stdout='"string"', stderr=""),
        )
        monkeypatch.setattr(codex_backend.subprocess, "call", lambda argv: 0)
        report = codex_backend.register()
        assert report.registered

    def test_add_command_failure_falls_back_to_toml(self, monkeypatch):
        """Cover lines 107-108: codex mcp add non-zero exit -> TOML fallback."""

        def which(name):
            return {"codex": "/bin/codex", "stays": "/bin/stays"}.get(name)

        monkeypatch.setattr(shutil, "which", which)
        monkeypatch.setattr(
            codex_backend.subprocess,
            "run",
            lambda argv, **kw: subprocess.CompletedProcess(argv, 0, stdout="[]", stderr=""),
        )
        monkeypatch.setattr(codex_backend.subprocess, "call", lambda argv: 1)  # add fails
        report = codex_backend.register()
        assert not report.registered
        assert report.fallback_toml is not None
        assert "[mcp_servers.stays]" in report.fallback_toml


class TestBackendsProtocol:
    """Coverage for the Protocol-path wrappers (stays.mcp.setup.BACKENDS).

    The legacy module-level ``register()`` / ``build()`` calls tested
    above stay the authoritative source of truth — these tests only
    verify that adapters correctly forward kwargs and wrap reports.
    """

    def test_backends_registry_populated(self):
        assert set(BACKENDS.keys()) == {"claude", "codex", "chatgpt"}

    def test_backends_claude_register_forwards_kwargs(self, monkeypatch):
        """ClaudeAdapter.register must forward every kwarg to claude.register."""
        captured: dict[str, object] = {}

        def fake_register(**kwargs):
            captured.update(kwargs)
            rep = claude_backend.ClaudeSetupReport()
            rep.claude_code_registered = True
            rep.messages.append("ok")
            return rep

        monkeypatch.setattr(claude_backend, "register", fake_register)
        report = BACKENDS["claude"].register(
            replace=True,
            force_desktop_only=False,
            print_json_only=False,
        )
        assert captured == {
            "replace": True,
            "force_desktop_only": False,
            "print_json_only": False,
        }
        assert isinstance(report, SetupReport)
        assert report.kind == "claude"
        assert report.ok is True
        assert "ok" in report.message

    def test_backends_claude_register_surfaces_fallback_json(self, monkeypatch):
        """When the legacy register returns a fallback_json, the adapter
        must surface it via ``config_text``."""

        def fake_register(**kwargs):
            rep = claude_backend.ClaudeSetupReport()
            rep.fallback_json = '{"mcpServers": {"stays": {}}}'
            rep.messages.append("No Claude client detected.")
            return rep

        monkeypatch.setattr(claude_backend, "register", fake_register)
        report = BACKENDS["claude"].register()
        assert report.ok is True  # fallback json counts as useful output
        assert report.config_text is not None
        assert "mcpServers" in report.config_text

    def test_backends_codex_register_forwards_kwargs(self, monkeypatch):
        """CodexAdapter.register must forward kwargs verbatim."""
        captured: dict[str, object] = {}

        def fake_register(**kwargs):
            captured.update(kwargs)
            rep = codex_backend.CodexSetupReport()
            rep.registered = True
            rep.messages.append("Codex: registered 'stays'.")
            return rep

        monkeypatch.setattr(codex_backend, "register", fake_register)
        report = BACKENDS["codex"].register(replace=False, print_toml_only=True)
        assert captured == {"replace": False, "print_toml_only": True}
        assert isinstance(report, SetupReport)
        assert report.kind == "codex"
        assert report.ok is True
        assert "registered" in report.message

    def test_backends_codex_register_returns_fallback_toml(self, monkeypatch):
        """When the legacy register surfaces fallback_toml, it must end
        up on ``SetupReport.config_text``."""

        def fake_register(**kwargs):
            rep = codex_backend.CodexSetupReport()
            rep.fallback_toml = '[mcp_servers.stays]\ncommand = "/bin/stays"\n'
            rep.messages.append("Codex CLI not found.")
            return rep

        monkeypatch.setattr(codex_backend, "register", fake_register)
        report = BACKENDS["codex"].register()
        assert report.ok is True
        assert report.config_text is not None
        assert "[mcp_servers.stays]" in report.config_text

    def test_backends_chatgpt_build_instructions_is_non_empty(self):
        """ChatGPTAdapter.build_instructions must be non-empty and
        include the things we document (OAuth, Developer Mode)."""
        text = BACKENDS["chatgpt"].build_instructions()
        assert text  # non-empty
        assert "OAuth" in text
        assert "Developer Mode" in text
        assert "chatgpt.com" in text

    def test_backends_chatgpt_register_returns_ok_report_with_config_text(self):
        """ChatGPT has no automated registration — register() must
        return ok=True with the instructions materialized as
        ``config_text`` so callers can treat every backend uniformly."""
        report = BACKENDS["chatgpt"].register()
        assert isinstance(report, SetupReport)
        assert report.kind == "chatgpt"
        assert report.ok is True
        assert report.config_text is not None
        assert report.config_text == BACKENDS["chatgpt"].build_instructions()

    def test_backends_chatgpt_register_ignores_unknown_kwargs(self):
        """ChatGPTAdapter.register must tolerate arbitrary kwargs so
        caller code that passes ``replace=True`` (valid for other
        backends) doesn't blow up."""
        report = BACKENDS["chatgpt"].register(replace=True, foo="bar")
        assert report.ok is True
