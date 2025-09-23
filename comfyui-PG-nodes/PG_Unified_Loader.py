"""
ComfyUI — Unified Loader (v1.1)

What this module provides:
- A single "Unified Loader" node that can load: Checkpoint (MODEL/CLIP/VAE), Diffusion UNet, VAE
  (including TAESD/TAESDXL/TAESD3/Taef1 aliases), CLIP (multi-file), CLIP-Vision, ControlNet,
  IP-Adapter, and Upscale models — all from one node.
- A compact "Unified Loader (mini)" node with a reduced set of inputs/outputs for lightweight graphs.
- Robust import fallbacks for multiple ComfyUI versions and community plugins (e.g. comfy_extras,
  comfyui_ipadapter_plus). Best-effort CPU toggle and FP8 dtype options for UNet.

Author: Piotr Gredka & GPT
License: MIT
"""

from __future__ import annotations
from typing import List

# Optional dependency: PyTorch (used for device/dtype handling). Tolerate absence.
try:
    import torch
except Exception:
    torch = None

# --- ComfyUI & extras imports (with defensive fallbacks) -----------------------------------------
try:
    from folder_paths import (
        get_filename_list,
        get_full_path_or_raise,
        get_folder_paths,
    )
    import comfy.sd as comfy_sd
    import comfy.utils as comfy_utils
    import comfy.clip_vision as comfy_clip_vision
    import comfy.controlnet as comfy_controlnet
    import model_management as mm

    # IP-Adapter loader
    try:
        from comfy_extras.nodes.ipadapter import ipadapter_model_loader as comfy_ipadapter_model_loader
    except Exception:
        try:
            from comfy_extras.ipadapter.ipadapter import ipadapter_model_loader as comfy_ipadapter_model_loader
        except Exception:
            comfy_ipadapter_model_loader = None

    # Preferred loader from comfyui_ipadapter_plus (if installed)
    try:
        from comfyui_ipadapter_plus.IPAdapterPlus import ipadapter_model_loader as comfy_ipadapter_plus_loader
    except Exception:
        comfy_ipadapter_plus_loader = None

    # Fallback: loader from comfyui_ipadapter_plus if the comfy_extras one is missing
    if 'comfy_ipadapter_model_loader' not in globals() or comfy_ipadapter_model_loader is None:
        try:
            from comfyui_ipadapter_plus.IPAdapterPlus import ipadapter_model_loader as comfy_ipadapter_model_loader
        except Exception:
            pass

    # Upscale helpers (locations differ across versions)
    try:
        from comfy_extras.nodes_upscale_model import ImageModelDescriptor, ModelLoader
    except Exception:
        try:
            from comfy_extras.nodes_model_loader import ImageModelDescriptor, ModelLoader
        except Exception:
            try:
                from comfy_extras.nodes.upscale_model import ImageModelDescriptor, ModelLoader
            except Exception:
                ImageModelDescriptor = None
                ModelLoader = None
except Exception as e:
    # Gracefully degrade if ComfyUI internals are not importable (e.g. static analysis)
    get_filename_list = None
    get_full_path_or_raise = None
    get_folder_paths = None
    comfy_sd = None
    comfy_utils = None
    try:
        import comfy.clip_vision as comfy_clip_vision
    except Exception:
        comfy_clip_vision = None
    try:
        import comfy.controlnet as comfy_controlnet
    except Exception:
        comfy_controlnet = None
    try:
        import model_management as mm
    except Exception:
        mm = None
    try:
        from comfy_extras.nodes.ipadapter import ipadapter_model_loader as comfy_ipadapter_model_loader
    except Exception:
        comfy_ipadapter_model_loader = None
    # Preferred loader from comfyui_ipadapter_plus (if installed)
    try:
        from comfyui_ipadapter_plus.IPAdapterPlus import ipadapter_model_loader as comfy_ipadapter_plus_loader
    except Exception:
        comfy_ipadapter_plus_loader = None
    # Fallback: loader from comfyui_ipadapter_plus
    if 'comfy_ipadapter_model_loader' not in globals() or comfy_ipadapter_model_loader is None:
        try:
            from comfyui_ipadapter_plus.IPAdapterPlus import ipadapter_model_loader as comfy_ipadapter_model_loader
        except Exception:
            pass
    try:
        from comfy_extras.nodes_upscale_model import ImageModelDescriptor, ModelLoader
    except Exception:
        try:
            from comfy_extras.nodes_model_loader import ImageModelDescriptor, ModelLoader
        except Exception:
            try:
                from comfy_extras.nodes.upscale_model import ImageModelDescriptor, ModelLoader
            except Exception:
                ImageModelDescriptor = None
                ModelLoader = None
    print("[Unified Loader] Warning: ComfyUI modules not available:", e)

# --------------------------------------------------------------------------------------
# Helpers: type labels and folder keys
TYPE_LABELS = [
    "Load Checkpoint",
    "Load Diffusion Model",
    "Load VAE",
    "Load CLIP",
    "Load CLIP Vision",
    "Load ControlNet Model",
    "Load Upscale Model",
]

FOLDER_KEYS = {
    "Load Checkpoint": "checkpoints",
    "Load Diffusion Model": "diffusion_models",
    "Load VAE": "vae",
    "Load CLIP": "text_encoders",
    "Load CLIP Vision": "clip_vision",
    "Load ControlNet Model": "controlnet",
    "Load Upscale Model": "upscale_models",
}

CLIP_TYPES = [
    "stable_diffusion", "stable_cascade", "sd3", "stable_audio", "mochi",
    "ltxv", "pixart", "cosmos", "lumina2", "wan", "hidream", "chroma",
    "ace", "omnigen2", "qwen_image",
]


def _list_files(key: str) -> List[str]:
    if get_filename_list is None:
        return []
    try:
        files = list(get_filename_list(key))
        return files if files else []
    except Exception:
        return []


def _with_none(options: List[str]) -> List[str]:
    opts = [o for o in options if o]
    return ["none"] + opts


# --------------------------------------------------------------------------------------
# Main node (all internal loaders)
class PgUnifiedLoader:
    CATEGORY = "PG"
    NODE_DISPLAY_NAME = "Unified Loader"

    # --- Checkpoint --------------------------------------------------------
    @staticmethod
    def _load_checkpoint(ckpt_name: str, device: str = "default"):
        if not ckpt_name or ckpt_name == "none":
            return (None, None, None)
        if get_full_path_or_raise is None or comfy_sd is None or get_folder_paths is None:
            return (None, None, None)
        ckpt_path = get_full_path_or_raise("checkpoints", ckpt_name)
        model_options = {}
        if device == "cpu" and torch is not None:
            model_options["load_device"] = torch.device("cpu")
            model_options["offload_device"] = torch.device("cpu")
        out = comfy_sd.load_checkpoint_guess_config(
            ckpt_path,
            output_vae=True,
            output_clip=True,
            embedding_directory=get_folder_paths("embeddings"),
            model_options=model_options,
        )
        return out[:3]  # (MODEL, CLIP, VAE)

    # --- CLIP --------------------------------------------------------------
    @staticmethod
    def _load_clip(clip_names: List[str], type: str = "stable_diffusion", device: str = "default"):
        names = [n for n in (clip_names or []) if n and n != "none"]
        if not names:
            return (None,)
        if get_full_path_or_raise is None or comfy_sd is None or get_folder_paths is None:
            return (None,)
        clip_type = getattr(comfy_sd.CLIPType, type.upper(), getattr(comfy_sd.CLIPType, "STABLE_DIFFUSION", None))
        model_options = {}
        if device == "cpu" and torch is not None:
            model_options["load_device"] = model_options["offload_device"] = torch.device("cpu")
        ckpt_paths = [get_full_path_or_raise("text_encoders", n) for n in names]
        clip = comfy_sd.load_clip(
            ckpt_paths=ckpt_paths,
            embedding_directory=get_folder_paths("embeddings"),
            clip_type=clip_type,
            model_options=model_options,
        )
        return (clip,)

    # --- VAE (with TAESD aliases) -----------------------------------------
    @staticmethod
    def _load_taesd(name: str):
        if comfy_utils is None or get_filename_list is None or get_full_path_or_raise is None or torch is None:
            return None
        sd = {}
        approx_vaes = get_filename_list("vae_approx") or []
        try:
            encoder = next(a for a in approx_vaes if a.startswith(f"{name}_encoder."))
            decoder = next(a for a in approx_vaes if a.startswith(f"{name}_decoder."))
        except StopIteration:
            return None
        enc = comfy_utils.load_torch_file(get_full_path_or_raise("vae_approx", encoder))
        for k in enc:
            sd[f"taesd_encoder.{k}"] = enc[k]
        dec = comfy_utils.load_torch_file(get_full_path_or_raise("vae_approx", decoder))
        for k in dec:
            sd[f"taesd_decoder.{k}"] = dec[k]
        if name == "taesd":
            sd["vae_scale"] = torch.tensor(0.18215)
            sd["vae_shift"] = torch.tensor(0.0)
        elif name == "taesdxl":
            sd["vae_scale"] = torch.tensor(0.13025)
            sd["vae_shift"] = torch.tensor(0.0)
        elif name == "taesd3":
            sd["vae_scale"] = torch.tensor(1.5305)
            sd["vae_shift"] = torch.tensor(0.0609)
        elif name == "taef1":
            sd["vae_scale"] = torch.tensor(0.3611)
            sd["vae_shift"] = torch.tensor(0.1159)
        return sd

    @staticmethod
    def _load_vae(vae_name: str, device: str = "default"):
        if not vae_name or vae_name == "none":
            return (None,)
        if comfy_sd is None:
            return (None,)
        if vae_name in ["taesd", "taesdxl", "taesd3", "taef1"]:
            sd = PgUnifiedLoader._load_taesd(vae_name)
            if sd is None:
                return (None,)
        else:
            if get_full_path_or_raise is None or comfy_utils is None:
                return (None,)
            vae_path = get_full_path_or_raise("vae", vae_name)
            sd = comfy_utils.load_torch_file(vae_path)
        vae = comfy_sd.VAE(sd=sd)
        try:
            vae.throw_exception_if_invalid()
        except Exception as e:
            print(f"[Unified Loader] VAE invalid: {e}")
            return (None,)
        return (vae,)

    # --- UNet (Diffusion model) --------------------------------------------
    @staticmethod
    def _load_unet(unet_name: str, weight_dtype: str = "default", device: str = "default"):
        if not unet_name or unet_name == "none":
            return (None,)
        if get_full_path_or_raise is None or comfy_sd is None:
            return (None,)

        model_options = {}
        if weight_dtype == "fp8_e4m3fn" and hasattr(torch, "float8_e4m3fn"):
            model_options["dtype"] = getattr(torch, "float8_e4m3fn")
        elif weight_dtype == "fp8_e4m3fn_fast" and hasattr(torch, "float8_e4m3fn"):
            model_options["dtype"] = getattr(torch, "float8_e4m3fn")
            model_options["fp8_optimizations"] = True
        elif weight_dtype == "fp8_e5m2" and hasattr(torch, "float8_e5m2"):
            model_options["dtype"] = getattr(torch, "float8_e5m2")

        if device == "cpu" and torch is not None:
            model_options["load_device"] = torch.device("cpu")
            model_options["offload_device"] = torch.device("cpu")

        try:
            unet_path = get_full_path_or_raise("diffusion_models", unet_name)
            model = comfy_sd.load_diffusion_model(unet_path, model_options=model_options)
            return (model,)
        except Exception as e:
            print(f"[Unified Loader] unet load error: {e}")
            return (None,)

    # --- CLIP Vision -------------------------------------------------------
    @staticmethod
    def _load_clip_vision(clip_name: str, device: str = "default"):
        if not clip_name or clip_name == "none":
            return (None,)
        if get_full_path_or_raise is None or comfy_clip_vision is None:
            return (None,)

        clip_path = get_full_path_or_raise("clip_vision", clip_name)
        try:
            clip_vision = comfy_clip_vision.load(clip_path)
        except Exception as e:
            print(f"[Unified Loader] clip_vision load error: {e}")
            return (None,)

        if clip_vision is None:
            print("[Unified Loader] ERROR: CLIP Vision file invalid.")
            return (None,)

        if device == "cpu" and torch is not None:
            cpu = torch.device("cpu")
            if mm is not None and hasattr(mm, "ModelPatcher"):
                try:
                    clip_vision = mm.ModelPatcher(
                        clip_vision,
                        load_device=cpu,
                        offload_device=cpu,
                    )
                except Exception as e:
                    print(f"[Unified Loader] ModelPatcher clip_vision failed: {e}")
                    try:
                        clip_vision.to(cpu)
                    except Exception:
                        pass
            else:
                try:
                    clip_vision.to(cpu)
                except Exception:
                    pass

        return (clip_vision,)

    # --- IP-Adapter --------------------------------------------------------
    @staticmethod
    def _load_ipadapter(ipadapter_file: str, device: str = "default"):
        if not ipadapter_file or ipadapter_file == "none":
            return (None,)

        if get_full_path_or_raise is None:
            print("[Unified Loader] IPAdapter: missing folder paths.")
            return (None,)

        try:
            ip_path = get_full_path_or_raise("ipadapter", ipadapter_file)
        except Exception as e:
            print(f"[Unified Loader] IPAdapter path error: {e}")
            return (None,)

        # 1) Prefer loader from comfyui_ipadapter_plus; fallback: comfy_extras
        loader_fn = None
        if 'comfy_ipadapter_plus_loader' in globals() and comfy_ipadapter_plus_loader is not None:
            loader_fn = comfy_ipadapter_plus_loader
        elif 'comfy_ipadapter_model_loader' in globals() and comfy_ipadapter_model_loader is not None:
            loader_fn = comfy_ipadapter_model_loader

        if loader_fn is None:
            print("[Unified Loader] IPAdapter loader not available.")
            return (None,)

        # 2) Load raw package
        try:
            res = loader_fn(ip_path)
        except Exception as e:
            print(f"[Unified Loader] IPAdapter load error: {e}")
            return (None,)

        # 3) Normalize into a canonical pack structure
        #    pack: {'ipadapter': {'model': ...}, 'image_proj': {...}, 'image_proj_lite': {...}, ...}
        pack = None
        if isinstance(res, dict):
            pack = dict(res)
        elif isinstance(res, tuple):
            d = next((x for x in res if isinstance(x, dict)), None)
            if d is not None:
                pack = dict(d)
            else:
                first = next((x for x in res if x is not None), None)
                pack = {'ipadapter': {'model': first}} if first is not None else None
        elif res is not None:
            pack = {'ipadapter': {'model': res}}

        if pack is None:
            print("[Unified Loader] IPAdapter loader returned None.")
            return (None,)

        # If a loader returned top-level 'model', move it under 'ipadapter'
        if 'ipadapter' not in pack and 'model' in pack:
            model_obj = pack.pop('model')
            pack['ipadapter'] = {'model': model_obj}

        # Ensure 'ipadapter' is a dict with at least 'model'
        if 'ipadapter' not in pack or not isinstance(pack['ipadapter'], dict):
            pack['ipadapter'] = {'model': pack.get('ipadapter')}

        if pack['ipadapter'].get('model') is None:
            for k in ('ipadapter_model', 'adapter', 'net', 'module', 'model_raw'):
                if k in pack['ipadapter'] and pack['ipadapter'][k] is not None:
                    pack['ipadapter']['model'] = pack['ipadapter'][k]
                    break
            if pack['ipadapter'].get('model') is None:
                maybe = getattr(pack['ipadapter'], 'model', None)
                pack['ipadapter']['model'] = maybe or pack['ipadapter']

        # Find image projection(s) across variants
        def _find_proj(m):
            if not isinstance(m, dict):
                return None
            for k in ('image_proj', 'image_proj_model', 'image_proj_state',
                      'proj', 'proj_model', 'proj_state', 'proj_sd', 'proj_dict'):
                if k in m and m[k] is not None:
                    return m[k]
            return None

        proj = _find_proj(pack) or _find_proj(pack.get('ipadapter', {}))
        proj_lite = pack.get('image_proj_lite') or _find_proj({'image_proj_lite': pack.get('image_proj_lite')})

        if proj is None:
            proj = {}
        if proj_lite is None:
            proj_lite = {}

        pack['image_proj'] = proj
        pack['image_proj_lite'] = proj_lite

        # Some plugins expect projections also under pack['ipadapter'] — mirror them
        if isinstance(pack['ipadapter'], dict):
            pack['ipadapter'].setdefault('image_proj', pack['image_proj'])
            pack['ipadapter'].setdefault('image_proj_lite', pack['image_proj_lite'])

        # Prepare 'ip_adapter' (state dict) for IPAdapterAdvanced compatibility
        ip_sd = None
        # 1) if loader already provided it
        if isinstance(pack.get('ip_adapter'), dict):
            ip_sd = pack['ip_adapter']
        elif isinstance(pack['ipadapter'].get('ip_adapter'), dict):
            ip_sd = pack['ipadapter']['ip_adapter']
        else:
            # 2) attempt to extract from model.state_dict()
            model_obj = pack['ipadapter'].get('model')
            try:
                if model_obj is not None and hasattr(model_obj, 'state_dict'):
                    sd = model_obj.state_dict()
                    if sd is not None:
                        ip_sd = dict(sd)
            except Exception:
                ip_sd = None

        if ip_sd is None:
            ip_sd = {}

        pack['ip_adapter'] = ip_sd
        pack['ipadapter']['ip_adapter'] = ip_sd

        # CPU best-effort move
        if device == "cpu" and torch is not None:
            try:
                model_obj = pack['ipadapter'].get('model', None)
                if hasattr(model_obj, "to"):
                    model_obj.to(torch.device("cpu"))
                elif hasattr(model_obj, "model") and hasattr(model_obj.model, "to"):
                    model_obj.model.to(torch.device("cpu"))
            except Exception:
                pass

        return (pack,)

    # --- Upscale Model -----------------------------------------------------
    @staticmethod
    def _load_upscale(model_name: str, device: str = "default"):
        if not model_name or model_name == "none":
            return (None,)

        if get_full_path_or_raise is None or comfy_utils is None:
            print("[Unified Loader] Upscale loader: missing comfy utils/paths.")
            return (None,)

        # 1) Resolve model path
        try:
            model_path = get_full_path_or_raise("upscale_models", model_name)
        except Exception as e:
            print(f"[Unified Loader] Upscale loader: path error: {e}")
            return (None,)

        # 2) Try to locate ModelLoader/ImageModelDescriptor across versions
        ImageModelDescriptor_ = None
        ModelLoader_ = None
        try:
            from comfy_extras.nodes_upscale_model import ImageModelDescriptor as IMD1, ModelLoader as ML1
            ImageModelDescriptor_, ModelLoader_ = IMD1, ML1
        except Exception:
            try:
                from comfy_extras.nodes_model_loader import ImageModelDescriptor as IMD2, ModelLoader as ML2
                ImageModelDescriptor_, ModelLoader_ = IMD2, ML2
            except Exception:
                try:
                    from comfy_extras.nodes.upscale_model import ImageModelDescriptor as IMD3, ModelLoader as ML3
                    ImageModelDescriptor_, ModelLoader_ = IMD3, ML3
                except Exception:
                    pass

        out = None
        try:
            if ModelLoader_ is not None:
                ml = ModelLoader_()

                # A) Attempt direct file load
                try:
                    out = ml.load(model_path)
                except Exception as e1:
                    print(f"[Unified Loader] upscale load(model_path) failed: {e1}")

                # B) If that fails — build from state_dict
                if out is None:
                    try:
                        sd = comfy_utils.load_torch_file(model_path, safe_load=True)
                        if isinstance(sd, dict) and "module.layers.0.residual_group.blocks.0.norm1.weight" in sd:
                            sd = comfy_utils.state_dict_prefix_replace(sd, {"module.": ""})
                        out = ml.load_from_state_dict(sd)
                    except Exception as e2:
                        print(f"[Unified Loader] upscale load_from_state_dict failed: {e2}")
            else:
                print("[Unified Loader] Upscale loader: ModelLoader not available.")
                return (None,)

            if isinstance(out, tuple):
                out = next((x for x in out if x is not None), None)

            if out is None:
                print("[Unified Loader] Upscale loader: loader returned None.")
                return (None,)

            try:
                if hasattr(out, "eval"):
                    out = out.eval()
                elif hasattr(out, "model") and hasattr(out.model, "eval"):
                    out.model.eval()
            except Exception:
                pass

        except Exception as e:
            print(f"[Unified Loader] upscale load error: {e}")
            return (None,)

        # CPU handling (best-effort)
        if device == "cpu" and torch is not None:
            cpu = torch.device("cpu")
            try:
                if hasattr(out, "to"):
                    out.to(cpu)
                elif hasattr(out, "model") and hasattr(out.model, "to"):
                    out.model.to(cpu)
            except Exception:
                pass

        return (out,)

    # --- ControlNet --------------------------------------------------------
    @staticmethod
    def _load_controlnet(control_net_name: str, device: str = "default"):
        if not control_net_name or control_net_name == "none":
            return (None,)
        if get_full_path_or_raise is None or comfy_controlnet is None:
            print("[Unified Loader] ControlNet loader not available.")
            return (None,)

        try:
            controlnet_path = get_full_path_or_raise("controlnet", control_net_name)
            controlnet = comfy_controlnet.load_controlnet(controlnet_path)
        except Exception as e:
            print(f"[Unified Loader] controlnet load error: {e}")
            return (None,)

        if controlnet is None:
            print("[Unified Loader] ERROR: controlnet file invalid.")
            return (None,)

        # CPU handling (best-effort)
        if device == "cpu" and torch is not None:
            cpu = torch.device("cpu")
            if mm is not None and hasattr(mm, "ModelPatcher"):
                try:
                    controlnet = mm.ModelPatcher(controlnet, load_device=cpu, offload_device=cpu)
                except Exception:
                    try:
                        controlnet.to(cpu)
                    except Exception:
                        pass
            else:
                try:
                    controlnet.to(cpu)
                except Exception:
                    pass

        return (controlnet,)

    @classmethod
    def INPUT_TYPES(cls):
        lists = {label: _with_none(_list_files(FOLDER_KEYS[label])) for label in TYPE_LABELS}
        ipadapter_list = _with_none(_list_files("ipadapter"))
        return {
            "required": {
                # Global device toggle (used by internal loaders)
                "device_cpu": ("BOOLEAN", {"default": False, "label": "Device: CPU (toggle)"}),

                # Model selectors
                "checkpoint": (lists["Load Checkpoint"], {"default": "none", "label": "Checkpoint"}),
                "diffusion": (lists["Load Diffusion Model"], {"default": "none", "label": "Diffusion"}),
                "vae": (lists["Load VAE"], {"default": "none", "label": "VAE"}),
                "clip_1": (lists["Load CLIP"], {"default": "none", "label": "CLIP_1"}),
                "clip_2": (lists["Load CLIP"], {"default": "none", "label": "CLIP_2"}),
                "clip_3": (lists["Load CLIP"], {"default": "none", "label": "CLIP_3"}),
                "clip_vision": (lists["Load CLIP Vision"], {"default": "none", "label": "CLIP Vision"}),
                "controlnet": (lists["Load ControlNet Model"], {"default": "none", "label": "ControlNet"}),
                "ipadapter": (ipadapter_list, {"default": "none", "label": "IPAdapter"}),
                "upscale": (lists["Load Upscale Model"], {"default": "none", "label": "Upscale"}),

                # Divider as dropdown (single, disabled option)
                "models_options": (["——  MODELS OPTIONS  ——"], {
                    "default": "——  MODELS OPTIONS  ——",
                    "label": "MODELS OPTIONS",
                    "tooltip": "UI divider — inactive",
                    "disabled": True,
                }),

                # Types
                "clip_type": (CLIP_TYPES, {"default": "stable_diffusion", "label": "Clip_type"}),
                "diffusion_type": (
                    ["default", "fp8_e4m3fn", "fp8_e4m3fn_fast", "fp8_e5m2"],
                    {"default": "default", "label": "Diffusion_type"},
                ),
            }
        }

    # IPADAPTER precedes UPSCALE_MODEL in the tuple
    RETURN_TYPES = ("MODEL", "CLIP", "VAE", "DIFFUSION_MODEL", "CLIP", "VAE", "CLIP_VISION", "CONTROL_NET", "IPADAPTER", "UPSCALE_MODEL")
    RETURN_NAMES = ("CP_MODEL", "CP_CLIP", "CP_VAE", "DIFFUSION_MODEL", "CLIP", "VAE", "CLIP_VISION", "CONTROLNET", "IPADAPTER", "UPSCALE_MODEL")
    FUNCTION = "run"

    @classmethod
    def IS_CHANGED(cls, **kwargs):
        return ";".join(f"{k}={v}" for k, v in sorted(kwargs.items()))

    def run(self,
            device_cpu: bool,
            checkpoint: str,
            diffusion: str,
            vae: str,
            clip_1: str,
            clip_2: str,
            clip_3: str,
            clip_vision: str,
            controlnet: str,
            ipadapter: str,
            upscale: str,
            models_options: str,
            clip_type: str,
            diffusion_type: str,
            ):
        CP_MODEL = CP_CLIP = CP_VAE = DIFFUSION_MODEL = CLIP = VAE = CLIP_VISION = CONTROLNET = IPADAPTER = UPSCALE_MODEL = None

        device = "cpu" if device_cpu else "default"

        # Checkpoint → CP_MODEL/CP_CLIP/CP_VAE
        if checkpoint and checkpoint != "none":
            try:
                m, c, v = self._load_checkpoint(checkpoint, device=device)
                CP_MODEL, CP_CLIP, CP_VAE = m, c, v
            except Exception as e:
                print(f"[Unified Loader] checkpoint load error: {e}")

        # CLIP (dual/triple) → CLIP
        if (clip_1 and clip_1 != "none") or (clip_2 and clip_2 != "none") or (clip_3 and clip_3 != "none"):
            try:
                (c2,) = self._load_clip(
                    clip_names=[clip_1, clip_2, clip_3],
                    type=clip_type or "stable_diffusion",
                    device=device,
                )
                CLIP = c2
            except Exception as e:
                print(f"[Unified Loader] clip load error: {e}")

        # VAE → VAE
        if vae and vae != "none":
            try:
                (v2,) = self._load_vae(vae_name=vae, device=device)
                VAE = v2
            except Exception as e:
                print(f"[Unified Loader] vae load error: {e}")

        # UNet (Diffusion) → DIFFUSION_MODEL
        if diffusion and diffusion != "none":
            try:
                (dm,) = self._load_unet(unet_name=diffusion, weight_dtype=diffusion_type, device=device)
                DIFFUSION_MODEL = dm
            except Exception as e:
                print(f"[Unified Loader] unet load error: {e}")

        # CLIP Vision → CLIP_VISION
        if clip_vision and clip_vision != "none":
            try:
                (cv,) = self._load_clip_vision(clip_name=clip_vision, device=device)
                CLIP_VISION = cv
            except Exception as e:
                print(f"[Unified Loader] clip_vision load error: {e}")

        # ControlNet → CONTROLNET
        if controlnet and controlnet != "none":
            try:
                (cn,) = self._load_controlnet(control_net_name=controlnet, device=device)
                CONTROLNET = cn
            except Exception as e:
                print(f"[Unified Loader] controlnet load error: {e}")

        # IP-Adapter → IPADAPTER
        if ipadapter and ipadapter != "none":
            try:
                (ipa,) = self._load_ipadapter(ipadapter_file=ipadapter, device=device)
                IPADAPTER = ipa
            except Exception as e:
                print(f"[Unified Loader] ipadapter load error: {e}")

        # Upscale → UPSCALE_MODEL
        if upscale and upscale != "none":
            try:
                (um,) = self._load_upscale(model_name=upscale, device=device)
                UPSCALE_MODEL = um
            except Exception as e:
                print(f"[Unified Loader] upscale load error: {e}")

        return (CP_MODEL, CP_CLIP, CP_VAE, DIFFUSION_MODEL, CLIP, VAE, CLIP_VISION, CONTROLNET, IPADAPTER, UPSCALE_MODEL)


# --- MINI NODE ----------------------------------------------------------------------------------
class UnifiedLoaderMini:
    CATEGORY = "PG"
    NODE_DISPLAY_NAME = "Unified Loader (mini)"

    @classmethod
    def INPUT_TYPES(cls):
        lists = {label: _with_none(_list_files(FOLDER_KEYS[label])) for label in TYPE_LABELS}
        ipadapter_list = _with_none(_list_files("ipadapter"))
        return {
            "required": {
                "device_cpu": ("BOOLEAN", {"default": False, "label": "Device: CPU (toggle)"}),

                "checkpoint":  (lists["Load Checkpoint"],       {"default": "none", "label": "Checkpoint"}),
                "clip_vision": (lists["Load CLIP Vision"],      {"default": "none", "label": "CLIP Vision"}),
                "controlnet":  (lists["Load ControlNet Model"], {"default": "none", "label": "ControlNet"}),
                "ipadapter":   (ipadapter_list,                  {"default": "none", "label": "IPAdapter"}),
                "upscale":     (lists["Load Upscale Model"],    {"default": "none", "label": "Upscale"}),
            }
        }

    RETURN_TYPES = ("MODEL", "CLIP", "VAE", "CONTROL_NET", "IPADAPTER", "UPSCALE_MODEL", "CLIP_VISION")
    RETURN_NAMES = ("CP_MODEL", "CP_CLIP", "CP_VAE", "CONTROLNET", "IPADAPTER", "UPSCALE_MODEL", "CLIP_VISION")
    FUNCTION = "run"

    @classmethod
    def IS_CHANGED(cls, **kwargs):
        return ";".join(f"{k}={v}" for k, v in sorted(kwargs.items()))

    def run(self,
            device_cpu: bool,
            checkpoint: str,
            clip_vision: str,
            controlnet: str,
            ipadapter: str,
            upscale: str,
            ):
        CP_MODEL = CP_CLIP = CP_VAE = CONTROLNET = IPADAPTER = UPSCALE_MODEL = CLIP_VISION = None
        device = "cpu" if device_cpu else "default"

        # Checkpoint → CP_MODEL/CP_CLIP/CP_VAE
        if checkpoint and checkpoint != "none":
            try:
                m, c, v = PgUnifiedLoader._load_checkpoint(ckpt_name=checkpoint, device=device)
                CP_MODEL, CP_CLIP, CP_VAE = m, c, v
            except Exception as e:
                print(f"[Unified Loader (mini)] checkpoint load error: {e}")

        # CLIP Vision
        if clip_vision and clip_vision != "none":
            try:
                (cv,) = PgUnifiedLoader._load_clip_vision(clip_name=clip_vision, device=device)
                CLIP_VISION = cv
            except Exception as e:
                print(f"[Unified Loader (mini)] clip_vision load error: {e}")

        # ControlNet
        if controlnet and controlnet != "none":
            try:
                (cn,) = PgUnifiedLoader._load_controlnet(control_net_name=controlnet, device=device)
                CONTROLNET = cn
            except Exception as e:
                print(f"[Unified Loader (mini)] controlnet load error: {e}")

        # IP-Adapter
        if ipadapter and ipadapter != "none":
            try:
                (ipa,) = PgUnifiedLoader._load_ipadapter(ipadapter_file=ipadapter, device=device)
                IPADAPTER = ipa
            except Exception as e:
                print(f"[Unified Loader (mini)] ipadapter load error: {e}")

        # Upscale
        if upscale and upscale != "none":
            try:
                (um,) = PgUnifiedLoader._load_upscale(model_name=upscale, device=device)
                UPSCALE_MODEL = um
            except Exception as e:
                print(f"[Unified Loader (mini)] upscale load error: {e}")

        return (CP_MODEL, CP_CLIP, CP_VAE, CONTROLNET, IPADAPTER, UPSCALE_MODEL, CLIP_VISION)


# Node registry -----------------------------------------------------------------------------------
NODE_CLASS_MAPPINGS = {
    "PgUnifiedLoader": PgUnifiedLoader,
    "UnifiedLoaderMini": UnifiedLoaderMini,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "PgUnifiedLoader": PgUnifiedLoader.NODE_DISPLAY_NAME,
    "UnifiedLoaderMini": UnifiedLoaderMini.NODE_DISPLAY_NAME,
}
