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
from pydantic import BaseModel

SERVER_HOST = os.environ.get("SERVER_HOST", "bedrock")
SERVER_PORT = int(os.environ.get("SERVER_PORT", "19132"))
SERVER_CONTAINER = os.environ.get("SERVER_CONTAINER", "bedrock")
UPDATER_CONTAINER = os.environ.get("UPDATER_CONTAINER", "bedrock-updater")
BACKUPS_DIR = Path("/backups")
SERVER_DIR = Path("/server")

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


def backups_summary(limit: int = 5):
    files = sorted(
        BACKUPS_DIR.glob("*.mcworld"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    def entry(p: Path):
        st = p.stat()
        return {
            "name": p.name,
            "time": datetime.fromtimestamp(st.st_mtime, tz=timezone.utc).isoformat(),
            "size_mb": round(st.st_size / 1_048_576, 1),
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
        "backups": backups_summary(),
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
    # Detached: the check warns players for several minutes before restarting
    updater.exec_run(["check-update"], detach=True)
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


class Message(BaseModel):
    message: str


@app.post("/api/say")
def say(body: Message):
    text = body.message.strip()
    if not text:
        raise HTTPException(400, "empty message")
    try:
        container = client.containers.get(SERVER_CONTAINER)
        container.exec_run(["send-command", "say", text])
    except docker.errors.NotFound:
        raise HTTPException(404, "server container not found")
    return {"ok": True}


@app.get("/")
def index():
    return FileResponse(Path(__file__).parent / "static" / "index.html")
