# Native Hermes maintenance

Use this reference for a Hermes installation running directly on macOS or Linux.

## Discovery

Resolve the active Hermes home from `--home`, `HERMES_HOME` or `~/.hermes`. Discover named profiles only when a directory under `profiles/` contains `config.yaml`.

Never infer active profiles from shell wrappers alone. A wrapper can outlive a deleted profile.

## Supported command pattern

Default profile:

```bash
hermes doctor
hermes gateway status
```

Named profile:

```bash
hermes -p <profile> doctor
hermes -p <profile> gateway status
```

Always put `-p <profile>` immediately after `hermes`. Do not rely on inherited profile environment variables.

## Update workflow

1. Inspect version, source/install type and repository state.
2. Back up configuration before updating.
3. Run the supported update command.
4. Migrate and check every discovered profile configuration.
5. Restart only gateways intended to run.
6. Compare fresh process start times with the update time.
7. Run Doctor per profile.
8. Check database integrity per profile.
9. Inspect current logs for new errors.

Do not restart every profile blindly. An intentionally stopped profile should remain stopped.

## Launch services

On macOS, gateways may be managed by launchd. On Linux, they may use systemd or another service manager. Use `hermes gateway status` first and follow the service mechanism reported by the installed version.

A gateway shutdown line containing SIGTERM is expected when it correlates with a deliberate restart. It is not evidence of a crash by itself. An unexplained SIGTERM plus a missing replacement PID or failing health check is actionable.

## Configuration drift

Run migration before manual YAML surgery:

```bash
hermes config migrate
hermes config check
hermes -p <profile> config migrate
hermes -p <profile> config check
```

Use the current CLI help when syntax differs. Do not invent unsupported flags such as a dry-run option unless the installed command documents one.

## Session databases

Run `sessions repair --check-only` independently for the default and every named profile. Stop the affected gateway before a real repair to prevent concurrent writes.

Back up the database and its WAL/SHM siblings before repair. Preserve ownership and permissions.

## Logs

Prefer logs from the current process lifetime. Historical errors can survive successful repairs. Correlate each finding with timestamps, process IDs and current health before classifying it.
