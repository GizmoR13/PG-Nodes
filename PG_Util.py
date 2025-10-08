"""
ComfyUI — PG Utils (checkpoint switch, CFG swap guider, percent utils)

A small collection of utility nodes that help with model routing and guidance
control in ComfyUI.

Included nodes
--------------
1) PgCpSwitch: Two‑way switch for (MODEL, CLIP, VAE) triplets.
2) PgSwapCFGGuidance: A custom guider that uses **CFG1** for the early portion of denoising and **CFG2** afterwards.
3) PgPercentFloat: Converts an INT (typically 0..100) to a FLOAT in 0..1.

Author: Piotr Gredka & GPT
License: MIT
"""

from __future__ import annotations
try:
    import comfy.sd as comfy_sd
except Exception:
    import comfy_sd 
import comfy.hooks
from comfy.samplers import sampling_function, CFGGuider

class PgCpSwitch:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "model_a": ("MODEL",),
                "clip_a": ("CLIP",),
                "vae_a": ("VAE",),
                "model_b": ("MODEL",),
                "clip_b": ("CLIP",),
                "vae_b": ("VAE",),
                "a_true": ("BOOLEAN", {"forceInput": True}),
            }
        }
        
    RETURN_TYPES = ("MODEL", "CLIP", "VAE")
    FUNCTION = "cp_switch"
    CATEGORY = "PG/Utils"

    def cp_switch(self, model_a, clip_a, vae_a, model_b, clip_b, vae_b, a_true=True):
        if a_true:
            return (model_a, clip_a, vae_a)
        else:
            return (model_b, clip_b, vae_b)

class PgGuider_SwapCFG(CFGGuider):
    def set_cfgs(self, cfg1: float, cfg2: float, swap_percent: float):

        self.cfg1 = float(cfg1)
        self.cfg2 = float(cfg2)

        sp = float(swap_percent)
        if sp < 0.0: sp = 0.0
        if sp > 1.0: sp = 1.0
        self.swap_percent = sp

    def _current_step_index(self, steps, timestep):
        matched_step_index = (steps == timestep).nonzero()
        if len(matched_step_index) > 0:
            return matched_step_index.item()
        ts0 = timestep[0]
        for i in range(len(steps) - 1):
            if (steps[i] - ts0) * (steps[i + 1] - ts0) <= 0:
                return i
        return 0

    def predict_noise(self, x, timestep, model_options={}, seed=None):
        steps = model_options["transformer_options"]["sample_sigmas"]
        idx = self._current_step_index(steps, timestep)
        current_percent = idx / max(1, (len(steps) - 1))

        cfg = self.cfg1 if current_percent <= self.swap_percent else self.cfg2

        uncond = self.conds.get("negative", None)
        cond = self.conds.get("positive", None)

        return sampling_function(
            self.inner_model, x, timestep,
            uncond, cond, cfg,
            model_options=model_options, seed=seed
        )

class PgSwapCFGGuidance:
    @classmethod
    def INPUT_TYPES(s):
        return {"required": {
            "model": ("MODEL",),
            "positive": ("CONDITIONING", ),
            "negative": ("CONDITIONING", ),
            "cfg1": ("FLOAT", {"default": 6.0, "min": 0.0, "max": 100.0, "step": 0.01}),
            "cfg2": ("FLOAT", {"default": 1.0, "min": 0.0, "max": 100.0, "step": 0.01}),
            "swap_percent": ("FLOAT", {"default": 0.5, "min": 0.0, "max": 1.0, "step": 0.01}),
        }}

    RETURN_TYPES = ("GUIDER",)
    FUNCTION = "get_guider"
    CATEGORY = "PG"
    DESCRIPTION = """
A guider that splits the denoising pass into two intervals:
- [0.0, swap_percent] → CFG1
- (swap_percent, 1.0] → CFG2
The negative (uncond) prompt is used in both intervals.
"""

    def get_guider(self, model, positive, negative, cfg1, cfg2, swap_percent):
        guider = PgGuider_SwapCFG(model)
        guider.set_conds(positive, negative)
        guider.set_cfgs(cfg1, cfg2, swap_percent)
        return (guider,)

class PgPercentFloat:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "value": ("INT", {"forceInput": True}),
            }
        }

    RETURN_TYPES = ("FLOAT",)
    RETURN_NAMES = ("float",)
    CATEGORY = "PG/Utils"
    FUNCTION = "process"

    @classmethod
    def IS_CHANGED(cls, **kwargs):
        v = kwargs.get("value", 0)
        try:
            return str(int(v))
        except Exception:
            return "0"

    def process(self, value: int):
        try:
            iv = int(value)
        except Exception:
            iv = 0
        out = float(iv) / 100.0
        return (float(out),)

class PgXorDualToggle:
    CATEGORY = "PG/Utils"
    RETURN_TYPES = ("BOOLEAN", "BOOLEAN")
    RETURN_NAMES = ("boolean 1", "boolean 2")
    FUNCTION = "switch"

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "toggle": ("BOOLEAN", {"default": True}),
            }
        }

    @classmethod
    def IS_CHANGED(cls, **kw):
        # Changing the toggle flips the cache key so recompute
        return str(bool(kw.get("toggle", True)))

    def switch(self, toggle: bool):
        a = bool(toggle)
        b = not a
        return (a, b)

NODE_CLASS_MAPPINGS = {
    "PgCpSwitch": PgCpSwitch,
    "PgSwapCFGGuidance": PgSwapCFGGuidance,
    "PgPercentFloat": PgPercentFloat,
    "PgXorDualToggle": PgXorDualToggle,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "PgCpSwitch": "Checkpoint Switch",
    "PgSwapCFGGuidance": "Swap CFG Guidance",
    "PgPercentFloat": "%",
    "PgXorDualToggle": "Xor Toggle",
}