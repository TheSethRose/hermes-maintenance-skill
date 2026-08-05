# Docker Hermes maintenance

Use this reference for Hermes running in a Docker container, including multi-profile s6-supervised deployments.

## Discovery

Inspect before changing:

```bash
docker inspect <container>
docker logs --since <timestamp> <container>
docker exec <container> hermes --version
docker exec <container> hermes profile list
```

Record:

- exact image ID and tag
- command and entrypoint
- restart policy and count
- host source mounted at `/opt/data`
- published ports
- container start time
- registered s6 services and actual gateway worker processes

A container being `Up` does not prove every profile gateway is healthy.

## Command shim

Use:

```bash
docker exec <container> hermes <command>
docker exec <container> hermes -p <profile> <command>
```

Do not invoke `/opt/hermes/.venv/bin/hermes` directly as root. That bypasses the image’s privilege-dropping shim and can make Doctor inspect `/root` instead of `/opt/data`, producing false failures.

## Startup reconciliation

After container creation or restart, bootstrap may reconcile ownership and register profile services before gateways appear. Check the active bootstrap process and logs instead of repeatedly restarting.

Verify both the service layer and process layer:

```bash
docker exec <container> sh -c 'ls /run/service'
docker exec <container> ps -eo pid,ppid,etime,args
docker exec <container> hermes profile list
```

## Container replacement

Before replacement:

1. capture inspect output privately
2. preserve every mount, port, environment setting, command and restart policy
3. stop concurrent database writers
4. retain the old stopped container or immutable image ID for rollback
5. reuse the existing persistent data mount

After replacement:

1. wait for bootstrap reconciliation
2. verify `/health` if the API is exposed
3. verify container restart count
4. count gateway workers
5. run profile list and per-profile Doctor
6. run per-profile database checks
7. inspect only post-cutover logs

Never delete rollback assets during the same maintenance pass unless explicitly requested.

## Image rebuild verification

A tag can be moved to a new image while an existing container keeps the old image object. Compare IDs:

```bash
docker image inspect <tag> --format '{{.Id}}'
docker inspect <container> --format '{{.Image}}'
```

They must match before claiming the running container uses the rebuilt image.

## Platform collisions

Multiple profile gateways can collide through shared Telegram tokens or API ports. Prove token equality with secret hashes and report only owning profile names. Never print token values or hashes.

Disable a platform only when it is unintended. If multiple bots are intended, each profile needs its own credential.

## Browser integrations

Built-in Playwright browser tools and an MCP browser server are separate capabilities. A local auto-connect MCP inside Docker cannot reach a browser on the host unless an explicit remote transport exists. Remove a dead MCP block only after proving it cannot function and confirming built-in browser behavior remains available.

## Logs and SIGTERM

s6 sends SIGTERM during deliberate service restarts and container stops. Classify it as expected only when:

- timestamp matches a requested maintenance action
- a replacement gateway PID appears
- the container restart count is explained
- current status and health checks pass

A delayed log follower can surface old shutdown lines after maintenance. Check current logs and runtime state before escalating.
