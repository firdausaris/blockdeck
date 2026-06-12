"""blockdeck dashboard — status and controls for the Bedrock server stack."""

import base64
import os
import re
import secrets
import shutil
import socket
import struct
import tempfile
import threading
import time
import zipfile
from datetime import datetime, timezone
from pathlib import Path

import docker
from fastapi import FastAPI, Form, HTTPException, Request, Response, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

SERVER_HOST = os.environ.get("SERVER_HOST", "bedrock")
SERVER_PORT = int(os.environ.get("SERVER_PORT", "19132"))
SERVER_CONTAINER = os.environ.get("SERVER_CONTAINER", "bedrock")
UPDATER_CONTAINER = os.environ.get("UPDATER_CONTAINER", "bedrock-updater")
MAP_CONTAINER = os.environ.get("MAP_CONTAINER", "bedrock-map")
BACKUP_CONTAINER = os.environ.get("BACKUP_CONTAINER", "bedrock-backup")
BACKUPS_DIR = Path("/backups")
SERVER_DIR = Path("/server")
MAP_DIR = Path("/map-data/current")
PROPS_FILE = SERVER_DIR / "server.properties"
WORLDS_DIR = SERVER_DIR / "worlds"
BACKUP_CFG = Path("/backup-config/config.yml")
WORLD_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 _'-]{0,39}$")

app = FastAPI(title="blockdeck")
client = docker.from_env()

# --- Authentication ---
# HTTP Basic over the whole app (API, static page, map, downloads).
# Middleware rather than a route dependency so the /map static mount is
# covered too. No password set = open dashboard, warned about in the UI.

DASH_USERNAME = os.environ.get("DASH_USERNAME", "admin")
DASH_PASSWORD = os.environ.get("DASH_PASSWORD", "")

if not DASH_PASSWORD:
    print("WARNING: DASH_PASSWORD is not set - the dashboard is open to the whole LAN")


@app.middleware("http")
async def basic_auth(request: Request, call_next):
    if DASH_PASSWORD:
        header = request.headers.get("authorization", "")
        ok = False
        if header.lower().startswith("basic "):
            try:
                user, _, password = base64.b64decode(header[6:]).decode().partition(":")
                ok = secrets.compare_digest(user, DASH_USERNAME) and secrets.compare_digest(
                    password, DASH_PASSWORD
                )
            except Exception:
                ok = False
        if not ok:
            return Response(
                status_code=401,
                headers={"WWW-Authenticate": 'Basic realm="blockdeck"'},
            )
    return await call_next(request)

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


def human_size(n: float) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n} B" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024


# --- System stats ---
# /proc inside the container reflects the whole host (no cgroup limits are
# set), so host CPU/RAM/load come straight from there. CPU% is computed
# from the delta since the previous poll — zero added latency.

_prev_cpu: tuple[int, int] | None = None


def _read_cpu() -> tuple[int, int]:
    fields = [int(x) for x in Path("/proc/stat").read_text().splitlines()[0].split()[1:]]
    idle = fields[3] + (fields[4] if len(fields) > 4 else 0)
    return idle, sum(fields)


def host_stats():
    global _prev_cpu
    cpu_percent = None
    cur = _read_cpu()
    if _prev_cpu and cur[1] != _prev_cpu[1]:
        d_idle, d_total = cur[0] - _prev_cpu[0], cur[1] - _prev_cpu[1]
        cpu_percent = round(100 * (1 - d_idle / d_total), 1)
    _prev_cpu = cur

    mem = {}
    for line in Path("/proc/meminfo").read_text().splitlines():
        key, _, rest = line.partition(":")
        mem[key] = int(rest.strip().split()[0]) * 1024
    mem_total, mem_avail = mem["MemTotal"], mem["MemAvailable"]

    disk = shutil.disk_usage("/server")
    return {
        "cpu_percent": cpu_percent,
        "cpu_count": os.cpu_count(),
        "load": Path("/proc/loadavg").read_text().split()[0],
        "mem_used": human_size(mem_total - mem_avail),
        "mem_total": human_size(mem_total),
        "mem_percent": round(100 * (mem_total - mem_avail) / mem_total, 1),
        "disk_used": human_size(disk.used),
        "disk_total": human_size(disk.total),
        "disk_percent": round(100 * disk.used / disk.total, 1),
    }


# The server process's own usage via the docker stats API. One sample
# takes ~1-2s, so it's collected in a background thread and cached
# rather than blocking every status request.

_server_stats: dict = {}


def _server_stats_loop():
    while True:
        try:
            s = client.containers.get(SERVER_CONTAINER).stats(stream=False)
            mem = s["memory_stats"]["usage"] - s["memory_stats"].get("stats", {}).get(
                "inactive_file", 0
            )
            cpu_d = (
                s["cpu_stats"]["cpu_usage"]["total_usage"]
                - s["precpu_stats"]["cpu_usage"]["total_usage"]
            )
            sys_d = s["cpu_stats"].get("system_cpu_usage", 0) - s["precpu_stats"].get(
                "system_cpu_usage", 0
            )
            ncpu = s["cpu_stats"].get("online_cpus") or os.cpu_count() or 1
            _server_stats.update(
                {
                    "mem": human_size(mem),
                    "cpu_percent": round(cpu_d / sys_d * ncpu * 100, 1) if sys_d else None,
                }
            )
        except Exception:
            _server_stats.clear()
        time.sleep(10)


threading.Thread(target=_server_stats_loop, daemon=True).start()


# --- World management ---
# The active world is the level-name in data/server.properties — the file
# the server actually reads. The itzg image only overrides it when the
# LEVEL_NAME env var is set, which the compose file deliberately doesn't.


def active_world() -> str | None:
    try:
        for line in PROPS_FILE.read_text().splitlines():
            if line.startswith("level-name="):
                return line.split("=", 1)[1].strip()
    except OSError:
        pass
    return None


def set_properties(**props: str) -> None:
    """Update or append key=value pairs in server.properties."""
    lines = PROPS_FILE.read_text().splitlines() if PROPS_FILE.exists() else []
    pending = {k.replace("_", "-"): v for k, v in props.items()}
    out = []
    for line in lines:
        key = line.split("=", 1)[0]
        if key in pending:
            out.append(f"{key}={pending.pop(key)}")
        else:
            out.append(line)
    out.extend(f"{k}={v}" for k, v in pending.items())
    PROPS_FILE.write_text("\n".join(out) + "\n")
    _match_server_owner(PROPS_FILE)


def _match_server_owner(path: Path) -> None:
    """Files we create must be owned like the server data (we run as root)."""
    st = SERVER_DIR.stat()
    os.chown(path, st.st_uid, st.st_gid)
    if path.is_dir():
        for p in path.rglob("*"):
            os.chown(p, st.st_uid, st.st_gid)


def worlds_list():
    act = active_world()
    worlds = []
    if WORLDS_DIR.is_dir():
        for d in sorted(WORLDS_DIR.iterdir()):
            if not d.is_dir() or ".bak." in d.name:
                continue
            size = sum(f.stat().st_size for f in d.rglob("*") if f.is_file())
            worlds.append(
                {"name": d.name, "size": human_size(size), "active": d.name == act}
            )
    return worlds


def switch_world(name: str, seed: str | None = None) -> None:
    """Stop the server, point it (and the backup service) at a world, start."""
    try:
        server = client.containers.get(SERVER_CONTAINER)
    except docker.errors.NotFound:
        raise HTTPException(404, "server container not found")
    server.stop(timeout=60)
    props = {"level_name": name}
    if seed is not None:
        props["level_seed"] = seed
    set_properties(**props)
    if BACKUP_CFG.exists():
        text = re.sub(
            r"- /server/worlds/.*", f"- /server/worlds/{name}", BACKUP_CFG.read_text()
        )
        BACKUP_CFG.write_text(text)
    server.start()
    try:
        client.containers.get(BACKUP_CONTAINER).restart()
    except docker.errors.NotFound:
        pass


def world_seed() -> str | None:
    """Reads RandomSeed from the world's level.dat (Bedrock NBT).

    Bedrock NBT is uncompressed little-endian; rather than a full parser,
    locate the Long tag (0x04) named "RandomSeed" (name length 10) and
    read the 8 bytes after it. Returned as a string: seeds are int64 and
    would lose precision as a JavaScript number.
    """
    level_dat = WORLDS_DIR / (active_world() or "") / "level.dat"
    if not level_dat.exists():
        return None
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
    if not (MAP_DIR / "index.html").exists():
        return {"rendered": False, "rendered_at": None}
    # Prefer the renderer's marker file; uNmINeD's own output files carry
    # template mtimes, not the render time
    marker = MAP_DIR / ".rendered-at"
    stamp = marker if marker.exists() else MAP_DIR / "index.html"
    return {
        "rendered": True,
        "rendered_at": datetime.fromtimestamp(
            stamp.stat().st_mtime, tz=timezone.utc
        ).isoformat(),
    }


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
        "active_world": active_world(),
        "worlds": worlds_list(),
        "backups": backups_summary(),
        "map": map_info(),
        "system": host_stats(),
        "server_stats": _server_stats or None,
        "auth": bool(DASH_PASSWORD),
        "checked_at": datetime.now(tz=timezone.utc).isoformat(),
    }


@app.get("/api/backups/{name}")
def download_backup(name: str):
    """Download a backup (.mcworld = zip of the world, importable anywhere)."""
    path = BACKUPS_DIR / name
    if Path(name).name != name or not name.endswith(".mcworld") or not path.is_file():
        raise HTTPException(404, "backup not found")
    return FileResponse(path, filename=name, media_type="application/zip")


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


class NewWorld(BaseModel):
    name: str
    seed: str | None = None


@app.post("/api/worlds")
def create_world(body: NewWorld):
    name = body.name.strip()
    if not WORLD_NAME_RE.match(name):
        raise HTTPException(400, "invalid name: letters, digits, spaces, _ ' - only")
    if (WORLDS_DIR / name).exists():
        raise HTTPException(409, f"world '{name}' already exists")
    # empty seed = random; the server generates the world on startup
    switch_world(name, seed=(body.seed or "").strip())
    return {"ok": True, "message": f"Creating and starting world '{name}'."}


class ActivateWorld(BaseModel):
    name: str


@app.post("/api/worlds/activate")
def activate_world(body: ActivateWorld):
    name = body.name.strip()
    if not (WORLDS_DIR / name).is_dir():
        raise HTTPException(404, f"no such world: {name}")
    if name == active_world():
        return {"ok": True, "message": f"'{name}' is already active."}
    switch_world(name)
    return {"ok": True, "message": f"Switched to world '{name}'."}


@app.post("/api/worlds/import")
def import_world(file: UploadFile, name: str | None = Form(None)):
    with tempfile.TemporaryDirectory() as tmp:
        archive = Path(tmp) / "upload.mcworld"
        with archive.open("wb") as f:
            shutil.copyfileobj(file.file, f)
        extracted = Path(tmp) / "world"
        try:
            with zipfile.ZipFile(archive) as z:
                z.extractall(extracted)
        except zipfile.BadZipFile:
            raise HTTPException(400, "not a valid .mcworld/.zip file")

        root = extracted
        if not (root / "level.dat").exists():
            hits = list(root.glob("*/level.dat")) + list(root.glob("*/*/level.dat"))
            if not hits:
                raise HTTPException(400, "no level.dat found — not a Bedrock world?")
            root = hits[0].parent

        world_name = (name or "").strip()
        if not world_name and (root / "levelname.txt").exists():
            world_name = (root / "levelname.txt").read_text().strip()
        if not world_name and file.filename:
            world_name = Path(file.filename).stem
        if not WORLD_NAME_RE.match(world_name):
            raise HTTPException(400, f"invalid world name '{world_name}' — provide one")
        if (WORLDS_DIR / world_name).exists():
            raise HTTPException(409, f"world '{world_name}' already exists")

        dest = WORLDS_DIR / world_name
        shutil.copytree(root, dest)
        _match_server_owner(dest)

    switch_world(world_name)
    return {"ok": True, "message": f"Imported and switched to '{world_name}'."}


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


@app.get("/favicon.svg")
def favicon():
    return FileResponse(
        Path(__file__).parent / "static" / "favicon.svg", media_type="image/svg+xml"
    )


# The rendered world map; the directory appears after the first render
app.mount("/map", StaticFiles(directory=MAP_DIR, html=True, check_dir=False))
