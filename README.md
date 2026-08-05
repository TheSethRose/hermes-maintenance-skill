# Hermes Maintenance

A portable Hermes Agent skill for evidence-driven maintenance of native and multi-profile Docker installations.

It covers:

- per-profile configuration migration and validation
- native Hermes updates without modifying Docker images in place
- per-profile Doctor runs
- gateway and Docker runtime health
- Curator status and per-profile authentication checks with command output suppressed
- session statistics, retention and SQLite/FTS integrity
- built-in memory pressure
- cron error-state review
- privacy-safe platform/config hygiene
- recent gateway log-pattern review
- allowlisted profile backups
- narrow remediation and verification procedures

The included runner uses Python’s standard library, discovers profiles instead of assuming them and never prints environment values or credential hashes.

## Install

Directly from GitHub:

```bash
hermes skills install owner/repo/skills/hermes-maintenance
```

Or add the repository as a skill tap:

```bash
hermes skills tap add owner/repo
hermes skills install owner/repo/hermes-maintenance
```

Then load it in Hermes:

```text
/hermes-maintenance review this installation
```

## Runner examples

```bash
SCRIPT="$HOME/.hermes/skills/hermes-maintenance/scripts/hermes-maintenance.py"
python3 "$SCRIPT" --mode native --plan
python3 "$SCRIPT" --mode native --segment doctor-all
python3 "$SCRIPT" --mode docker --container hermes --segment session-integrity
```

Mutating segments require `--apply`. Every quarterly segment additionally requires `--include-quarterly`. `--force` bypasses cadence only; it never bypasses either safety gate.

The included native cron wrapper runs exactly one due weekly or monthly segment and passes the explicit `--apply` policy. It never enables quarterly work:

```bash
python3 "$HOME/.hermes/skills/hermes-maintenance/scripts/hermes-maintenance-cron.py"
```

Hermes cron only accepts real files under `~/.hermes/scripts`; absolute skill paths and external symlinks are rejected. Copy the published shim into that directory, then schedule its filename:

```bash
cp "$HOME/.hermes/skills/hermes-maintenance/scripts/hermes-maintenance-cron-shim.py" \
  "$HOME/.hermes/scripts/hermes-maintenance-skill-cron.py"
```

## Privacy

The repository contains no environment exports, credentials, chat/session data, databases, private profile names or machine-specific paths. Runtime audits report only metadata and counts.

See `skills/hermes-maintenance/references/privacy-review.md`.

## Development

```bash
python3 -m py_compile skills/hermes-maintenance/scripts/hermes-maintenance.py
python3 -m unittest discover -s tests -v
```

## License

MIT
