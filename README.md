# blockdeck

A replicable, Docker-based Minecraft Bedrock server with automated updates,
scheduled off-site backups, a status dashboard, and a world map.

Built on [itzg/minecraft-bedrock-server](https://github.com/itzg/docker-minecraft-bedrock-server).

## Quick start

On a fresh Ubuntu/Debian machine:

```bash
git clone <this-repo> && cd blockdeck
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

Updates are automatic. The `updater` service checks Mojang's release API
hourly (`UPDATE_CRON` in `.env`); when a new version is out it warns the
players in-game (`UPDATE_WARN_MINUTES`, default 5), restarts the server —
which downloads the new release on startup thanks to `VERSION=LATEST` —
and verifies it comes back up. The backup service keeps you covered if an
update ever misbehaves.

```bash
docker compose logs -f updater                 # see update checks
docker compose run --rm updater check-update   # check & update right now
docker compose restart bedrock                 # manual update, no warning
```

To hold a version back, pin `VERSION` in `.env` — the updater then stands
down. Note: the updater needs the docker socket to restart the server, so
it's as privileged as Docker itself (same trade-off as Watchtower).

## Backups

The `backup` service ([Bedrockifier](https://github.com/Kaiede/Bedrockifier))
takes **hot backups** — no server downtime — using the console's
`save hold/resume` mechanism, and writes them to `backups/` as `.mcworld`
files (importable by any Bedrock client). By default it backs up daily at
02:00 and whenever the last player logs out; schedule and retention are in
[`backup/config.yml`](backup/config.yml).

Set `RCON_PASSWORD` and `TZ` in `.env` — `bootstrap.sh` generates the
console credentials the backup service needs. If you change `LEVEL_NAME`,
update the world path in `backup/config.yml` to match.

```bash
docker compose logs -f backup    # watch backup activity
```

### Restoring

```bash
./scripts/restore.sh                          # restore the newest backup
./scripts/restore.sh backups/<file>.mcworld   # restore a specific one
```

The current world is kept as a `.bak` folder, so a restore is reversible.

## Off-site backups (optional)

A restic service pushes `backups/` to another machine on a schedule, with
encryption and retention. In `.env`, uncomment `COMPOSE_PROFILES=offsite`
and set `RESTIC_REPOSITORY` + `RESTIC_PASSWORD`.

For an SFTP destination (Linux box or NAS with SSH), give the service a
dedicated key:

```bash
mkdir -p offsite/ssh
ssh-keygen -t ed25519 -N "" -f offsite/ssh/id_ed25519
ssh-copy-id -i offsite/ssh/id_ed25519.pub backup@192.168.2.50
docker compose up -d --build
```

Useful commands:

```bash
docker compose run --rm offsite offsite-backup     # push a backup right now
docker compose run --rm offsite restic snapshots   # list off-site snapshots
```

### Restoring from off-site

```bash
docker compose run --rm -v ./restored:/restored offsite \
    restic restore latest --target /restored
./scripts/restore.sh restored/backups/<file>.mcworld
```

## Dashboard

`http://<server-ip>:8080` (port: `DASH_PORT` in `.env`) shows live status —
online players by name, server version and uptime, the world seed (parsed
from `level.dat`, click to copy), recent backups, and the world map — with
buttons to back up now, check for updates, restart the server, re-render
the map, and broadcast a message to players.

It reads player names from the server log and the player count from the
Bedrock ping protocol, so it works without any server-side mods. **It has
no authentication**: it is meant for your LAN. Don't port-forward it.

## World map

The `map` service renders a zoomable web map with
[uNmINeD](https://unmined.net), served by the dashboard at
`http://<server-ip>:8080/map/`. It renders daily (`MAP_CRON` in `.env`)
from the **newest backup snapshot** — never the live world, whose database
can't be read safely while the server writes to it. So the map is only as
fresh as the last backup, and a brand-new world shows nothing until
someone has played on it (and a backup has run).

```bash
docker compose run --rm map render-map   # render right now (or use the
                                         # dashboard's Render map button)
```

## Console commands

```bash
./scripts/console.sh list                  # who's online
./scripts/console.sh say Hello everyone    # broadcast a message
docker attach bedrock                      # interactive console (detach: Ctrl-p Ctrl-q)
```

## Layout

```
docker-compose.yml   server + backup + offsite services
.env                 your configuration (not committed)
data/                server binary, configs, worlds (not committed)
backups/             .mcworld backups (not committed)
backup/              backup service config (config.yml)
updater/             automatic update service (Dockerfile, scripts)
dashboard/           web dashboard (FastAPI + static page)
map/                 world map renderer (uNmINeD CLI)
map-data/            rendered map tiles (not committed)
offsite/             restic off-site service (Dockerfile, scripts, ssh key)
scripts/             bootstrap, world import, restore, console helpers
```

## Roadmap

- [x] Phase 1 — Dockerized server, bootstrap, world import
- [x] Phase 2 — scheduled hot backups + off-site push (restic) + restore script
- [x] Phase 3 — automatic update checks with graceful restart
- [x] Phase 4 — web dashboard (status, players, controls)
- [x] Phase 5 — rendered world map (uNmINeD)
