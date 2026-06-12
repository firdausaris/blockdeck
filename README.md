# mc-monitor

A replicable, Docker-based Minecraft Bedrock server with automated updates,
scheduled off-site backups, a status dashboard, and a world map.

Built on [itzg/minecraft-bedrock-server](https://github.com/itzg/docker-minecraft-bedrock-server).

## Quick start

On a fresh Ubuntu/Debian machine:

```bash
git clone <this-repo> && cd mc-monitor
cp .env.example .env        # review settings (server name, gamemode, allowlist...)
./scripts/bootstrap.sh      # installs Docker if needed, starts the server
```

The server listens on UDP **19132**. All gameplay settings live in `.env` —
edit and run `docker compose up -d` to apply.

> Setting `EULA=TRUE` in `.env` means you accept the
> [Minecraft EULA](https://minecraft.net/terms).

## Importing an existing world

From a world folder, `.mcworld`, or `.zip`:

```bash
./scripts/import-world.sh /path/to/my-world
```

To migrate from another host first copy the world over, e.g.:

```bash
scp -r user@192.168.2.204:/home/mcserver/minecraft_bedrock/worlds/"Bedrock level" /tmp/old-world
./scripts/import-world.sh /tmp/old-world
```

The script stops the server, installs the world as `data/worlds/$LEVEL_NAME`
(keeping any existing world as a `.bak` folder), and starts it again.

## Updating the server

With `VERSION=LATEST` the container downloads the newest Bedrock server
every time it starts, so updating is just:

```bash
docker compose restart bedrock
```

(Automatic update checks are coming in a later phase.)

## Console commands

```bash
./scripts/console.sh list                  # who's online
./scripts/console.sh say Hello everyone    # broadcast a message
docker attach bedrock                      # interactive console (detach: Ctrl-p Ctrl-q)
```

## Layout

```
docker-compose.yml   server definition
.env                 your configuration (not committed)
data/                server binary, configs, worlds (not committed)
scripts/             bootstrap, world import, console helpers
```

## Roadmap

- [x] Phase 1 — Dockerized server, bootstrap, world import
- [ ] Phase 2 — scheduled hot backups + off-site push (restic) + restore script
- [ ] Phase 3 — automatic update checks with graceful restart
- [ ] Phase 4 — web dashboard (status, players, controls)
- [ ] Phase 5 — rendered world map (uNmINeD)
