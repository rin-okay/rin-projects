"""Reconnectable browser transport for Forge Neo's Gradio 4.40 WebUI."""

import argparse
import asyncio
import hashlib
from importlib.util import module_from_spec, spec_from_file_location
import json
import logging
import os
import re
import secrets
import time
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import quote, urlsplit

from aiohttp import ClientError, ClientSession, ClientTimeout, DummyCookieJar, web
from multidict import CIMultiDict
from yarl import URL

from mobile_extensions import MobileExtensions

HERE = Path(__file__).resolve().parent
VERSION = (HERE / "VERSION").read_text(encoding="utf-8").strip()
PREFIX = "/_forge_mobile"
PROMPT_NAMES = (
    "txt2img_prompt", "txt2img_neg_prompt", "hires_prompt", "hires_neg_prompt",
    "img2img_prompt", "img2img_neg_prompt", "img2img_hr_prompt", "img2img_hr_neg_prompt",
)
SUBMIT = re.compile(r"\b(submit_txt2img_upscale|submit_img2img|i2iHiresPrepare|submit)\s*(?:\(|$)")
INLINE_CONFIG = re.compile(r"window\.gradio_config\s*=\s*")
TASK_ID = re.compile(r"task\([a-zA-Z0-9_-]+\)")
HOP_HEADERS = {
    "connection", "keep-alive", "transfer-encoding", "upgrade", "proxy-authenticate",
    "proxy-authorization", "te", "trailer", "content-length", "content-encoding",
}


def json_bytes(data):
    return json.dumps(data, separators=(",", ":"), ensure_ascii=True).encode()


def apply_props(target, value):
    if isinstance(value, dict) and value.get("__type__") == "update":
        target.update({key: val for key, val in value.items() if key != "__type__"})
    else:
        target["value"] = value


def file_urls(value, origin):
    """Rebase Gradio FileData URLs when the phone opens a different LAN address."""
    if isinstance(value, list):
        return [file_urls(item, origin) for item in value]
    if isinstance(value, dict):
        out = {key: file_urls(item, origin) for key, item in value.items()}
        url = out.get("url")
        if isinstance(url, str) and isinstance(out.get("meta"), dict) and out["meta"].get("_type") == "gradio.FileData":
            parsed = urlsplit(url)
            if parsed.path.startswith(("/file=", "/file/")):
                out["url"] = origin + parsed.path + ("?" + parsed.query if parsed.query else "")
        return out
    return value


class Workspace:
    def __init__(self, path):
        self.path = path
        self.deps = {}
        self.generation = {}
        self.fields = set()
        self.gallery_ids = set()
        self.tab_choices = {}
        self.controlnet = {}
        self.controlnet_props = set()
        self.hires_fields = set()
        self.editable_fields = set()
        self.component_names = {}
        self.img2img_hires = {}
        self.token_validators = {}
        self.fingerprint = None
        self.draft = {}
        self.results = {}
        self.revision = 0
        if path.exists():
            try:
                saved = json.loads(path.read_text(encoding="utf-8"))
                self.fingerprint = saved["fingerprint"]
                self.draft = saved["draft"]
                self.results = saved["results"]
                self.revision = saved["revision"]
            except (ValueError, KeyError, OSError):
                logging.exception("Could not read the saved workspace")

    def configure(self, config):
        deps = {dep["id"]: dep.copy() for dep in config["dependencies"]}
        components = {c["id"]: c for c in config["components"]}
        generation = {}
        fields = set()
        galleries = set()
        for index, dep in deps.items():
            match = SUBMIT.search((dep.get("js") or "").strip())
            if not match or not dep.get("backend_fn"):
                continue
            output_ids = dep["outputs"]
            gallery = next((i for i in output_ids if components.get(i, {}).get("type") == "gallery"), None)
            if gallery is None:
                continue
            name = match[1]
            generation[index] = (name, gallery)
            galleries.add(gallery)
            first = 4 if name in {"submit_txt2img_upscale", "i2iHiresPrepare"} else 1
            fields.update(
                i for i in dep["inputs"][first:]
                if components.get(i, {}).get("type") not in {"state", "gallery"}
            )
        if not generation:
            raise ValueError("No compatible Forge Generate buttons found")
        self.editable_fields = {
            i for i, component in components.items()
            if component.get("props", {}).get("interactive") is not False
            and component.get("type") in {
                "textbox", "number", "slider", "checkbox", "checkboxgroup",
                "dropdown", "radio", "image", "file", "imageeditor", "colorpicker",
            }
        }
        self.component_names = {
            component["props"]["elem_id"]: i
            for i, component in components.items()
            if i in self.editable_fields and component.get("props", {}).get("elem_id")
        }
        self.img2img_hires = {}
        for index, (kind, _) in generation.items():
            if kind != "i2iHiresPrepare":
                continue
            inputs = deps[index]["inputs"]
            by_label = {
                str(components[i]["props"].get("label", "")).strip().casefold(): (position, i)
                for position, i in enumerate(inputs)
                if i in components and components[i]["type"] == "textbox"
            }
            pair = [by_label.get(label) for label in ("hires prompt", "hires negative prompt")]
            if all(pair):
                self.img2img_hires[index] = pair
                for name, (_, component_id) in zip(("img2img_hr_prompt", "img2img_hr_neg_prompt"), pair):
                    self.component_names[name] = component_id
        self.token_validators = {}
        for dep in deps.values():
            inputs, outputs = dep["inputs"], dep["outputs"]
            if not dep.get("backend_fn") or len(inputs) not in (1, 2) or len(outputs) != 1:
                continue
            prompt = components.get(inputs[0], {}).get("props", {}).get("elem_id")
            counter = components.get(outputs[0], {}).get("props", {})
            if (prompt in {"txt2img_prompt", "txt2img_neg_prompt", "img2img_prompt", "img2img_neg_prompt"}
                    and ((counter.get("elem_id") or "").endswith("token_counter")
                         or "token-counter" in (counter.get("elem_classes") or []))):
                self.token_validators[prompt] = dep
        signature = [
            config.get("version"),
            [(i, c["type"], c["props"].get("elem_id"), c["props"].get("label")) for i, c in components.items()],
            [(i, deps[i]["inputs"], deps[i]["outputs"], kind)
             for i, kind in generation.items() if kind[0] != "i2iHiresPrepare"],
        ]
        fingerprint = hashlib.sha256(json_bytes(signature)).hexdigest()
        if self.fingerprint != fingerprint:
            self.fingerprint = fingerprint
            self.draft = {}
            self.results = {}
            self.revision = 0
        self.deps, self.generation, self.fields, self.gallery_ids = deps, generation, fields | self.editable_fields, galleries
        self.hires_fields = {
            i for i in fields
            if (name := components[i]["props"].get("elem_id") or "").startswith("txt2img_hr_")
            or name in {
                "txt2img_hr-checkbox", "txt2img_hires_steps", "txt2img_denoising_strength",
                "hr_checkpoint", "hr_vae_te", "hr_sampler", "hr_scheduler", "hires_prompt", "hires_neg_prompt",
            }
        }
        # ControlNet sends a server-side State as its generation input. The
        # native click callback exposes the browser controls that build it.
        builders = {}
        controlnet_props = set()
        controls_by_state = {}
        for dep in deps.values():
            if dep.get("queue") is not False or len(dep["outputs"]) != 1:
                continue
            state = dep["outputs"][0]
            if components.get(state, {}).get("type") != "state":
                continue
            names = [components[i]["props"].get("elem_id") or "" for i in dep["inputs"]]
            enabled = next((name for name in names if name.endswith("_controlnet_enable_checkbox")), None)
            if enabled is None:
                continue
            prefix = enabled.removesuffix("_enable_checkbox") + "_"
            controls = {
                i for i in dep["inputs"] if components[i]["type"] != "state"
            }
            controls.update(
                i for i, component in components.items()
                if (component["props"].get("elem_id") or "").startswith(prefix)
                and component["type"] not in {"button", "html", "state"}
            )
            # The range slider updates its two hidden guidance values through
            # a separate Gradio callback. Reapply it before building the unit.
            guidance = [
                callback for callback in deps.values()
                if len(callback["outputs"]) == 2
                and all(i in dep["inputs"] and components[i]["type"] == "state" for i in callback["outputs"])
                and len(callback["inputs"]) == 1
                and callback["inputs"][0] in controls
            ]
            builders[state] = [*guidance, dep]
            controls_by_state[state] = controls
            controlnet_props.update(controls)
            # Preprocessor/type callbacks also configure choices, visibility
            # and slider bounds. Keep their native updates across reloads.
            for callback in deps.values():
                if any(i in controls for i, _ in callback.get("targets", [])):
                    controlnet_props.update(
                        i for i in callback["outputs"] if components[i]["type"] not in {"state", "button", "html"}
                    )
        self.controlnet = {
            index: (
                [callback for i in deps[index]["inputs"] if i in builders for callback in builders[i]],
                sorted({c for i in deps[index]["inputs"] if i in builders for c in controls_by_state[i]}),
            )
            for index in generation
        }
        self.controlnet_props = controlnet_props
        self.tab_choices = {}
        pending = [config["layout"]]
        while pending:
            node = pending.pop()
            children = node.get("children", [])
            pending.extend(children)
            component = components.get(node["id"], {})
            name = component.get("props", {}).get("elem_id")
            if component.get("type") == "tabs" and name in {"tabs", "mode_img2img", "img2img_tabs_resize"}:
                ids = [components.get(child["id"], {}).get("props", {}).get("id") for child in children]
                self.tab_choices[name] = (node["id"], ids)

    def select_tab(self, group, selected):
        if group not in self.tab_choices:
            return
        component, choices = self.tab_choices[group]
        if type(selected) is int and 0 <= selected < len(choices):
            selected = choices[selected]
        if selected is not None and selected in choices:
            self.draft[str(component)] = {"selected": selected}

    def save(self):
        payload = dict(fingerprint=self.fingerprint, draft=self.draft, results=self.results, revision=self.revision)
        pending = self.path.with_suffix(".tmp")
        pending.write_bytes(json_bytes(payload))
        os.replace(pending, self.path)

    def capture(self, index, data, controlnet):
        for component, value in controlnet.items():
            self.draft.setdefault(str(component), {})["value"] = value
        for component, value in zip(self.deps[index]["inputs"], data):
            if component in self.fields:
                self.draft[str(component)] = {"value": value}
        name, _ = self.generation[index]
        self.select_tab("tabs", "img2img" if name in {"submit_img2img", "i2iHiresPrepare"} else "txt2img")
        if name == "submit_img2img" and len(data) > 23:
            # Positions are the two mode inputs in Forge Neo's native img2img event.
            self.select_tab("mode_img2img", data[1])
            self.select_tab("img2img_tabs_resize", data[23])
        self.save()

    def complete(self, index, data):
        dep = self.deps.get(index, {})
        outputs = dep.get("outputs", [])
        relevant = index in self.generation
        touched = False
        controlnet_changed = False
        for component, value in zip(outputs, data):
            if component in self.controlnet_props or component in self.editable_fields:
                props = self.draft.setdefault(str(component), {})
                apply_props(props, value)
                controlnet_changed = True
            if relevant or component in self.gallery_ids:
                if not relevant and not (isinstance(value, dict) and value.get("__type__") == "update"):
                    continue
                apply_props(self.results.setdefault(str(component), {}), value)
                touched = True
        if touched:
            self.revision += 1
        if touched or controlnet_changed:
            self.save()

    def restore_hires_on_load(self, index, data):
        dep = self.deps.get(index, {})
        if not any(event == "load" for _, event in dep.get("targets", [])):
            return
        for position, component in enumerate(dep["outputs"][:len(data)]):
            props = self.draft.get(str(component), {})
            if component in self.editable_fields and "value" in props:
                value = data[position]
                if isinstance(value, dict) and value.get("__type__") == "update":
                    data[position] = {**value, "value": props["value"]}
                else:
                    data[position] = props["value"]

    def config_for(self, config, origin):
        updates = self.draft | self.results
        prompt_ids = {
            self.component_names[name]: name for name in ("img2img_hr_prompt", "img2img_hr_neg_prompt")
            if name in self.component_names
        }
        for component in config["components"]:
            name = prompt_ids.get(component["id"])
            if name and not component["props"].get("elem_id"):
                component["props"]["elem_id"] = name
            props = updates.get(str(component["id"]))
            if props:
                component["props"].update(file_urls(props, origin))
        mobile_prompts = {self.component_names[name]: name for name in PROMPT_NAMES if name in self.component_names}
        token_events = {dep["id"] for dep in self.token_validators.values()}
        for dep in config["dependencies"]:
            if dep["id"] in token_events:
                dep["targets"] = [target for target in dep.get("targets", [])
                                  if target[0] not in mobile_prompts or target[1] != "input"]
            kind = self.generation.get(dep["id"], (None, None))[0]
            if kind in {"submit_txt2img_upscale", "i2iHiresPrepare"}:
                dep["trigger_mode"] = "multiple"
            if kind == "i2iHiresPrepare":
                native_js = dep["js"]
                prepare = "window.forgeMobilePrepareImg2imgHires?.(data); " if dep["id"] in self.img2img_hires else ""
                dep["js"] = (
                    f"async (...args) => {{ const data = await ({native_js})(...args); {prepare}"
                    "if (typeof selected_gallery_index_id === 'function') { "
                    "const index = selected_gallery_index_id('img2img_gallery_container'); "
                    "if (index >= 0) data[2] = index; } return data; }"
                )
            if not kind:
                continue
            _, controls = self.controlnet.get(dep["id"], ([], []))
            slots = [(position, mobile_prompts[component]) for position, component in enumerate(dep["inputs"])
                     if component in mobile_prompts]
            if not controls and not slots:
                continue
            count = len(dep["inputs"])
            native_js = dep["js"]
            read_prompts = f"window.forgeMobileReadPrompts?.(args, {json.dumps(slots)}); " if slots else ""
            if controls:
                # Keep Forge's native callback arguments in their original positions.
                dep["js"] = (
                    f"async (...args) => {{ const native = ({native_js}); {read_prompts}"
                    f"const extra = args.splice({count}, {len(controls)}); "
                    f"const data = await native(...args); "
                    f"return [...data.slice(0, {count}), ...extra]; }}"
                )
                dep["inputs"] = dep["inputs"] + controls
            else:
                dep["js"] = f"(...args) => {{ {read_prompts}return ({native_js})(...args); }}"
        outputs = sorted({
            component for index in self.generation
            for component in self.deps[index]["outputs"]
        })
        root = config["layout"]["id"]
        pull_dependency = {
            "id": max(self.deps) + 1,
            "targets": [[root, "load"], [root, "forge_mobile_pull"]],
            "inputs": [], "outputs": outputs, "backend_fn": False,
            "js": f"() => window.forgeMobilePull({root},{json.dumps(outputs)})",
            "queue": False, "api_name": False, "scroll_to_output": False,
            "show_progress": "hidden", "batch": False, "max_batch_size": 4,
            "cancels": [], "types": {"generator": False, "cancel": False},
            "collects_event_data": False, "trigger_after": None,
            "trigger_only_on_success": False, "trigger_mode": "once",
            "show_api": False, "zerogpu": False, "rendered_in": None,
        }
        config["dependencies"].append(pull_dependency)
        for offset, component in enumerate(sorted(self.editable_fields - mobile_prompts.keys()), start=1):
            config["dependencies"].append({
                **pull_dependency,
                "id": pull_dependency["id"] + offset,
                "targets": [[component, "input"]],
                "inputs": [component],
                "outputs": [],
                "js": f"(value) => window.forgeMobileSaveField({component}, {json.dumps(self.fingerprint)}, value)",
            })
        return config


@dataclass
class Event:
    page: str
    index: int
    task_id: str | None
    fingerprint: str
    status: str = "queued"
    archive_restore: object = None
    finished: float = 0


@dataclass
class Page:
    frames: list = field(default_factory=list)
    sequence: int = 0
    changed: asyncio.Event = field(default_factory=asyncio.Event)
    touched: float = field(default_factory=time.monotonic)

    def publish(self, message):
        self.sequence += 1
        self.frames.append((self.sequence, message))
        if len(self.frames) > 512:
            del self.frames[:128]
        self.changed.set()


class Companion:
    def __init__(self, upstream, workspace):
        self.upstream = upstream.rstrip("/")
        self.workspace = workspace
        self.session = secrets.token_hex(20)
        self.events = {}
        self.tasks = {}
        self.pages = defaultdict(Page)
        self.reader = None
        self.join_lock = asyncio.Lock()
        self.config_lock = asyncio.Lock()
        self.http = None
        self.last_config = 0
        self.browser_script = (HERE / "mobile.js").read_bytes()
        self.extensions = MobileExtensions(
            HERE / "extensions", json.loads((HERE / "defaults.json").read_text(encoding="utf-8"))
        )

        self.input_archive = None
        archive = HERE / "extensions" / "parameters-saver" / "archive.py"
        if archive.is_file():
            spec = spec_from_file_location("forge_mobile_input_archive", archive)
            module = module_from_spec(spec)
            spec.loader.exec_module(module)
            self.input_archive = module.InputArchive(self)

    def browser_config(self, config, origin):
        self.workspace.config_for(config, origin)
        if self.input_archive:
            self.input_archive.patch_config(config)
        return config

    async def lifecycle(self, app):
        async with ClientSession(
            timeout=ClientTimeout(total=None, connect=8, sock_read=None),
            cookie_jar=DummyCookieJar(), auto_decompress=True,
        ) as self.http:
            yield
            if self.reader:
                self.reader.cancel()
                await asyncio.gather(self.reader, return_exceptions=True)

    def origin(self, request):
        return f"{request.scheme}://{request.host}"

    def headers(self, request):
        excluded = HOP_HEADERS | {
            "host", "authorization", "forwarded", "x-forwarded-host", "x-forwarded-proto",
            "x-forwarded-for", "accept-encoding",
        }
        headers = {k: v for k, v in request.headers.items() if k.lower() not in excluded}
        headers["X-Forwarded-Host"] = request.host
        headers["X-Forwarded-Proto"] = request.scheme
        return headers

    def url(self, request, path=None):
        return URL(self.upstream + (request.raw_path if path is None else path), encoded=True)

    def response_headers(self, upstream, request):
        headers = CIMultiDict(
            (k, v) for k, v in upstream.headers.items() if k.lower() not in HOP_HEADERS
        )
        location = headers.get("Location")
        if location and location.startswith(self.upstream + "/"):
            headers["Location"] = self.origin(request) + location[len(self.upstream):]
        return headers

    def configure(self, config):
        version = str(config.get("version", ""))
        if version != "4.40.0" or config.get("protocol") != "sse_v3":
            raise ValueError(f"Expected Gradio 4.40.0 and sse_v3, got {version} / {config.get('protocol')}")
        if config.get("enable_queue") is False:
            raise ValueError("Forge Mobile needs Forge's native Gradio queue enabled")
        self.workspace.configure(config)
        if self.input_archive:
            self.input_archive.configure(config)

    async def ensure_config(self, request):
        async with self.config_lock:
            if self.workspace.deps and time.monotonic() - self.last_config < 2:
                return
            async with self.http.get(self.url(request, "/config"), headers=self.headers(request)) as response:
                if response.status != 200:
                    raise web.HTTPBadGateway(text="Could not read Forge configuration. Sign into Forge first.")
                self.configure(await response.json())
                self.last_config = time.monotonic()

    def page_id(self, value):
        if not isinstance(value, str) or not re.fullmatch(r"[a-zA-Z0-9_-]{1,100}", value):
            raise web.HTTPBadRequest(text="Invalid Gradio session")
        return value

    def collect_old_events(self):
        cutoff = time.monotonic() - 3600
        for event_id, event in list(self.events.items()):
            if event.finished and event.finished < cutoff:
                if event.task_id:
                    self.tasks.pop(event.task_id, None)
                del self.events[event_id]
        active_pages = {event.page for event in self.events.values()}
        for name, page in list(self.pages.items()):
            if name not in active_pages and page.touched < cutoff:
                del self.pages[name]

    async def join(self, request, payload):
        await self.ensure_config(request)
        page = self.page_id(payload.get("session_hash"))
        index = payload.get("fn_index")
        if not isinstance(index, int) or index not in self.workspace.deps or not isinstance(payload.get("data"), list):
            raise web.HTTPBadRequest(text="Unknown Forge event")
        data = payload["data"]
        hires_prompts = None
        if index in self.workspace.img2img_hires and data and isinstance(data[-1], dict):
            hires_prompts = data[-1].get("forge_mobile_img2img_prompts")
            if isinstance(hires_prompts, list) and len(hires_prompts) == 2 and all(isinstance(p, str) for p in hires_prompts):
                data = data[:-1]
                payload["data"] = data
            else:
                hires_prompts = None
        builders, controls = self.workspace.controlnet.get(index, ([], []))
        native_count = len(self.workspace.deps[index]["inputs"])
        controlnet = dict(zip(controls, data[native_count:]))
        if controlnet:
            data = data[:native_count]
            payload["data"] = data
        task = data[0] if index in self.workspace.generation and data else None
        if not isinstance(task, str) or not TASK_ID.fullmatch(task):
            task = None
        payload["session_hash"] = self.session
        headers = self.headers(request)
        async with self.join_lock:
            self.collect_old_events()
            if task in self.tasks:
                return web.json_response({"event_id": self.tasks[task]})
            if controlnet:
                for builder in builders:
                    api_name = quote(str(builder.get("api_name") or "predict"), safe="")
                    native = {
                        "fn_index": builder["id"],
                        "session_hash": self.session,
                        "data": [controlnet.get(i) for i in builder["inputs"]],
                    }
                    async with self.http.post(self.url(request, "/run/" + api_name), json=native, headers=headers) as response:
                        if response.status != 200:
                            logging.warning("ControlNet callback %s failed: %s", builder["id"], await response.text())
                            raise web.HTTPBadGateway(text="Forge could not apply the ControlNet settings")
                        await response.read()
            if hires_prompts is not None:
                slots = self.workspace.img2img_hires[index]
                if all(position < len(data) for position, _ in slots):
                    payload["data"] = list(data)
                    for (position, _), prompt in zip(slots, hires_prompts):
                        # A truthy blank keeps Forge from using the source image's text.
                        payload["data"][position] = data[position] or prompt or " "
            archive_restore = None
            if self.input_archive:
                if task:
                    payload["data"] = await self.input_archive.capture(index, payload["data"], controlnet, headers)
                else:
                    payload["data"], archive_restore = await self.input_archive.prepare_paste(index, data, headers)
            async with self.http.post(self.url(request), json=payload, headers=headers) as response:
                if response.status != 200:
                    return web.Response(status=response.status, body=await response.read(),
                                        headers=self.response_headers(response, request))
                event_id = (await response.json())["event_id"]
            self.events[event_id] = Event(
                page, index, task, self.workspace.fingerprint, archive_restore=archive_restore)
            if task:
                self.tasks[task] = event_id
                try:
                    self.workspace.capture(index, data, controlnet)
                except OSError:
                    logging.exception("Could not save the workspace")
            if not self.reader or self.reader.done():
                self.reader = asyncio.create_task(self.read_queue(headers))
            return web.json_response({"event_id": event_id})

    def receive(self, message):
        event_id = message.get("event_id")
        event = self.events.get(event_id)
        if not event:
            return
        kind = message.get("msg")
        if kind in {"process_starts", "progress", "process_generating"}:
            event.status = "running"
        if kind == "process_completed":
            if event.fingerprint == self.workspace.fingerprint and message.get("success"):
                data = (message.get("output") or {}).get("data")
                if isinstance(data, list):
                    try:
                        if self.input_archive and event.archive_restore is not None:
                            data = self.input_archive.apply_paste(event.index, data, event.archive_restore)
                            message["output"]["data"] = data
                        self.workspace.complete(event.index, data)
                    except OSError:
                        logging.exception("Could not save Forge's result")
            event.archive_restore = None
            event.status = "complete" if message.get("success") else "failed"
            event.finished = time.monotonic()
        self.pages[event.page].publish(message)

    async def read_queue(self, headers):
        url = URL(self.upstream + "/queue/data").with_query(session_hash=self.session)
        # The reader belongs to the PC. A disconnected phone only loses its subscriber.
        while True:
            try:
                async with self.http.get(url, headers=headers) as response:
                    response.raise_for_status()
                    pending = b""
                    closed = False
                    async for chunk in response.content.iter_any():
                        lines = (pending + chunk).split(b"\n")
                        pending = lines.pop()
                        for line in lines:
                            if not line.startswith(b"data:"):
                                continue
                            message = json.loads(line[5:])
                            if message.get("msg") == "close_stream":
                                closed = True
                                break
                            self.receive(message)
                        if closed:
                            break
                    if not closed:
                        raise ClientError("Forge closed the queue without completing it")
            except (ClientError, ValueError, asyncio.TimeoutError) as error:
                logging.warning("Forge queue stream ended: %s", error)
                async with self.join_lock:
                    for event_id, event in self.events.items():
                        if not event.finished:
                            self.receive(dict(msg="process_completed", event_id=event_id, success=False,
                                              output={"error": "Lost the PC connection to Forge."}))
                    self.reader = None
                return
            async with self.join_lock:
                if not any(not event.finished for event in self.events.values()):
                    self.reader = None
                    return
            await asyncio.sleep(0.05)

    async def subscribe(self, request):
        page_id = self.page_id(request.query.get("session_hash"))
        page = self.pages[page_id]
        try:
            cursor = int(request.query.get("__fm_after", "0"))
        except ValueError:
            raise web.HTTPBadRequest(text="Invalid stream cursor")
        response = web.StreamResponse(headers={"Content-Type": "text/event-stream", "Cache-Control": "no-store"})
        await response.prepare(request)
        try:
            while True:
                page.touched = time.monotonic()
                page.changed.clear()
                for sequence, message in list(page.frames):
                    if sequence > cursor:
                        await response.write(f"id: {sequence}\ndata: ".encode() + json_bytes(message) + b"\n\n")
                        cursor = sequence
                if page.sequence > cursor:
                    continue
                if not any(event.page == page_id and not event.finished for event in self.events.values()):
                    await response.write(b'data: {"msg":"close_stream"}\n\n')
                    break
                try:
                    await asyncio.wait_for(page.changed.wait(), timeout=5)
                except asyncio.TimeoutError:
                    await response.write(b'data: {"msg":"heartbeat"}\n\n')
        except (ConnectionError, asyncio.CancelledError):
            pass
        return response

    async def heartbeat(self, request):
        # Retain the upstream Gradio state without sending browser unload events to it.
        response = web.StreamResponse(headers={"Content-Type": "text/event-stream", "Cache-Control": "no-store"})
        await response.prepare(request)
        try:
            while True:
                await response.write(b"data: ALIVE\n\n")
                await asyncio.sleep(15)
        except (ConnectionError, asyncio.CancelledError):
            return response

    def state(self, request):
        jobs = [
            {"task_id": event.task_id, "status": event.status, "kind": self.workspace.generation[event.index][0]}
            for event in self.events.values()
            if event.task_id and event.fingerprint == self.workspace.fingerprint
            and event.index in self.workspace.generation
        ]
        return web.json_response({
            "revision": self.workspace.revision,
            "results": file_urls(self.workspace.results, self.origin(request)),
            "jobs": jobs[-20:],
        }, headers={"Cache-Control": "no-store"})

    def patch_html(self, body, origin):
        match = INLINE_CONFIG.search(body)
        if not match:
            raise ValueError("Gradio inline configuration was not found")
        config, end = json.JSONDecoder().raw_decode(body, match.end())
        if config.get("auth_required"):
            return body
        self.configure(config)
        self.last_config = time.monotonic()
        self.browser_config(config, origin)
        safe_config = json_bytes(config).decode().replace("<", "\\u003c")
        page = body[:match.end()] + safe_config + body[end:]
        script = (
            f'<script>window.forgeMobileRevision={self.workspace.revision};</script>'
            f'<script src="{PREFIX}/mobile.js?v={VERSION}"></script>'
            f'<script defer src="{PREFIX}/client-loader.js?v={VERSION}"></script>'
        )
        return page.replace("</head>", script + "</head>", 1)

    async def forward(self, request):
        path = request.path.rstrip("/") or "/"
        if path.startswith(PREFIX + "/"):
            extension_response = await self.extensions.handle(request, path[len(PREFIX) + 1:])
            if extension_response is not None:
                return extension_response
        if path == PREFIX + "/client-loader.js" and request.method == "GET":
            return web.FileResponse(HERE / "client-loader.js", headers={"Cache-Control": "no-store"})
        if path == PREFIX + "/state" and request.method == "GET":
            return self.state(request)
        if path == PREFIX + "/prompt-validity" and request.method == "POST":
            payload = await request.json()
            prompt, text = payload.get("prompt"), payload.get("text")
            if not isinstance(prompt, str) or not isinstance(text, str):
                raise web.HTTPBadRequest(text="Invalid prompt")
            await self.ensure_config(request)
            dep = self.workspace.token_validators.get(prompt)
            if dep is None:
                return web.json_response({"invalid": None})
            data = [text]
            if len(dep["inputs"]) == 2:
                steps = payload.get("steps")
                data.append(steps if type(steps) is int and steps > 0 else 20)
            api_name = quote(str(dep.get("api_name") or "predict"), safe="")
            async with self.http.post(
                self.url(request, "/run/" + api_name), headers=self.headers(request),
                json={"fn_index": dep["id"], "session_hash": self.session, "data": data},
            ) as response:
                if response.status != 200:
                    return web.json_response({"invalid": None})
                value = (await response.json()).get("data") or [None]
                value = value[0]
                if isinstance(value, dict):
                    value = value.get("value")
                return web.json_response({
                    "invalid": bool(re.search(r"\berror\b", value, re.I)) if isinstance(value, str) else None
                })
        if path == PREFIX + "/controls":
            await self.ensure_config(request)
            if request.method == "GET":
                values = {
                    name: self.workspace.draft[str(component)]["value"]
                    for name, component in self.workspace.component_names.items()
                    if "value" in self.workspace.draft.get(str(component), {})
                }
                return web.json_response(values, headers={"Cache-Control": "no-store"})
            if request.method == "POST":
                values = await request.json()
                if not isinstance(values, dict):
                    raise web.HTTPBadRequest(text="Invalid Forge settings")
                for name, value in values.items():
                    component = self.workspace.component_names.get(name)
                    if component is not None:
                        self.workspace.draft.setdefault(str(component), {})["value"] = value
                self.workspace.save()
                return web.Response(status=204)
        if path == PREFIX + "/fields" and request.method == "POST":
            payload = await request.json()
            updates = payload.get("updates")
            if payload.get("fingerprint") != self.workspace.fingerprint or not isinstance(updates, dict):
                raise web.HTTPConflict(text="Reload Forge Mobile before saving controls")
            if not all(key.isdecimal() and int(key) in self.workspace.editable_fields for key in updates):
                raise web.HTTPBadRequest(text="Unknown Forge control")
            for component, value in updates.items():
                self.workspace.draft.setdefault(component, {})["value"] = value
            self.workspace.save()
            return web.Response(status=204)
        if path in {PREFIX + "/hires", PREFIX + "/field"} and request.method == "POST":
            payload = await request.json()
            component = payload.get("component")
            if (payload.get("fingerprint") != self.workspace.fingerprint
                    or not isinstance(component, int)
                    or component not in self.workspace.editable_fields
                    or "value" not in payload):
                raise web.HTTPConflict(text="Reload Forge Mobile before saving settings")
            self.workspace.draft.setdefault(str(component), {})["value"] = payload["value"]
            self.workspace.save()
            return web.Response(status=204)
        if path == PREFIX + "/mobile.js" and request.method == "GET":
            return web.Response(body=self.browser_script, content_type="application/javascript",
                                headers={"Cache-Control": "no-store"})
        if path == "/queue/join" and request.method == "POST":
            payload = await request.json()
            return await asyncio.shield(self.join(request, payload))
        if path == "/queue/data" and request.method == "GET":
            return await self.subscribe(request)
        if path.startswith("/heartbeat/") and request.method == "GET":
            return await self.heartbeat(request)

        headers = self.headers(request)
        body = request.content if request.can_read_body else None
        remap = path.startswith(("/run/", "/api/")) or path in {"/cancel", "/reset", "/component_server"}
        index = None
        archive_restore = None
        if remap and request.content_type == "application/json" and request.method == "POST":
            payload = await request.json()
            if "session_hash" in payload:
                payload["session_hash"] = self.session
            index = payload.get("fn_index")
            if self.input_archive and isinstance(index, int) and isinstance(payload.get("data"), list):
                payload["data"], archive_restore = await self.input_archive.prepare_paste(index, payload["data"], headers)
            body = json_bytes(payload)

        url = self.url(request)
        if path == "/upload" and "session_hash" in request.query:
            query = dict(request.query)
            query["session_hash"] = self.session
            url = url.with_query(query)
        async with self.http.request(request.method, url, headers=headers, data=body, allow_redirects=False) as upstream:
            response_headers = self.response_headers(upstream, request)
            if request.method == "GET" and path == "/" and upstream.status == 200:
                page = self.patch_html(await upstream.text(), self.origin(request))
                response_headers["Cache-Control"] = "no-store"
                return web.Response(text=page, status=upstream.status, headers=response_headers)
            if request.method == "GET" and path == "/config" and upstream.status == 200:
                config = await upstream.json()
                self.configure(config)
                self.last_config = time.monotonic()
                response_headers["Cache-Control"] = "no-store"
                return web.Response(body=json_bytes(self.browser_config(config, self.origin(request))),
                                    status=upstream.status, headers=response_headers)
            if index is not None and upstream.content_type == "application/json" and upstream.status == 200:
                output = await upstream.json()
                if isinstance(output.get("data"), list):
                    if self.input_archive and archive_restore is not None:
                        output["data"] = self.input_archive.apply_paste(index, output["data"], archive_restore)
                    self.workspace.restore_hires_on_load(index, output["data"])
                    self.workspace.complete(index, output["data"])
                return web.Response(body=json_bytes(output), status=upstream.status, headers=response_headers)

            response = web.StreamResponse(status=upstream.status, headers=response_headers)
            await response.prepare(request)
            try:
                async for chunk in upstream.content.iter_chunked(64 * 1024):
                    await response.write(chunk)
            except ConnectionError:
                pass
            return response


def create_app(upstream, workspace):
    companion = Companion(upstream, workspace)

    @web.middleware
    async def check_request(request, handler):
        origin = request.headers.get("Origin")
        if request.headers.get("Sec-Fetch-Site") == "cross-site" or (origin and origin != companion.origin(request)):
            raise web.HTTPForbidden(text="Cross-site request blocked")
        try:
            return await handler(request)
        except (ClientError, asyncio.TimeoutError) as error:
            raise web.HTTPBadGateway(text=f"Forge is unavailable at {upstream}: {error}") from error
        except ValueError as error:
            raise web.HTTPBadRequest(text=str(error)) from error

    app = web.Application(middlewares=[check_request], client_max_size=128 * 1024**2)
    app.cleanup_ctx.append(companion.lifecycle)
    app.router.add_route("*", "/{tail:.*}", companion.forward)
    return app


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--forge", default="http://127.0.0.1:7860")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", default=7862, type=int)
    args = parser.parse_args()
    upstream = urlsplit(args.forge)
    if upstream.scheme not in {"http", "https"} or not upstream.netloc or upstream.path not in {"", "/"}:
        parser.error("--forge must be an HTTP(S) origin without a subpath")
    logging.basicConfig(level=logging.INFO)
    print(f"[Forge Mobile Client] Installed version: v{VERSION}. Open http://<your-PC-IP>:{args.port}.", flush=True)
    web.run_app(create_app(args.forge, Workspace(HERE / "workspace.json")),
                host=args.host, port=args.port, access_log=None)


if __name__ == "__main__":
    main()
