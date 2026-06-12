"""blockdeck dashboard — status and controls for the Bedrock server stack."""

import os
import re
import socket
import struct
import time
from datetime import datetime, timezone
from pathlib import Path

import docker
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

SERVER_HOST = os.environ.get("SERVER_HOST", "bedrock")
SERVER_PORT = int(os.environ.get("SERVER_PORT", "19132"))
SERVER_CONTAINER = os.environ.get("SERVER_CONTAINER", "bedrock")
UPDATER_CONTAINER = os.environ.get("UPDATER_CONTAINER", "bedrock-updater")
MAP_CONTAINER = os.environ.get("MAP_CONTAINER", "bedrock-map")
LEVEL_NAME = os.environ.get("LEVEL_NAME", "world")
BACKUPS_DIR = Path("/backups")
SERVER_DIR = Path("/server")
MAP_DIR = Path("/map-data/current")

app = FastAPI(title="blockdeck")
client = docker.from_env()

# --- Bedrock (RakNet) unconnected ping ---

RAKNET_MAGIC = bytes.fromhex("00ffff00fefefefefdfdfdfd12345678")


def ping_server(host: str, port: int, timeout: float = 2.0):
    """Returns MOTD/version/player counts from the server's ping response."""
    packet = (
        struct.pack(">BQ", 0x01, int(time.time() * 1000) & 0xFFFFFFFFFFFFFFFF)
        + RAKNET_MAGIC
        + struct.pack(">Q", 0x2A)
    )
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.settimeout(timeout)
    try:
        sock.sendto(packet, (host, port))
        data, _ = sock.recvfrom(4096)
    except OSError:
        return None
    finally:
        sock.close()

    if len(data) < 35 or data[0] != 0x1C:
        return None
    (strlen,) = struct.unpack(">H", data[33:35])
    fields = data[35 : 35 + strlen].decode("utf-8", "replace").split(";")
    # MCPE;motd;protocol;version;online;max;guid;world;gamemode;...
    def field(i, default=""):
        return fields[i] if len(fields) > i else default

    def num(i):
        return int(fields[i]) if len(fields) > i and fields[i].isdigit() else None

    return {
        "motd": field(1),
        "version": field(3),
        "players_online": num(4),
        "players_max": num(5),
        "world": field(7),
        "gamemode": field(8),
    }


# --- Player names from the server log ---

CONNECT_RE = re.compile(r"Player connected: ([^,\r\n]+)")
DISCONNECT_RE = re.compile(r"Player disconnected: ([^,\r\n]+)")


def online_players(container) -> list[str]:
    """Replays join/leave events from the current container run's log."""
    log = container.logs(tail=10000).decode("utf-8", "replace")
    players: list[str] = []
    for line in log.splitlines():
        if m := CONNECT_RE.search(line):
            name = m.group(1).strip()
            if name not in players:
                players.append(name)
        elif m := DISCONNECT_RE.search(line):
            name = m.group(1).strip()
            if name in players:
                players.remove(name)
    return players


# --- Local facts: installed version, backups ---


def installed_version() -> str | None:
    versions = []
    for p in SERVER_DIR.glob("bedrock_server-*"):
        v = p.name.removeprefix("bedrock_server-")
        versions.append([int(x) for x in v.split(".") if x.isdigit()])
    if not versions:
        return None
    return ".".join(str(x) for x in max(versions))


def world_seed() -> str | None:
    """Reads RandomSeed from the world's level.dat (Bedrock NBT).

    Bedrock NBT is uncompressed little-endian; rather than a full parser,
    locate the Long tag (0x04) named "RandomSeed" (name length 10) and
    read the 8 bytes after it. Returned as a string: seeds are int64 and
    would lose precision as a JavaScript number.
    """
    level_dat = SERVER_DIR / "worlds" / LEVEL_NAME / "level.dat"
    if not level_dat.exists():
        candidates = sorted(SERVER_DIR.glob("worlds/*/level.dat"))
        if not candidates:
            return None
        level_dat = candidates[0]
    try:
        data = level_dat.read_bytes()
    except OSError:
        return None
    pos = data.find(b"\x04\x0a\x00RandomSeed")
    if pos < 0:
        return None
    (seed,) = struct.unpack_from("<q", data, pos + 13)
    return str(seed)


def map_info():
    index = MAP_DIR / "index.html"
    if not index.exists():
        return {"rendered": False, "rendered_at": None}
    return {
        "rendered": True,
        "rendered_at": datetime.fromtimestamp(
            index.stat().st_mtime, tz=timezone.utc
        ).isoformat(),
    }


def backups_summary(limit: int = 5):
    files = sorted(
        BACKUPS_DIR.glob("*.mcworld"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    def human_size(n: int) -> str:
        for unit in ("B", "KB", "MB", "GB"):
            if n < 1024 or unit == "GB":
                return f"{n:.1f} {unit}" if unit != "B" else f"{n} {unit}"
            n /= 1024

    def entry(p: Path):
        st = p.stat()
        return {
            "name": p.name,
            "time": datetime.fromtimestamp(st.st_mtime, tz=timezone.utc).isoformat(),
            "size": human_size(st.st_size),
        }
    return {"count": len(files), "recent": [entry(p) for p in files[:limit]]}


# --- API ---


@app.get("/api/status")
def status():
    try:
        container = client.containers.get(SERVER_CONTAINER)
        state = container.status
        started_at = container.attrs["State"].get("StartedAt")
    except docker.errors.NotFound:
        container, state, started_at = None, "not created", None

    ping = ping_server(SERVER_HOST, SERVER_PORT) if state == "running" else None
    players = online_players(container) if state == "running" else []

    return {
        "container": {"state": state, "started_at": started_at},
        "ping": ping,
        "players": players,
        "installed_version": installed_version(),
        "seed": world_seed(),
        "backups": backups_summary(),
        "map": map_info(),
        "checked_at": datetime.now(tz=timezone.utc).isoformat(),
    }


@app.post("/api/restart")
def restart():
    try:
        client.containers.get(SERVER_CONTAINER).restart()
    except docker.errors.NotFound:
        raise HTTPException(404, "server container not found")
    return {"ok": True, "message": "Server is restarting."}


@app.post("/api/update")
def update():
    try:
        updater = client.containers.get(UPDATER_CONTAINER)
    except docker.errors.NotFound:
        raise HTTPException(404, "updater container not found")
    # Detached: the check warns players for several minutes before restarting.
    # Output goes to the container log so it shows in `docker compose logs`.
    updater.exec_run(["sh", "-c", "check-update >> /proc/1/fd/1 2>&1"], detach=True)
    return {
        "ok": True,
        "message": "Update check started - follow it with: docker compose logs -f updater",
    }


BACKUP_HOST = os.environ.get("BACKUP_HOST", "bedrock-backup")
BACKUP_TOKEN_FILE = Path("/backup-config/.bedrockifierToken")


@app.post("/api/backup")
def backup_now():
    """Trigger an on-demand hot backup via Bedrockifier's HTTP API."""
    import urllib.error
    import urllib.request

    if not BACKUP_TOKEN_FILE.exists():
        raise HTTPException(503, "backup service token not found (is it running?)")
    req = urllib.request.Request(f"http://{BACKUP_HOST}:8080/start-backup")
    req.add_header("Authorization", f"Bearer {BACKUP_TOKEN_FILE.read_text().strip()}")
    try:
        urllib.request.urlopen(req, timeout=120)
    except (urllib.error.URLError, OSError) as e:
        raise HTTPException(502, f"backup service unreachable: {e}")
    return {"ok": True, "message": "Backup completed."}


@app.post("/api/render-map")
def render_map():
    try:
        map_container = client.containers.get(MAP_CONTAINER)
    except docker.errors.NotFound:
        raise HTTPException(404, "map container not found")
    map_container.exec_run(["sh", "-c", "render-map >> /proc/1/fd/1 2>&1"], detach=True)
    return {
        "ok": True,
        "message": "Map render started - it appears here when done (can take a while).",
    }


class Message(BaseModel):
    message: str


@app.post("/api/say")
def say(body: Message):
    text = body.message.strip()
    if not text:
        raise HTTPException(400, "empty message")
    try:
        container = client.containers.get(SERVER_CONTAINER)
        result = container.exec_run(["send-command", "say", text])
    except docker.errors.NotFound:
        raise HTTPException(404, "server container not found")
    if result.exit_code != 0:
        raise HTTPException(
            500, f"send-command failed: {result.output.decode(errors='replace').strip()}"
        )
    return {"ok": True}


@app.get("/")
def index():
    return FileResponse(Path(__file__).parent / "static" / "index.html")


# The rendered world map; the directory appears after the first render
app.mount("/map", StaticFiles(directory=MAP_DIR, html=True, check_dir=False))
