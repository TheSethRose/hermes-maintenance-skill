#!/usr/bin/env python3
"""Segmented, privacy-safe maintenance runner for Hermes Agent.

The runner supports native Hermes homes and multi-profile Docker containers.
It discovers profiles from disk, never prints secret values, runs at most one
segment with --next, and requires --apply for mutating operations.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tarfile
import time
import urllib.request
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

WEEKLY_DAYS = 7
MONTHLY_DAYS = 30
QUARTERLY_DAYS = 90
DEFAULT_RETENTION_DAYS = 60
DEFAULT_BACKUP_KEEP = 4
LOCK_STALE_SECONDS = 3 * 60 * 60
TAIL_CHARS = 4000

CADENCE_DAYS = {"weekly": WEEKLY_DAYS, "monthly": MONTHLY_DAYS, "quarterly": QUARTERLY_DAYS}
SECRET_KEY_FRAGMENT = r"(?:TOKEN|SECRET|PASSWORD|PASSWD|API[_-]?KEY|PRIVATE[_-]?KEY|AUTH(?:ORIZATION)?|COOKIE|SESSION[_-]?KEY)"
SECRET_KEY_RE = re.compile(SECRET_KEY_FRAGMENT, re.IGNORECASE)
COLON_SECRET_ASSIGN_RE = re.compile(
    rf"(?P<prefix>(?:^|[\{{\[,\s:-])['\"]?[A-Za-z0-9_.-]*{SECRET_KEY_FRAGMENT}[A-Za-z0-9_.-]*['\"]?\s*:\s*)"
    r"(?P<value>\"(?:\\.|[^\"])*\"|'(?:\\.|[^'])*'|[^,}\]]+)"
    ,
    re.IGNORECASE,
)
CONFIG_VERSION_RE = re.compile(r"^\s*_config_version\s*:\s*(\d+)\s*$", re.MULTILINE)
LOG_PATTERNS = {
    "error": re.compile(r"\bERROR\b|Traceback", re.IGNORECASE),
    "token_collision": re.compile(r"token already in use|terminated by other getUpdates", re.IGNORECASE),
    "port_conflict": re.compile(r"address already in use|Errno 48|Errno 98", re.IGNORECASE),
    "database": re.compile(r"database disk image is malformed|unable to get the page|fts.*malformed", re.IGNORECASE),
    "provider": re.compile(r"APIConnectionError|authentication failed|HTTP 401|HTTP 403", re.IGNORECASE),
}


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def now_iso() -> str:
    return utc_now().isoformat(timespec="seconds")


def parse_time(value: str | None) -> float | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


def redact(text: str) -> str:
    """Redact likely secret assignments and bot-token URL fragments."""
    lines: list[str] = []
    for raw in text.splitlines():
        line = re.sub(r"(https://api\.telegram\.org/bot)[^/\s]+", r"\1[REDACTED]", raw)
        if "=" in line:
            key, _value = line.split("=", 1)
            if SECRET_KEY_RE.search(key):
                line = f"{key}=[REDACTED]"
        line = COLON_SECRET_ASSIGN_RE.sub(lambda match: f"{match.group('prefix')}[REDACTED]", line)
        line = re.sub(r"(?i)(bearer\s+)[A-Za-z0-9._~+\-/=]+", r"\1[REDACTED]", line)
        lines.append(line)
    return "\n".join(lines)


@dataclass(frozen=True)
class Segment:
    name: str
    bucket: str
    description: str
    mutating: bool
    quarterly_gate: bool
    handler: Callable[[], list[dict[str, Any]]]


class Maintenance:
    def __init__(self, args: argparse.Namespace):
        self.args = args
        self.container = args.container
        self.mode = self._resolve_mode(args.mode)
        self.home = self._resolve_home(args.home)
        self.state_dir = Path(args.state_dir).expanduser() if args.state_dir else self.home / "maintenance"
        self.state_file = self.state_dir / "state.json"
        self.log_file = self.state_dir / "maintenance.log"
        self.lock_file = self.state_dir / "run.lock"
        self.backup_dir = self.home / "profile-backups"
        self.run_id = ""

    def _resolve_mode(self, requested: str) -> str:
        if requested != "auto":
            return requested
        if shutil.which("docker") and self._container_exists(self.container):
            return "docker"
        return "native"

    def _container_exists(self, name: str) -> bool:
        result = subprocess.run(
            ["docker", "inspect", name],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
        return result.returncode == 0

    def _resolve_home(self, requested: str | None) -> Path:
        if requested:
            return Path(requested).expanduser().resolve()
        if self.mode == "native":
            return Path(os.environ.get("HERMES_HOME", Path.home() / ".hermes")).expanduser().resolve()
        try:
            proc = subprocess.run(
                ["docker", "inspect", self.container, "--format", "{{json .Mounts}}"],
                text=True,
                capture_output=True,
                timeout=30,
                check=False,
            )
            mounts = json.loads(proc.stdout) if proc.returncode == 0 else []
            for mount in mounts:
                if mount.get("Destination") == "/opt/data" and mount.get("Source"):
                    return Path(mount["Source"]).expanduser().resolve()
        except (json.JSONDecodeError, OSError, subprocess.SubprocessError):
            pass
        raise SystemExit("Could not discover the host path mounted at /opt/data; pass --home PATH")

    def ensure_dirs(self) -> None:
        self.state_dir.mkdir(parents=True, exist_ok=True)

    def profiles(self) -> list[str]:
        result = ["default"]
        root = self.home / "profiles"
        if root.exists():
            for path in sorted(root.iterdir()):
                if path.is_dir() and (path / "config.yaml").exists():
                    result.append(path.name)
        return result

    def profile_root(self, profile: str) -> Path:
        return self.home if profile == "default" else self.home / "profiles" / profile

    def hermes_cmd(self, profile: str, *args: str) -> list[str]:
        inner = ["hermes"]
        if profile != "default":
            inner += ["-p", profile]
        inner += list(args)
        if self.mode == "docker":
            # Use the image shim, not /opt/hermes/.venv/bin/hermes as root.
            return ["docker", "exec", self.container, *inner]
        return inner

    def run_command(self, cmd: list[str], label: str, segment: str, timeout: int = 300) -> dict[str, Any]:
        started = time.time()
        print(f"running: {label}", flush=True)
        try:
            proc = subprocess.run(
                cmd,
                cwd=str(self.home),
                text=True,
                capture_output=True,
                timeout=timeout,
                check=False,
            )
            result = {
                "label": label,
                "cmd": cmd,
                "code": proc.returncode,
                "seconds": round(time.time() - started, 1),
                "stdout_tail": redact(proc.stdout[-TAIL_CHARS:]),
                "stderr_tail": redact(proc.stderr[-TAIL_CHARS:]),
            }
        except subprocess.TimeoutExpired as exc:
            result = {
                "label": label,
                "cmd": cmd,
                "code": 124,
                "seconds": round(time.time() - started, 1),
                "stdout_tail": redact(exc.stdout[-TAIL_CHARS:] if isinstance(exc.stdout, str) else ""),
                "stderr_tail": redact(exc.stderr[-TAIL_CHARS:] if isinstance(exc.stderr, str) else f"timeout after {timeout}s"),
            }
        except OSError as exc:  # pragma: no cover - platform-specific execution failures
            result = {
                "label": label,
                "cmd": cmd,
                "code": 1,
                "seconds": round(time.time() - started, 1),
                "stdout_tail": "",
                "stderr_tail": redact(repr(exc)),
            }
        self.append_log(segment, result)
        status = "ok" if result["code"] == 0 else f"error {result['code']}"
        print(f"result: {label}: {status} ({result['seconds']}s)", flush=True)
        return result

    def result(self, label: str, segment: str, output: str, code: int = 0) -> dict[str, Any]:
        value = {
            "label": label,
            "cmd": [label],
            "code": code,
            "seconds": 0,
            "stdout_tail": redact(output[-TAIL_CHARS:]),
            "stderr_tail": "",
        }
        self.append_log(segment, value)
        print(value["stdout_tail"] or label, flush=True)
        return value

    def append_log(self, segment: str, result: dict[str, Any]) -> None:
        self.ensure_dirs()
        entry = {
            "timestamp": now_iso(),
            "run_id": self.run_id,
            "mode": self.mode,
            "segment": segment,
            "label": result["label"],
            "command": result["cmd"],
            "exit_code": result["code"],
            "elapsed_seconds": result["seconds"],
            "stdout_tail": result["stdout_tail"],
            "stderr_tail": result["stderr_tail"],
        }
        with self.log_file.open("a") as handle:
            handle.write(json.dumps(entry, sort_keys=True) + "\n")

    def load_state(self) -> dict[str, Any]:
        self.ensure_dirs()
        if not self.state_file.exists():
            return {"created_at": now_iso(), "last_run": {}, "runs": {}, "active_run_id": None}
        try:
            data = json.loads(self.state_file.read_text())
        except (json.JSONDecodeError, OSError):
            data = {"created_at": now_iso(), "last_run": {}, "runs": {}, "active_run_id": None, "state_read_error": True}
        data.setdefault("last_run", {})
        data.setdefault("runs", {})
        data.setdefault("active_run_id", None)
        return data

    def save_state(self, state: dict[str, Any]) -> None:
        self.ensure_dirs()
        temp = self.state_file.with_suffix(".tmp")
        temp.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n")
        temp.replace(self.state_file)

    def acquire_lock(self, segment: str) -> None:
        self.ensure_dirs()
        if self.lock_file.exists():
            try:
                data = json.loads(self.lock_file.read_text())
                pid = int(data.get("pid", 0))
                started = parse_time(data.get("started_at")) or 0
                alive = pid > 0 and self._pid_alive(pid)
                stale = not alive or time.time() - started > LOCK_STALE_SECONDS
            except (ValueError, json.JSONDecodeError, OSError):
                stale = True
            if stale:
                self.lock_file.unlink(missing_ok=True)
            else:
                raise SystemExit(f"Another segment is running; lock: {self.lock_file}")
        self.lock_file.write_text(json.dumps({"pid": os.getpid(), "segment": segment, "started_at": now_iso()}, indent=2) + "\n")

    def _pid_alive(self, pid: int) -> bool:
        return subprocess.run(
            ["ps", "-p", str(pid)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        ).returncode == 0

    def release_lock(self) -> None:
        self.lock_file.unlink(missing_ok=True)

    # Segment handlers
    def inventory(self) -> list[dict[str, Any]]:
        results = [self.run_command(self.hermes_cmd("default", "--version"), "Hermes version", "inventory", 120)]
        results.append(self.run_command(self.hermes_cmd("default", "profile", "list"), "profile inventory", "inventory", 180))
        versions = []
        for profile in self.profiles():
            config = self.profile_root(profile) / "config.yaml"
            match = CONFIG_VERSION_RE.search(config.read_text(errors="replace")) if config.exists() else None
            versions.append(f"{profile}: config_version={match.group(1) if match else 'unknown'}")
        results.append(self.result("config version inventory", "inventory", "\n".join(versions)))
        if self.mode == "docker":
            results.extend(self.docker_runtime())
        return results

    def config_migrate(self) -> list[dict[str, Any]]:
        return [self.run_command(self.hermes_cmd(p, "config", "migrate"), f"config migrate {p}", "config-migrate", 300) for p in self.profiles()]

    def config_check(self) -> list[dict[str, Any]]:
        return [self.run_command(self.hermes_cmd(p, "config", "check"), f"config check {p}", "config-check", 300) for p in self.profiles()]

    def gateway_status(self) -> list[dict[str, Any]]:
        return [self.run_command(self.hermes_cmd(p, "gateway", "status"), f"gateway status {p}", "gateway-status", 180) for p in self.profiles()]

    def doctor_all(self) -> list[dict[str, Any]]:
        return [self.run_command(self.hermes_cmd(p, "doctor"), f"doctor {p}", "doctor-all", 900) for p in self.profiles()]

    def skills_check(self) -> list[dict[str, Any]]:
        return [self.run_command(self.hermes_cmd("default", "skills", "check"), "skills check", "skills-check", 300)]

    def session_stats(self) -> list[dict[str, Any]]:
        return [self.run_command(self.hermes_cmd(p, "sessions", "stats"), f"sessions stats {p}", "session-stats", 300) for p in self.profiles()]

    def session_prune(self) -> list[dict[str, Any]]:
        days = str(self.args.retention_days)
        return [self.run_command(self.hermes_cmd(p, "sessions", "prune", "--older-than", days, "--yes"), f"sessions prune {p}", "session-prune", 900) for p in self.profiles()]

    def session_integrity(self) -> list[dict[str, Any]]:
        return [self.run_command(self.hermes_cmd(p, "sessions", "repair", "--check-only"), f"session integrity {p}", "session-integrity", 300) for p in self.profiles()]

    def memory_pressure(self) -> list[dict[str, Any]]:
        lines = []
        for profile in self.profiles():
            root = self.profile_root(profile)
            for rel in (Path("memories/MEMORY.md"), Path("memories/USER.md")):
                path = root / rel
                lines.append(f"{profile}/{rel.name}: {path.stat().st_size if path.exists() else 'missing'}")
        return [self.result("memory pressure", "memory-pressure", "\n".join(lines))]

    def config_hygiene(self) -> list[dict[str, Any]]:
        token_owners: dict[str, list[str]] = {}
        lines: list[str] = []
        for profile in self.profiles():
            root = self.profile_root(profile)
            config_text = (root / "config.yaml").read_text(errors="replace") if (root / "config.yaml").exists() else ""
            provider_match = re.search(r"(?m)^memory:\s*\n(?:^[ \t].*\n)*?^[ \t]+provider:\s*['\"]?([^'\"\n#]*)", config_text)
            provider = provider_match.group(1).strip() if provider_match else ""
            env_keys: set[str] = set()
            env_path = root / ".env"
            if env_path.exists():
                for raw in env_path.read_text(errors="replace").splitlines():
                    text = raw.strip()
                    if not text or text.startswith("#") or "=" not in text:
                        continue
                    key, value = text.split("=", 1)
                    env_keys.add(key)
                    if key in {"TELEGRAM_BOT_TOKEN", "TELEGRAM_TOKEN"} and value:
                        digest = hashlib.sha256(value.encode()).hexdigest()
                        token_owners.setdefault(digest, []).append(profile)
            stale = sorted(k for k in env_keys if k in {"TERMINAL_CWD", "MESSAGING_CWD"})
            mem0_keys = sorted(k for k in env_keys if k.startswith("MEM0_"))
            lines.append(
                f"{profile}: memory_provider={provider or 'built-in'} "
                f"deprecated_env={','.join(stale) or 'none'} mem0_env_keys={len(mem0_keys)}"
            )
        duplicates = [owners for owners in token_owners.values() if len(owners) > 1]
        lines.append(f"telegram_credential_collisions={duplicates or 'none'}")
        return [self.result("config hygiene", "config-hygiene", "\n".join(lines), 1 if duplicates else 0)]

    def cron_health(self) -> list[dict[str, Any]]:
        lines: list[str] = []
        failures = 0
        for profile in self.profiles():
            path = self.profile_root(profile) / "cron" / "jobs.json"
            if not path.exists():
                lines.append(f"{profile}: jobs=0 errors=0")
                continue
            try:
                jobs = json.loads(path.read_text()).get("jobs", [])
                errors = sum(1 for job in jobs if job.get("last_status") == "error" or job.get("state", {}).get("last_status") == "error")
                failures += errors
                lines.append(f"{profile}: jobs={len(jobs)} errors={errors}")
            except (json.JSONDecodeError, OSError):
                failures += 1
                lines.append(f"{profile}: jobs=unknown errors=parse_failure")
        return [self.result("cron health", "cron-health", "\n".join(lines), 1 if failures else 0)]

    def gateway_log_scan(self) -> list[dict[str, Any]]:
        counts: dict[str, dict[str, int]] = {}
        for profile in self.profiles():
            log_dir = self.profile_root(profile) / "logs"
            paths = [log_dir / "gateway.log", log_dir / "gateway.error.log"]
            profile_counts = {name: 0 for name in LOG_PATTERNS}
            for path in paths:
                if not path.exists():
                    continue
                lines = path.read_text(errors="ignore").splitlines()[-self.args.log_lines :]
                for line in lines:
                    for name, pattern in LOG_PATTERNS.items():
                        if pattern.search(line):
                            profile_counts[name] += 1
            counts[profile] = profile_counts
        output = "\n".join(f"{profile}: " + " ".join(f"{k}={v}" for k, v in values.items()) for profile, values in counts.items())
        return [self.result("gateway log scan", "gateway-log-scan", output)]

    def docker_runtime(self) -> list[dict[str, Any]]:
        if self.mode != "docker":
            return [self.result("docker runtime", "docker-runtime", "not_applicable")]
        inspect = self.run_command(
            ["docker", "inspect", self.container, "--format", "Running={{.State.Running}} RestartCount={{.RestartCount}} Image={{.Config.Image}}"],
            "docker container state",
            "docker-runtime",
            120,
        )
        workers = self.run_command(
            ["docker", "exec", self.container, "sh", "-c", "ps -eo args= | grep '[h]ermes .*gateway run --replace' | wc -l"],
            "docker gateway worker count",
            "docker-runtime",
            120,
        )
        results = [inspect, workers]
        health_url = self._docker_health_url()
        if health_url:
            try:
                with urllib.request.urlopen(health_url, timeout=10) as response:
                    payload = response.read(1000).decode(errors="replace")
                results.append(self.result("docker API health", "docker-runtime", f"status={response.status} body={payload}"))
            except (OSError, TimeoutError, ValueError) as exc:
                results.append(self.result("docker API health", "docker-runtime", f"failed={type(exc).__name__}", 1))
        else:
            results.append(self.result("docker API health", "docker-runtime", "not_exposed"))
        return results

    def _docker_health_url(self) -> str | None:
        try:
            proc = subprocess.run(
                ["docker", "port", self.container, "8642/tcp"],
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                timeout=30,
                check=False,
            )
            if proc.returncode != 0 or not proc.stdout.strip():
                return None
            address = proc.stdout.strip().splitlines()[0]
            host, port = address.rsplit(":", 1)
            host = host.strip("[]")
            if host in {"0.0.0.0", "::"}:
                host = "127.0.0.1"
            return f"http://{host}:{port}/health"
        except (OSError, subprocess.SubprocessError, ValueError):
            return None

    def profile_backups(self) -> list[dict[str, Any]]:
        self.backup_dir.mkdir(parents=True, exist_ok=True)
        results = []
        for profile in self.profiles():
            root = self.profile_root(profile)
            stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
            output = self.backup_dir / f"{profile}-{stamp}.tar.gz"
            allowed = ["config.yaml", "memories", "skills", "cron/jobs.json", "scripts"]
            started = time.time()
            try:
                with tarfile.open(output, "w:gz") as archive:
                    for rel in allowed:
                        path = root / rel
                        if not path.exists():
                            continue
                        archive.add(path, arcname=f"{profile}/{rel}", filter=self._backup_filter)
                self._prune_backups(profile)
                result = {
                    "label": f"profile backup {profile}",
                    "cmd": ["profile-backup", profile],
                    "code": 0,
                    "seconds": round(time.time() - started, 1),
                    "stdout_tail": f"wrote {output}",
                    "stderr_tail": "",
                }
            except (OSError, tarfile.TarError) as exc:
                result = {
                    "label": f"profile backup {profile}",
                    "cmd": ["profile-backup", profile],
                    "code": 1,
                    "seconds": round(time.time() - started, 1),
                    "stdout_tail": "",
                    "stderr_tail": redact(repr(exc)),
                }
            self.append_log("profile-backups", result)
            results.append(result)
        return results

    def _backup_filter(self, info: tarfile.TarInfo) -> tarfile.TarInfo | None:
        parts = set(Path(info.name).parts)
        excluded = {".git", ".env", "auth.json", "auth.lock", "state.db", "sessions", "logs", "cache", ".cache", "node_modules", "__pycache__", "backups", "checkpoints"}
        if parts & excluded or info.name.endswith((".db-wal", ".db-shm", ".pyc")):
            return None
        return info

    def _prune_backups(self, profile: str) -> None:
        backups = sorted(self.backup_dir.glob(f"{profile}-*.tar.gz"), key=lambda p: p.stat().st_mtime, reverse=True)
        for old in backups[self.args.backup_keep :]:
            old.unlink(missing_ok=True)


def build_segments(m: Maintenance) -> list[Segment]:
    return [
        Segment("inventory", "weekly", "version, profiles and runtime inventory", False, False, m.inventory),
        Segment("config-migrate", "weekly", "migrate every discovered profile config", True, False, m.config_migrate),
        Segment("config-check", "weekly", "validate every discovered profile config", False, False, m.config_check),
        Segment("gateway-status", "weekly", "check every profile gateway", False, False, m.gateway_status),
        Segment("doctor-all", "monthly", "run Doctor independently for every profile", False, False, m.doctor_all),
        Segment("skills-check", "monthly", "check installed skill updates", False, False, m.skills_check),
        Segment("session-stats", "monthly", "collect session statistics for every profile", False, False, m.session_stats),
        Segment("session-prune", "monthly", "prune old sessions for every profile", True, False, m.session_prune),
        Segment("session-integrity", "monthly", "check every profile SQLite/FTS database", False, False, m.session_integrity),
        Segment("memory-pressure", "monthly", "report built-in memory file sizes", False, False, m.memory_pressure),
        Segment("config-hygiene", "monthly", "detect token collisions and stale env/config markers", False, False, m.config_hygiene),
        Segment("cron-health", "monthly", "report cron job counts and error states", False, False, m.cron_health),
        Segment("gateway-log-scan", "quarterly", "count recent actionable gateway log patterns", False, True, m.gateway_log_scan),
        Segment("docker-runtime", "weekly", "inspect Docker health when applicable", False, False, m.docker_runtime),
        Segment("profile-backups", "quarterly", "create allowlisted identity/config backups", True, True, m.profile_backups),
    ]


def due(state: dict[str, Any], segment: Segment, include_quarterly: bool, force: bool) -> bool:
    if segment.quarterly_gate and not include_quarterly:
        return False
    if force:
        return True
    last = parse_time(state.get("last_run", {}).get(segment.name))
    return last is None or time.time() - last >= CADENCE_DAYS[segment.bucket] * 86400


def pending_segments(m: Maintenance, segments: list[Segment], state: dict[str, Any], include_quarterly: bool, force: bool) -> list[Segment]:
    active = state.get("runs", {}).get(state.get("active_run_id"), {}) if state.get("active_run_id") else {}
    done = active.get("segments", {})
    return [s for s in segments if due(state, s, include_quarterly, force) and (force or done.get(s.name, {}).get("status") != "success")]


def run_segment(m: Maintenance, segment: Segment, state: dict[str, Any]) -> int:
    if segment.mutating and not m.args.apply:
        print(f"Refusing mutating segment '{segment.name}' without --apply", file=sys.stderr)
        return 2
    if segment.quarterly_gate and not m.args.include_quarterly:
        print(f"Refusing quarterly segment '{segment.name}' without --include-quarterly", file=sys.stderr)
        return 2
    active_id = state.get("active_run_id")
    if not active_id:
        active_id = utc_now().strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:8]
        state["active_run_id"] = active_id
        state.setdefault("runs", {})[active_id] = {"started_at": now_iso(), "segments": {}}
    m.run_id = active_id
    run = state["runs"][active_id]
    if any(v.get("status") == "failed" for v in run.get("segments", {}).values()) and not m.args.force:
        print("A previous segment failed; fix it and use --reset-run before continuing", file=sys.stderr)
        return 1
    m.acquire_lock(segment.name)
    try:
        print(f"HERMES_MAINTENANCE_SEGMENT_START name={segment.name}", flush=True)
        run.setdefault("segments", {})[segment.name] = {"status": "running", "started_at": now_iso()}
        m.save_state(state)
        started = time.time()
        results = segment.handler()
        code = next((int(r["code"]) for r in results if r.get("code")), 0)
        status = "success" if code == 0 else "failed"
        run["segments"][segment.name] = {
            "status": status,
            "started_at": run["segments"][segment.name]["started_at"],
            "completed_at": now_iso(),
            "seconds": round(time.time() - started, 1),
            "code": code,
        }
        if code == 0:
            state.setdefault("last_run", {})[segment.name] = now_iso()
        m.save_state(state)
        marker = "DONE" if code == 0 else "FAILED"
        print(f"HERMES_MAINTENANCE_SEGMENT_{marker} name={segment.name} code={code}", flush=True)
        return code
    finally:
        m.release_lock()


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Segmented Hermes Agent maintenance")
    p.add_argument("--mode", choices=["auto", "native", "docker"], default="auto")
    p.add_argument("--home", help="Hermes data root; auto-detected when possible")
    p.add_argument("--container", default=os.environ.get("HERMES_CONTAINER", "hermes"))
    p.add_argument("--state-dir", help="Override maintenance state/log directory")
    p.add_argument("--retention-days", type=int, default=DEFAULT_RETENTION_DAYS)
    p.add_argument("--backup-keep", type=int, default=DEFAULT_BACKUP_KEEP)
    p.add_argument("--log-lines", type=int, default=500)
    p.add_argument("--list-segments", action="store_true")
    p.add_argument("--plan", action="store_true")
    p.add_argument("--status", action="store_true")
    p.add_argument("--next", action="store_true")
    p.add_argument("--segment")
    p.add_argument("--reset-run", action="store_true")
    p.add_argument("--apply", action="store_true", help="Allow mutating segments")
    p.add_argument("--include-quarterly", action="store_true")
    p.add_argument("--force", action="store_true")
    return p


def main() -> int:
    args = parser().parse_args()
    if args.retention_days < 1 or args.backup_keep < 1 or args.log_lines < 1:
        raise SystemExit("retention-days, backup-keep and log-lines must be positive")
    m = Maintenance(args)
    segments = build_segments(m)
    by_name = {s.name: s for s in segments}
    state = m.load_state()

    if args.list_segments:
        for s in segments:
            flags = ["mutating" if s.mutating else "read-only", "quarterly-gated" if s.quarterly_gate else s.bucket]
            print(f"{s.name}\t{','.join(flags)}\t{s.description}")
        return 0
    if args.reset_run:
        state["active_run_id"] = None
        m.save_state(state)
        m.release_lock()
        print("reset active maintenance run")
        return 0
    if args.status:
        active = state.get("runs", {}).get(state.get("active_run_id"), {}) if state.get("active_run_id") else {}
        payload = {
            "mode": m.mode,
            "home": str(m.home),
            "container": m.container if m.mode == "docker" else None,
            "profiles": m.profiles(),
            "active_run_id": state.get("active_run_id"),
            "active_segments": active.get("segments", {}),
            "last_run": state.get("last_run", {}),
            "state_file": str(m.state_file),
            "log_file": str(m.log_file),
        }
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 0
    pending = pending_segments(m, segments, state, args.include_quarterly, args.force)
    if args.plan:
        print(f"mode={m.mode}\nhome={m.home}\nprofiles={','.join(m.profiles())}")
        for s in pending:
            gate = " requires=--apply" if s.mutating else ""
            if s.quarterly_gate:
                gate += " requires=--include-quarterly"
            print(f"- {s.name}:{gate}")
        return 0
    if args.segment:
        if args.segment not in by_name:
            raise SystemExit(f"Unknown segment: {args.segment}")
        return run_segment(m, by_name[args.segment], state)
    if args.next or len(sys.argv) == 1:
        if not pending:
            if args.next:
                print("HERMES_MAINTENANCE_COMPLETE")
            return 0
        segment = pending[0]
        print(f"HERMES_MAINTENANCE_NEXT_SEGMENT {segment.name}")
        return run_segment(m, segment, state)
    parser().print_help()
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
