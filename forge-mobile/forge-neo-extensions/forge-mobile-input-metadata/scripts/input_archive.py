"""Add the companion's archive reference to Forge's normal image metadata."""
import re

import gradio as gr
from modules import scripts


class Script(scripts.Script):
    def title(self):
        return "Forge Mobile input archive"

    def show(self, is_img2img):
        return scripts.AlwaysVisible

    def ui(self, is_img2img):
        mode = "img2img" if is_img2img else "txt2img"
        return [gr.Textbox(value="", visible=False, interactive=False,
                           elem_id=f"{mode}_fm_input_archive")]

    def process(self, p, reference):
        if isinstance(reference, str) and re.fullmatch(r"[a-f0-9]{64}", reference):
            p.extra_generation_params["Forge Mobile input archive"] = reference
