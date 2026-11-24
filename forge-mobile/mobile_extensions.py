"""Companion-owned frontend extensions and persistent UI settings."""
import hashlib
import json
import re
from pathlib import Path

from aiohttp import web


TRACE_LABELS = {
    "kind", "event", "target", "view", "route", "phase",
}
TRACE_TIMINGS = {
    "at", "dispatchDelayMs", "releaseToClickMs", "nextFrameMs", "totalMs",
    "firstByteMs", "status", "betweenMessagesMs", "handlerMs", "throughPaintMs", "durationMs",
}
TRACE_FLAGS = {"trusted", "success"}
TRACE_KINDS = {"recording", "interaction", "frame-delay", "request", "queue", "event-timing", "long-task"}
TRACE_LIMIT = 64 * 1024


def valid_trace_record(row):
    if not isinstance(row, dict) or not isinstance(row.get("kind"), str) or row["kind"] not in TRACE_KINDS:
        return False
    trace_id = row.get("trace")
    if not isinstance(trace_id, str) or not re.fullmatch(r"[0-9a-f]{8}", trace_id):
        return False
    for key, value in row.items():
        if key == "trace":
            continue
        if key in TRACE_LABELS and isinstance(value, str) and re.fullmatch(r"[a-zA-Z0-9_/-]{1,64}", value):
            continue
        if key in TRACE_TIMINGS and (value is None or (type(value) in (int, float) and 0 <= value <= 1e12)):
            continue
        if key in TRACE_FLAGS and (value is None or isinstance(value, bool)):
            continue
        return False
    return True


async def print_trace(request):
    if request.content_type != "application/json":
        raise web.HTTPUnsupportedMediaType()
    rows = await request.clone(client_max_size=TRACE_LIMIT).json()
    if not isinstance(rows, list) or not 1 <= len(rows) <= 160 or not all(map(valid_trace_record, rows)):
        raise web.HTTPBadRequest(text="Invalid performance trace")
    lines = ("[Forge Mobile trace] " + json.dumps(row, separators=(",", ":")) for row in rows)
    print("\n".join(lines), flush=True)
    return web.Response(status=204)


class MobileExtensions:
    def __init__(self, root, defaults):
        self.root = root.resolve()
        self.path = self.root.parent / "mobile-settings.json"
        self.defaults = defaults
        self.values = {}
        if self.path.exists():
            self.values = json.loads(self.path.read_text(encoding="utf-8"))

    def save(self):
        pending = self.path.with_suffix(".tmp")
        pending.write_text(json.dumps(self.values, ensure_ascii=True, indent=2), encoding="utf-8")
        pending.replace(self.path)

    def registry(self):
        docks = []
        folder = self.root / "docker-manager" / "docks"
        for manifest_path in sorted(folder.glob("*/dock.json")):
            entry = json.loads(manifest_path.read_text(encoding="utf-8"))
            dock_id = entry.get("id")
            if not isinstance(dock_id, str) or not re.fullmatch(r"[a-zA-Z0-9_-]+", dock_id):
                raise ValueError(f"Invalid dock id in {manifest_path.name}")
            entry.setdefault("script", "dock.js")
            entry.setdefault("style", "style.css")
            digest = hashlib.sha256()
            for field in ("script", "style"):
                path = (manifest_path.parent / entry[field]).resolve()
                if not path.is_relative_to(manifest_path.parent.resolve()) or not path.is_file():
                    raise ValueError(f"Missing or invalid {field} for dock {dock_id}")
                digest.update(path.read_bytes())
                relative = path.relative_to(self.root).as_posix()
                entry[field + "_url"] = "/_forge_mobile/extensions/" + relative
            entry["content_hash"] = digest.hexdigest()[:16]
            docks.append(entry)
        return {"revision": 1, "debug": {"allow_multiple_instances": False}, "docks": docks}

    def manifests(self):
        manifests = {}
        for path in sorted(self.root.glob("*/extension.json")):
            value = json.loads(path.read_text(encoding="utf-8"))
            if value.get("id") != path.parent.name:
                raise ValueError("Extension id must match its directory")
            assets = value.get("styles", []) + value.get("scripts", []) + value.get("templates", [])
            digest = hashlib.sha256()
            for asset in assets:
                asset_path = (path.parent / asset).resolve()
                if not asset_path.is_relative_to(path.parent.resolve()):
                    raise ValueError(f"Invalid asset in {path.name}")
                digest.update(asset_path.read_bytes())
            value["asset_version"] = digest.hexdigest()[:16]
            manifests[value["id"]] = value
        ordered = []
        active = set()
        complete = set()

        def visit(name):
            if name in complete:
                return
            if name in active or name not in manifests:
                raise ValueError("Invalid mobile extension dependencies")
            active.add(name)
            for requirement in manifests[name].get("requires", []):
                visit(requirement)
            active.remove(name)
            complete.add(name)
            ordered.append(manifests[name])

        for name in manifests:
            visit(name)
        return ordered

    async def handle(self, request, tail):
        if tail == "trace" and request.method == "POST":
            return await print_trace(request)
        if tail == "taps" and request.method == "GET":
            return web.FileResponse(self.root / "mobile-workspace" / "tap-report.html",
                                    headers={"Cache-Control": "no-store"})
        if tail == "bootstrap" and request.method == "GET":
            return web.json_response({
                "settings": self.defaults | self.values,
                "extensions": self.manifests(),
                "registry": self.registry(),
            }, headers={"Cache-Control": "no-store"})
        if tail == "settings":
            if request.method == "GET":
                return web.json_response(self.defaults | self.values)
            if request.method == "POST":
                patch = await request.json()
                if not isinstance(patch, dict) or not all(key in self.defaults for key in patch):
                    raise web.HTTPBadRequest(text="Unknown mobile settings")
                self.values.update(patch)
                self.save()
                return web.json_response({"ok": True})
        if tail == "docker/registry" and request.method == "GET":
            return web.json_response(self.registry(), headers={"Cache-Control": "no-store"})
        if tail == "docker/state":
            if request.method == "GET":
                return web.json_response(self.values.get("mobile-docks", self.defaults["mobile-docks"]))
            if request.method == "POST":
                value = await request.json()
                if not isinstance(value, dict) or not isinstance(value.get("docks"), list):
                    raise web.HTTPBadRequest(text="Invalid dock state")
                self.values["mobile-docks"] = value
                self.save()
                return web.json_response({"ok": True})
        if tail.startswith("extensions/") and request.method == "GET":
            path = (self.root / tail.removeprefix("extensions/")).resolve()
            if not path.is_relative_to(self.root) or not path.is_file():
                raise web.HTTPNotFound()
            if path.suffix == ".js" and "docks" in path.relative_to(self.root).parts:
                # Accept the original custom-dock registration format in this isolated client.
                source = path.read_text(encoding="utf-8").replace("window.ForgeDockManager", "window.ForgeMobileDockManager")
                return web.Response(text=source, content_type="application/javascript",
                                    headers={"Cache-Control": "no-cache"})
            return web.FileResponse(path, headers={"Cache-Control": "no-cache"})
        return None
