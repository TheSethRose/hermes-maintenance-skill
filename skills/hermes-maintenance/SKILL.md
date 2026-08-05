---
name: hermes-maintenance
description: Maintain native or Docker Hermes installs with per-profile Doctor, database integrity, config, gateway, session, cron, memory and log checks.
version: 1.0.0
author: Hermes Maintenance Contributors
license: MIT
platforms: [macos, linux]
metadata:
  hermes:
    tags: [hermes, maintenance, doctor, docker, profiles, sqlite, cron, backups]
    requires_toolsets: [terminal, file]
---

# Hermes Maintenance

Use this skill when the user asks to inspect, maintain, update, repair or run Doctor on a Hermes Agent installation. It covers native installations and multi-profile Docker containers.

Authoritative product documentation: <https://hermes-agent.nousresearch.com/docs/>

## Operating contract

1. Discover the actual environment before recommending or changing anything.
2. Treat native Hermes and Docker Hermes as separate maintenance scopes. A clean native Doctor does not prove Docker is healthy.
3. Never assume profile names, container names, data paths, messaging platforms, model providers or memory providers.
4. Inspect first. Mutate one thing at a time, preserve rollback and verify after every repair.
5. Never print `.env` values, tokens, API keys, OAuth state, auth files, cron prompts, database message content or backup payloads.
6. Run Doctor and session database integrity checks independently for every discovered profile. Default-profile checks do not cover every profile database.
7. Do not force gateway restarts, updates, pruning, migrations or backups merely to make a report look clean. Obtain authorization when the user requested review only.
8. Distinguish optional-tool warnings from broken capabilities. Do not copy credentials between profiles or disable intended tools without evidence.
9. Preserve the configured memory design. An empty `memory.provider` means built-in file memory. A non-empty provider may be intentional; report it instead of changing it unless the user asked.
10. A successful command is not enough. Verify the resulting runtime, database, API or file state.

## Included runner

The deterministic runner is [`scripts/hermes-maintenance.py`](scripts/hermes-maintenance.py). It uses only Python’s standard library.

It:

- discovers profiles from their `config.yaml` files
- supports native and Docker execution
- runs one segment at a time
- keeps compact state and JSONL logs
- redacts likely credentials from captured output
- requires `--apply` for mutating segments
- requires `--include-quarterly` for backups and broad log review
- uses the Docker `hermes` shim rather than invoking the venv binary as root

The runner never edits configuration values directly. Repairs remain evidence-driven agent work.

## Start here

Locate the installed script:

```bash
SCRIPT="$HOME/.hermes/skills/hermes-maintenance/scripts/hermes-maintenance.py"
```

If the skill was installed under a category, use the path returned by `hermes skills list` or find its directory under `$HERMES_HOME/skills/`.

Inspect available segments:

```bash
python3 "$SCRIPT" --list-segments
```

Preview the due work without changing state:

```bash
python3 "$SCRIPT" --mode native --plan
python3 "$SCRIPT" --mode docker --container hermes --plan
```

Inspect runner state:

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

Create allowlisted profile backups only when explicitly requested:

```bash
python3 "$SCRIPT" --mode native --segment profile-backups --apply --include-quarterly
```

## Mode and path discovery

Explicit mode is safest:

```bash
--mode native
--mode docker --container <name>
```

Native home resolution:

1. `--home PATH`
2. `HERMES_HOME`
3. `~/.hermes`

Docker home resolution:

1. `--home PATH`
2. host source mounted at `/opt/data` in the selected container

If discovery is ambiguous, stop and ask for the Hermes data root or container name. Do not guess based on unrelated directories.

## Segments

### Weekly

- `inventory`: version, profiles, config versions and Docker runtime when applicable
- `config-migrate`: apply supported config migrations to every discovered profile; requires `--apply`
- `config-check`: validate every profile config
- `gateway-status`: inspect every profile gateway
- `docker-runtime`: container state, restart count, gateway worker count and `/health` when exposed

### Monthly

- `doctor-all`: run Doctor separately for every profile
- `skills-check`: inspect upstream skill updates
- `session-stats`: report every profile’s session store statistics
- `session-prune`: prune sessions older than the configured retention; requires `--apply`
- `session-integrity`: run supported SQLite/FTS check-only repair on every profile
- `memory-pressure`: report `MEMORY.md` and `USER.md` sizes without reading their content
- `config-hygiene`: report external memory provider state, deprecated environment keys and duplicate Telegram token ownership without printing tokens
- `cron-health`: report counts and error states without exposing job prompts

### Quarterly-gated

- `gateway-log-scan`: count actionable recent warning patterns without reproducing sensitive log lines
- `profile-backups`: create allowlisted identity/config backups; requires `--apply --include-quarterly`

Backups include only selected configuration, built-in memory, skills, cron definitions and scripts. They exclude credentials, identity/instruction/prefill files, auth state, session databases, logs, caches, dependency trees and runtime state. Agent-control files require deliberate manual handling and are never copied by the community runner.

## Required maintenance workflow

### 1. Inventory

Collect:

- installed Hermes version
- runtime mode and data root
- discovered profile count
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

Rank repairs by blast radius. Prefer narrow config fixes over rebuilds or recreates.

### 3. Back up affected artifacts

Before modifying configuration, environment files, cron definitions or databases:

- create a timestamped copy outside the active path
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
- remove one dead MCP integration that cannot function in the runtime
- pin one cron provider/model when runtime safety requires explicit values

Never copy secrets from another profile merely to silence Doctor.

### 5. Verify the repair

Use the narrowest authoritative check:

- config change: `config check`, fresh gateway PID and logs
- database repair: `sessions repair --check-only`, SQLite quick check and FTS integrity through supported Hermes output
- messaging: read-only platform identity/health call when available
- Docker: container state, restart count, worker count and `/health`
- dependency repair: rerun the exact audit and relevant build/test command

Then rerun Doctor for the affected profile.

### 6. Final pass

Before declaring completion:

- all intended profiles were checked
- all databases open cleanly
- all intended gateways are running
- container restart count is explained
- current logs contain no unexplained hard errors
- expected SIGTERM lines are correlated with deliberate maintenance stops/restarts
- optional warnings are labeled as optional rather than silently “fixed”
- rollback assets still exist

## Native maintenance

Read [`references/native-maintenance.md`](references/native-maintenance.md) before native gateway cycling, updates or launch-service work.

Important rules:

- Pass `-p <profile>` explicitly for named-profile commands.
- Do not blanket-restart intentionally stopped profiles.
- After an update, run config migration/check and Doctor before assuming old gateways loaded new code.
- A stale gateway can keep old Python modules loaded after files update; compare process start time with update time.

## Docker maintenance

Read [`references/docker-maintenance.md`](references/docker-maintenance.md) before container replacement, database repair or image work.

Important rules:

- Inspect the running container’s exact image, mounts, command and restart policy before replacement.
- Preserve `/opt/data` bind-mounted state.
- Invoke `docker exec <container> hermes ...`; do not bypass the privilege-dropping shim with `/opt/hermes/.venv/bin/hermes` as root.
- Wait for ownership/bootstrap reconciliation before diagnosing missing profile services.
- Verify s6 service count and actual gateway worker count.
- Preserve the old stopped container or exact image as rollback when replacing a custom image.

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

Do not assume missing application tables indicate corruption without checking the installed schema.

## Configuration and platform hygiene

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

Do not manually run scheduled jobs merely to clear historical error state. A forced job may send messages, publish content or incur model spend. Get authorization for the exact job first.

## Dependency vulnerabilities

Doctor checks Hermes’ bundled browser, web and UI dependency scopes. If it reports vulnerabilities:

1. identify the affected workspace and dependency chain
2. use the package manager’s audit report
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
2. inspect the failed command’s redacted output and maintenance JSONL log
3. determine root cause
4. repair narrowly
5. rerun the failed segment explicitly
6. use `--reset-run` only when abandoning the current run

Do not delete the state file to hide a failure.

## Automation guidance

The safest automated pattern is an agent-driven cron that loads this skill, runs `--plan`, executes at most one due segment and reports only failures or a compact completion summary.

Do not schedule the runner with unconditional `--apply --force`. Quarterly backups should never be silently enabled.

A script-only cron can run read-only segments. Mutating segments should remain explicit unless the operator has reviewed and accepted the exact maintenance policy.

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

Use placeholders such as `<profile>`, `<container>` and `<path>`. Before publishing changes, scan the complete working tree and Git history. See [`references/privacy-review.md`](references/privacy-review.md).

## Skill self-improvement

When this skill is used and a generic, reproducible gap is discovered, patch the skill and add a regression test. Do not add local profile names, incident transcripts or environment-specific assumptions to the public package.
