"""

 PG_Just_Save_Image.py

 Minimal ComfyUI nodes that save images when a boolean toggle is ON.
 - PgJustSaveImage: output node (no outputs) — saves batch to the output folder.
 - PgJustSaveImageOut: passthrough node — same saving behavior, but returns IMAGE.

 Author: Piotr Gredka & GPT
 License: MIT
 
"""

import os
import json
import re
import numpy as np
from PIL import Image
from PIL.PngImagePlugin import PngInfo
import folder_paths

DEFAULT_PREFIX = "ComfyUI"

def _save_batch_shared(images, prompt=None, extra_pnginfo=None, prefix=DEFAULT_PREFIX):
    """Save all frames from an IMAGE batch to ComfyUI's output directory.
    Files are named as: <prefix>_<counter>_.png, where <counter> is incremental
    and continues from the highest existing counter in the output folder.
    """
    out_dir = folder_paths.get_output_directory()
    os.makedirs(out_dir, exist_ok=True)

    # Find the largest existing counter for files like: <prefix>_00001_.png
    pattern = re.compile(rf"^{re.escape(prefix)}_(\d+)_.png$", re.I)
    existing = []
    for f in os.listdir(out_dir):
        m = pattern.match(f)
        if m:
            existing.append(int(m.group(1)))
    base_counter = (max(existing) + 1) if existing else 0

    for idx, image in enumerate(images):
        arr = (255.0 * image.cpu().numpy()).clip(0, 255).astype(np.uint8)
        img = Image.fromarray(arr)

        meta = PngInfo()
        if prompt is not None:
            meta.add_text("prompt", json.dumps(prompt, ensure_ascii=False))

        if extra_pnginfo:
            for k, v in extra_pnginfo.items():
                if k == "parameters":
                    if not isinstance(v, str):
                        v = json.dumps(v, ensure_ascii=False)
                    meta.add_text(k, v)
                elif k in ("workflow", "prompt"):
                    meta.add_text(k, json.dumps(v, ensure_ascii=False))
                else:
                    meta.add_text(k, json.dumps(v, ensure_ascii=False))

        if prefix:
            meta.add_text("filename_prefix", json.dumps(prefix, ensure_ascii=False))

        file_index = base_counter + idx
        file_name = f"{prefix}_{file_index:05d}_.png"
        img.save(os.path.join(out_dir, file_name), pnginfo=meta, compress_level=4)


class PgJustSaveImage:
    @classmethod
    def INPUT_TYPES(s):
        return {
            "required": {
                "image": ("IMAGE",),
                "save": ("BOOLEAN", {"default": False}),
            },
            "hidden": {
                "prompt": "PROMPT",
                "extra_pnginfo": "EXTRA_PNGINFO",
            },
        }

    RETURN_TYPES = ()
    FUNCTION = "save_if_true"
    OUTPUT_NODE = True
    CATEGORY = "PG/Utils"

    def save_if_true(self, image, save=False, prompt=None, extra_pnginfo=None):
        if save:
            _save_batch_shared(image, prompt=prompt, extra_pnginfo=extra_pnginfo, prefix=DEFAULT_PREFIX)
        return {}


class PgJustSaveImageOut:
    @classmethod
    def INPUT_TYPES(s):
        return {
            "required": {
                "image": ("IMAGE",),
                "save": ("BOOLEAN", {"default": False}),
            },
            "hidden": {
                "prompt": "PROMPT",
                "extra_pnginfo": "EXTRA_PNGINFO",
            },
        }

    RETURN_TYPES = ("IMAGE",)
    FUNCTION = "save_and_pass"
    CATEGORY = "PG/Utils"

    def save_and_pass(self, image, save=False, prompt=None, extra_pnginfo=None):
        if save:
            _save_batch_shared(image, prompt=prompt, extra_pnginfo=extra_pnginfo, prefix=DEFAULT_PREFIX)
        return (image,)


NODE_CLASS_MAPPINGS = {
    "PgJustSaveImage": PgJustSaveImage,
    "PgJustSaveImageOut": PgJustSaveImageOut,
}
NODE_DISPLAY_NAME_MAPPINGS = {
    "PgJustSaveImage": "Just Save Image",
    "PgJustSaveImageOut": "Just Save Image & Out",
}
