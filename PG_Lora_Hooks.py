"""
ComfyUI — PG LoRA Hooks (bundle)

This module provides a compact, interoperable toolkit for applying LoRA to
both the MODEL (UNet) and CLIP paths in ComfyUI. It includes a lightweight
LoRA bridge loader, hook builders for MODEL/CLIP/both, non‑destructive hook
application nodes, merge (bake‑in) nodes, and a small keyframe utility.

Typical wiring
--------------
MODEL path:  Checkpoint/Diffusion → Set Model Hooks (LoRA) → Flux Guidance → Sampler
CLIP path:   CLIP Loader → Set CLIP Hooks (LoRA) → Prompt Encoding → Sampler

Design notes
------------
- Hook application is cloned/merged to avoid shared‑state side effects.
- Fallbacks are included so nodes remain usable when a local hooks.py helper
  is not present; comfy.hooks APIs are used when available.
- Keyframe utility preserves ascending levels by swapping levels and triggers
  if needed.

Author: Piotr Gredka & GPT
License: MIT
"""


from __future__ import annotations
from typing import List, Dict, Any, Optional

try:
    import hooks as pg_hooks
except Exception:
    pg_hooks = None

try:
    import torch
except Exception:
    torch = None

try:
    from .hooks import set_hooks_for_clip, _hooks_is_effective, _ensure_hooks
except Exception:
    try:
        from hooks import set_hooks_for_clip, _hooks_is_effective, _ensure_hooks
    except Exception:
        set_hooks_for_clip = None
        def _hooks_is_effective(h) -> bool:
            try:
                return bool(h) and (getattr(h, "is_effective", None)() if hasattr(h, "is_effective") else True)
            except Exception:
                return bool(h)
        def _ensure_hooks(h):
            return h

try:
    _ = set_hooks_for_clip
except NameError:
    set_hooks_for_clip = None

if set_hooks_for_clip is None:
    def set_hooks_for_clip(clip, hooks, append_hooks: bool = True):  # type: ignore
        """Minimal local implementation using comfy.hooks APIs.
        Ensures hooks affect both CLIP's internal patches **and** text encodings.

        Behaviour:
        - If append_hooks=True, merges existing `clip.patcher.forced_hooks` with `hooks`.
        - Sets `clip.apply_hooks_to_conds = hooks` so token encodings are modified.
        - Disables scheduling (use_clip_schedule=False) and clears keyframes, like SetClipHooks.
        - Registers patches against the CLIP target.
        """
        # Safety: if comfy.hooks isn't available, do passthrough
        if 'comfy_hooks' not in globals() or comfy_hooks is None or hooks is None:
            return clip

        # clone CLIP to avoid in-place mutation
        c = clip.clone() if hasattr(clip, 'clone') else clip

        # clone hooks if possible (prevents shared-state side effects)
        new_hooks = hooks.clone() if hasattr(hooks, 'clone') else hooks

        # append/merge with any existing forced hooks on this CLIP
        if append_hooks:
            try:
                prev = getattr(c.patcher, 'forced_hooks', None)
            except Exception:
                prev = None
            if prev is not None:
                try:
                    new_hooks = comfy_hooks.HookGroup.combine_all_hooks([prev, new_hooks])
                except Exception:
                    # if combine fails, just prefer new_hooks
                    pass

        try:
            # 1) make hooks impact encoders
            setattr(c, 'apply_hooks_to_conds', new_hooks)

            # 2) set forced hooks & disable scheduling
            c.patcher.forced_hooks = new_hooks
            c.use_clip_schedule = False
            try:
                c.patcher.forced_hooks.set_keyframes_on_hooks(None)
            except Exception:
                pass

            # 3) register patches for CLIP target
            c.patcher.register_all_hook_patches(
                new_hooks,
                comfy_hooks.create_target_dict(comfy_hooks.EnumWeightTarget.Clip)
            )
        except Exception:
            # on any unexpected issue, fall back to passthrough to keep graphs running
            return clip
        return c

try:
    from folder_paths import get_filename_list, get_full_path_or_raise
    import comfy.sd as comfy_sd
    import comfy.utils as comfy_utils
    import comfy.hooks as comfy_hooks
except Exception as e:
    get_filename_list = None
    get_full_path_or_raise = None
    comfy_sd = None
    comfy_utils = None
    comfy_hooks = None
    print("[LoRA Bridge] Warning: ComfyUI modules not available:", e)


# ---Helpers----------------------------------------------------------------------------------------------

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

def _lora_to_cpu(obj):
    """Best‑effort move of a LoRA object or raw state_dict to CPU."""
    try:
        if torch is None:
            return obj
        # Try module-like .to('cpu') first
        if hasattr(obj, "to"):
            try:
                return obj.to("cpu")
            except Exception:
                pass
        # Fallback for raw state_dicts
        if isinstance(obj, dict):
            for k, v in list(obj.items()):
                if hasattr(v, "to"):
                    try:
                        obj[k] = v.to("cpu")
                    except Exception:
                        pass
        return obj
    except Exception:
        return obj

def _load_lora(lora_name: str, device: str = "default"):
    """Load a LoRA by file name from the "loras" folder.
    Returns (lora_obj,) or (None,).
    """
    try:
        if not lora_name or lora_name == "none":
            return (None,)
        if get_full_path_or_raise is None:
            return (None,)
        lora_path = get_full_path_or_raise("loras", lora_name)
    except Exception as e:
        print(f"[LoRA Bridge] lora path error: {e}")
        return (None,)

    lora_obj = None

    # Preferred: comfy_sd.load_lora
    try:
        if comfy_sd is not None and hasattr(comfy_sd, 'load_lora'):
            lora_obj = comfy_sd.load_lora(lora_path)
            if isinstance(lora_obj, tuple):
                lora_obj = next((x for x in lora_obj if x is not None), None)
    except Exception as e:
        print(f"[LoRA Bridge] comfy_sd.load_lora error: {e}")
        lora_obj = None

    # Fallback: raw state_dict
    if lora_obj is None:
        try:
            if comfy_utils is not None:
                lora_obj = comfy_utils.load_torch_file(lora_path, safe_load=True)
            else:
                import torch as _torch
                map_loc = 'cpu' if device == 'cpu' else None
                lora_obj = _torch.load(lora_path, map_location=map_loc) if map_loc else _torch.load(lora_path)
        except Exception as e:
            print(f"[LoRA Bridge] raw load error: {e}")
            lora_obj = None

    if lora_obj is None:
        print("[LoRA Bridge] ERROR: LoRA file invalid or unsupported format.")
        return (None,)

    if device == "cpu":
        lora_obj = _lora_to_cpu(lora_obj)

    return (lora_obj,)

def _hooks_is_effective(h) -> bool:
    try:
        if h is None:
            return False
        if hasattr(h, 'is_empty') and callable(h.is_empty):
            return not h.is_empty()
        if hasattr(h, '__len__'):
            try:
                if len(h) == 0:
                    return False
            except Exception:
                pass
        if hasattr(h, 'hooks') and hasattr(h.hooks, '__len__'):
            if len(h.hooks) == 0:
                return False
        if hasattr(h, 'to_dict') and callable(h.to_dict):
            d = h.to_dict()
            if isinstance(d, dict):
                items = d.get('items') or d.get('hooks') or []
                if not items:
                    return False
        return True
    except Exception:
        return True

def _bridge_pick_clip(bridge: Dict[str, Any], slot_index: int):
    try:
        if not bridge or bridge.get("type") != "LORA_BRIDGE":
            return None
        items = bridge.get("items") or []
        if 1 <= slot_index <= len(items):
            return items[slot_index - 1].get("clip")
        return None
    except Exception:
        return None

def _bridge_pick_model(bridge: Dict[str, Any], slot_index: int):
    try:
        if not bridge or bridge.get("type") != "LORA_BRIDGE":
            return None
        items = bridge.get("items") or []
        if 1 <= slot_index <= len(items):
            return items[slot_index - 1].get("model")
        return None
    except Exception:
        return None


# ---Main node----------------------------------------------------------------------------------------------

class PgLoraBridgeLoader:

    @classmethod
    def INPUT_TYPES(cls):
        lora_list = _with_none(_list_files("loras"))
        return {
            "required": {
                "device_cpu": ("BOOLEAN", {"default": False, "label": "Device: CPU (toggle)"}),
                "lora1": (lora_list, {"default": "none", "label": "LoRA #1"}),
                "lora2": (lora_list, {"default": "none", "label": "LoRA #2"}),
                "lora3": (lora_list, {"default": "none", "label": "LoRA #3"}),
                "lora4": (lora_list, {"default": "none", "label": "LoRA #4"}),
            }
        }

    # Single packed output for downstream selection/switching
    RETURN_TYPES = ("LORA_BRIDGE",)
    RETURN_NAMES = ("LORA_BRIDGE",)
    CATEGORY = "PG/Lora"
    FUNCTION = "run"

    @classmethod
    def IS_CHANGED(cls, **kwargs):
        # Keep it cache-friendly but sensitive to menu choices and CPU toggle
        keys = [
            str(kwargs.get("device_cpu", False)),
            str(kwargs.get("lora1", "none")),
            str(kwargs.get("lora2", "none")),
            str(kwargs.get("lora3", "none")),
            str(kwargs.get("lora4", "none")),
        ]
        return ";".join(keys)

    def run(self, device_cpu: bool, lora1: str, lora2: str, lora3: str, lora4: str):
        device = "cpu" if device_cpu else "default"
        names = [lora1, lora2, lora3, lora4]
        items = []

        for idx, name in enumerate(names, start=1):
            model = clip = None
            if name and name != "none":
                try:
                    (obj,) = _load_lora(name, device=device)
                    if obj is not None:
                        # For LoRA, MODEL and CLIP share the same backing object
                        model, clip = obj, obj
                except Exception as e:
                    print(f"[LoRA Bridge] lora{idx} load error: {e}")

            items.append({
                "index": idx,
                "name": name or "none",
                "model": model,
                "clip": clip,
            })

        bridge: Dict[str, Any] = {
            "type": "LORA_BRIDGE",
            "device": device,
            "count": len(items),
            "items": items,
        }

        return (bridge,)

# Create Hook (CLIP‑only) from LORA_BRIDGE
class PgCreateHookLoraClipOnly:

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "lora_bridge": ("LORA_BRIDGE",),
                "which_lora": (("lora_1", "lora_2", "lora_3", "lora_4"), {"default": "lora_1"}),
                "strength_clip": ("FLOAT", {"default": 1.0, "min": -20.0, "max": 20.0, "step": 0.01}),
            },
            "optional": {
                "prev_hooks": ("HOOKS",),
            },
        }

    RETURN_TYPES = ("HOOKS",)
    CATEGORY = "PG/Lora"
    FUNCTION = "create_hook"

    @classmethod
    def IS_CHANGED(cls, **kwargs):
        # Cache key based on slot and strength (bridge is a structure; Comfy will handle changes upstream)
        return f"{kwargs.get('which_lora','lora_1')};{float(kwargs.get('strength_clip',1.0)):.4f}"

    def create_hook(self, lora_bridge: Dict[str, Any], which_lora: str, strength_clip: float, prev_hooks=None):
        # Validate comfy_hooks availability
        if 'comfy_hooks' not in globals() or comfy_hooks is None:
            raise RuntimeError("comfy.hooks module unavailable")

        # Initialize / clone hooks chain
        if prev_hooks is None:
            prev_hooks = comfy_hooks.HookGroup()
        prev_hooks.clone()

        # Early exit if nothing to apply
        if strength_clip == 0:
            return (prev_hooks,)

        # Map option to index 1..4
        slot = {"lora_1": 1, "lora_2": 2, "lora_3": 3, "lora_4": 4}.get(which_lora, 1)
        lora_clip = _bridge_pick_clip(lora_bridge, slot)

        if lora_clip is None:
            return (prev_hooks,)

        # Create LoRA hooks with model part disabled
        hooks = comfy_hooks.create_hook_lora(
            lora=lora_clip,
            strength_model=0.0,
            strength_clip=float(strength_clip),
        )
        return (prev_hooks.clone_and_combine(hooks),)


class PgCreateHookLoraModelOnly:

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "lora_bridge": ("LORA_BRIDGE",),
                "which_lora": (("lora_1", "lora_2", "lora_3", "lora_4"), {"default": "lora_1"}),
                "strength_model": ("FLOAT", {"default": 1.0, "min": -20.0, "max": 20.0, "step": 0.01}),
            },
            "optional": {
                "prev_hooks": ("HOOKS",),
            },
        }

    RETURN_TYPES = ("HOOKS",)
    CATEGORY = "PG/Lora"
    FUNCTION = "create_hook"

    @classmethod
    def IS_CHANGED(cls, **kwargs):
        return f"{kwargs.get('which_lora','lora_1')};{float(kwargs.get('strength_model',1.0)):.4f}"

    def create_hook(self, lora_bridge: Dict[str, Any], which_lora: str, strength_model: float, prev_hooks=None):
        if 'comfy_hooks' not in globals() or comfy_hooks is None:
            raise RuntimeError("comfy.hooks module unavailable")

        if prev_hooks is None:
            prev_hooks = comfy_hooks.HookGroup()
        prev_hooks.clone()

        if strength_model == 0:
            return (prev_hooks,)

        slot = {"lora_1": 1, "lora_2": 2, "lora_3": 3, "lora_4": 4}.get(which_lora, 1)
        lora_model = _bridge_pick_model(lora_bridge, slot)

        if lora_model is None:
            return (prev_hooks,)

        hooks = comfy_hooks.create_hook_lora(
            lora=lora_model,
            strength_model=float(strength_model),
            strength_clip=0.0,
        )
        return (prev_hooks.clone_and_combine(hooks),)


class PgCreateHookLoraBoth:

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "lora_bridge": ("LORA_BRIDGE",),
                "which_lora": (("lora_1", "lora_2", "lora_3", "lora_4"), {"default": "lora_1"}),
                "strength_model": ("FLOAT", {"default": 1.0, "min": -20.0, "max": 20.0, "step": 0.01}),
                "strength_clip": ("FLOAT", {"default": 1.0, "min": -20.0, "max": 20.0, "step": 0.01}),
            },
            "optional": {
                "prev_hooks": ("HOOKS",),
            },
        }

    RETURN_TYPES = ("HOOKS",)
    CATEGORY = "PG/Lora"
    FUNCTION = "create_hook"

    @classmethod
    def IS_CHANGED(cls, **kwargs):
        return (
            f"{kwargs.get('which_lora','lora_1')};"
            f"m={float(kwargs.get('strength_model',1.0)):.4f};"
            f"c={float(kwargs.get('strength_clip',1.0)):.4f}"
        )

    def create_hook(self, lora_bridge: Dict[str, Any], which_lora: str,
                    strength_model: float, strength_clip: float, prev_hooks=None):
        if 'comfy_hooks' not in globals() or comfy_hooks is None:
            raise RuntimeError("comfy.hooks module unavailable")

        if prev_hooks is None:
            prev_hooks = comfy_hooks.HookGroup()
        prev_hooks.clone()

        # Early exit if both strengths are zero
        if strength_model == 0 and strength_clip == 0:
            return (prev_hooks,)

        slot = {"lora_1": 1, "lora_2": 2, "lora_3": 3, "lora_4": 4}.get(which_lora, 1)
        # We can take model or clip from the same LoRA object; both refs are valid
        lora_obj = _bridge_pick_model(lora_bridge, slot) or _bridge_pick_clip(lora_bridge, slot)
        if lora_obj is None:
            return (prev_hooks,)

        hooks = comfy_hooks.create_hook_lora(
            lora=lora_obj,
            strength_model=float(strength_model),
            strength_clip=float(strength_clip),
        )
        return (prev_hooks.clone_and_combine(hooks),)


class PgMergeLoraModelOnly:

    @classmethod
    def INPUT_TYPES(s):
        return {
            "required": {
                "model": ("MODEL",),
                "lora_bridge": ("LORA_BRIDGE",),
                "which_lora": (("lora_1", "lora_2", "lora_3", "lora_4"), {"default": "lora_1"}),
                "strength_model": ("FLOAT", {"default": 1.0, "min": -100.0, "max": 100.0, "step": 0.01}),
            }
        }

    RETURN_TYPES = ("MODEL",)
    CATEGORY = "PG/Lora"
    FUNCTION = "merge_lora_model_only"

    @classmethod
    def IS_CHANGED(cls, **kwargs):
        return f"{kwargs.get('which_lora','lora_1')};{float(kwargs.get('strength_model',1.0)):.4f}"

    def merge_lora_model_only(self, model, lora_bridge: Dict[str, Any], which_lora: str, strength_model: float):
        try:
            if strength_model == 0:
                return (model,)
            slot = {"lora_1": 1, "lora_2": 2, "lora_3": 3, "lora_4": 4}.get(which_lora, 1)
            lora_model = _bridge_pick_model(lora_bridge, slot)
            if lora_model is None:
                return (model,)
            patched_model, _ = comfy_sd.load_lora_for_models(model, None, lora_model, float(strength_model), 0.0)
            return (patched_model,)
        except Exception as e:
            print(f"[PgMergeLoraModelOnly] apply error: {e}")
            return (model,)


class PgMergeLoraClipOnly:

    @classmethod
    def INPUT_TYPES(s):
        return {
            "required": {
                "clip": ("CLIP",),
                "lora_bridge": ("LORA_BRIDGE",),
                "which_lora": (("lora_1", "lora_2", "lora_3", "lora_4"), {"default": "lora_1"}),
                "strength_clip": ("FLOAT", {"default": 1.0, "min": -100.0, "max": 100.0, "step": 0.01}),
            }
        }

    RETURN_TYPES = ("CLIP",)
    CATEGORY = "PG/Lora"
    FUNCTION = "merge_lora_clip_only"

    @classmethod
    def IS_CHANGED(cls, **kwargs):
        return f"{kwargs.get('which_lora','lora_1')};{float(kwargs.get('strength_clip',1.0)):.4f}"

    def merge_lora_clip_only(self, clip, lora_bridge: Dict[str, Any], which_lora: str, strength_clip: float):
        try:
            if strength_clip == 0:
                return (clip,)
            slot = {"lora_1": 1, "lora_2": 2, "lora_3": 3, "lora_4": 4}.get(which_lora, 1)
            lora_clip = _bridge_pick_clip(lora_bridge, slot)
            if lora_clip is None:
                return (clip,)
            _, patched_clip = comfy_sd.load_lora_for_models(None, clip, lora_clip, 0.0, float(strength_clip))
            return (patched_clip,)
        except Exception as e:
            print(f"[PgMergeLoraClipOnly] apply error: {e}")
            return (clip,)


class PgMergeLoraBoth:

    @classmethod
    def INPUT_TYPES(s):
        return {
            "required": {
                "model": ("MODEL",),
                "clip": ("CLIP",),
                "lora_bridge": ("LORA_BRIDGE",),
                "which_lora": (("lora_1", "lora_2", "lora_3", "lora_4"), {"default": "lora_1"}),
                "strength_model": ("FLOAT", {"default": 1.0, "min": -100.0, "max": 100.0, "step": 0.01}),
                "strength_clip": ("FLOAT", {"default": 1.0, "min": -100.0, "max": 100.0, "step": 0.01}),
            }
        }

    RETURN_TYPES = ("MODEL", "CLIP")
    RETURN_NAMES = ("model", "clip")
    CATEGORY = "PG/Lora"
    FUNCTION = "merge_lora_both"

    @classmethod
    def IS_CHANGED(cls, **kwargs):
        return (
            f"{kwargs.get('which_lora','lora_1')};"
            f"m={float(kwargs.get('strength_model',1.0)):.4f};"
            f"c={float(kwargs.get('strength_clip',1.0)):.4f}"
        )

    def merge_lora_both(self, model, clip, lora_bridge: Dict[str, Any], which_lora: str,
                         strength_model: float, strength_clip: float):
        try:
            # Early outs
            if (strength_model == 0 and strength_clip == 0):
                return (model, clip)

            slot = {"lora_1": 1, "lora_2": 2, "lora_3": 3, "lora_4": 4}.get(which_lora, 1)
            lora_obj_m = _bridge_pick_model(lora_bridge, slot)
            lora_obj_c = _bridge_pick_clip(lora_bridge, slot)

            # Prefer exact refs; if one is None but the other exists, reuse it (same backing object)
            lora_obj = lora_obj_m or lora_obj_c
            if lora_obj is None:
                return (model, clip)

            patched_model, patched_clip = comfy_sd.load_lora_for_models(
                model, clip, lora_obj, float(strength_model), float(strength_clip)
            )
            return (patched_model, patched_clip)
        except Exception as e:
            print(f"[PgMergeLoraBoth] apply error: {e}")
            return (model, clip)


# ---------- Small compatibility layer ----------
HookKeyframe = None
HookKeyframeGroup = None
set_hooks_for_conditioning = None

if pg_hooks is not None:
    HookKeyframe = pg_hooks.HookKeyframe
    HookKeyframeGroup = pg_hooks.HookKeyframeGroup
    set_hooks_for_conditioning = pg_hooks.set_hooks_for_conditioning
elif comfy_hooks is not None:
    HookKeyframe = comfy_hooks.HookKeyframe
    HookKeyframeGroup = comfy_hooks.HookKeyframeGroup

def _ensure_hooks(hooks):
    if hooks is None:
        if comfy_hooks is None:
            raise RuntimeError("Hooks API unavailable: neither hooks.py nor comfy.hooks present")
        return comfy_hooks.HookGroup()
    return hooks

class PgSetHookKeyframes:

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "hooks": ("HOOKS",),
                "first_level_percent": ("FLOAT", {"default": 0.0, "min": 0.0, "max": 1.0, "step": 0.01}),
                "first_lev_trigger_at": ("FLOAT", {"default": 1.0, "min": -20.0, "max": 20.0, "step": 0.01}),
                "second_level_percent": ("FLOAT", {"default": 1.0, "min": 0.0, "max": 1.0, "step": 0.01}),
                "second_lev_trigger_at": ("FLOAT", {"default": 0.0, "min": -20.0, "max": 20.0, "step": 0.01}),
            }
        }

    RETURN_TYPES = ("HOOKS",)
    CATEGORY = "PG/Lora"
    FUNCTION = "set_keyframes"

    @classmethod
    def IS_CHANGED(cls, **kw):
        return (
            f"{float(kw.get('first_level_percent', 0)):.4f};"
            f"{float(kw.get('second_level_percent', 1)):.4f};"
            f"{float(kw.get('first_lev_trigger_at', 1)):.4f};"
            f"{float(kw.get('second_lev_trigger_at', 0)):.4f}"
        )

    def set_keyframes(self, hooks, **kw: Dict[str, Any]):
        """Create a HookKeyframeGroup using either the new or old param names.
        Supports both:
        - New:  first_level_percent, first_lev_trigger_at, second_level_percent, second_lev_trigger_at
        - Old:  start_percent, strength_start, end_percent, strength_end
        """
        if HookKeyframeGroup is None:
            raise RuntimeError("HookKeyframeGroup unavailable (need hooks.py or comfy.hooks)")

        # --- BEGIN SHIM: map old → new -----------------------------------------------------------
        first_level_percent   = kw.get('first_level_percent',   kw.get('start_percent', 0.0))
        first_lev_trigger_at  = kw.get('first_lev_trigger_at',  kw.get('strength_start', 1.0))
        second_level_percent  = kw.get('second_level_percent',  kw.get('end_percent', 1.0))
        second_lev_trigger_at = kw.get('second_lev_trigger_at', kw.get('strength_end', 0.0))
        # --- END SHIM ---------------------------------------------------------------------------

        hooks = _ensure_hooks(hooks)
        kfg = HookKeyframeGroup()
        GUARANTEE_STEPS = 1

        # clamp levels to [0..1]
        s0 = float(min(max(float(first_level_percent), 0.0), 1.0))
        s1 = float(min(max(float(second_level_percent), 0.0), 1.0))

        t0 = float(first_lev_trigger_at)
        t1 = float(second_lev_trigger_at)

        # keep ascending levels by swapping if needed (plus their triggers)
        if s1 < s0:
            s0, s1 = s1, s0
            t0, t1 = t1, t0

        kfg.add(HookKeyframe(strength=t0, start_percent=s0, guarantee_steps=GUARANTEE_STEPS))
        kfg.add(HookKeyframe(strength=t1, start_percent=s1, guarantee_steps=GUARANTEE_STEPS))

        hooks.set_keyframes_on_hooks(kfg)
        return (hooks,)


class PgSetModelHooks:
    """Apply a HOOKS group onto CONDITIONING (append/replace). Use this to affect the MODEL path.
    Note: This relies on hooks.py's set_hooks_for_conditioning to merge hooks into conditioning dicts.
    """

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "conditioning": ("CONDITIONING",),
                "hooks": ("HOOKS",),
                "append": ("BOOLEAN", {"default": True}),
            }
        }

    RETURN_TYPES = ("CONDITIONING",)
    CATEGORY = "PG/Lora"
    FUNCTION = "apply"

    @classmethod
    def IS_CHANGED(cls, **kw):
        return str(bool(kw.get("append", True)))

    def apply(self, conditioning, hooks, append: bool):
        if set_hooks_for_conditioning is None:
            raise RuntimeError("set_hooks_for_conditioning unavailable (provide hooks.py)")

        if not append:
            return (conditioning,)

        if hooks is None or not _hooks_is_effective(hooks):
            return (conditioning,)

        hooks = _ensure_hooks(hooks)
        out = set_hooks_for_conditioning(conditioning, hooks, append_hooks=True)
        return (out,)

class PgSetClipHooks:
    """Apply a HOOKS group onto CLIP (append/replace). Use this to affect the CLIP path.
    Note: This relies on hooks.py's set_hooks_for_clip to merge hooks into a CLIP object.
    """

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "clip": ("CLIP",),
                "hooks": ("HOOKS",),
                "append": ("BOOLEAN", {"default": True}),
            }
        }

    RETURN_TYPES = ("CLIP",)
    CATEGORY = "PG/Lora"
    FUNCTION = "apply"

    @classmethod
    def IS_CHANGED(cls, **kw):
        # Keep same change signature logic: toggling append flips cache key
        return str(bool(kw.get("append", True)))

    def apply(self, clip, hooks, append: bool):
        if set_hooks_for_clip is None:
            raise RuntimeError("set_hooks_for_clip unavailable (provide hooks.py)")

        # append=False → passthrough (no changes) ALWAYS
        if not append:
            return (clip,)

        # append=True → merge ONLY when hooks are effective (non-empty)
        if hooks is None or not _hooks_is_effective(hooks):
            return (clip,)

        hooks = _ensure_hooks(hooks)
        out = set_hooks_for_clip(clip, hooks, append_hooks=True)
        return (out,)


NODE_CLASS_MAPPINGS = {
    "PgLoraBridgeLoader": PgLoraBridgeLoader,
    "PgCreateHookLoraClipOnly": PgCreateHookLoraClipOnly,
    "PgCreateHookLoraModelOnly": PgCreateHookLoraModelOnly,
    "PgCreateHookLoraBoth": PgCreateHookLoraBoth,
    "PgMergeLoraModelOnly": PgMergeLoraModelOnly,
    "PgMergeLoraClipOnly": PgMergeLoraClipOnly,
    "PgMergeLoraBoth": PgMergeLoraBoth,
    "PgSetHookKeyframes": PgSetHookKeyframes,
    "PgSetClipHooks": PgSetClipHooks,
    "PgSetModelHooks": PgSetModelHooks,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "PgLoraBridgeLoader": "LoRA Bridge Loader",
    "PgCreateHookLoraClipOnly": "Create LoRA Clip Hook",
    "PgCreateHookLoraModelOnly": "Create LoRA Model Hook",
    "PgCreateHookLoraBoth": "Create LoRA Hook",
    "PgMergeLoraModelOnly": "Merge LoRA Model",
    "PgMergeLoraClipOnly": "Merge LoRA Clip",
    "PgMergeLoraBoth": "Merge LoRA",
    "PgSetHookKeyframes": "Set Hook Keyframes",
    "PgSetClipHooks": "Set Clip Hooks",
    "PgSetModelHooks": "Set Model Hooks",
}
