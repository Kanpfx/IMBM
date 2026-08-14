"""Serve the local replay viewer and parse selected SC2 replays in memory.

This is deliberately a static parser: it never launches StarCraft II.  It
uses replay tracker events for the approximate world state and reads the
terrain layers directly from the matching SC2Map archive.  Passing a log
directory keeps the old single-JSON export available as a compatibility mode.
"""

from __future__ import annotations

import argparse
import io
import json
import struct
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace
from typing import Any, BinaryIO, Iterable


# Small, display-only catalog.  Missing entries are still rendered and simply
# show "unknown" for attributes that are not stored in a normal replay.
UNIT_META: dict[str, dict[str, Any]] = {
    "SCV": {"hp": 45, "kind": "worker"},
    "Marine": {"hp": 45, "kind": "army"},
    "Marauder": {"hp": 125, "kind": "army"},
    "Reaper": {"hp": 60, "kind": "army"},
    "Ghost": {"hp": 100, "kind": "army"},
    "Hellion": {"hp": 90, "kind": "army"},
    "HellionTank": {"hp": 135, "kind": "army"},
    "WidowMine": {"hp": 90, "kind": "army"},
    "SiegeTank": {"hp": 175, "kind": "army"},
    "SiegeTankSieged": {"hp": 175, "kind": "army"},
    "Cyclone": {"hp": 130, "kind": "army"},
    "Thor": {"hp": 400, "kind": "army"},
    "VikingFighter": {"hp": 135, "kind": "army"},
    "VikingAssault": {"hp": 135, "kind": "army"},
    "Medivac": {"hp": 150, "kind": "army"},
    "Liberator": {"hp": 180, "kind": "army"},
    "Raven": {"hp": 140, "kind": "army"},
    "Banshee": {"hp": 140, "kind": "army"},
    "Battlecruiser": {"hp": 550, "kind": "army"},
    "CommandCenter": {"hp": 1500, "kind": "structure"},
    "OrbitalCommand": {"hp": 1500, "kind": "structure"},
    "PlanetaryFortress": {"hp": 1500, "kind": "structure"},
    "SupplyDepot": {"hp": 400, "kind": "structure"},
    "SupplyDepotLowered": {"hp": 400, "kind": "structure"},
    "Refinery": {"hp": 500, "kind": "structure"},
    "Barracks": {"hp": 1000, "kind": "structure"},
    "Factory": {"hp": 1250, "kind": "structure"},
    "Starport": {"hp": 1300, "kind": "structure"},
    "EngineeringBay": {"hp": 850, "kind": "structure"},
    "Armory": {"hp": 750, "kind": "structure"},
    "FusionCore": {"hp": 750, "kind": "structure"},
    "Bunker": {"hp": 400, "kind": "structure"},
    "MissileTurret": {"hp": 250, "kind": "structure"},
    "SensorTower": {"hp": 200, "kind": "structure"},
    "TechLab": {"hp": 400, "kind": "structure"},
    "Reactor": {"hp": 400, "kind": "structure"},
    "Probe": {"hp": 20, "shield": 20, "kind": "worker"},
    "Zealot": {"hp": 100, "shield": 50, "kind": "army"},
    "Stalker": {"hp": 80, "shield": 80, "kind": "army"},
    "Adept": {"hp": 70, "shield": 70, "kind": "army"},
    "Sentry": {"hp": 40, "shield": 40, "kind": "army"},
    "Nexus": {"hp": 1000, "shield": 1000, "kind": "structure"},
    "Pylon": {"hp": 200, "shield": 200, "kind": "structure"},
    "Assimilator": {"hp": 300, "shield": 300, "kind": "structure"},
    "Gateway": {"hp": 500, "shield": 500, "kind": "structure"},
    "CyberneticsCore": {"hp": 550, "shield": 550, "kind": "structure"},
    "Drone": {"hp": 40, "kind": "worker"},
    "Zergling": {"hp": 35, "kind": "army"},
    "Baneling": {"hp": 30, "kind": "army"},
    "Roach": {"hp": 145, "kind": "army"},
    "Hydralisk": {"hp": 90, "kind": "army"},
    "Queen": {"hp": 175, "kind": "army"},
    "Overlord": {"hp": 200, "kind": "unit"},
    "Hatchery": {"hp": 1500, "kind": "structure"},
    "Lair": {"hp": 2000, "kind": "structure"},
    "Hive": {"hp": 2500, "kind": "structure"},
    "Extractor": {"hp": 500, "kind": "structure"},
    "SpawningPool": {"hp": 1000, "kind": "structure"},
}

RESOURCE_MARKERS = ("MineralField", "VespeneGeyser", "RichMineralField")
HIDDEN_MARKERS = ("Beacon", "Placeholder", "Dummy", "Invisible")


def _rle(values: Iterable[int]) -> list[int]:
    result: list[int] = []
    iterator = iter(values)
    try:
        current = next(iterator)
    except StopIteration:
        return result
    count = 1
    for value in iterator:
        if value == current and count < 65535:
            count += 1
        else:
            result.extend((int(current), count))
            current, count = value, 1
    result.extend((int(current), count))
    return result


def _read_metadata(log_directory: Path) -> dict[str, Any]:
    path = log_directory / "metadata.json"
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _map_candidates(log_directory: Path, map_name: str) -> list[Path]:
    root = Path(__file__).resolve().parents[1]
    names = [map_name]
    if map_name.endswith("_v4"):
        names.append(map_name.removesuffix("_v4"))
    candidates: list[Path] = []
    for name in names:
        filename = name if name.lower().endswith(".sc2map") else f"{name}.SC2Map"
        candidates.extend(
            (
                log_directory / filename,
                root / "ares-sc2" / "tests" / "maps" / filename,
                root / "maps" / filename,
            )
        )
    return candidates


def find_map(log_directory: Path, map_name: str, explicit: Path | None) -> Path:
    if explicit:
        if explicit.is_file():
            return explicit
        raise FileNotFoundError(f"地图文件不存在：{explicit}")
    for candidate in _map_candidates(log_directory, map_name):
        if candidate.is_file():
            return candidate
    raise FileNotFoundError(f"找不到 {map_name}.SC2Map；请用 --map 指定地图文件，或把地图放到日志目录。")


def parse_map(
    source: Path | BinaryIO, display_name: str | None = None
) -> dict[str, Any]:
    import mpyq
    from sc2reader.objects import MapInfo

    archive = mpyq.MPQArchive(str(source) if isinstance(source, Path) else source)
    height_payload = archive.read_file(b"t3HeightMap")
    if not height_payload or len(height_payload) < 32:
        raise ValueError("地图中没有可用的 t3HeightMap")
    magic, _version, vertex_width, vertex_height = struct.unpack_from(
        "<4sIII", height_payload
    )
    if magic != b"HMAP":
        raise ValueError("t3HeightMap 格式不受支持")
    expected = 32 + vertex_width * vertex_height * 6
    if len(height_payload) < expected:
        raise ValueError("t3HeightMap 数据不完整")
    heights = height_payload[36:expected:6]

    width, height = vertex_width - 1, vertex_height - 1
    pathing_payload = archive.read_file(b"CellAttribute_Pnp")
    if not pathing_payload or len(pathing_payload) != width * height + 4:
        raise ValueError("地图中没有可用的 CellAttribute_Pnp 可行域")
    pathable = (1 if value == 0 else 0 for value in pathing_payload[4:])
    playable = {"left": 0, "bottom": 0, "right": width, "top": height}
    map_info_payload = archive.read_file(b"MapInfo")
    if map_info_payload:
        map_info = MapInfo(map_info_payload)
        if all(
            hasattr(map_info, name)
            for name in ("camera_left", "camera_bottom", "camera_right", "camera_top")
        ):
            # MapInfo stores camera padding outside the editor's playable rectangle.
            playable = {
                "left": max(0, min(width, int(map_info.camera_left) + 7)),
                "bottom": max(0, min(height, int(map_info.camera_bottom) + 4)),
                "right": max(0, min(width, int(map_info.camera_right) - 7)),
                "top": max(0, min(height, int(map_info.camera_top) - 4)),
            }
            if (
                playable["right"] <= playable["left"]
                or playable["top"] <= playable["bottom"]
            ):
                playable = {"left": 0, "bottom": 0, "right": width, "top": height}
    return {
        "name": display_name
        or (source.name if isinstance(source, Path) else "map.SC2Map"),
        "width": width,
        "height": height,
        "playable": playable,
        "height_width": vertex_width,
        "height_height": vertex_height,
        "height_rle": _rle(heights),
        "pathable_rle": _rle(pathable),
    }


def replay_map_name(source: Path | BinaryIO) -> str:
    import mpyq

    archive = mpyq.MPQArchive(str(source) if isinstance(source, Path) else source)
    payload = archive.read_file(b"replay.gamemetadata.json")
    if not payload:
        return ""
    raw_name = str(json.loads(payload).get("MapName") or "")
    return Path(raw_name.replace("\\", "/")).stem


def _enable_local_replays() -> None:
    """sc2reader 1.9 assumes Battle.net cache handles; local API games omit them."""
    import sc2reader.resources as resources

    resources.GAME_SPEED_FACTOR.setdefault("", resources.GAME_SPEED_FACTOR["LotV"])
    original = resources.Replay.load_details
    if getattr(original, "_imbm_local_patch", False):
        return

    def load_details(replay: Any) -> None:
        details = replay.raw_data.get("replay.details") or replay.raw_data.get(
            "replay.details.backup"
        )
        if details is not None and not details.get("cache_handles"):
            details["cache_handles"] = [SimpleNamespace(server="local", hash="")]
        original(replay)

    load_details._imbm_local_patch = True  # type: ignore[attr-defined]
    resources.Replay.load_details = load_details


def _player_info(replay: Any, metadata: dict[str, Any]) -> list[dict[str, Any]]:
    details = replay.raw_data.get("replay.details", {})
    colors = ("#e84545", "#4385ff", "#35b46f", "#f0b429")
    players = []
    for index, player in enumerate(details.get("players", []), start=1):
        raw_color = player.get("color", {})
        color = "#{r:02x}{g:02x}{b:02x}".format(
            r=raw_color.get("r", 100),
            g=raw_color.get("g", 100),
            b=raw_color.get("b", 100),
        )
        race = (
            metadata.get("own_race") if index == 1 else metadata.get("enemy_race")
        ) or player.get("race", "Unknown")
        players.append(
            {
                "id": index,
                "name": player.get("name") or f"Player {index}",
                "race": race,
                "result": {1: "Win", 2: "Loss"}.get(player.get("result"), "Unknown"),
                "color": color or colors[(index - 1) % len(colors)],
            }
        )
    return players


def _display_meta(unit_type: str) -> dict[str, Any]:
    result = dict(UNIT_META.get(unit_type, {}))
    if any(marker in unit_type for marker in RESOURCE_MARKERS):
        result["kind"] = "resource"
    result.setdefault("kind", "unit")
    return result


def parse_replay(
    source: Path | BinaryIO,
    metadata: dict[str, Any],
    display_name: str | None = None,
) -> dict[str, Any]:
    try:
        import sc2reader
        from sc2reader.engine.engine import GameEngine
    except ImportError as exc:
        raise RuntimeError("缺少 sc2reader；请先执行 `poetry install`") from exc

    _enable_local_replays()
    replay_source = str(source) if isinstance(source, Path) else source
    replay = sc2reader.load_replay(replay_source, load_level=4, engine=GameEngine([]))
    events: list[list[Any]] = []
    unit_types: set[str] = set()
    for event in replay.tracker_events:
        name = event.name
        if name in {"UnitBornEvent", "UnitInitEvent"}:
            unit_type = event.unit_type_name
            if any(marker in unit_type for marker in HIDDEN_MARKERS):
                continue
            unit_types.add(unit_type)
            events.append(
                [
                    "b" if name == "UnitBornEvent" else "i",
                    event.frame,
                    str(event.unit_id),
                    event.unit_id_index,
                    event.upkeep_pid,
                    unit_type,
                    event.x,
                    event.y,
                ]
            )
        elif name == "UnitDoneEvent":
            events.append(["f", event.frame, str(event.unit_id)])
        elif name == "UnitDiedEvent":
            events.append(["d", event.frame, str(event.unit_id), event.x, event.y])
        elif name == "UnitTypeChangeEvent":
            unit_types.add(event.unit_type_name)
            events.append(["t", event.frame, str(event.unit_id), event.unit_type_name])
        elif name == "UnitOwnerChangeEvent":
            events.append(["o", event.frame, str(event.unit_id), event.upkeep_pid])
        elif name == "UnitPositionsEvent":
            for unit_index, (x, y) in event.positions:
                events.append(["p", event.frame, unit_index, x, y])

    stats = [
        [
            event.frame,
            event.pid,
            event.minerals_current,
            event.vespene_current,
            event.food_used,
            event.food_made,
            event.workers_active_count,
        ]
        for event in replay.tracker_events
        if event.name == "PlayerStatsEvent"
    ]
    return {
        "version": 1,
        "replay": {
            "file": display_name
            or (source.name if isinstance(source, Path) else "replay.SC2Replay"),
            "game_version": replay.release_string,
            "loops": replay.frames,
            "players": _player_info(replay, metadata),
        },
        "unit_meta": {name: _display_meta(name) for name in sorted(unit_types)},
        "events": events,
        "stats": stats,
    }


def build(log_directory: Path, replay_path: Path, map_path: Path) -> dict[str, Any]:
    metadata = _read_metadata(log_directory)
    result = parse_replay(replay_path, metadata)
    result["map"] = parse_map(map_path)
    result["alignment"] = {
        "game_step": int(metadata.get("game_step", 2)),
        "note": "game_loop = log iteration × game_step",
    }
    return result


def build_in_memory(
    replay_data: bytes,
    metadata: dict[str, Any],
    map_data: bytes = b"",
    map_filename: str = "",
) -> dict[str, Any]:
    result = parse_replay(io.BytesIO(replay_data), metadata, "replay.SC2Replay")
    if map_data:
        result["map"] = parse_map(io.BytesIO(map_data), map_filename or "map.SC2Map")
    else:
        map_name = str(
            metadata.get("map_name") or replay_map_name(io.BytesIO(replay_data))
        )
        if not map_name:
            raise ValueError("无法确定地图名称；请把对应 SC2Map 和日志放在同一选择目录中")
        map_path = find_map(Path.cwd(), map_name, None)
        result["map"] = parse_map(map_path)
    result["alignment"] = {
        "game_step": int(metadata.get("game_step", 2)),
        "note": "game_loop = log iteration × game_step",
    }
    return result


MAX_REQUEST_BYTES = 128 * 1024 * 1024


class ReplayViewerHandler(BaseHTTPRequestHandler):
    html_path = Path(__file__).with_name("日志查看器.html")

    def log_message(self, format: str, *args: Any) -> None:
        print(f"[viewer] {self.address_string()} - {format % args}")

    def _send(self, status: int, payload: bytes, content_type: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(payload)

    def do_GET(self) -> None:
        if self.path in {"/", "/index.html"}:
            self._send(200, self.html_path.read_bytes(), "text/html; charset=utf-8")
        elif self.path == "/favicon.ico":
            self._send(204, b"", "image/x-icon")
        else:
            self._send(404, b"Not found", "text/plain; charset=utf-8")

    def do_POST(self) -> None:
        if self.path != "/api/replay-view":
            self._send(404, b"Not found", "text/plain; charset=utf-8")
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if length < 12 or length > MAX_REQUEST_BYTES:
                raise ValueError("上传内容大小不合法")
            body = self.rfile.read(length)
            replay_size, map_size, metadata_size = struct.unpack_from("<III", body)
            if 12 + replay_size + map_size + metadata_size != len(body):
                raise ValueError("Replay 请求数据不完整")
            cursor = 12
            replay_data = body[cursor : cursor + replay_size]
            cursor += replay_size
            map_data = body[cursor : cursor + map_size]
            cursor += map_size
            request_metadata = json.loads(body[cursor:].decode("utf-8"))
            metadata = request_metadata.get("metadata") or {}
            payload = build_in_memory(
                replay_data,
                metadata,
                map_data,
                str(request_metadata.get("map_filename") or ""),
            )
            encoded = json.dumps(
                payload, ensure_ascii=False, separators=(",", ":")
            ).encode("utf-8")
            self._send(200, encoded, "application/json; charset=utf-8")
        except Exception as exc:
            encoded = json.dumps({"error": str(exc)}, ensure_ascii=False).encode(
                "utf-8"
            )
            self._send(400, encoded, "application/json; charset=utf-8")


def serve(host: str, port: int, open_browser: bool) -> None:
    server = ThreadingHTTPServer((host, port), ReplayViewerHandler)
    url = f"http://{host}:{server.server_port}/"
    print(f"日志查看器已启动：{url}")
    print("选择日志目录后 Replay 会在内存中解析；关闭此窗口即可停止服务。")
    if open_browser:
        threading.Timer(0.35, webbrowser.open, args=(url,)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n日志查看器已停止。")
    finally:
        server.server_close()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="启动本地日志查看器，或显式把 SC2Replay 编译为 replay_view.json。"
    )
    parser.add_argument(
        "log_directory", nargs="?", type=Path, help="兼容模式：输出 JSON 的日志目录"
    )
    parser.add_argument("--host", default="127.0.0.1", help="本地服务地址")
    parser.add_argument("--port", type=int, default=0, help="本地服务端口，0 表示自动选择")
    parser.add_argument("--no-browser", action="store_true", help="启动服务但不自动打开浏览器")
    parser.add_argument("--replay", type=Path, help="显式指定 SC2Replay 文件")
    parser.add_argument("--map", dest="map_path", type=Path, help="显式指定 SC2Map 文件")
    parser.add_argument("--output", type=Path, help="输出路径，默认写入日志目录")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.log_directory is None:
        serve(args.host, args.port, not args.no_browser)
        return
    log_directory = args.log_directory.resolve()
    replay_path = (args.replay or log_directory / "replay.SC2Replay").resolve()
    if not replay_path.is_file():
        raise FileNotFoundError(f"Replay 文件不存在：{replay_path}")
    metadata = _read_metadata(log_directory)
    map_name = str(metadata.get("map_name") or replay_map_name(replay_path))
    if not map_name and not args.map_path:
        raise ValueError("metadata.json 中没有 map_name；请使用 --map 指定地图")
    map_path = find_map(log_directory, map_name, args.map_path)
    output = (args.output or log_directory / "replay_view.json").resolve()
    payload = build(log_directory, replay_path, map_path)
    output.write_text(
        json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8",
    )
    print(
        f"已生成 {output}（{len(payload['events'])} 个状态事件，"
        f"地图 {payload['map']['width']}×{payload['map']['height']}）"
    )


if __name__ == "__main__":
    main()
