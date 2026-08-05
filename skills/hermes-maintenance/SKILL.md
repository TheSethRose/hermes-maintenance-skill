---
name: hermes-maintenance
description: Maintain native or Docker Hermes installs with per-profile Doctor, database integrity, config, gateway, session, cron, memory and log checks.
version: 1.1.2
author: Hermes Maintenance Contributors
license: MIT
platforms: [macos, linux]
metadata:
  hermes:
    tags: [hermes, maintenance, doctor, docker, profiles, sqlite, cron, backups]
    requires_toolsets: [terminal, file]
---

# Hermes Maintenance

Use this skill when the user asks to inspect, maintain, update, repair or run Doctor on a Hermes Agent installation. It covers native installs and multi-profile Docker containers.

Authoritative product docs: <https://hermes-agent.nousresearch.com/docs/>

## How this works

1. Find out what the actual environment is before recommending or changing anything.
2. Treat native Hermes and Docker Hermes as separate scopes. A clean native Doctor does not prove Docker is healthy.
3. Never assume profile names, container names, data paths, messaging platforms, model providers or memory providers.
4. Inspect first. Change one thing at a time, keep a rollback, and verify after every repair.
5. Never print `.env` values, tokens, API keys, OAuth state, auth files, cron prompts, database message content or backup payloads.
6. Run Doctor and the session database integrity check separately for every profile found. Checking the default profile does not cover every profile's database.
7. Do not force gateway restarts, updates, pruning, migrations or backups just to make a report look clean. If the user asked for review only, get authorization before changing anything.
8. Tell optional-tool warnings apart from broken capabilities. Do not copy credentials between profiles or switch off intended tools without evidence.
9. Keep the configured memory design as-is. An empty `memory.provider` means built-in file memory. A non-empty provider may be deliberate; report it rather than changing it unless the user asked.
10. A command that succeeds is not enough. Verify the resulting runtime, database, API or file state.

## Included runner

The deterministic runner is [`scripts/hermes-maintenance.py`](scripts/hermes-maintenance.py). It uses only Python's standard library.

What it does:

- finds profiles from their `config.yaml` files
- supports native and Docker execution
- updates native Hermes installations without changing Docker images in place
- checks Curator status and per-profile authentication state
- runs one segment at a time
- keeps compact state and JSONL logs, with one JSON record per line
- redacts likely credentials from captured output
- requires `--apply` for mutating segments
- requires `--include-quarterly` for every quarterly segment
- uses the Docker `hermes` shim rather than calling the Python virtual environment (`venv`) binary as root

The runner never edits configuration values directly. The agent must inspect the evidence and make repairs deliberately.

## Start here

Locate the installed script:

```bash
SCRIPT="$HOME/.hermes/skills/hermes-maintenance/scripts/hermes-maintenance.py"
```

If the skill was installed under a category, use the path from `hermes skills list` or find its directory under `$HERMES_HOME/skills/`.

List available segments:

```bash
python3 "$SCRIPT" --list-segments
```

Preview the due work without changing state:

```bash
python3 "$SCRIPT" --mode native --plan
python3 "$SCRIPT" --mode docker --container hermes --plan
```

Check runner state:

```bash
python3 "$SCRIPT" --mode native --status
```

Run one explicit read-only segment:

```bash
python3 "$SCRIPT" --mode native --segment doctor-all
python3 "$SCRIPT" --mode docker --container hermes --segment session-integrity
```

Run a mutating segment only after reviewing its plan:

```bash
python3 "$SCRIPT" --mode native --segment config-migrate --apply
python3 "$SCRIPT" --mode native --segment session-prune --retention-days 60 --apply
```

Create allowlisted profile backups only when explicitly asked:

```bash
python3 "$SCRIPT" --mode native --segment profile-backups --apply --include-quarterly
```

## Mode and path discovery

Explicit mode is safest:

```bash
--mode native
--mode docker --container <name>
```

Native home resolution, in order:

1. `--home PATH`
2. `HERMES_HOME`
3. `~/.hermes`

Docker home resolution, in order:

1. `--home PATH`
2. host source mounted at `/opt/data` in the selected container

If discovery is ambiguous, stop and ask for the Hermes data root or container name. Do not guess from unrelated directories.

## Segments

### Weekly

- `hermes-update`: update a native Hermes installation; requires `--apply`; Docker reports `not_applicable` so the image can be updated from the host
- `inventory`: version, profiles, config versions and Docker runtime when applicable
- `config-migrate`: apply supported config migrations to every profile found; requires `--apply`
- `config-check`: validate every profile config
- `gateway-status`: inspect every profile gateway
- `curator-status`: inspect Hermes Curator status
- `docker-runtime`: container state, restart count, gateway worker count and `/health` when exposed

### Monthly

- `doctor-all`: run Doctor separately for every profile
- `skills-check`: inspect upstream skill updates
- `session-stats`: report every profile's session store statistics
- `session-prune`: prune sessions older than the configured retention; requires `--apply`
- `session-integrity`: run supported SQLite and full-text-search (FTS) check-only repair on every profile
- `memory-pressure`: report `MEMORY.md` and `USER.md` sizes without reading their content
- `config-hygiene`: report external memory provider state, deprecated environment keys and duplicate Telegram token ownership without printing tokens
- `cron-health`: report counts and error states without exposing job prompts

### Quarterly-gated

- `auth-status`: check authentication state separately for every profile while suppressing account and credential output
- `gateway-log-scan`: count actionable recent warning patterns without reproducing sensitive log lines
- `profile-backups`: create allowlisted profile recovery backups; requires `--apply --include-quarterly`

Backups include only selected config, built-in memory, skills, cron definitions and scripts. They exclude credentials, identity/instruction/prefill files, auth state, session databases, logs, caches, dependency trees and runtime state. Agent-control files need deliberate manual handling and are never copied by the community runner.

## The maintenance workflow

### 1. Inventory

Collect:

- installed Hermes version
- runtime mode and data root
- number of profiles found
- container image/restart count when applicable
- gateway states
- config versions
- session database sizes and integrity
- cron error counts
- memory file pressure
- recent actionable log-pattern counts

Do not infer live health from directory presence or an old log.

### 2. Plan

Classify every finding:

- verified healthy
- actionable misconfiguration
- stale historical event
- optional capability not configured
- external/transient failure
- requires user decision

Rank repairs by blast radius, meaning how much they could affect. Prefer narrow config fixes over rebuilds or recreates.

### 3. Back up affected artifacts

Before modifying config, environment files, cron definitions or databases:

- make a timestamped copy outside the active path
- do not print or commit its contents
- preserve file ownership and permissions where relevant
- record the rollback location privately in the maintenance report

Stop gateways or the container before repairing a database that can receive concurrent writes.

### 4. Repair one finding

Read [`references/remediation-guide.md`](references/remediation-guide.md) for evidence requirements and narrow fixes for common findings.

Examples:

- migrate one stale config
- disable one proven duplicate platform binding
- assign one unique API port
- repair one database using the supported Hermes command
- remove one dead Model Context Protocol (MCP) integration that cannot function in the runtime
- pin one cron provider/model when runtime safety requires explicit values

Never copy secrets from another profile just to silence Doctor.

### 5. Verify the repair

Use the most direct trusted check:

- config change: `config check`, fresh gateway process ID (PID) and logs
- database repair: `sessions repair --check-only`, SQLite quick check and FTS integrity through supported Hermes output
- messaging: read-only platform identity/health call when available
- Docker: container state, restart count, worker count and `/health`
- dependency repair: rerun the exact audit and the relevant build/test command

Then rerun Doctor for the affected profile.

### 6. Final pass

Before declaring completion:

- all intended profiles were checked
- all databases open cleanly
- all intended gateways are running
- container restart count is explained
- current logs have no unexplained hard errors
- expected SIGTERM lines line up with deliberate maintenance stops/restarts
- optional warnings are labeled optional rather than silently "fixed"
- rollback assets still exist

## Native maintenance

Read [`references/native-maintenance.md`](references/native-maintenance.md) before native gateway cycling, updates or launch-service work.

Key rules:

- Pass `-p <profile>` explicitly for named-profile commands.
- Do not blanket-restart profiles that were stopped on purpose.
- After an update, run config migration/check and Doctor before assuming old gateways loaded the new code.
- A stale gateway can keep old Python modules loaded after files update; compare process start time with update time.

## Docker maintenance

Read [`references/docker-maintenance.md`](references/docker-maintenance.md) before container replacement, database repair or image work.

Key rules:

- Inspect the running container's exact image, mounts, command and restart policy before replacement.
- Preserve `/opt/data` bind-mounted state.
- Invoke `docker exec <container> hermes ...`; do not bypass the privilege-dropping shim with `/opt/hermes/.venv/bin/hermes` as root.
- Wait for ownership/bootstrap reconciliation before diagnosing missing profile services.
- Verify the s6 service count and the actual gateway worker count.
- Keep the old stopped container or exact image as rollback when replacing a custom image.

## Database integrity

Use supported Hermes commands first:

```bash
hermes sessions repair --check-only
hermes -p <profile> sessions repair --check-only
```

For Docker:

```bash
docker exec <container> hermes sessions repair --check-only
docker exec <container> hermes -p <profile> sessions repair --check-only
```

If repair is needed:

1. stop concurrent writers
2. back up `state.db`, `state.db-wal` and `state.db-shm` if present
3. run supported `sessions repair`
4. rerun `--check-only`
5. verify session/message counts when available
6. restart only the affected runtime

Do not assume missing application tables mean corruption without checking the installed schema.

## Config and platform checks

Check without exposing values:

- duplicate Telegram token ownership using hashes
- API server ports enabled in more than one profile
- deprecated environment keys
- stale loopback proxy URLs inside Docker
- provider/model mismatches
- dead MCP servers
- active external memory files/providers

A token collision is proven only when equal secret hashes map to multiple active profiles. Never print the hash or token.

## Cron health

Cron jobs are profile-scoped and gateway-dependent.

Inspect:

- enabled/disabled state
- last status and last error category
- provider/model/base URL overrides
- script existence
- gateway availability
- delivery target availability

Do not manually run scheduled jobs just to clear historical error state. A forced job may send messages, publish content or cost model spend. Get authorization for the exact job first.

## Dependency vulnerabilities

Doctor checks Hermes' bundled browser, web and UI dependency scopes. If it reports vulnerabilities:

1. identify the affected workspace and dependency chain
2. use the package manager's audit report
3. prefer narrow patched versions or reviewed overrides
4. preserve repository supply-chain policies such as minimum release age
5. never use forceful major-version audit fixes without review
6. run workspace checks/tests after updates
7. rebuild the image if Docker uses the changed source
8. verify the running container image ID matches the rebuilt tag

## Failure handling

Every runner segment emits:

```text
HERMES_MAINTENANCE_SEGMENT_START name=<segment>
HERMES_MAINTENANCE_SEGMENT_DONE name=<segment> code=0
```

or:

```text
HERMES_MAINTENANCE_SEGMENT_FAILED name=<segment> code=<code>
```

On failure:

1. stop the sequence
2. inspect the failed command's redacted output and the maintenance JSONL log
3. pin down root cause
4. repair narrowly
5. rerun the failed segment explicitly
6. use `--reset-run` only when abandoning the current run

Do not delete the state file to hide a failure.

## Automating maintenance

The safest automated pattern is an agent-driven cron that loads this skill, runs `--plan`, runs at most one due segment, and reports only failures or a compact completion summary.

Do not schedule the runner with unconditional `--apply --force`. Quarterly backups should never be enabled silently.

A script-only cron can run read-only segments. Mutating segments stay explicit unless the operator has reviewed and accepted the exact maintenance policy.

The included native cron wrapper, [`scripts/hermes-maintenance-cron.py`](scripts/hermes-maintenance-cron.py), is that explicit policy boundary. Scheduling it runs exactly one due weekly or monthly segment with `--apply`. It never enables quarterly work:

```bash
CRON_SCRIPT="$HOME/.hermes/skills/hermes-maintenance/scripts/hermes-maintenance-cron.py"
python3 "$CRON_SCRIPT"
```

For Docker, update the image from the host. The `hermes-update` segment reports `not_applicable` instead of modifying a running container.

Hermes cron requires a real script file under `~/.hermes/scripts`; it rejects absolute skill paths and symlinks that resolve outside that directory. Copy the published containment shim there after reviewing it:

```bash
SHIM_SOURCE="$HOME/.hermes/skills/hermes-maintenance/scripts/hermes-maintenance-cron-shim.py"
SHIM="$HOME/.hermes/scripts/hermes-maintenance-skill-cron.py"
test ! -e "$SHIM" && cp "$SHIM_SOURCE" "$SHIM"
```

The shim is [`scripts/hermes-maintenance-cron-shim.py`](scripts/hermes-maintenance-cron-shim.py). Schedule `hermes-maintenance-skill-cron.py`; it contains no maintenance logic and always loads the installed published wrapper.

## Privacy and publishing rules

This public skill must never contain:

- personal names, usernames, email addresses or chat IDs
- real home-directory paths
- private profile names
- employer, tenant or customer references
- bot usernames or tokens
- API keys, OAuth state or credential fingerprints
- cron IDs, session IDs or database contents
- private repository names or URLs

Use placeholders such as `<profile>`, `<container>` and `<path>`. Before publishing changes, scan the full working tree and Git history. See [`references/privacy-review.md`](references/privacy-review.md).

## Improving this skill

When this skill is used and you find a generic, reproducible gap, patch the skill and add a regression test. Do not add local profile names, incident transcripts or environment-specific assumptions to the public package.
