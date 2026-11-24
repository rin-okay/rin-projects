"""Run with python -m unittest discover -s tests."""
import asyncio
import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

import companion
from companion import Workspace, create_app
from mobile_extensions import MobileExtensions


def forge_config():
    # Matches Gradio 4.40's dependency shape and Forge's submission convention.
    components = [
        {"id": 0, "type": "column", "props": {}},
        {"id": 1, "type": "textbox", "props": {"elem_id": "task", "value": ""}},
        {"id": 2, "type": "textbox", "props": {"elem_id": "txt2img_prompt", "value": ""}},
        {"id": 3, "type": "checkbox", "props": {"elem_id": "txt2img_hr-checkbox", "value": False}},
        {"id": 4, "type": "gallery", "props": {"elem_id": "txt2img_gallery", "value": []}},
        {"id": 5, "type": "textbox", "props": {"elem_id": "generation_info_txt2img", "interactive": False}},
    ]
    return {
        "version": "4.40.0", "protocol": "sse_v3", "enable_queue": True,
        "components": components,
        "layout": {"id": 0, "children": []},
        "dependencies": [{
            "id": 0, "backend_fn": True, "js": "submit",
            "inputs": [1, 2, 3], "outputs": [4, 5], "targets": [[10, "click"]],
        }],
    }


class CompanionIntegration(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.workspace = Workspace(self.root / "workspace.json")
        self.config = forge_config()
        self.submissions = []

        async def upstream(request):
            if request.path == "/config":
                return web.json_response(copy.deepcopy(self.config))
            if request.path == "/":
                return web.Response(text="<html><head><script>window.gradio_config=" +
                                    json.dumps(self.config) + ";</script></head><body></body></html>")
            if request.path == "/run/test_tokens":
                data = (await request.json())["data"]
                return web.json_response({"data": ["<span>Error</span>" if data[0] == "bad" else "<span>2/75</span>"]})
            if request.path == "/queue/join":
                self.submissions.append(await request.json())
                return web.json_response({"event_id": "event-1"})
            if request.path == "/queue/data":
                await asyncio.sleep(.04)
                message = {"msg": "process_completed", "event_id": "event-1",
                           "success": True, "output": {"data": [
                               [{"image": {"path": "/tmp/result.png", "url": "/file=/tmp/result.png",
                                           "meta": {"_type": "gradio.FileData"}}, "caption": None}],
                               '{"index_of_first_image":0,"all_seeds":[42]}',
                           ]}}
                return web.Response(text="data: " + json.dumps(message) +
                                    '\n\ndata: {"msg":"close_stream"}\n\n',
                                    content_type="text/event-stream")
            return web.Response(status=404)

        upstream_app = web.Application()
        upstream_app.router.add_route("*", "/{tail:.*}", upstream)
        self.upstream = TestServer(upstream_app)
        await self.upstream.start_server()
        app = create_app(str(self.upstream.make_url("")).rstrip("/"), self.workspace)
        self.client = TestClient(TestServer(app))
        await self.client.start_server()

    async def asyncTearDown(self):
        await self.client.close()
        await self.upstream.close()
        self.temp.cleanup()

    async def test_client_configuration_and_draft_reload(self):
        response = await self.client.get("/")
        page = await response.text()
        self.assertIn("/_forge_mobile/client-loader.js", page)
        fields = await self.client.post("/_forge_mobile/fields", json={
            "fingerprint": self.workspace.fingerprint, "updates": {"2": "unsent edit", "3": True}})
        self.assertEqual(fields.status, 204)
        restored = await (await self.client.get("/config")).json()
        self.assertEqual(restored["components"][2]["props"]["value"], "unsent edit")
        self.assertTrue(restored["components"][3]["props"]["value"])
        self.assertEqual(Workspace(self.workspace.path).draft["2"]["value"], "unsent edit")

    async def test_prompts_are_saved_on_generate_instead_of_input(self):
        self.config["components"].extend([
            {"id": 6, "type": "textbox", "props": {"elem_id": "txt2img_neg_prompt"}},
            {"id": 7, "type": "textbox", "props": {"elem_id": "hires_prompt"}},
            {"id": 8, "type": "html", "props": {"elem_id": "txt2img_token_counter"}},
        ])
        self.config["dependencies"][0]["inputs"].extend([6, 7])
        self.config["dependencies"].append({
            "id": 1, "backend_fn": True, "inputs": [2], "outputs": [8], "targets": [[2, "input"]],
        })
        config = await (await self.client.get("/config")).json()
        input_savers = {
            dep["inputs"][0] for dep in config["dependencies"]
            if "forgeMobileSaveField" in (dep.get("js") or "")
        }
        self.assertTrue({2, 6, 7}.isdisjoint(input_savers))
        self.assertIn(3, input_savers)
        self.assertEqual(config["dependencies"][1]["targets"], [])
        self.assertIn('[[1, "txt2img_prompt"], [3, "txt2img_neg_prompt"], [4, "hires_prompt"]]',
                      config["dependencies"][0]["js"])

        submitted = ["task(fresh-prompts)", "new positive", True, "new negative", "new hires"]
        response = await self.client.post("/queue/join", json={
            "fn_index": 0, "session_hash": "phone", "data": submitted,
        })
        self.assertEqual(response.status, 200)
        self.assertEqual(self.submissions[-1]["data"], submitted)
        saved = Workspace(self.workspace.path).draft
        self.assertEqual([saved[str(i)]["value"] for i in (2, 6, 7)],
                         ["new positive", "new negative", "new hires"])

    async def test_img2img_hires_uses_current_prompts_without_overwriting_drafts(self):
        self.config["components"].extend([
            {"id": 6, "type": "textbox", "props": {"elem_id": "img2img_prompt"}},
            {"id": 7, "type": "textbox", "props": {"label": "Hires prompt"}},
            {"id": 8, "type": "textbox", "props": {"label": "Hires negative prompt"}},
            {"id": 9, "type": "html", "props": {"elem_id": "img2img_token_counter"}},
        ])
        self.config["dependencies"].extend([
            {"id": 1, "backend_fn": True, "js": "i2iHiresPrepare", "inputs": [1, 4, 10, 5, 7, 8],
             "outputs": [4, 5], "targets": [[10, "click"]]},
            {"id": 2, "backend_fn": True, "api_name": "test_tokens", "inputs": [6], "outputs": [9],
             "targets": [[6, "input"]]},
        ])
        config = await (await self.client.get("/config")).json()
        self.assertEqual(config["components"][7]["props"]["elem_id"], "img2img_hr_prompt")
        self.assertEqual(config["components"][8]["props"]["elem_id"], "img2img_hr_neg_prompt")
        self.assertEqual(config["dependencies"][1]["trigger_mode"], "multiple")

        for prompt, expected in (("bad", True), ("good", False)):
            response = await self.client.post("/_forge_mobile/prompt-validity", json={
                "prompt": "img2img_prompt", "text": prompt})
            self.assertEqual((await response.json())["invalid"], expected)

        for item, (hires_pair, current_pair, expected) in enumerate([
            (["", "explicit negative"], ["current positive", "current negative"], ["current positive", "explicit negative"]),
            (["", ""], ["", ""], [" ", " "]),
            (["", ""], None, ["", ""]),
        ]):
            data = [f"task(hires-{item})", [], 0, "source info", *hires_pair]
            if current_pair is not None:
                data.append({"forge_mobile_img2img_prompts": current_pair})
            response = await self.client.post("/queue/join", json={
                "fn_index": 1, "session_hash": "mobile", "data": data})
            self.assertEqual(response.status, 200)
            self.assertEqual(self.submissions[-1]["data"][4:], expected)
            self.assertEqual(self.workspace.draft["7"]["value"], hires_pair[0])
            self.assertEqual(self.workspace.draft["8"]["value"], hires_pair[1])

    async def test_generation_survives_phone_disconnect(self):
        await self.client.get("/config")
        queued = await self.client.post("/queue/join", json={
            "fn_index": 0, "session_hash": "phone-first", "data": ["task(test-id)", "native prompt", False]})
        self.assertEqual(queued.status, 200)
        await asyncio.sleep(.15)
        self.assertTrue(self.workspace.results["4"]["value"])
        self.assertIn("all_seeds", self.workspace.results["5"]["value"])
        replay = await self.client.post("/queue/join", json={
            "fn_index": 0, "session_hash": "phone-reloaded", "data": ["task(test-id)", "native prompt", False]})
        self.assertEqual(replay.status, 200)
        self.assertEqual(len(self.submissions), 1)
        restored = await (await self.client.get("/config")).json()
        self.assertTrue(restored["components"][4]["props"]["value"])

    async def test_named_control_export_import(self):
        await self.client.get("/config")
        response = await self.client.post("/_forge_mobile/controls", json={
            "txt2img_prompt": "imported prompt", "txt2img_hr-checkbox": True, "unknown-old-control": 99})
        self.assertEqual(response.status, 204)
        values = await (await self.client.get("/_forge_mobile/controls")).json()
        self.assertEqual(values["txt2img_prompt"], "imported prompt")
        self.assertTrue(values["txt2img_hr-checkbox"])
        self.assertNotIn("unknown-old-control", values)

    async def test_invalid_field_batch_is_atomic(self):
        await self.client.get("/config")
        response = await self.client.post("/_forge_mobile/fields", json={
            "fingerprint": self.workspace.fingerprint, "updates": {"2": "should not save", "999": "bad"}})
        self.assertEqual(response.status, 400)
        self.assertNotIn("2", self.workspace.draft)


class ExtensionDiscovery(unittest.IsolatedAsyncioTestCase):
    async def test_custom_dock_and_settings(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            dock = root / "extensions/docker-manager/docks/custom"
            dock.mkdir(parents=True)
            (dock / "dock.json").write_text(json.dumps({
                "id": "custom", "name": "Custom", "default_width": "half", "allowed_widths": ["half"]}))
            (dock / "dock.js").write_text("window.ForgeDockManager.registerDock({id:'custom'});")
            (dock / "style.css").write_text(".custom {}")
            manager = MobileExtensions(root / "extensions", {"mobile-docks": {"docks": []}})
            registry = manager.registry()
            self.assertEqual(registry["docks"][0]["id"], "custom")
            self.assertIn("/_forge_mobile/extensions/docker-manager/docks/custom/dock.js",
                          registry["docks"][0]["script_url"])
            manager.values["mobile-docks"] = {"docks": [{"dock_id": "custom"}]}
            manager.save()
            self.assertEqual(MobileExtensions(manager.root, manager.defaults).values, manager.values)


if __name__ == "__main__":
    unittest.main()
