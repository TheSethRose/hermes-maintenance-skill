# Remediation decision guide

Use this after inspection identifies a finding. Repairs should be minimal, reversible and verified.

## Config version drift

Preferred action: supported `config migrate`, then `config check` for the affected profile. Back up the original config first. Do not manually paste defaults from another profile.

## Gateway running old code

Evidence: source/install updated after the gateway process started, current CLI works and gateway logs show missing imports or old behavior.

Action: restart only the affected gateway and verify a fresh PID plus clean current logs.

## Duplicate Telegram credential

Evidence: equal secret hashes map to more than one active profile, or Telegram reports competing polling requests.

Action: determine intended owner. Remove the credential only from unintended profiles, restart those gateways and verify read-only bot identity/health. Do not print or move the credential.

## API port collision

Evidence: multiple enabled servers bind the same address/port and logs show bind failure.

Action: disable an unused API server or assign an intentional unique port. Verify the listener and affected gateway.

## Database corruption

Evidence: supported check-only repair, SQLite quick check or FTS integrity fails.

Action: stop writers, back up database/WAL/SHM, run supported repair, verify integrity and record counts, then restart.

## Historical cron error

Evidence: job state reports an old failure but current config/gateway is healthy.

Action: fix the proven root cause. Do not force-run a job that may send, publish or spend merely to clear state. Let its next scheduled run verify unless the operator authorizes a test.

## Missing optional API key

Evidence: Doctor lists a toolset as enabled but unavailable while model connectivity passes.

Action: decide whether the profile needs that tool. Disable an unintended toolset or configure an authorized credential. Never copy another profile’s key without explicit permission.

## External memory warning

Evidence: provider is non-empty or provider-specific files/environment keys exist.

Action: confirm intended memory architecture. Preserve it unless migration was requested. Built-in memory normally uses `MEMORY.md` and `USER.md` with an empty provider.

## Dead MCP server

Evidence: repeated startup failure, no reachable transport or dependency and an alternative built-in capability is healthy.

Action: remove only the dead server block, validate config, restart the affected gateway and confirm the warnings stop.

## Dependency vulnerability

Evidence: Doctor or package-manager audit identifies an advisory and affected dependency path.

Action: make the narrowest compatible update, preserve supply-chain policy, rerun audit and workspace tests, then rebuild/redeploy if needed.

## Transient external network failure

Evidence: current direct connectivity and platform identity calls succeed, gateways stayed alive and errors are limited to a past interval.

Action: report the event as transient. Do not churn config or restart healthy gateways.
