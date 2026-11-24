"""Archive raw Forge inputs and restore them alongside native IIB sends."""
import asyncio
import base64
import binascii
import hashlib
import json
import logging
import re
from pathlib import Path
from tempfile import NamedTemporaryFile
from urllib.parse import quote, urlsplit

from aiohttp import ClientError, ClientTimeout, FormData
from yarl import URL

PNG = "data:image/png;base64,"
HASH = re.compile(r"[a-f0-9]{64}")
REFERENCE = re.compile(r'(?:^|, )Forge Mobile input archive: "?([a-f0-9]{64})"?(?=,|$)')
LIMIT = 24 * 1024 * 1024
TIMEOUT = ClientTimeout(total=15)
UPDATE = {"__type__": "update"}
# Forge Neo's submit_img2img input positions, guarded by the canvas classes.
LAYERS = {0: (5,), 1: (6, 7), 2: (8, 9), 3: (10, 11), 4: (12, 13)}
MODE_IDS = ("img2img", "img2img_sketch", "inpaint", "inpaint_sketch", "inpaint_upload")
IMG_SETTINGS = {
    "img2img_mask_blur", "img2img_mask_alpha", "img2img_inpainting_fill",
    "resize_mode", "img2img_inpaint_full_res", "img2img_inpaint_full_res_padding",
    "img2img_mask_mode", "img2img_scale", "img2img_width", "img2img_height",
}
# Save browser values used to build the unit, excluding tool/panel state.
CN_SETTINGS = {
    "enable_checkbox", "pixel_perfect_checkbox", "mask_upload_checkbox", "same_img2img_checkbox",
    "type_filter_radio", "preprocessor_dropdown", "model_dropdown", "control_weight_slider",
    "control_step_slider", "preprocessor_resolution_slider", "threshold_A_slider",
    "threshold_B_slider", "control_mode_radio", "resize_mode_radio", "hr_option_radio",
}


def json_data(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=True, separators=(",", ":")).encode()


def put(folder, data):
    digest = hashlib.sha256(data).hexdigest()
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / digest
    if not path.exists():
        with NamedTemporaryFile(dir=folder, delete=False) as handle:
            temporary = Path(handle.name)
            handle.write(data)
        try:
            temporary.replace(path)
        finally:
            temporary.unlink(missing_ok=True)
    return digest


def read(folder, digest, limit):
    if not isinstance(digest, str) or not HASH.fullmatch(digest):
        raise ValueError("Invalid archive hash")
    path = folder / digest
    with path.open("rb") as handle:
        data = handle.read(limit + 1)
    if len(data) > limit or hashlib.sha256(data).hexdigest() != digest:
        raise ValueError("Archived data failed its hash or size check")
    return data


def media_type(data):
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png", "png"
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg", "jpg"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp", "webp"
    raise ValueError("Expected PNG, JPEG or WebP image data")


class InputArchive:
    def __init__(self, companion):
        self.companion = companion
        self.root = companion.workspace.path.resolve().parent / "input-archive"
        self.markers = {}
        self.cn = {}
        self.img_inputs = None
        self.img_for_mode = {}
        self.img_settings = {}
        self.mode_select = None
        self.scale_select = None
        self.pastes = {}

    def configure(self, config):
        ws = self.companion.workspace
        components = {c["id"]: c for c in config["components"]}
        props = {i: c.get("props", {}) for i, c in components.items()}
        names = {p["elem_id"]: i for i, p in props.items() if p.get("elem_id")}
        self.markers, self.cn, self.img_for_mode, self.pastes = {}, {}, {}, {}
        self.img_inputs = None
        for index, (kind, _) in ws.generation.items():
            if kind not in {"submit", "submit_img2img"}:
                continue
            tab = "img2img" if kind == "submit_img2img" else "txt2img"
            inputs = ws.deps[index]["inputs"]
            marker = names.get(tab + "_fm_input_archive")
            if marker not in inputs:
                continue
            self.markers[index] = (inputs.index(marker), tab)
            units = {}
            controls = ws.controlnet[index][1]
            for builder in ws.controlnet[index][0]:
                slots = builder["inputs"]
                enable = next((props[c].get("elem_id") for c in slots
                               if (props[c].get("elem_id") or "").endswith("_controlnet_enable_checkbox")), None)
                if not enable:
                    continue
                prefix = enable.removesuffix("enable_checkbox")
                unit = {}
                for c in controls:
                    name = props[c].get("elem_id") or ""
                    key = name.removeprefix(prefix)
                    if name.startswith(prefix) and key in CN_SETTINGS:
                        unit[key] = c
                canvas = [c for c in slots if any(
                    css.startswith("logical_image_") for css in props[c].get("elem_classes") or []
                )]
                for c in slots:
                    if "cnet-preview-as-input" in (props[c].get("elem_classes") or []):
                        unit["use_preview"] = c
                for position, c in enumerate(canvas):
                    # The unit builder places the main canvas background at input 9.
                    key = "canvas/input" if len(slots) > 9 and c == slots[9] else f"canvas/{position}"
                    unit[key] = c
                units[prefix.removeprefix(tab + "_")] = unit
            # Match unit order across tabs even when titles differ.
            self.cn[tab] = tuple(units.values())
            if tab == "img2img" and len(inputs) > 31 and all(
                "logical_image_background" in (props[inputs[n]].get("elem_classes") or [])
                for n in (5, 6, 8, 10)
            ):
                self.img_inputs = inputs
                self.img_for_mode = {mode: tuple(inputs[pos] for pos in positions) for mode, positions in LAYERS.items()}
        if not self.markers:
            return

        self.img_settings = {name: names[name] for name in IMG_SETTINGS if name in names}
        self.scale_select = names.get("img2img_tabs_resize")
        self.mode_select = names.get("mode_img2img")
        info = names.get("iib_hidden_img_file_info")
        image = names.get("iib_hidden_img")
        for index, dep in ws.deps.items():
            for button, event in dep.get("targets", []):
                name = props.get(button, {}).get("elem_id") or ""
                target = name.removeprefix("iib_hidden_tab_")
                if not name.startswith("iib_hidden_tab_") or target not in {"txt2img", "img2img", "inpaint"} or event != "click":
                    continue
                if not dep.get("backend_fn"):
                    continue
                if info in dep["inputs"]:
                    tab = "img2img" if target == "inpaint" else target
                    extra = {c for unit in self.cn.get(tab, ()) for key, c in unit.items()
                             if not key.startswith("canvas/")}
                    if tab == "img2img" and self.img_inputs:
                        extra.update(self.img_settings.values())
                        extra.update(c for layers in self.img_for_mode.values() for c in layers)
                        extra.update((self.img_inputs[1], self.img_inputs[23]))
                        if self.scale_select is not None:
                            extra.add(self.scale_select)
                        if self.mode_select is not None:
                            extra.add(self.mode_select)
                    self.pastes[index] = (target, dep["inputs"].index(info), False, tuple(sorted(extra - set(dep["outputs"]))))
                elif image in dep["inputs"] and info is not None and target != "txt2img":
                    self.pastes[index] = (target, len(dep["inputs"]), True, ())

    def patch_config(self, config):
        info = next((c["id"] for c in config["components"]
                     if c["props"].get("elem_id") == "iib_hidden_img_file_info"), None)
        for dep in config["dependencies"]:
            spec = self.pastes.get(dep["id"])
            if not spec:
                continue
            _, _, image, extra = spec
            if image:
                dep["inputs"] = [*dep["inputs"], info]
            dep["outputs"] = [*dep["outputs"], *extra]

    async def archive_value(self, value, headers):
        if isinstance(value, str) and value.startswith(PNG):
            if len(value) > len(PNG) + (LIMIT * 4 // 3) + 4:
                raise ValueError("Canvas image exceeds archive size limit")
            data = base64.b64decode(value[len(PNG):], validate=True)
            if media_type(data)[1] != "png":
                raise ValueError("ForgeCanvas must contain PNG data")
            kind = "canvas"
        elif isinstance(value, dict) and value.get("meta", {}).get("_type") == "gradio.FileData":
            path = urlsplit(value.get("url") or "").path
            if not path.startswith(("/file=", "/file/")):
                original = value.get("path")
                if not isinstance(original, str) or not original:
                    raise ValueError("No Gradio file reference")
                path = "/file=" + quote(original.replace("\\", "/"), safe="/:")
            # Fetch only through the configured Forge file endpoint.
            async with self.companion.http.get(URL(self.companion.upstream + path, encoded=True), headers=headers,
                                               timeout=TIMEOUT, allow_redirects=False) as response:
                response.raise_for_status()
                data = bytearray()
                async for chunk in response.content.iter_chunked(65536):
                    data.extend(chunk)
                    if len(data) > LIMIT:
                        raise ValueError("Uploaded image exceeds archive size limit")
            media_type(data)
            kind = "file"
        elif value is None or type(value) in (str, bool, int, float, list):
            return value
        else:
            raise ValueError("Unrecognized image input")
        digest = await asyncio.to_thread(put, self.root / "images", bytes(data))
        return {"image": digest, "kind": kind}

    async def capture(self, index, data, controls, headers):
        marker = self.markers.get(index)
        if not marker or marker[0] >= len(data):
            return data
        position, tab = marker
        try:
            units = []
            for unit in self.cn.get(tab, ()):
                units.append({key: await self.archive_value(controls[c], headers)
                              for key, c in unit.items() if c in controls})
            img = None
            if tab == "img2img" and self.img_inputs and len(data) > 13 and data[1] in LAYERS:
                mode = int(data[1])
                layers = [await self.archive_value(data[i], headers) for i in LAYERS[mode]]
                if layers and isinstance(layers[0], dict):
                    values = dict(zip(self.img_inputs, data))
                    img = {"mode": mode, "layers": layers, "scale_mode": data[23] if len(data) > 23 else 0, "settings": {
                        key: values[c] for key, c in self.img_settings.items() if c in values
                    }}
            if img is None and not any(units):
                return data
            record = {"version": 1, "img2img": img, "controlnet": units}
            reference = await asyncio.to_thread(put, self.root / "recipes", json_data(record))
        except (OSError, ValueError, TypeError, KeyError, ClientError, asyncio.TimeoutError, binascii.Error) as error:
            logging.warning("Could not archive Forge inputs: %s", error)
            return data
        result = list(data)
        result[position] = reference
        return result

    async def restore_value(self, value, headers, file_cache):
        if not isinstance(value, dict):
            return value
        digest = value["image"]
        kind = value["kind"]
        data = await asyncio.to_thread(read, self.root / "images", digest, LIMIT)
        mime, suffix = media_type(data)
        if kind == "canvas":
            return PNG + base64.b64encode(data).decode()
        if kind != "file":
            raise ValueError("Unknown archive image type")
        if digest in file_cache:
            return file_cache[digest]
        form = FormData()
        filename = f"{digest}.{suffix}"
        form.add_field("files", data, filename=filename, content_type=mime)
        upload_headers = {k: v for k, v in headers.items() if k.lower() != "content-type"}
        async with self.companion.http.post(self.companion.upstream + "/upload", data=form, headers=upload_headers,
                                            timeout=TIMEOUT, allow_redirects=False) as response:
            response.raise_for_status()
            path = (await response.json())[0]
        result = {"path": path, "orig_name": filename, "mime_type": mime, "size": len(data),
                  "url": "/file=" + quote(path.replace("\\", "/"), safe="/:"), "meta": {"_type": "gradio.FileData"}}
        file_cache[digest] = result
        return result

    def mode_for_target(self, img, target):
        mode = img["mode"]
        # Explicit Send to Inpaint uses an inpaint mode, even for an img2img source.
        return 2 if target == "inpaint" and mode < 2 else mode

    async def prepare_paste(self, index, data, headers):
        spec = self.pastes.get(index)
        if spec is None:
            return data, None
        target, position, image, extra = spec
        info = data[position] if len(data) > position else None
        if image:
            data = data[:position]
        # Forge puts all generation parameters on the last line of infotext.
        match = REFERENCE.search(info.strip().split("\n")[-1]) if isinstance(info, str) else None
        values = {}
        if match:
            try:
                raw = await asyncio.to_thread(read, self.root / "recipes", match[1], 512 * 1024)
                record = json.loads(raw)
                if record["version"] != 1:
                    raise ValueError("Unsupported input archive version")
                img = record["img2img"]
                cache = {}
                if image and img and self.img_for_mode:
                    mode = self.mode_for_target(img, target)
                    direct_mode = 2 if target == "inpaint" else 0
                    if mode == direct_mode:
                        base = img["layers"][0]
                        if base["kind"] == "canvas":
                            values[self.img_for_mode[mode][0]] = await self.restore_value(base, headers, cache)
                    for name in ("img2img_width", "img2img_height"):
                        if name in img["settings"] and name in self.img_settings:
                            values[self.img_settings[name]] = img["settings"][name]
                if not image:
                    tab = "img2img" if target == "inpaint" else target
                    for unit, saved in zip(self.cn.get(tab, ()), record["controlnet"]):
                        for key, c in unit.items():
                            # ControlNet canvas images are archived for reference only.
                            if key in saved and not key.startswith("canvas/") and not isinstance(saved[key], dict):
                                values[c] = saved[key]
                    if tab == "img2img" and img and self.img_for_mode:
                        mode = self.mode_for_target(img, target)
                        layers = img["layers"] if mode == img["mode"] else [img["layers"][0], None]
                        for c, value in zip(self.img_for_mode[mode], layers):
                            values[c] = await self.restore_value(value, headers, cache)
                        for key, value in img["settings"].items():
                            if key in self.img_settings:
                                values[self.img_settings[key]] = value
                        values[self.img_inputs[1]] = mode
                        scale = 1 if img.get("scale_mode") == 1 else 0
                        values[self.img_inputs[23]] = scale
                        if self.scale_select is not None:
                            values[self.scale_select] = {"__type__": "update", "selected": "by" if scale else "to"}
                        if self.mode_select is not None:
                            values[self.mode_select] = {"__type__": "update", "selected": MODE_IDS[mode]}
            except (OSError, ValueError, KeyError, TypeError, IndexError, ClientError, asyncio.TimeoutError) as error:
                logging.warning("Could not restore Forge input archive %s: %s", match[1], error)
                values = {}
        return data, (values, extra)

    def apply_paste(self, index, data, prepared):
        if prepared is None:
            return data
        values, extra = prepared
        ws = self.companion.workspace
        native = ws.deps[index]["outputs"]
        if len(data) != len(native):
            return data
        result = [values.get(c, original) for c, original in zip(native, data)]
        for c in set(native) | set(extra):
            if c not in values:
                continue
            value = values[c]
            if c == self.mode_select:
                ws.select_tab("mode_img2img", value["selected"])
            elif c == self.scale_select:
                ws.select_tab("img2img_tabs_resize", value["selected"])
            else:
                ws.draft.setdefault(str(c), {})["value"] = value
        if values:
            try:
                ws.save()
            except OSError:
                logging.exception("Could not persist restored input archive")
        return result + [values.get(c, UPDATE) for c in extra]
