from __future__ import annotations

import argparse
import importlib.util
import io
import sys
import tarfile
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

SCRIPT = Path(__file__).parents[1] / "skills" / "hermes-maintenance" / "scripts" / "hermes-maintenance.py"
SPEC = importlib.util.spec_from_file_location("hermes_maintenance", SCRIPT)
assert SPEC and SPEC.loader
module = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = module
SPEC.loader.exec_module(module)


def args(home: Path, **overrides):
    values = {
        "mode": "native",
        "home": str(home),
        "container": "test-container",
        "state_dir": str(home / "maintenance-test"),
        "retention_days": 60,
        "backup_keep": 2,
        "log_lines": 100,
        "list_segments": False,
        "plan": False,
        "status": False,
        "next": False,
        "segment": None,
        "reset_run": False,
        "apply": False,
        "include_quarterly": False,
        "force": False,
    }
    values.update(overrides)
    return argparse.Namespace(**values)


class MaintenanceTests(unittest.TestCase):
    def fixture(self):
        temp = tempfile.TemporaryDirectory()
        root = Path(temp.name)
        (root / "config.yaml").write_text("_config_version: 33\nmemory:\n  provider: ''\n")
        profile = root / "profiles" / "example-agent"
        profile.mkdir(parents=True)
        (profile / "config.yaml").write_text("_config_version: 33\nmemory:\n  provider: ''\n")
        return temp, root, profile

    def test_redact_secret_assignments_and_bot_urls(self):
        text = (
            "API_KEY=abc123\n"
            "token: yaml-secret\n"
            "\"access_token\": \"json-secret\",\n"
            "body={\"api_key\":\"compact-secret\",\"name\":\"fixture\"}\n"
            "items=[{\"client_secret\":\"array-secret\"}]\n"
            "nested={\"data\":{\"auth_token\":\"nested-secret\"}}\n"
            "deep={\"a\":{\"b\":{\"database_password\":\"deep-secret\"}}}\n"
            "value=ok\n"
            "https://api.telegram.org/bot123:secret/getMe"
        )
        output = module.redact(text)
        self.assertNotIn("abc123", output)
        self.assertNotIn("yaml-secret", output)
        self.assertNotIn("json-secret", output)
        self.assertNotIn("compact-secret", output)
        self.assertNotIn("array-secret", output)
        self.assertNotIn("nested-secret", output)
        self.assertNotIn("deep-secret", output)
        self.assertIn('\"name\":\"fixture\"', output)
        self.assertNotIn("123:secret", output)
        self.assertIn("value=ok", output)

    def test_force_does_not_bypass_quarterly_gate(self):
        temp, root, _ = self.fixture()
        self.addCleanup(temp.cleanup)
        maintenance = module.Maintenance(args(root, force=True))
        state = maintenance.load_state()
        segment = next(s for s in module.build_segments(maintenance) if s.name == "profile-backups")
        self.assertFalse(module.due(state, segment, include_quarterly=False, force=True))
        self.assertTrue(module.due(state, segment, include_quarterly=True, force=True))

    def test_memory_provider_parser_does_not_cross_yaml_sections(self):
        temp, root, _ = self.fixture()
        self.addCleanup(temp.cleanup)
        (root / "config.yaml").write_text("memory:\n  enabled: true\nmodel:\n  provider: example\n")
        maintenance = module.Maintenance(args(root))
        maintenance.run_id = "test"
        result = maintenance.config_hygiene()[0]
        self.assertIn("memory_provider=built-in", result["stdout_tail"])

    def test_discovers_only_profile_directories_with_config(self):
        temp, root, _ = self.fixture()
        self.addCleanup(temp.cleanup)
        (root / "profiles" / "ignored").mkdir()
        maintenance = module.Maintenance(args(root))
        self.assertEqual(maintenance.profiles(), ["default", "example-agent"])

    def test_auto_mode_resolves_after_container_is_initialized(self):
        temp, root, _ = self.fixture()
        self.addCleanup(temp.cleanup)
        with patch.object(module.Maintenance, "_container_exists", return_value=False):
            maintenance = module.Maintenance(args(root, mode="auto"))
        self.assertEqual(maintenance.container, "test-container")
        self.assertEqual(maintenance.mode, "native")

    def test_docker_commands_use_privilege_drop_shim(self):
        temp, root, _ = self.fixture()
        self.addCleanup(temp.cleanup)
        maintenance = module.Maintenance(args(root, mode="docker"))
        command = maintenance.hermes_cmd("example-agent", "doctor")
        self.assertEqual(command, ["docker", "exec", "test-container", "hermes", "-p", "example-agent", "doctor"])
        self.assertNotIn("/opt/hermes/.venv/bin/hermes", command)

    def test_config_hygiene_detects_collision_without_disclosing_token(self):
        temp, root, profile = self.fixture()
        self.addCleanup(temp.cleanup)
        token = "synthetic-secret-token"
        (root / ".env").write_text(f"TELEGRAM_BOT_TOKEN={token}\n")
        (profile / ".env").write_text(f"TELEGRAM_BOT_TOKEN={token}\nTERMINAL_CWD=/old/path\n")
        maintenance = module.Maintenance(args(root))
        maintenance.run_id = "test"
        capture = io.StringIO()
        with redirect_stdout(capture):
            result = maintenance.config_hygiene()[0]
        output = capture.getvalue() + result["stdout_tail"]
        self.assertEqual(result["code"], 1)
        self.assertIn("telegram_credential_collisions", output)
        self.assertIn("TERMINAL_CWD", output)
        self.assertNotIn(token, output)
        self.assertNotRegex(output, r"[a-f0-9]{64}")

    def test_backups_are_allowlisted_and_exclude_secrets_and_databases(self):
        temp, root, profile = self.fixture()
        self.addCleanup(temp.cleanup)
        (profile / "SOUL.md").write_text("Synthetic persona\n")
        (profile / "AGENTS.md").write_text("Synthetic rules\n")
        (profile / "prefill.json").write_text("{}\n")
        (profile / ".env").write_text("API_KEY=synthetic\n")
        (profile / "state.db").write_bytes(b"not-a-real-db")
        (profile / "memories").mkdir()
        (profile / "memories" / "MEMORY.md").write_text("Synthetic memory\n")
        maintenance = module.Maintenance(args(root, apply=True, include_quarterly=True))
        maintenance.run_id = "test"
        results = maintenance.profile_backups()
        self.assertTrue(all(result["code"] == 0 for result in results))
        archives = sorted((root / "profile-backups").glob("example-agent-*.tar.gz"))
        self.assertEqual(len(archives), 1)
        with tarfile.open(archives[0]) as archive:
            names = archive.getnames()
        self.assertTrue(any(name.endswith("config.yaml") for name in names))
        self.assertTrue(any(name.endswith("MEMORY.md") for name in names))
        self.assertFalse(any(name.endswith("SOUL.md") for name in names))
        self.assertFalse(any(name.endswith("AGENTS.md") for name in names))
        self.assertFalse(any(name.endswith("prefill.json") for name in names))
        self.assertFalse(any(name.endswith(".env") for name in names))
        self.assertFalse(any(name.endswith("state.db") for name in names))

    def test_mutating_segment_requires_apply(self):
        temp, root, _ = self.fixture()
        self.addCleanup(temp.cleanup)
        maintenance = module.Maintenance(args(root))
        state = maintenance.load_state()
        segment = next(s for s in module.build_segments(maintenance) if s.name == "session-prune")
        self.assertEqual(module.run_segment(maintenance, segment, state), 2)

    def test_quarterly_segment_requires_explicit_gate(self):
        temp, root, _ = self.fixture()
        self.addCleanup(temp.cleanup)
        maintenance = module.Maintenance(args(root, apply=True))
        state = maintenance.load_state()
        segment = next(s for s in module.build_segments(maintenance) if s.name == "profile-backups")
        self.assertEqual(module.run_segment(maintenance, segment, state), 2)


if __name__ == "__main__":
    unittest.main()
