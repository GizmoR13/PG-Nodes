"""
PG Lazy Prompt — ComfyUI nodes & HTTP helpers

This module provides:
- Two ComfyUI nodes: `PgLazyPrompt` and `PgLazyPromptMini`. They convert positive/negative text prompts
  to CONDITIONING via `CLIPTextEncode` and can (optionally) augment text with lens/time/light/temperature
  phrases. Both persist an on-disk JSON prompt history (LRU) and will reuse keys.
- Lightweight HTTP endpoints (`/pg/history/list`, `/pg/history/preview`, `/pg/history/prefs`) for reading
  and configuring history at runtime.
- Config loader (`PG_Lazy_Prompt_Config.json`) with runtime override via env var `PG_CFG_PATH` for maps
  like `POS_LIGHT_MAP`, `NEG_LIGHT_MAP`, `LENS_CHOICES`, `TIME_MAP`.

Author: Piotr Gredka & GPT
License: MIT
"""

from __future__ import annotations
import os, json, time, hashlib, threading
from typing import Any, Dict, List, Tuple
from typing import Tuple as _T_Tuple, Optional as _T_Optional
import random as _rnd

# Try to import rapidfuzz for smart fuzzy search
try:
    from rapidfuzz import fuzz
    _HAS_RAPIDFUZZ = True
except ImportError:
    _HAS_RAPIDFUZZ = False
    fuzz = None

# --- ComfyUI & server imports (optional; tolerate absence during static checks) -----------------
try:
    import nodes
except Exception:
    nodes = None
try:
    from server import PromptServer
    from aiohttp import web
except Exception:
    PromptServer = None
    web = None

PG_ALWAYS_REROLL: bool = True

_SCHEMA_VERSION = 1
_HIST_LOCK = threading.Lock()
_PREFS_LOCK = threading.Lock()
_RUNTIME_PREFS = {
    "history_path": "custom_nodes\\prompt_history.json",
    "max_entries": 500,
}

# === Helpers ====================================================================================

def _resolve_cfg_path() -> str:
    """Resolve path to JSON config with maps (env `PG_CFG_PATH` has priority)."""
    env = os.environ.get("PG_CFG_PATH")
    if env:
        return os.path.abspath(env)
    here = os.path.dirname(os.path.abspath(__file__))
    cwd  = os.getcwd()
    candidates = [
        os.path.join(here, "PG_Lazy_Prompt_Config.json"),
        os.path.join(cwd,  "custom_nodes", "PG-nodes", "PG_Lazy_Prompt_Config.json"),
        os.path.join(cwd,  "custom_nodes", "PG_Lazy_Prompt_Config.json"),
    ]
    for p in candidates:
        if os.path.isfile(p):
            return p
    return candidates[0]

_CONFIG_JSON_PATH = _resolve_cfg_path()
_CFG_CACHE: Dict[str, Any] = {"mtime": None, "data": None}

# Default values (fallback when the config is missing)
_POS_LIGHT_MAP_DEFAULT = {
    "none": "",
    "front": ["frontlit", "front lighting"],
    "back":  ["backlit", "back lighting"],
    "left":  ["light from left"],
    "right": ["light from right"],
    "top":   ["top light"],
}

_NEG_LIGHT_MAP_DEFAULT = {
    "none": "",
    "front": ["backlighting artifact", "silhouette loss", "underexposed background"],
    "back":  ["harsh front light", "blown highlights", "lens flare", "specular glare"],
    "left":  ["uneven side glare", "shadow banding on right"],
    "right": ["uneven side glare", "shadow banding on left"],
    "top":   ["raccoon eyes", "overhead hotspot"],
}

_LENS_CHOICES_DEFAULT = [
    "none","14mm","24mm","35mm","50mm","85mm","105mm","135mm","200mm","wide-angle","fisheye","macro"
]

_TIME_MAP_DEFAULT = {
    "none": "",
    "morning": "soft morning light",
    "midday": "bright midday light",
    "evening": "warm evening golden hour",
    "night": "low-light nighttime scene",
}


def _safe_json_load(path: str) -> Dict[str, Any]:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return {}
    except Exception as ex:
        print(f"[PG config] JSON parse error in {path}: {ex}")
        return {}


def _load_config_json(force: bool = False) -> Dict[str, Any]:
    path = _CONFIG_JSON_PATH
    try:
        st = os.stat(path)
        mtime = int(st.st_mtime)
    except Exception:
        mtime = None
    if (not force) and (_CFG_CACHE["data"] is not None) and (_CFG_CACHE["mtime"] == mtime):
        return _CFG_CACHE["data"] or {}
    data = _safe_json_load(path)
    _CFG_CACHE["mtime"] = mtime
    _CFG_CACHE["data"] = data
    keys = list(data.keys()) if isinstance(data, dict) else type(data)
    print(f"[PG config] loaded {path} (mtime={mtime}) keys={keys}")
    return data or {}


def _cfg_get_json(name: str, default: Any) -> Any:
    data = _load_config_json()
    try:
        if isinstance(data, dict) and name in data:
            val = data[name]
            if isinstance(default, dict) and isinstance(val, dict):
                return val
            if isinstance(default, (list, tuple)) and isinstance(val, (list, tuple)):
                return list(val)
            return val
    except Exception:
        pass
    return default

# Public vars used by nodes
POS_LIGHT_MAP = _cfg_get_json("POS_LIGHT_MAP", _POS_LIGHT_MAP_DEFAULT)
NEG_LIGHT_MAP = _cfg_get_json("NEG_LIGHT_MAP", _NEG_LIGHT_MAP_DEFAULT)
LENS_CHOICES  = _cfg_get_json("LENS_CHOICES",  _LENS_CHOICES_DEFAULT)
TIME_MAP      = _cfg_get_json("TIME_MAP",      _TIME_MAP_DEFAULT)
TEMP_CHOICES  = ["none"] + [str(k) for k in range(2500, 9001, 500)]


def _normalize_temp_choice(val) -> int | None:
    if val is None:
        return None
    s = str(val).strip().lower()
    if s in ("", "none", "null"):
        return None
    if s.endswith("k"):
        s = s[:-1]
    try:
        n = int(float(s))
        if 1000 <= n <= 20000:
            return n
    except Exception:
        pass
    return None


# Choice randomizer
# Examples:
#        expand_choices("{iron|gold|silver}") -> e.g. "gold"
#        expand_choices("a {red|green|blue{ light| dark}} car") -> e.g. "a blue dark car"
#        expand_choices("brace \\{literal\\}") -> "brace {literal}"

def expand_choices(text: str, seed: _T_Optional[int] = None) -> str:
    rng = _rnd.Random(seed)

    def _grp(s: str, i: int) -> _T_Tuple[str, int]:
        assert s[i] == '{'; i += 1
        parts, cur = [], []
        while i < len(s):
            ch = s[i]
            if ch == '\\':  # ESC: treat next char literally
                i += 1
                if i < len(s):
                    cur.append(s[i])
                    i += 1
                continue
            if ch == '{':
                sub, i = _grp(s, i)
                cur.append(sub)
                continue
            if ch == '|':
                parts.append(''.join(cur)); cur = []; i += 1; continue
            if ch == '}':
                i += 1; parts.append(''.join(cur))
                return (rng.choice(parts) if parts else ''), i
            cur.append(ch); i += 1
        return '{' + ''.join(cur), i

    def _top(s: str, i: int = 0) -> str:
        out = []
        while i < len(s):
            ch = s[i]
            if ch == '\\':  # ESC: treat next char literally
                i += 1
                if i < len(s):
                    out.append(s[i])
                    i += 1
                continue
            if ch == '{':
                sub, i = _grp(s, i)
                out.append(sub)
                continue
            out.append(ch); i += 1
        return ''.join(out)

    return _top(text, 0)


def has_choice_syntax(text: str) -> bool:
    if not text:
        return False
    s = str(text)
    i = 0
    depth = 0
    has_bar_in_group = False
    while i < len(s):
        ch = s[i]
        if ch == '\\':
            i += 2
            continue
        if ch == '{':
            depth += 1
            has_bar_in_group = False
            i += 1
            continue
        if ch == '|':
            if depth > 0:
                has_bar_in_group = True
            i += 1
            continue
        if ch == '}':
            if depth > 0 and has_bar_in_group:
                return True
            depth = max(0, depth - 1)
            has_bar_in_group = False
            i += 1
            continue
        i += 1
    return False


def _get_prefs():
    with _PREFS_LOCK:
        hp = str(_RUNTIME_PREFS.get("history_path", "prompt_history.json") or "prompt_history.json")
        me = int(_RUNTIME_PREFS.get("max_entries", 500) or 500)
        return hp, me


def _as_list(x):
    if not x:
        return []
    if isinstance(x, (list, tuple)):
        return [str(i) for i in x if str(i).strip()]
    return [str(x)]


def _normalize_history_path(p: str) -> str:
    p = os.path.expanduser(p)
    if not os.path.isabs(p):
        base = os.getcwd()
        p = os.path.join(base, p)
    return os.path.abspath(p)


def _read_history(path: str) -> Dict[str, Any]:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {"schema": _SCHEMA_VERSION, "items": []}


def _write_history_atomic(path: str, data: Dict[str, Any]):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write("\n")
    os.replace(tmp, path)


def _compute_key_hash(core: Dict[str, Any]) -> str:
    s = json.dumps(core, sort_keys=True, ensure_ascii=False)
    return hashlib.sha1(s.encode("utf-8")).hexdigest()


def _trim_lru(items: List[Dict[str, Any]], max_entries: int) -> List[Dict[str, Any]]:
    return items[: max(1, int(max_entries))]


def _parse_kh_prefix(s: str) -> str:
    if not s or s == "none":
        return ""
    return s.split(" ", 1)[0].split("—", 1)[0].strip()


def _a_or_an_for_lens(lens: str) -> str:
    return "an" if lens and lens[0].lower() in "aeiou" else "a"


def _normalize_phrases(x: Any) -> List[str]:
    if not x:
        return []
    if isinstance(x, (list, tuple)):
        return [str(i) for i in x if str(i).strip()]
    return [str(x)]


def _weight_each(phrases: List[str], w: float, style: str) -> List[str]:
    if style == "parentheses":
        return [f"({p}:{w:.2f})" for p in phrases]
    elif style == "no_parentheses":
        return [f"{p}:{w:.2f}" for p in phrases]
    return phrases


def _canonical_core(entry: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "positive": str(entry.get("positive") or ""),
        "negative": str(entry.get("negative") or ""),
    }


def _find_by_hash(items: List[Dict[str, Any]], kh: str) -> int:
    for i, e in enumerate(items):
        if e.get("key_hash") == kh:
            return i
    return -1


def _infer_weight_style_from_clip(clip):
    try:
        name = (getattr(clip, '__class__', type(clip)).__name__ or "").lower()

        # 1) SD3 / SD3.5
        sd3_markers = ("sd3", "sd_3", "stable_diffusion_3", "sd3.5", "sd35", "sd_3_5")
        if any(m in name for m in sd3_markers):
            return "none"

        # 2) Tokenizer path (T5 dla SD3/3.5 itd.)
        tok = getattr(clip, "tokenizer", None)
        npath = (getattr(tok, "name_or_path", "") or "").lower()
        if "t5" in npath and any(x in npath for x in ("3", "3.5", "sd3", "sd35")):
            return "none"

        none_markers = (
            "flux",        # cz. Black Forest Labs / Flux
            "mochi",       # pokrewne / warianty
            "qwen",        # Qwen generatywne
            "wan",         # WAN diffusion
            "hidream",     # HiDream
        )
        if any(m in name for m in none_markers) or any(m in npath for m in none_markers):
            return "none"

        return "parentheses"

    except Exception:
        return "parentheses"


# === Classes ====================================================================================

class PgLazyPrompt:

    DESCRIPTION = "Prompt -> CONDITIONING with on-disk JSON history (LRU)."

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "clip": ("CLIP", {}),
                "positive": ("STRING", {"multiline": True, "default": ""}),
                "negative": ("STRING", {"multiline": True, "default": ""}),
                "all_parameters_on": ("BOOLEAN", {"default": True, "label": "All parameters ON"}),
                "lens": (LENS_CHOICES, {"default": "none"}),
                "time_of_day": (list(TIME_MAP.keys()), {"default": "none"}),
                "light_from": (list(POS_LIGHT_MAP.keys()), {"default": "none"}),
                "temperature_K_choice": (TEMP_CHOICES, {"default": "none"}),
                "pos_lighting_boost": ("FLOAT", {"default": 1.0, "min": 1.0, "max": 2.0, "step": 0.05}),
                "neg_lighting_boost": ("FLOAT", {"default": 1.0, "min": 1.0, "max": 2.0, "step": 0.05}),
                "weighting_target_model": (
                    ["auto","parentheses","no_parentheses"],
                    {
                        "default": "auto",
                        "tooltip": "AUTO checks: SD1.5/SDXL -> parentheses; SD3/SD3.5 (T5) & Flux/Qwen/Wan/HiDream -> none (no weights)."
                    }
                ),
            },
            "optional": {}
        }

    RETURN_TYPES  = ("CONDITIONING","CONDITIONING")
    RETURN_NAMES  = ("POS_OUT","NEG_OUT")
    FUNCTION      = "build_encode_and_history"
    CATEGORY      = "PG"
    @classmethod
    def IS_CHANGED(cls, **kwargs):
        if not PG_ALWAYS_REROLL:
            return None
        try:
            positive_val = kwargs.get('positive', '')
        except Exception:
            positive_val = ''
        if has_choice_syntax(positive_val):
            try:
                return time.time_ns()
            except Exception:
                return time.time()
        return None
    OUTPUT_NODE   = True

    def build_encode_and_history(
        self,
        clip,
        positive,
        negative,
        all_parameters_on,
        lens,
        time_of_day,
        light_from,
        temperature_K_choice,
        pos_lighting_boost,
        neg_lighting_boost,
        weighting_target_model,
        history_ui_slot: str = "",
    ):
        _ = history_ui_slot

        positive_orig = (positive or "").strip()
        negative_raw = (negative or "").strip()

        # Reroll seed if enabled (env `PG_REROLL` overrides)
        _reroll = bool(PG_ALWAYS_REROLL)
        try:
            if "PG_REROLL" in os.environ:
                _reroll = bool(int(os.environ.get("PG_REROLL", "0")))
        except Exception:
            pass
        _seed = None
        if _reroll:
            try:
                _seed = time.time_ns() & 0xFFFFFFFF
            except Exception:
                _seed = int(time.time()*1000) & 0xFFFFFFFF
        positive_raw = expand_choices(positive_orig, seed=_seed)

        # Load runtime prefs set via /pg/history/prefs
        _hp, _me = _get_prefs()
        history_path = _normalize_history_path(_hp)
        max_entries = int(_me)
        history = _read_history(history_path)

        if   weighting_target_model == "auto":            style = _infer_weight_style_from_clip(clip)
        elif weighting_target_model == "parentheses":    style = "parentheses"
        elif weighting_target_model == "no_parentheses": style = "no_parentheses"
        else:                                             style = "none"

        if not all_parameters_on:
            pos_text = positive_raw
            neg_text = negative_raw
        else:
            lens_phrase_text = ""
            if lens and lens != "none":
                lens_phrase  = f"{lens} lens"
                lens_phrase_text = f"{_a_or_an_for_lens(lens)} {lens_phrase}"

            pos_phrases = []
            if light_from and light_from != "none":
                pos_phrases = _normalize_phrases(POS_LIGHT_MAP.get(light_from, light_from))
                if pos_phrases and (pos_lighting_boost != 1.0) and (style != "none"):
                    pos_phrases = _weight_each(pos_phrases, float(pos_lighting_boost), style)
            light_phrase = ", ".join(pos_phrases) if pos_phrases else ""

            time_list = _as_list(TIME_MAP.get(time_of_day, ""))
            time_phrase = ", ".join(time_list)
            temp_K = _normalize_temp_choice(temperature_K_choice)
            temp_phrase = f"{temp_K}K white balance" if temp_K is not None else ""

            pos_suffix = ", ".join([p for p in [lens_phrase_text, light_phrase, time_phrase, temp_phrase] if p])
            pos_text   = f"{positive_raw}\n{pos_suffix}" if positive_raw and pos_suffix else (positive_raw or pos_suffix)

            neg_text = negative_raw
            if light_from and light_from != "none":
                neg_list = _normalize_phrases(NEG_LIGHT_MAP.get(light_from, []))
                if neg_list and (float(neg_lighting_boost) > 1.0) and (style != "none"):
                    neg_list = _weight_each(neg_list, float(neg_lighting_boost), style)
                if neg_list:
                    neg_block = ", ".join(neg_list)
                    neg_text = (neg_text + (", " if neg_text and not neg_text.endswith(",") else "") + neg_block) if neg_text else neg_block

        # Encode
        if nodes is None:
            raise RuntimeError("ComfyUI 'nodes' not available")
        pos_cond, = nodes.CLIPTextEncode().encode(clip, pos_text)
        neg_cond, = nodes.CLIPTextEncode().encode(clip, neg_text)

        # History write (skip if both empty)
        key_hash = ""
        if (positive_orig == "" and negative_raw == ""):
            print("[PG history] skip: empty positive & negative; not saving")
        else:
            core = {"positive": positive_orig, "negative": negative_raw}
            key_hash = _compute_key_hash(core)
            now = int(time.time())
            record = {
                "key_hash": key_hash,
                "positive": core["positive"],
                "negative": core["negative"],
                "created_at": now,
                "last_used_at": now,
                "hits": 1,
            }
            with _HIST_LOCK:
                hist = _read_history(history_path)
                items = hist.get("items", [])
                before_len = len(items)
                ix = _find_by_hash(items, key_hash)
                if ix >= 0:
                    old = items.pop(ix)
                    record["created_at"] = int(old.get("created_at", now))
                    record["hits"] = int(old.get("hits", 0)) + 1

                items.insert(0, record)
                items = _trim_lru(items, int(max_entries))
                print(f"[PG history] save: before={before_len} after={len(items)} max_entries={max_entries}")

                hist["items"] = items
                _write_history_atomic(history_path, hist)

        return (pos_cond, neg_cond)


class PgLazyPromptMini:
    DESCRIPTION = "Prompt -> CONDITIONING with on-disk JSON history (LRU). Minimal UI."

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "clip": ("CLIP", {}),
                "positive": ("STRING", {"multiline": True, "default": ""}),
                "negative": ("STRING", {"multiline": True, "default": ""}),
            },
            "optional": {}
        }

    RETURN_TYPES  = ("CONDITIONING","CONDITIONING")
    RETURN_NAMES  = ("POS_OUT","NEG_OUT")
    FUNCTION      = "build_encode_and_history"
    CATEGORY      = "PG"
    OUTPUT_NODE   = True

    @classmethod
    def IS_CHANGED(cls, **kwargs):
        if not PG_ALWAYS_REROLL:
            return None
        try:
            positive_val = kwargs.get('positive', '')
        except Exception:
            positive_val = ''
        if has_choice_syntax(positive_val):
            try:
                return time.time_ns()
            except Exception:
                return time.time()
        return None

    def build_encode_and_history(
        self,
        clip,
        positive,
        negative,
        history_ui_slot: str = "",
    ):
        _ = history_ui_slot

        positive_orig = (positive or "").strip()
        negative_raw  = (negative or "").strip()

        # Reroll seed if enabled (env `PG_REROLL` overrides)
        _reroll = bool(PG_ALWAYS_REROLL)
        try:
            if "PG_REROLL" in os.environ:
                _reroll = bool(int(os.environ.get("PG_REROLL", "0")))
        except Exception:
            pass
        _seed = None
        if _reroll:
            try:
                _seed = time.time_ns() & 0xFFFFFFFF
            except Exception:
                _seed = int(time.time()*1000) & 0xFFFFFFFF
        positive_raw = expand_choices(positive_orig, seed=_seed)

        pos_text = positive_raw
        neg_text = negative_raw

        # Encode
        if nodes is None:
            raise RuntimeError("ComfyUI 'nodes' not available")
        pos_cond, = nodes.CLIPTextEncode().encode(clip, pos_text)
        neg_cond, = nodes.CLIPTextEncode().encode(clip, neg_text)

        # History write (skip if both empty)
        if (positive_orig == "" and negative_raw == ""):
            print("[PG history] skip: empty positive & negative; not saving (mini)")
        else:
            _hp, _me = _get_prefs()
            history_path = _normalize_history_path(_hp)
            max_entries = int(_me)

            core = {"positive": positive_orig, "negative": negative_raw}
            key_hash = _compute_key_hash(core)
            now = int(time.time())

            with _HIST_LOCK:
                hist = _read_history(history_path)
                items = hist.get("items", [])
                before_len = len(items)
                ix = _find_by_hash(items, key_hash)
                old_entry = items.pop(ix) if ix >= 0 else None

                record = _make_history_record(key_hash, positive_orig, negative_raw, now, old_entry)
                items.insert(0, record)
                items = _trim_lru(items, max_entries)
                print(f"[PG history mini] save: before={before_len} after={len(items)} max_entries={max_entries}")

                hist["items"] = items
                _write_history_atomic(history_path, hist)

        return (pos_cond, neg_cond)


class PgLazyPromptExt:
    DESCRIPTION = "Prompt -> CONDITIONING with on-disk JSON history (LRU). Extended out."

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "clip": ("CLIP", {}),
                "positive": ("STRING", {"multiline": True, "default": ""}),
                "negative": ("STRING", {"multiline": True, "default": ""}),
            },
            "optional": {}
        }

    RETURN_TYPES  = ("CONDITIONING","CONDITIONING","STRING","STRING")
    RETURN_NAMES  = ("POS_OUT","NEG_OUT","pos_raw","neg_raw")
    FUNCTION      = "build_encode_and_history"
    CATEGORY      = "PG"
    OUTPUT_NODE   = True

    @classmethod
    def IS_CHANGED(cls, **kwargs):
        if not PG_ALWAYS_REROLL:
            return None
        try:
            positive_val = kwargs.get('positive', '')
        except Exception:
            positive_val = ''
        if has_choice_syntax(positive_val):
            try:
                return time.time_ns()
            except Exception:
                return time.time()
        return None

    def build_encode_and_history(
        self,
        clip,
        positive,
        negative,
        history_ui_slot: str = "",
    ):
        _ = history_ui_slot

        positive_orig = (positive or "").strip()
        negative_raw  = (negative or "").strip()

        # Reroll seed if enabled (env `PG_REROLL` overrides)
        _reroll = bool(PG_ALWAYS_REROLL)
        try:
            if "PG_REROLL" in os.environ:
                _reroll = bool(int(os.environ.get("PG_REROLL", "0")))
        except Exception:
            pass
        _seed = None
        if _reroll:
            try:
                _seed = time.time_ns() & 0xFFFFFFFF
            except Exception:
                _seed = int(time.time()*1000) & 0xFFFFFFFF
        positive_raw = expand_choices(positive_orig, seed=_seed)

        pos_text = positive_raw
        neg_text = negative_raw

        # Encode
        if nodes is None:
            raise RuntimeError("ComfyUI 'nodes' not available")
        pos_cond, = nodes.CLIPTextEncode().encode(clip, pos_text)
        neg_cond, = nodes.CLIPTextEncode().encode(clip, neg_text)

        # History write (skip if both empty)
        if (positive_orig == "" and negative_raw == ""):
            print("[PG history] skip: empty positive & negative; not saving (ext)")
        else:
            _hp, _me = _get_prefs()
            history_path = _normalize_history_path(_hp)
            max_entries = int(_me)

            core = {"positive": positive_orig, "negative": negative_raw}
            key_hash = _compute_key_hash(core)
            now = int(time.time())

            with _HIST_LOCK:
                hist = _read_history(history_path)
                items = hist.get("items", [])
                before_len = len(items)
                ix = _find_by_hash(items, key_hash)
                old_entry = items.pop(ix) if ix >= 0 else None

                record = _make_history_record(key_hash, positive_orig, negative_raw, now, old_entry)
                items.insert(0, record)
                items = _trim_lru(items, max_entries)
                print(f"[PG history ext] save: before={before_len} after={len(items)} max_entries={max_entries}")

                hist["items"] = items
                _write_history_atomic(history_path, hist)

        pos_raw_text = (pos_text).strip()
        neg_raw_text = (neg_text).strip()
        return (pos_cond, neg_cond, pos_raw_text, neg_raw_text)


class PgPromptSimple:
    DESCRIPTION = "Simple prompt node (no CLIP) - outputs strings with on-disk JSON history."

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "positive": ("STRING", {"multiline": True, "default": ""}),
                "negative": ("STRING", {"multiline": True, "default": ""}),
            },
            "optional": {}
        }

    RETURN_TYPES  = ("STRING", "STRING")
    RETURN_NAMES  = ("positive", "negative")
    FUNCTION      = "execute_and_history"
    CATEGORY      = "PG"
    OUTPUT_NODE   = True

    @classmethod
    def IS_CHANGED(cls, **kwargs):
        if not PG_ALWAYS_REROLL:
            return None
        try:
            positive_val = kwargs.get('positive', '')
        except Exception:
            positive_val = ''
        if has_choice_syntax(positive_val):
            try:
                return time.time_ns()
            except Exception:
                return time.time()
        return None

    def execute_and_history(
        self,
        positive,
        negative,
        history_ui_slot: str = "",
    ):
        _ = history_ui_slot

        positive_orig = (positive or "").strip()
        negative_raw  = (negative or "").strip()

        # Reroll seed if enabled (env `PG_REROLL` overrides)
        _reroll = bool(PG_ALWAYS_REROLL)
        try:
            if "PG_REROLL" in os.environ:
                _reroll = bool(int(os.environ.get("PG_REROLL", "0")))
        except Exception:
            pass
        _seed = None
        if _reroll:
            try:
                _seed = time.time_ns() & 0xFFFFFFFF
            except Exception:
                _seed = int(time.time()*1000) & 0xFFFFFFFF
        positive_raw = expand_choices(positive_orig, seed=_seed)

        pos_text = positive_raw
        neg_text = negative_raw

        # History write (skip if both empty)
        if (positive_orig == "" and negative_raw == ""):
            print("[PG history] skip: empty positive & negative; not saving (simple)")
        else:
            _hp, _me = _get_prefs()
            history_path = _normalize_history_path(_hp)
            max_entries = int(_me)

            core = {"positive": positive_orig, "negative": negative_raw}
            key_hash = _compute_key_hash(core)
            now = int(time.time())

            with _HIST_LOCK:
                hist = _read_history(history_path)
                items = hist.get("items", [])
                before_len = len(items)
                ix = _find_by_hash(items, key_hash)
                old_entry = items.pop(ix) if ix >= 0 else None

                record = _make_history_record(key_hash, positive_orig, negative_raw, now, old_entry)
                items.insert(0, record)
                items = _trim_lru(items, max_entries)
                print(f"[PG history simple] save: before={before_len} after={len(items)} max_entries={max_entries}")

                hist["items"] = items
                _write_history_atomic(history_path, hist)

        return (pos_text, neg_text)


NODE_CLASS_MAPPINGS = {
    "PgLazyPrompt": PgLazyPrompt,
    "PgLazyPromptMini": PgLazyPromptMini,
    "PgLazyPromptExt": PgLazyPromptExt,
    "PgPromptSimple": PgPromptSimple,
}
NODE_DISPLAY_NAME_MAPPINGS = {
    "PgLazyPrompt": "Lazy Prompt",
    "PgLazyPromptMini": "Lazy Prompt (mini)",
    "PgLazyPromptExt": "Lazy Prompt (ext)",
    "PgPromptSimple": "Simple Prompt",
}


# === API helpers =================================================================================

def _search_score(query: str, text: str) -> float:
    """
    Smart fuzzy search with multi-term matching and optional typo tolerance.

    Returns a score 0-100:
    - 0 = no match
    - 100 = perfect match
    - Uses rapidfuzz if available for typo tolerance, otherwise falls back to substring matching
    """
    if not query or not text:
        return 100.0

    query_lower = query.lower().strip()
    text_lower = text.lower()

    # Split query into terms
    terms = query_lower.split()
    if not terms:
        return 100.0

    # If only one term, use fuzzy matching
    if len(terms) == 1:
        if _HAS_RAPIDFUZZ and fuzz:
            # Use rapidfuzz partial_ratio for keyword/substring matching with typo tolerance
            return float(fuzz.partial_ratio(query_lower, text_lower))
        else:
            # Fallback: simple substring match
            if query_lower in text_lower:
                return 100.0
            return 0.0

    # Multi-term matching: all terms must be present
    # Split text into words and check if each query term matches any word (with fuzzy matching)
    text_words = text_lower.split()
    term_scores = []

    for term in terms:
        if _HAS_RAPIDFUZZ and fuzz:
            # Find best matching word in text for this term
            best_score = 0.0
            for text_word in text_words:
                # Use token_ratio for word-level comparison
                score = float(fuzz.token_ratio(term, text_word))
                best_score = max(best_score, score)
            term_scores.append(best_score)
        else:
            # Fallback: simple substring match
            score = 100.0 if term in text_lower else 0.0
            term_scores.append(score)

    # All terms must match (minimum 60% for fuzzy word matching)
    min_threshold = 60.0 if _HAS_RAPIDFUZZ else 1.0
    if all(score >= min_threshold for score in term_scores):
        # Return average score of all term matches
        return sum(term_scores) / len(term_scores)
    else:
        return 0.0


def _make_history_record(key_hash: str, positive: str, negative: str, now: int, old_entry: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Create a history record, preserving custom_name and created_at from old entry if it exists."""
    record = {
        "key_hash": key_hash,
        "positive": positive,
        "negative": negative,
        "created_at": now,
        "last_used_at": now,
        "hits": 1,
    }
    if old_entry:
        record["created_at"] = int(old_entry.get("created_at", now))
        record["hits"] = int(old_entry.get("hits", 0)) + 1
        # Preserve custom_name if it exists
        if "custom_name" in old_entry and old_entry.get("custom_name"):
            record["custom_name"] = old_entry.get("custom_name")
    return record


def _history_preview_payload(history_path: str, history_select: str):
    try:
        hp = _normalize_history_path(history_path or "prompt_history.json")
        hist = _read_history(hp)
        kh_pref = _parse_kh_prefix(history_select)
        items = hist.get("items", [])
        for entry in items:
            kh = entry.get("key_hash", "")
            if not kh:
                continue
            if kh_pref and not kh.startswith(kh_pref):
                continue
            core = _canonical_core(entry)
            pos_text = core.get("positive", "")
            neg_text = core.get("negative", "")
            payload = {
                "positive_raw": core.get("positive", ""),
                "negative_raw": core.get("negative", ""),
                "pos_text": pos_text,
                "neg_text": neg_text,
            }
            text = (pos_text + ("\n---\n" + neg_text if neg_text else "")).strip()
            return True, {"preview_text": text, "payload": payload}
        return False, {"error": "not_found", "message": "No history match"}
    except Exception as e:
        return False, {"error": "exception", "message": str(e)}


def _history_list_items(history_path: str, max_entries: int, as_objects: bool = False, search_query: str = ""):
    try:
        hp = _normalize_history_path(history_path or "prompt_history.json")
        hist = _read_history(hp)
        items = hist.get("items", [])
        scored_items: list[tuple[float, dict, str, str]] = []  # (score, item, label, key_hash)

        import time as _t
        MON = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"]

        def _fmt(ts) -> str:
            try:
                if ts is None:
                    return ""
                s = str(ts).strip()
                if not s:
                    return ""
                it = int(float(s))
                if it <= 0:
                    return ""
                lt = _t.localtime(it)
                return f"{lt.tm_mday:02d}{MON[max(0, lt.tm_mon-1)]}{lt.tm_hour:02d}:{lt.tm_min:02d}"
            except Exception:
                return ""

        for e in items[: int(max_entries)]:
            kh  = (e.get("key_hash") or "").strip()
            pos = (e.get("positive") or "").strip()
            neg = (e.get("negative") or "").strip()
            custom_name = (e.get("custom_name") or "").strip()

            # Calculate search score (custom_name weighted higher, then pos, then neg)
            search_query_clean = str(search_query or "").strip()
            if search_query_clean:
                # Score each field and take the best match
                custom_name_score = _search_score(search_query_clean, custom_name) if custom_name else 0.0
                pos_score = _search_score(search_query_clean, pos) if pos else 0.0
                neg_score = _search_score(search_query_clean, neg) if neg else 0.0

                # Weight: custom_name > positive > negative
                score = max(custom_name_score * 1.2, pos_score, neg_score)

                # Skip if score is too low (no match)
                if score < 50.0:
                    continue
            else:
                # No search query: all results shown equally
                score = 100.0

            pos_display = pos.replace("\n", " ")
            neg_display = neg.replace("\n", " ")

            # Display logic: use custom_name if available, else content snippet
            if custom_name:
                text = custom_name
            else:
                text = pos_display if pos_display else (("negative: " + neg_display) if neg_display else "")
                if len(text) > 60:
                    text = text[:60] + "…"

            ts = e.get("last_used_at") or e.get("created_at") or 0
            date_s = _fmt(ts)

            if date_s and text:
                label = f"{date_s} — {text}"
            elif text:
                label = text
            elif kh:
                label = kh[:8]
            else:
                label = ""

            if not label:
                continue

            scored_items.append((score, e, label, kh))

        # Sort by score (descending), then by last_used_at for ties
        scored_items.sort(key=lambda x: (-x[0], -int(x[1].get("last_used_at", 0) or 0)))

        out_strings: list[str] = []
        out_objects: list[dict] = []

        for score, e, label, kh in scored_items:
            custom_name = (e.get("custom_name") or "").strip()
            pos = (e.get("positive") or "").strip()
            neg = (e.get("negative") or "").strip()

            if as_objects:
                out_objects.append({
                    "key_hash": kh,
                    "label_short": label,
                    "custom_name": custom_name,
                    "positive": pos,
                    "negative": neg,
                    "search_score": round(score, 2),
                    "created_at": int(e.get("created_at", 0) or 0),
                    "last_used_at": int(e.get("last_used_at", 0) or 0),
                    "hits": int(e.get("hits", 0) or 0),
                })
            else:
                out_strings.append(label)

        return True, (out_objects if as_objects else out_strings)
    except Exception as ex:
        return False, str(ex)


# ROUTES (single registration; no duplicates)
if PromptServer is not None and web is not None:
    _PG_ROUTES_FLAG = "_pg_history_routes_registered_v2"
    if not getattr(PromptServer.instance, _PG_ROUTES_FLAG, False):
        routes = PromptServer.instance.routes

        @routes.post("/pg/history/list")
        async def pg_history_list(request):
            try:
                data = await request.json()
            except Exception:
                data = {}
            _hp, _me = _get_prefs()
            history_path = data.get("history_path", _hp)
            try:
                if "max_entries" in data:
                    max_entries = int(data.get("max_entries"))
                else:
                    max_entries = int(data.get("topn", _me))
            except Exception:
                max_entries = int(_me)

            as_objects = bool(data.get("objects"))
            search_query = str(data.get("search_query", "")).strip() if "search_query" in data else ""
            ok, res = _history_list_items(history_path, max_entries, as_objects=as_objects, search_query=search_query)
            if ok:
                return web.json_response({"ok": True, "items": res})
            return web.json_response({"ok": False, "error": res})

        @routes.post("/pg/history/preview")
        async def pg_history_preview(request):
            try:
                data = await request.json()
            except Exception:
                data = {}
            _hp, _ = _get_prefs()
            history_path = data.get("history_path", _hp)
            history_select = data.get("history_select", "none")
            if not isinstance(history_path, (str, bytes, bytearray)):
                history_path = str(history_path)
            ok, res = _history_preview_payload(history_path, history_select)
            if ok:
                return web.json_response({"ok": True, **res})
            return web.json_response({"ok": False, **res})

        @routes.post("/pg/history/prefs")
        async def pg_history_prefs(request):
            try:
                data = await request.json()
            except Exception:
                data = {}
            updated = {}
            with _PREFS_LOCK:
                if "history_path" in data:
                    try:
                        hp = str(data.get("history_path") or "").strip()
                        if hp:
                            _RUNTIME_PREFS["history_path"] = hp
                            updated["history_path"] = hp
                    except Exception:
                        pass
                if "max_entries" in data:
                    try:
                        me = int(data.get("max_entries"))
                        if 1 <= me <= 1000:
                            _RUNTIME_PREFS["max_entries"] = me
                            updated["max_entries"] = me
                    except Exception:
                        pass
                snap = dict(_RUNTIME_PREFS)
            return web.json_response({"ok": True, **snap, "updated": updated})

        @routes.post("/pg/history/rename")
        async def pg_history_rename(request):
            try:
                data = await request.json()
            except Exception:
                data = {}
            _hp, _me = _get_prefs()
            history_path = data.get("history_path", _hp)
            history_select = data.get("history_select", "")
            custom_name = data.get("custom_name", "").strip()

            if not isinstance(history_path, (str, bytes, bytearray)):
                history_path = str(history_path)

            try:
                hp = _normalize_history_path(history_path or "prompt_history.json")
                kh_pref = _parse_kh_prefix(history_select)

                if not kh_pref:
                    return web.json_response({"ok": False, "error": "invalid_key_hash"})

                with _HIST_LOCK:
                    hist = _read_history(hp)
                    items = hist.get("items", [])

                    # Find entry by key_hash prefix
                    for entry in items:
                        kh = entry.get("key_hash", "")
                        if kh and kh.startswith(kh_pref):
                            if custom_name:
                                entry["custom_name"] = custom_name
                            else:
                                # Remove custom_name if empty string provided
                                entry.pop("custom_name", None)

                            hist["items"] = items
                            _write_history_atomic(hp, hist)
                            return web.json_response({"ok": True, "custom_name": custom_name})

                    return web.json_response({"ok": False, "error": "not_found"})
            except Exception as e:
                return web.json_response({"ok": False, "error": "exception", "message": str(e)})

        # set the flag *inside* this block
        setattr(PromptServer.instance, _PG_ROUTES_FLAG, True)
