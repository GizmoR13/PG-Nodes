"""
ComfyUI — PG Selectors (checkpoint / diffusion / clip / vae / vision / controlnet / ipadapter / upscale / lora)

A tiny set of selector helper nodes used to pick model file names from
ComfyUI's `folder_paths` registry. Each selector returns the chosen name as
its output so you can route it into your loaders.

Key features
------------
- Provides both **Uni** variants (include a leading "none") and plain variants
  (only actual filenames) for each model family.
- Graceful discovery: tries multiple `folder_paths` keys per family to work
  across different ComfyUI node packs and conventions (e.g., `"diffusion_models"`,
  `"diffusion"`, `"diffusion_model"`).
- Safe fallbacks: if a lookup fails, returns an empty list to avoid hard errors.
- Lists are materialized once at import time for snappy UI dropdowns.

Author: Piotr Gredka & GPT
License: MIT
"""

import folder_paths
try:
    import comfy
    from comfy.samplers import KSampler as _KSampler
except Exception as _e:
    comfy = None
    _KSampler = None

def _get_checkpoint_list():
    try:
        lst = list(folder_paths.get_filename_list("checkpoints"))
        return lst
    except Exception:
        return []

def _get_diffusion_list():
    for key in ("diffusion_models", "diffusion", "diffusion_model"):
        try:
            lst = list(folder_paths.get_filename_list(key))
            if lst:
                return lst
        except Exception:
            pass
    return []

def _get_clip_list():
    for key in ("clip", "clip_text", "clip_models"):
        try:
            lst = list(folder_paths.get_filename_list(key))
            if lst:
                return lst
        except Exception:
            pass
    return []

def _get_vae_list():
    for key in ("vae", "vaes", "autoencoder"):
        try:
            lst = list(folder_paths.get_filename_list(key))
            if lst:
                return lst
        except Exception:
            pass
    return []

def _get_clip_vision_list():
    for key in ("clip_vision", "clip_vision_models", "vision_models", "clip_vision_encoder"):
        try:
            lst = list(folder_paths.get_filename_list(key))
            if lst:
                return lst
        except Exception:
            pass
    return []

def _get_controlnet_list():
    for key in ("controlnet", "controlnets"):
        try:
            lst = list(folder_paths.get_filename_list(key))
            if lst:
                return lst
        except Exception:
            pass
    return []

def _get_ipadapter_list():
    for key in ("ipadapter", "ip_adapter", "ipadapter_models", "ip-adapter"):
        try:
            lst = list(folder_paths.get_filename_list(key))
            if lst:
                return lst
        except Exception:
            pass
    return []

def _get_upscale_list():
    for key in ("upscale_models", "upscale", "upscalers", "realesrgan"):
        try:
            lst = list(folder_paths.get_filename_list(key))
            if lst:
                return lst
        except Exception:
            pass
    return []

def _get_lora_list():
    for key in ("loras", "lora", "lora_models"):
        try:
            lst = list(folder_paths.get_filename_list(key))
            if lst:
                return lst
        except Exception:
            pass
    return []

CKPTS = _get_checkpoint_list()
CKPTS_WITH_NONE = ["none"] + CKPTS
DIFF = _get_diffusion_list()
DIFF_WITH_NONE = ["none"] + DIFF
CLIPS = _get_clip_list()
CLIPS_WITH_NONE = ["none"] + CLIPS
VAES = _get_vae_list()
VAES_WITH_NONE = ["none"] + VAES
CLIPV = _get_clip_vision_list()
CLIPV_WITH_NONE = ["none"] + CLIPV
CNETS = _get_controlnet_list()
CNETS_WITH_NONE = ["none"] + CNETS
IPAS = _get_ipadapter_list()
IPAS_WITH_NONE = ["none"] + IPAS
UPS = _get_upscale_list()
UPS_WITH_NONE = ["none"] + UPS
LORAS = _get_lora_list()
LORAS_WITH_NONE = ["none"] + LORAS

class PgUniCheckpointSelect:
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "chkpt_name": (CKPTS_WITH_NONE, {"default": "none"}),
        }}

    CATEGORY = "PG/Select/UniLoader"
    RETURN_TYPES = (CKPTS_WITH_NONE,)
    RETURN_NAMES = ("chkpt_name",)
    FUNCTION = "process"

    def process(self, chkpt_name):
        return (chkpt_name,)

class PgCheckpointSelect:
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "chkpt_name": (CKPTS, {}),
        }}

    CATEGORY = "PG/Select"
    RETURN_TYPES = (CKPTS,)
    RETURN_NAMES = ("chkpt_name",)
    FUNCTION = "process"

    def process(self, chkpt_name):
        return (chkpt_name,)

class PgUniDiffusionSelect:
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "diffusion_name": (DIFF_WITH_NONE, {"default": "none"}),
        }}

    CATEGORY = "PG/Select/UniLoader"
    RETURN_TYPES = (DIFF_WITH_NONE,)
    RETURN_NAMES = ("diffusion_name",)
    FUNCTION = "process"

    def process(self, diffusion_name):
        return (diffusion_name,)

class PgDiffusionSelect:
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "diffusion_name": (DIFF, {}),
        }}

    CATEGORY = "PG/Select"
    RETURN_TYPES = (DIFF,)
    RETURN_NAMES = ("diffusion_name",)
    FUNCTION = "process"

    def process(self, diffusion_name):
        return (diffusion_name,)

class PgUniClipSelect:
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "clip_name": (CLIPS_WITH_NONE, {"default": "none"}),
        }}

    CATEGORY = "PG/Select/UniLoader"
    RETURN_TYPES = (CLIPS_WITH_NONE,)
    RETURN_NAMES = ("clip_name",)
    FUNCTION = "process"

    def process(self, clip_name):
        return (clip_name,)

class PgClipSelect:
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "clip_name": (CLIPS, {}),
        }}

    CATEGORY = "PG/Select"
    RETURN_TYPES = (CLIPS,)
    RETURN_NAMES = ("clip_name",)
    FUNCTION = "process"

    def process(self, clip_name):
        return (clip_name,)

class PgUniVAESelect:
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "vae_name": (VAES_WITH_NONE, {"default": "none"}),
        }}

    CATEGORY = "PG/Select/UniLoader"
    RETURN_TYPES = (VAES_WITH_NONE,)
    RETURN_NAMES = ("vae_name",)
    FUNCTION = "process"

    def process(self, vae_name):
        return (vae_name,)

class PgVAESelect:
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "vae_name": (VAES, {}),
        }}

    CATEGORY = "PG/Select"
    RETURN_TYPES = (VAES,)
    RETURN_NAMES = ("vae_name",)
    FUNCTION = "process"

    def process(self, vae_name):
        return (vae_name,)

class PgUniClipVisionSelect:
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "clip_vision_name": (CLIPV_WITH_NONE, {"default": "none"}),
        }}

    CATEGORY = "PG/Select/UniLoader"
    RETURN_TYPES = (CLIPV_WITH_NONE,)
    RETURN_NAMES = ("clip_vision_name",)
    FUNCTION = "process"

    def process(self, clip_vision_name):
        return (clip_vision_name,)

class PgClipVisionSelect:
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "clip_vision_name": (CLIPV, {}),
        }}

    CATEGORY = "PG/Select"
    RETURN_TYPES = (CLIPV,)
    RETURN_NAMES = ("clip_vision_name",)
    FUNCTION = "process"

    def process(self, clip_vision_name):
        return (clip_vision_name,)

class PgUniControlNetSelect:
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "controlnet_name": (CNETS_WITH_NONE, {"default": "none"}),
        }}

    CATEGORY = "PG/Select/UniLoader"
    RETURN_TYPES = (CNETS_WITH_NONE,)
    RETURN_NAMES = ("controlnet_name",)
    FUNCTION = "process"

    def process(self, controlnet_name):
        return (controlnet_name,)

class PgControlNetSelect:
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "controlnet_name": (CNETS, {}),
        }}

    CATEGORY = "PG/Select"
    RETURN_TYPES = (CNETS,)
    RETURN_NAMES = ("controlnet_name",)
    FUNCTION = "process"

    def process(self, controlnet_name):
        return (controlnet_name,)

class PgUniIPAdapterSelect:
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "ipadapter_name": (IPAS_WITH_NONE, {"default": "none"}),
        }}

    CATEGORY = "PG/Select/UniLoader"
    RETURN_TYPES = (IPAS_WITH_NONE,)
    RETURN_NAMES = ("ipadapter_name",)
    FUNCTION = "process"

    def process(self, ipadapter_name):
        return (ipadapter_name,)

class PgIPAdapterSelect:
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "ipadapter_name": (IPAS, {}),
        }}

    CATEGORY = "PG/Select"
    RETURN_TYPES = (IPAS,)
    RETURN_NAMES = ("ipadapter_name",)
    FUNCTION = "process"

    def process(self, ipadapter_name):
        return (ipadapter_name,)

class PgUniUpscaleSelect:
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "upscale_name": (UPS_WITH_NONE, {"default": "none"}),
        }}

    CATEGORY = "PG/Select/UniLoader"
    RETURN_TYPES = (UPS_WITH_NONE,)
    RETURN_NAMES = ("upscale_name",)
    FUNCTION = "process"

    def process(self, upscale_name):
        return (upscale_name,)

class PgUpscaleSelect:
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "upscale_name": (UPS, {}),
        }}

    CATEGORY = "PG/Select"
    RETURN_TYPES = (UPS,)
    RETURN_NAMES = ("upscale_name",)
    FUNCTION = "process"

    def process(self, upscale_name):
        return (upscale_name,)

class PgUniLORASelect:
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "lora_name": (LORAS_WITH_NONE, {"default": "none"}),
        }}

    CATEGORY = "PG/Select/UniLoader"
    RETURN_TYPES = (LORAS_WITH_NONE,)
    RETURN_NAMES = ("lora_name",)
    FUNCTION = "process"

    def process(self, lora_name):
        return (lora_name,)

class PgLORASelect:
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "lora_name": (LORAS, {}),
        }}

    CATEGORY = "PG/Select"
    RETURN_TYPES = (LORAS,)
    RETURN_NAMES = ("lora_name",)
    FUNCTION = "process"

    def process(self, lora_name):
        return (lora_name,)

class PgSamplerSelect:
    @classmethod
    def INPUT_TYPES(cls):
        if comfy is None or _KSampler is None:
            return {"required": {"sampler_name": (("euler", "euler_ancestral"), {"default": "euler"})}}
        names = getattr(comfy.samplers, "SAMPLER_NAMES", None)
        if names is None:
            names = getattr(_KSampler, "SAMPLERS", None)
        if not names:
            names = ("euler", "euler_ancestral")
        return {"required": {"sampler_name": (names,)}}

    CATEGORY = "PG/Select"
    RETURN_TYPES = ("SAMPLER",)
    RETURN_NAMES = ("sampler",)
    FUNCTION = "get_sampler"

    def get_sampler(self, sampler_name: str):
        if comfy is None:
            return (sampler_name,)
        sampler_object = getattr(comfy.samplers, "sampler_object", None)
        if callable(sampler_object):
            sampler = sampler_object(sampler_name)
            return (sampler,)
        return (sampler_name,)


class PgSchedulerSelect:
    @classmethod
    def INPUT_TYPES(cls):
        if comfy is None or _KSampler is None:
            return {"required": {"scheduler_name": (("normal", "karras"), {"default": "karras"})}}
        names = getattr(comfy.samplers, "SCHEDULER_NAMES", None)
        if names is None:
            names = getattr(_KSampler, "SCHEDULERS", None)
        if not names:
            names = ("normal", "karras")
        return {"required": {"scheduler_name": (names,)}}

    CATEGORY = "PG/Select"
    RETURN_TYPES = ("SCHEDULER",)
    RETURN_NAMES = ("scheduler",)
    FUNCTION = "get_scheduler"

    def get_scheduler(self, scheduler_name: str):
        if comfy is None:
            return (scheduler_name,)
        scheduler_object = getattr(comfy.samplers, "scheduler_object", None)
        if callable(scheduler_object):
            sched = scheduler_object(scheduler_name)
            return (sched,)
        return (scheduler_name,)

class PgSamplerSelectCombo:
    @classmethod
    def INPUT_TYPES(cls):
        if _KSampler is None:
            return {"required": {"sampler_name": (("euler", "euler_ancestral"), {"default": "euler"})}}
        return {"required": {"sampler_name": (_KSampler.SAMPLERS,)}}

    CATEGORY = "PG/Select"
    RETURN_TYPES = (_KSampler.SAMPLERS,)
    RETURN_NAMES = ("sampler",)
    FUNCTION = "process"

    def process(self, sampler_name):
        return (sampler_name,)


class PgSchedulerSelectCombo:
    @classmethod
    def INPUT_TYPES(cls):
        if _KSampler is None:
            return {"required": {"scheduler_name": (("normal", "karras"), {"default": "karras"})}}
        return {"required": {"scheduler_name": (_KSampler.SCHEDULERS,)}}

    CATEGORY = "PG/Select"
    RETURN_TYPES = (_KSampler.SCHEDULERS,)
    RETURN_NAMES = ("scheduler",)
    FUNCTION = "process"

    def process(self, scheduler_name):
        return (scheduler_name,)


NODE_CLASS_MAPPINGS = {
    "PgUniCheckpointSelect": PgUniCheckpointSelect,
    "PgCheckpointSelect": PgCheckpointSelect,
    "PgUniDiffusionSelect": PgUniDiffusionSelect,
    "PgDiffusionSelect": PgDiffusionSelect,
    "PgUniClipSelect": PgUniClipSelect,
    "PgClipSelect": PgClipSelect,
    "PgUniVAESelect": PgUniVAESelect,
    "PgVAESelect": PgVAESelect,
    "PgUniClipVisionSelect": PgUniClipVisionSelect,
    "PgClipVisionSelect": PgClipVisionSelect,
    "PgUniControlNetSelect": PgUniControlNetSelect,
    "PgControlNetSelect": PgControlNetSelect,
    "PgUniIPAdapterSelect": PgUniIPAdapterSelect,
    "PgIPAdapterSelect": PgIPAdapterSelect,
    "PgUniUpscaleSelect": PgUniUpscaleSelect,
    "PgUpscaleSelect": PgUpscaleSelect,
    "PgUniLORASelect": PgUniLORASelect,
    "PgLORASelect": PgLORASelect,
    "PgSamplerSelect": PgSamplerSelect,
    "PgSchedulerSelect": PgSchedulerSelect,
    "PgSamplerSelectCombo": PgSamplerSelectCombo,
    "PgSchedulerSelectCombo": PgSchedulerSelectCombo,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "PgUniCheckpointSelect": "Checkpoint Select (Uni)",
    "PgCheckpointSelect": "Checkpoint Select",
    "PgUniDiffusionSelect": "Diffusion Select (Uni)",
    "PgDiffusionSelect": "Diffusion Select",
    "PgUniClipSelect": "Clip Select (Uni)",
    "PgClipSelect": "Clip Select",
    "PgUniVAESelect": "Vae Select (Uni)",
    "PgVAESelect": "Vae Select",
    "PgUniClipVisionSelect": "ClipVision Select (Uni)",
    "PgClipVisionSelect": "ClipVision Select",
    "PgUniControlNetSelect": "ControlNet Select (Uni)",
    "PgControlNetSelect": "ControlNet Select",
    "PgUniIPAdapterSelect": "IPAdapter Select (Uni)",
    "PgIPAdapterSelect": "IPAdapter Select",
    "PgUniUpscaleSelect": "Upscale Select (Uni)",
    "PgUpscaleSelect": "Upscale Select",
    "PgUniLORASelect": "LORA Select (Uni)",
    "PgLORASelect": "LORA Select",
    "PgSamplerSelect": "Sampler Select",
    "PgSchedulerSelect": "Scheduler Select",
    "PgSamplerSelectCombo": "Sampler Select name",
    "PgSchedulerSelectCombo": "Scheduler Select name",
}
