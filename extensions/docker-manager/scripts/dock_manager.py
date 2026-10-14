import hashlib
import html
import json
import time
from pathlib import Path

import gradio as gr
from fastapi import Body

from modules import script_callbacks, scripts
from modules.ui_gradio_extensions import webpath


EXT_ROOT = Path(__file__).resolve().parents[1]
DOCKS_ROOT = EXT_ROOT / "docks"
DEBUG_PATH = EXT_ROOT / "debug.json"
STATE_DIR = EXT_ROOT / "state"
STATE_PATH = STATE_DIR / "dock-layout.json"


def read_debug_flags():
    defaults = {"allow_multiple_instances": False}
    if not DEBUG_PATH.is_file():
        return defaults

    try:
        parsed = json.loads(DEBUG_PATH.read_text(encoding="utf-8"))
    except Exception as exc:
        print(f"[Forge Dock Manager] Ignoring invalid debug.json ({exc})")
        return defaults

    return {
        "allow_multiple_instances": parsed.get("allow_multiple_instances") is True,
    }



def fingerprint_dock_folder(folder: Path) -> str:
    """Hash a dock folder so frontend refresh can detect code/style/asset changes."""
    digest = hashlib.sha256()

    try:
        files = sorted(
            (
                path
                for path in folder.rglob("*")
                if path.is_file()
                and "__pycache__" not in path.parts
                and path.suffix.lower() not in {".pyc", ".pyo"}
                and not path.name.endswith("~")
            ),
            key=lambda path: path.relative_to(folder).as_posix().lower(),
        )

        for path in files:
            relative = path.relative_to(folder).as_posix().encode("utf-8", errors="replace")
            digest.update(len(relative).to_bytes(4, "big"))
            digest.update(relative)
            with path.open("rb") as handle:
                while chunk := handle.read(1024 * 1024):
                    digest.update(chunk)
    except Exception as exc:
        print(f"[Forge Dock Manager] Unable to fingerprint {folder.name} ({exc})")
        # Keep discovery working even if an editor temporarily locks a file.
        digest.update(str(time.time_ns()).encode("ascii"))

    return digest.hexdigest()[:20]

def discover_docks():
    docks = []

    if not DOCKS_ROOT.is_dir():
        return docks

    for folder in sorted(DOCKS_ROOT.iterdir(), key=lambda p: p.name.lower()):
        if not folder.is_dir():
            continue

        manifest_path = folder / "dock.json"
        if not manifest_path.is_file():
            continue

        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except Exception as exc:
            print(f"[Forge Dock Manager] Skipping {folder.name}: invalid dock.json ({exc})")
            continue

        dock_id = str(manifest.get("id", "")).strip()
        name = str(manifest.get("name", dock_id)).strip()
        script_name = str(manifest.get("script", "dock.js")).strip()
        style_name = str(manifest.get("style", "style.css")).strip()
        allowed_widths = manifest.get("allowed_widths", ["half", "full"])
        default_width = str(manifest.get("default_width", "half")).strip().lower()

        if not dock_id or not name:
            print(f"[Forge Dock Manager] Skipping {folder.name}: manifest requires id and name")
            continue

        if dock_id != folder.name:
            print(
                f"[Forge Dock Manager] Skipping {folder.name}: manifest id '{dock_id}' "
                "must match the dock folder name"
            )
            continue

        allowed_widths = [
            str(value).lower()
            for value in allowed_widths
            if str(value).lower() in {"half", "full"}
        ]
        if not allowed_widths:
            allowed_widths = ["half", "full"]
        if default_width not in allowed_widths:
            default_width = allowed_widths[0]

        script_path = folder / script_name
        if not script_path.is_file():
            print(f"[Forge Dock Manager] Skipping {dock_id}: missing {script_name}")
            continue

        style_path = folder / style_name

        docks.append(
            {
                "id": dock_id,
                "name": name,
                "version": manifest.get("version", 1),
                "default_width": default_width,
                "allowed_widths": allowed_widths,
                "tabs": manifest.get("tabs", []),
                "content_hash": fingerprint_dock_folder(folder),
                "script_url": webpath(str(script_path)),
                "style_url": webpath(str(style_path)) if style_path.is_file() else None,
            }
        )

    return docks


def build_registry_payload():
    return {
        "docks": discover_docks(),
        "debug": read_debug_flags(),
        "revision": time.time_ns(),
    }


def render_registry_html(payload):
    registry_json = html.escape(json.dumps(payload, separators=(",", ":")), quote=True)
    return f'<span class="fdm-registry" data-fdm-registry="{registry_json}" hidden></span>'


def render_native_dock_select(docks, tabname):
    options = []
    for dock in docks:
        dock_id = html.escape(str(dock["id"]), quote=True)
        dock_name = html.escape(str(dock["name"]))
        options.append(f'<option value="{dock_id}">{dock_name}</option>')

    disabled = " disabled" if not options else ""
    options_html = "".join(options)
    return (
        f'<div class="fdm-native-dock-field">'
        f'<label for="{tabname}_fdm_dock_native">Dock</label>'
        f'<select id="{tabname}_fdm_dock_native" class="fdm-native-dock-select" '
        f'data-fdm-tab="{tabname}"{disabled}>{options_html}</select>'
        f'</div>'
    )


def render_native_width_select(tabname, default_width="half"):
    default_width = "full" if default_width == "full" else "half"
    half_selected = " selected" if default_width == "half" else ""
    full_selected = " selected" if default_width == "full" else ""
    return (
        f'<div class="fdm-native-width-field">'
        f'<label for="{tabname}_fdm_width_native">Width</label>'
        f'<select id="{tabname}_fdm_width_native" class="fdm-native-width-select" '
        f'data-fdm-tab="{tabname}">'
        f'<option value="half"{half_selected}>Half</option>'
        f'<option value="full"{full_selected}>Full</option>'
        f'</select>'
        f'</div>'
    )


def refresh_registry():
    payload = build_registry_payload()
    return render_registry_html(payload)


def read_saved_layout():
    default = {"version": 2, "locked": False, "docks": []}
    if not STATE_PATH.is_file():
        return default

    try:
        parsed = json.loads(STATE_PATH.read_text(encoding="utf-8"))
    except Exception as exc:
        print(f"[Forge Dock Manager] Ignoring invalid dock layout ({exc})")
        return default

    docks = parsed.get("docks") if isinstance(parsed, dict) else []
    if not isinstance(docks, list):
        docks = []

    return {
        "version": 2,
        "locked": parsed.get("locked") is True if isinstance(parsed, dict) else False,
        "docks": docks,
    }


def normalize_layout(payload):
    locked = payload.get("locked") is True if isinstance(payload, dict) else False
    docks = payload.get("docks") if isinstance(payload, dict) else []
    if not isinstance(docks, list):
        docks = []

    normalized = []
    for item in docks:
        if not isinstance(item, dict):
            continue

        dock_id = str(item.get("dock_id", "")).strip()
        instance_id = str(item.get("instance_id", dock_id)).strip()
        width = str(item.get("width", "half")).strip().lower()
        side = str(item.get("side", "right")).strip().lower()
        y = item.get("y", 1)
        ordinal = item.get("ordinal", 1)
        labels = item.get("labels", False) is True

        if not dock_id or not instance_id:
            continue
        if width not in {"half", "full"}:
            width = "half"
        if side not in {"left", "right", "center"}:
            side = "right"
        try:
            y = float(y)
        except Exception:
            y = 1.0
        y = min(1.0, max(0.0, y))
        try:
            ordinal = int(ordinal)
        except Exception:
            ordinal = 1
        ordinal = max(1, ordinal)

        normalized.append({
            "instance_id": instance_id,
            "dock_id": dock_id,
            "width": width,
            "side": side,
            "y": y,
            "ordinal": ordinal,
            "labels": labels,
        })

    return {"version": 2, "locked": locked, "docks": normalized}


def write_saved_layout(payload):
    normalized = normalize_layout(payload)

    try:
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        tmp_path = STATE_PATH.with_suffix(".tmp")
        tmp_path.write_text(
            json.dumps(normalized, ensure_ascii=False, separators=(",", ":")),
            encoding="utf-8",
        )
        tmp_path.replace(STATE_PATH)
    except Exception as exc:
        print(f"[Forge Dock Manager] Failed to save dock layout ({exc})")
        return False

    return True


async def api_get_state():
    return read_saved_layout()


async def api_set_state(payload: dict = Body(...)):
    ok = write_saved_layout(payload)
    return {"ok": ok, "state": read_saved_layout() if ok else None}


async def api_get_registry():
    return build_registry_payload()


def register_api(_demo, app):
    app.add_api_route(
        "/forge-dock-manager/state",
        api_get_state,
        methods=["GET"],
        name="forge_dock_manager_get_state",
    )
    app.add_api_route(
        "/forge-dock-manager/state",
        api_set_state,
        methods=["POST"],
        name="forge_dock_manager_set_state",
    )
    app.add_api_route(
        "/forge-dock-manager/registry",
        api_get_registry,
        methods=["GET"],
        name="forge_dock_manager_get_registry",
    )


script_callbacks.on_app_started(register_api, name="forge_dock_manager_api")


class DockerManager(scripts.ScriptBuiltinUI):
    section = None
    create_group = False
    sorting_priority = 1000

    def title(self):
        return "Docker Manager"

    def ui(self, is_img2img):
        docks = discover_docks()
        tabname = "img2img" if is_img2img else "txt2img"

        choices = [(dock["name"], dock["id"]) for dock in docks]
        default_dock = docks[0]["id"] if docks else None
        default_width = docks[0]["default_width"] if docks else "half"

        registry_payload = build_registry_payload()

        with gr.Accordion(
            "Docker Manager",
            open=False,
            elem_id=f"{tabname}_docker_manager",
            elem_classes=["fdm-manager-accordion"],
        ):
            # Registry data is kept in ordinary HTML rather than executable script.
            # The frontend runtime reads the first available copy.
            registry_host = gr.HTML(
                value=render_registry_html(registry_payload),
                elem_classes=["fdm-registry-host"],
            )

            with gr.Row(elem_classes=["fdm-manager-dock-row"]):
                gr.HTML(
                    value=render_native_dock_select(docks, tabname),
                    elem_classes=["fdm-native-dock-host"],
                )
                refresh_button = gr.Button(
                    value="↻",
                    variant="secondary",
                    elem_id=f"{tabname}_fdm_refresh",
                    elem_classes=["fdm-refresh-button"],
                    scale=0,
                    min_width=46,
                )
            gr.HTML(
                value=render_native_width_select(tabname, default_width),
                elem_classes=["fdm-native-width-host"],
            )
            labels_select = gr.Checkbox(
                label="Labels",
                value=False,
                elem_id=f"{tabname}_fdm_labels",
            )
            gr.Checkbox(
                label="Lock Docks",
                value=False,
                elem_id=f"{tabname}_fdm_lock_docks",
                elem_classes=["fdm-lock-docks-control"],
            )
            open_button = gr.Button(
                value="Open Dock",
                variant="secondary",
                interactive=bool(choices),
                elem_id=f"{tabname}_fdm_open",
            )
            close_all_button = gr.Button(
                value="Close All Docks",
                variant="secondary",
                elem_id=f"{tabname}_fdm_close_all",
            )
            refresh_button.click(
                fn=refresh_registry,
                inputs=None,
                outputs=[registry_host],
                queue=False,
                show_progress=False,
            )
            full_refresh_button = gr.Button(
                value="Full Dock Refresh",
                variant="secondary",
                elem_id=f"{tabname}_fdm_full_refresh",
                elem_classes=["fdm-full-refresh-button"],
            )
            full_refresh_button.click(
                fn=None,
                _js="fdmFullRefreshDocks",
                inputs=None,
                outputs=None,
                queue=False,
                show_progress=False,
            )

            open_button.click(
                fn=None,
                _js="fdmOpenDock",
                inputs=[labels_select],
                outputs=None,
                queue=False,
                show_progress=False,
            )
            close_all_button.click(
                fn=None,
                _js="fdmCloseAllDocks",
                inputs=None,
                outputs=None,
                queue=False,
                show_progress=False,
            )

        # UI-only: do not add manager fields to txt2img/img2img processing inputs.
        return None
