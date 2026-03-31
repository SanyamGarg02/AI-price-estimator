from dotenv import load_dotenv
load_dotenv()

import json
import os
import re
import difflib
from typing import Dict, List, Optional, Tuple

import streamlit as st

from pricing_ai_for_ui import run_pricing_pipeline

try:
    from openai import OpenAI
except Exception:
    OpenAI = None


def get_env(key: str, default=None):
    env_val = os.getenv(key)
    if env_val is not None and str(env_val).strip() != "":
        return env_val
    try:
        return st.secrets.get(key, default)
    except Exception:
        return default


OPENAI_API_KEY = get_env("OPENAI_API_KEY")
ENABLE_AI = str(get_env("ENABLE_AI", "true")).lower() == "true"
PRICE_SOURCE = str(get_env("PRICE_SOURCE", "gemgem")).lower()
USE_RAPNET = PRICE_SOURCE == "rapnet"
FORM_ESTIMATOR_URL = get_env("FORM_ESTIMATOR_URL", "https://ai-price-estimator-improved.streamlit.app/")
MODEL_NAME = get_env("OPENAI_CHATBOT_MODEL", "gpt-4o-mini")

JEWELRY_TYPES = ["Loose Diamond", "Diamond Jewelry"]
ITEM_TYPES = ["ring", "necklace", "bracelet", "earring", "pendant", "chain", "bangle", "anklet", "brooch"]
SHAPES = [
    "Round", "Pear", "Oval", "Marquise", "Heart", "Radiant", "Princess",
    "Emerald", "Triangle", "Asscher", "Cushion", "Baguette",
    "Tapered Baguette", "Trilliant", "Hexagonal", "Pentagonal", "Octagonal", "Other"
]
COLORS = list("DEFGHIJKLMNOPQRSTUVWXYZ")
CLARITIES = ["FL", "IF", "VVS1", "VVS2", "VS1", "VS2", "SI1", "SI2", "SI3", "I1", "I2", "I3"]
CUTS = ["Heart & Arrow", "Ideal", "Excellent", "Very Good", "Good"]
CONDITIONS = ["Excellent", "Like New", "Good", "Fair"]
METALS = ["White Gold", "Yellow Gold", "Rose Gold", "Dual Tone Gold", "Platinum"]
PURITY = ["10K", "12K", "14K", "16K", "18K", "22K", "PT950"]
FLUORESCENCE = ["None", "Faint", "Medium", "Strong", "Very Strong"]


def _default_profile() -> Dict:
    return {
        "jewelry_type": None,
        "jewelry_item_type": None,
        "carat": None,
        "shape": None,
        "color": None,
        "clarity": None,
        "cut": None,
        "fluorescence": None,
        "condition": None,
        "metal": None,
        "purity": None,
        "metal_weight_grams": None,
        "brand_selection": None,
        "brand": None,
        "brand_proof": None,
        "side_stones": [],
        "side_stone_present": None,
    }


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").strip())


def _friendly_label(k: str) -> str:
    m = {
        "jewelry_type": "whether this is a loose diamond or jewelry",
        "jewelry_item_type": "the jewelry type (ring/necklace/etc.)",
        "carat": "center-stone carat",
        "shape": "stone shape",
        "color": "color grade",
        "clarity": "clarity grade",
        "cut": "cut grade",
        "fluorescence": "fluorescence",
        "condition": "overall condition",
        "metal": "metal type",
        "purity": "metal purity",
        "metal_weight_grams": "metal weight",
        "brand_selection": "brand status",
    }
    return m.get(k, k.replace("_", " "))


def _fuzzy_pick(value: Optional[str], options: List[str], cutoff: float = 0.78) -> Optional[str]:
    if not value:
        return None
    v = str(value).strip().lower()
    lower_map = {o.lower(): o for o in options}
    if v in lower_map:
        return lower_map[v]
    m = difflib.get_close_matches(v, list(lower_map.keys()), n=1, cutoff=cutoff)
    return lower_map[m[0]] if m else None


def _canonical_condition(value: Optional[str]) -> Optional[str]:
    if not value:
        return None
    v = str(value).strip().lower()
    aliases = {
        "excellent": "Excellent",
        "exc": "Excellent",
        "ex": "Excellent",
        "like new": "Like New",
        "likenew": "Like New",
        "almost new": "Like New",
        "nearly new": "Like New",
        "new": "Like New",
        "ne": "Like New",
        "ln": "Like New",
        "good": "Good",
        "fair": "Fair",
    }
    if v in aliases:
        return aliases[v]
    for k, mapped in aliases.items():
        if k in v:
            return mapped
    return _fuzzy_pick(value, CONDITIONS, 0.66)


def _sanitize_profile(p: Dict) -> Dict:
    profile = dict(p)
    profile["jewelry_type"] = _fuzzy_pick(profile.get("jewelry_type"), JEWELRY_TYPES, 0.72)
    profile["jewelry_item_type"] = _fuzzy_pick(profile.get("jewelry_item_type"), ITEM_TYPES, 0.72)
    profile["shape"] = _fuzzy_pick(profile.get("shape"), SHAPES, 0.72)
    profile["clarity"] = _fuzzy_pick(profile.get("clarity"), CLARITIES, 0.72)
    profile["cut"] = _fuzzy_pick(profile.get("cut"), CUTS, 0.70)
    profile["condition"] = _canonical_condition(profile.get("condition"))
    profile["metal"] = _fuzzy_pick(profile.get("metal"), METALS, 0.70)
    profile["purity"] = _fuzzy_pick(profile.get("purity"), PURITY, 0.70)
    profile["fluorescence"] = _fuzzy_pick(profile.get("fluorescence"), FLUORESCENCE, 0.70)

    color = profile.get("color")
    if color:
        c = str(color).strip().upper()
        profile["color"] = c if c in COLORS else None
    else:
        profile["color"] = None

    # Platinum should always use PT950 in this flow.
    if profile.get("metal") == "Platinum":
        profile["purity"] = "PT950"

    for k in ["carat", "metal_weight_grams"]:
        if profile.get(k) is not None:
            try:
                fv = float(profile.get(k))
                profile[k] = fv if fv > 0 else None
            except Exception:
                profile[k] = None

    groups = profile.get("side_stones") if isinstance(profile.get("side_stones"), list) else []
    cleaned = []
    for g in groups:
        try:
            q = int(g.get("quantity") or 0)
            tcw = float(g.get("total_carat_weight") or 0.0)
        except Exception:
            continue
        if q > 0 and tcw > 0:
            cleaned.append({
                "stone_type": "Diamond",
                "quantity": q,
                "total_carat_weight": tcw,
                "shape": _fuzzy_pick(g.get("shape") or profile.get("shape"), SHAPES, 0.72),
                "color": (str(g.get("color") or profile.get("color") or "").upper() or None),
                "clarity": _fuzzy_pick(g.get("clarity") or profile.get("clarity"), CLARITIES, 0.72),
                "cut": _fuzzy_pick(g.get("cut") or profile.get("cut"), CUTS, 0.70),
            })
    profile["side_stones"] = cleaned
    if cleaned:
        profile["side_stone_present"] = True
    elif profile.get("side_stone_present") not in (True, False):
        profile["side_stone_present"] = None

    if profile.get("jewelry_type") == "Loose Diamond":
        profile["jewelry_item_type"] = None
        profile["metal"] = None
        profile["purity"] = None
        profile["metal_weight_grams"] = None
        profile["brand_selection"] = None
        profile["brand"] = None
        profile["brand_proof"] = None
        profile["side_stones"] = []
        profile["side_stone_present"] = False

    return profile


def _required_fields(profile: Dict) -> List[str]:
    req = ["jewelry_type", "condition"]
    has_center = float(profile.get("carat") or 0) > 0
    has_side = bool(profile.get("side_stones"))

    if has_center:
        req += ["shape", "color", "clarity", "cut"]
    elif not has_side:
        req += ["carat"]

    if profile.get("jewelry_type") == "Diamond Jewelry":
        # Ask side-stone flow right after metal details (before brand) for better UX.
        req += ["jewelry_item_type", "metal", "purity", "metal_weight_grams", "side_stone_present"]
        if profile.get("side_stone_present") is True and not profile.get("side_stones"):
            req += ["side_stones"]
        req += ["brand_selection"]

    missing = []
    for k in req:
        v = profile.get(k)
        if k == "side_stones":
            if not isinstance(v, list) or len(v) == 0:
                missing.append(k)
            continue
        if v in (None, ""):
            missing.append(k)
    return missing


DEFAULTS = {
    "carat": 1.0,
    "shape": "Round",
    "color": "G",
    "clarity": "VS1",
    "cut": "Excellent",
    "condition": "Excellent",
    "fluorescence": "None",
    "jewelry_item_type": "ring",
    "metal": "White Gold",
    "purity": "14K",
    "metal_weight_grams": 4.0,
    "brand_selection": "Other / Unknown",
    "brand_proof": "No",
    "side_stone_present": False,
}


def _apply_defaults(profile: Dict, unknown_fields: List[str], assumptions: List[str]) -> Dict:
    p = dict(profile)
    for f in unknown_fields:
        if p.get(f) in (None, "") and f in DEFAULTS:
            default_val = DEFAULTS[f]
            if f == "purity" and p.get("metal") == "Platinum":
                default_val = "PT950"
            p[f] = default_val
            assumptions.append(f"{_friendly_label(f)}={default_val}")
    return _sanitize_profile(p)


def _regex_fallback(user_msg: str, last_asked: Optional[str]) -> Dict:
    t = _norm(user_msg)
    tl = t.lower()
    out = {}

    if "loose" in tl and "diamond" in tl:
        out["jewelry_type"] = "Loose Diamond"
    elif any(x in tl for x in ["ring", "necklace", "pendant", "bracelet", "earring", "jewelry", "jewellery"]):
        out["jewelry_type"] = "Diamond Jewelry"

    for item in ITEM_TYPES:
        if item in tl:
            out["jewelry_item_type"] = item
            break

    # Center carat should still be captured even when tcw also exists in the same sentence.
    center_carat = (
        re.search(r"(?:center|centre|main)\s*stone[^\d]{0,16}(\d+(?:\.\d+)?)\s*(?:ct|carat)", tl)
        or re.search(r"(\d+(?:\.\d+)?)\s*(?:ct|carat)[^\n]{0,24}(?:center|centre|main)\s*stone", tl)
    )
    if center_carat:
        out["carat"] = float(center_carat.group(1))
    else:
        # If tcw is mentioned and no explicit center cue, treat carat mentions as side-stone context.
        carat = re.search(r"(\d+(?:\.\d+)?)\s*(?:ct|carat)", tl)
        if carat and "tcw" not in tl:
            out["carat"] = float(carat.group(1))

    if last_asked == "color":
        one = re.match(r"^\s*([d-z])\s*$", tl)
        if one:
            out["color"] = one.group(1).upper()

    c1 = re.search(r"\bcolor\s*[:\-]?\s*([d-z])\b", tl)
    c2 = re.search(r"\b([d-z])\s*color\b", tl)
    c = c1 or c2
    if c:
        out["color"] = c.group(1).upper()

    for v in CLARITIES:
        if re.search(rf"\b{re.escape(v.lower())}\b", tl):
            out["clarity"] = v
            break

    if re.search(r"\b(ex|exc|excellent)\b", tl):
        if last_asked == "condition":
            out["condition"] = "Excellent"
        elif last_asked == "cut":
            out["cut"] = "Excellent"
        else:
            out["cut"] = "Excellent"
            if "condition" not in tl:
                out["condition"] = "Excellent"
    if re.search(r"\b(vg|very good)\b", tl):
        if last_asked == "condition":
            out["condition"] = "Good"
        else:
            out["cut"] = "Very Good"
    if re.search(r"\bideal\b", tl):
        if last_asked == "condition":
            out["condition"] = "Excellent"
        else:
            out["cut"] = "Ideal"
    if re.search(r"\bgood\b", tl):
        out["condition"] = "Good"
    if "like new" in tl or "likenew" in tl or "almost new" in tl or "nearly new" in tl:
        out["condition"] = "Like New"
    if last_asked == "condition" and re.match(r"^\s*(ne|new|ln)\s*$", tl):
        out["condition"] = "Like New"
    if "fair" in tl:
        out["condition"] = "Fair"

    for s in SHAPES:
        if s.lower() in tl:
            out["shape"] = s
            break

    for f in FLUORESCENCE:
        if f.lower() in tl:
            out["fluorescence"] = f
            break

    for m in METALS:
        if m.lower() in tl:
            out["metal"] = m
            break

    purity = re.search(r"\b(10k|12k|14k|16k|18k|22k|pt950)\b", tl)
    if purity:
        out["purity"] = purity.group(1).upper()
    grams = re.search(r"(\d+(?:\.\d+)?)\s*(?:g|gram|grams)\b", tl)
    if grams:
        out["metal_weight_grams"] = float(grams.group(1))

    # Brand intent handling
    if any(x in tl for x in [
        "no brand", "not branded", "unbranded", "without brand", "other brand", "unknown brand"
    ]):
        out["brand_selection"] = "Other / Unknown"
        out["brand"] = None
        out["brand_proof"] = "No"
    elif last_asked == "brand_selection" and re.search(r"\b(no|none|nah|n)\b", tl):
        out["brand_selection"] = "Other / Unknown"
        out["brand"] = None
        out["brand_proof"] = "No"

    if last_asked == "brand_proof":
        if re.search(r"\b(yes|y)\b", tl):
            out["brand_proof"] = "Yes"
        elif re.search(r"\b(no|none|nah|n)\b", tl):
            out["brand_proof"] = "No"

    if last_asked == "side_stone_present":
        if re.search(r"\b(yes|y)\b", tl):
            out["side_stone_present"] = True
        elif re.search(r"\b(no|none|nah|n)\b", tl):
            out["side_stone_present"] = False

    if "brand proof" in tl:
        if re.search(r"\b(yes|have|available)\b", tl):
            out["brand_proof"] = "Yes"
        if re.search(r"\b(no|none|not)\b", tl):
            out["brand_proof"] = "No"

    side_groups = []
    pattern = re.compile(
        r"(\d+)\s*(?:side\s*stones?|stones)\b[^\d]{0,24}(?:tcw|total\s*carat(?:\s*weight)?|carat(?:\s*weight)?)\s*(?:is\s*)?(\d+(?:\.\d+)?)\s*(?:ct|carat)?"
    )
    for m in pattern.finditer(tl):
        q = int(m.group(1))
        tcw = float(m.group(2))
        if q > 0 and tcw > 0:
            side_groups.append({"stone_type": "Diamond", "quantity": q, "total_carat_weight": tcw})
    if side_groups:
        out["side_stones"] = side_groups
        out["side_stone_present"] = True
    if any(x in tl for x in [
        "side stone", "side stones", "tcw", "melee", "pave", "pavé"
    ]):
        if out.get("side_stone_present") is None:
            out["side_stone_present"] = True
    if any(x in tl for x in [
        "no side stone", "no side stones", "without side stone", "without side stones"
    ]):
        out["side_stone_present"] = False
    if any(x in tl for x in ["no center stone", "only side stones", "side stones only"]):
        out["carat"] = None
        out["side_stone_present"] = True

    return out


def _has_explicit_side_stone_specs(user_msg: str) -> bool:
    tl = _norm(user_msg).lower()
    # Require hard evidence like quantity + tcw/carat-weight pair.
    pair = re.search(
        r"(\d+)\s*(?:side\s*stones?|stones)\b[^\d]{0,24}(?:tcw|total\s*carat(?:\s*weight)?|carat(?:\s*weight)?)\s*(?:is\s*)?(\d+(?:\.\d+)?)",
        tl,
    )
    return bool(pair)


def _explicit_side_stone_presence(user_msg: str) -> Optional[bool]:
    tl = _norm(user_msg).lower()
    if re.search(r"\b(no|none|without)\s+side\s*stones?\b", tl):
        return False
    if re.search(r"\b(has|have|with)\s+side\s*stones?\b", tl):
        return True
    if re.search(r"\bside\s*stones?\b", tl) and _has_explicit_side_stone_specs(user_msg):
        return True
    if re.search(r"^\s*(yes|y)\s*$", tl):
        return True
    if re.search(r"^\s*(no|n|nah)\s*$", tl):
        return False
    return None


def _ai_turn(user_msg: str, profile: Dict, missing: List[str], last_asked: Optional[str]) -> Dict:
    if not (OPENAI_API_KEY and OpenAI):
        return {"updates": _regex_fallback(user_msg, last_asked), "unknown_fields": [], "assistant_reply": "", "off_topic": False}

    prompt = (
        "You are an expert jewelry valuation concierge.\n"
        "Goal: move the conversation naturally toward collecting pricing fields, while sounding warm and human.\n"
        "If user is off-topic, politely bring them back to jewelry details.\n"
        "Accept typos/slang. If user answers short token in context (like 'f' after color), map correctly.\n"
        "Never mention internal field names.\n"
        "Return strict JSON only with schema:\n"
        "{"
        "\"updates\":{"
        "\"jewelry_type\":null|\"Loose Diamond\"|\"Diamond Jewelry\","
        "\"jewelry_item_type\":null|\"ring\"|\"necklace\"|\"bracelet\"|\"earring\"|\"pendant\"|\"chain\"|\"bangle\"|\"anklet\"|\"brooch\","
        "\"carat\":number|null,"
        "\"shape\":string|null,"
        "\"color\":string|null,"
        "\"clarity\":string|null,"
        "\"cut\":string|null,"
        "\"fluorescence\":string|null,"
        "\"condition\":string|null,"
        "\"metal\":string|null,"
        "\"purity\":string|null,"
        "\"metal_weight_grams\":number|null,"
        "\"brand_selection\":string|null,"
        "\"brand\":string|null,"
        "\"brand_proof\":string|null,"
        "\"side_stone_present\":boolean|null,"
        "\"center_stone_present\":boolean|null,"
        "\"side_stones\":[{\"quantity\":number,\"total_carat_weight\":number,\"shape\":string|null,\"color\":string|null,\"clarity\":string|null,\"cut\":string|null}]"
        "},"
        "\"unknown_fields\":[string],"
        "\"off_topic\":boolean,"
        "\"assistant_reply\":string"
        "}\n"
        f"Current profile: {json.dumps(profile)}\n"
        f"Currently missing: {missing}\n"
        f"Last asked: {last_asked}\n"
        f"User message: {user_msg}\n"
        "Important intent rules:\n"
        "- quantity + tcw usually means side stones.\n"
        "- single carat mention without quantity/tcw usually means center stone.\n"
        "- multiple quantity/tcw groups means side-stones-only unless center stone is explicitly mentioned.\n"
        "- If unsure, prefer side-stone interpretation when qty/tcw exists.\n"
    )
    try:
        client = OpenAI(api_key=OPENAI_API_KEY)
        rsp = client.chat.completions.create(
            model=MODEL_NAME,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.5,
            max_tokens=420,
            response_format={"type": "json_object"},
        )
        data = json.loads((rsp.choices[0].message.content or "{}").strip() or "{}")
        if not isinstance(data, dict):
            return {"updates": {}, "unknown_fields": [], "assistant_reply": "", "off_topic": False}
        return data
    except Exception:
        return {"updates": _regex_fallback(user_msg, last_asked), "unknown_fields": [], "assistant_reply": "", "off_topic": False}


def _merge_profile(profile: Dict, updates: Dict) -> Dict:
    merged = dict(profile)
    prev = dict(profile)
    for k, v in (updates or {}).items():
        if k == "side_stones" and isinstance(v, list):
            merged[k] = v
            continue
        if v in ("", None):
            continue
        merged[k] = v
    cleaned = _sanitize_profile(merged)
    # Do not allow invalid new values to erase previously valid captured values.
    protected = [
        "jewelry_type", "jewelry_item_type", "carat", "shape", "color", "clarity", "cut",
        "fluorescence", "condition", "metal", "purity", "metal_weight_grams", "brand_selection"
    ]
    for k in protected:
        if cleaned.get(k) in (None, "") and prev.get(k) not in (None, ""):
            cleaned[k] = prev[k]
    return cleaned


def _infer_stone_structure(profile: Dict, user_msg: str, last_asked: Optional[str]) -> Dict:
    p = dict(profile)
    t = _norm(user_msg).lower()
    has_side_groups = bool(p.get("side_stones"))
    has_center = float(p.get("carat") or 0) > 0

    mentions_center = bool(re.search(r"\b(center|centre|main|solitaire)\s*stone\b", t))
    qty_tcw_pairs = len(re.findall(
        r"(\d+)\s*(?:side\s*stones?|stones)\b[^\d]{0,24}(?:tcw|total\s*carat(?:\s*weight)?|carat(?:\s*weight)?)\s*(?:is\s*)?(\d+(?:\.\d+)?)",
        t
    ))
    has_qty_tcw = qty_tcw_pairs > 0

    # If message strongly indicates side-only structure, clear center for this structure.
    if has_qty_tcw and not mentions_center and not has_center:
        p["side_stone_present"] = True
        p["carat"] = None

    # Multiple qty/tcw groups almost always indicate side-stone groups, not a center.
    if qty_tcw_pairs >= 2 and not mentions_center:
        p["side_stone_present"] = True
        if last_asked in ("side_stones", "side_stone_present", "carat"):
            p["carat"] = None

    # If center is explicit, keep center + side combination.
    if mentions_center and has_side_groups:
        p["side_stone_present"] = True

    return _sanitize_profile(p)


def _build_user_input(profile: Dict) -> Dict:
    p = dict(profile)
    if p.get("jewelry_type") == "Diamond Jewelry":
        p["metal"] = p.get("metal") or "White Gold"
        p["purity"] = p.get("purity") or "14K"
        p["metal_weight_grams"] = p.get("metal_weight_grams") or 4.0
        p["brand_selection"] = p.get("brand_selection") or "Other / Unknown"
        p["brand_proof"] = p.get("brand_proof") or "No"

    center = {
        "shape": p.get("shape") or "Round",
        "carat": p.get("carat") or 0.0,
        "color": p.get("color") or "G",
        "clarity": p.get("clarity") or "VS1",
        "cut": p.get("cut") or "Excellent",
        "polish": None,
        "symmetry": None,
        "fluorescence": p.get("fluorescence") or "None",
    }
    return {
        "images": [],
        "jewelry_type": p.get("jewelry_type") or "Loose Diamond",
        "center_stone": center,
        "condition": p.get("condition") or "Excellent",
        "metal": p.get("metal"),
        "purity": p.get("purity"),
        "metal_weight_grams": p.get("metal_weight_grams"),
        "side_stones": p.get("side_stones") or [],
        "brand_selection": p.get("brand_selection") or "Other / Unknown",
        "brand": p.get("brand"),
        "brand_proof": p.get("brand_proof") or "No",
    }


def _progress(profile: Dict) -> Tuple[int, int, int]:
    keys = [
        "jewelry_type", "jewelry_item_type", "carat", "shape", "color", "clarity",
        "cut", "fluorescence", "condition", "metal", "purity", "metal_weight_grams",
        "brand_selection"
    ]
    got = sum(1 for k in keys if profile.get(k) not in (None, ""))
    total = len(keys)
    if profile.get("side_stones"):
        got += 1
        total += 1
    pct = int(100 * got / max(total, 1))
    return got, total, pct


def _sort_comps(comps: List[Dict]) -> List[Dict]:
    def key(c):
        w = c.get("similarity_weight")
        if w is None:
            w = c.get("weight", 0)
        try:
            return float(w)
        except Exception:
            return 0.0
    return sorted(comps or [], key=key, reverse=True)


def _price_story(result: Dict) -> Dict:
    fp = result.get("final_price") or {}
    low = float(fp.get("low") or 0)
    high = float(fp.get("high") or 0)
    if high < low:
        low, high = high, low
    spread = max(0.0, high - low)
    return {
        "low": low,
        "high": high,
        "premium_top": high * 1.12,
        "sell_fast": low + 0.2 * spread,
        "max_value": high,
    }


def _what_if(low: float, high: float, mode: str, profile: Dict) -> Tuple[float, float]:
    bump = {"brand": 0.06, "timing": 0.03}.get(mode, 0.0)
    if mode == "condition":
        # Scenario means "what if condition were Like New".
        # If current is Excellent, this should reduce value.
        rank = {"Fair": 1, "Good": 2, "Like New": 3, "Excellent": 4}
        current = rank.get(str(profile.get("condition") or "Like New"), 3)
        target = rank["Like New"]
        bump = (target - current) * 0.03
    return round(low * (1 + bump), 2), round(high * (1 + bump), 2)


def _next_question_text(field_key: str, profile: Dict) -> str:
    prompts = {
        "jewelry_type": "Is this a loose diamond or diamond jewelry?",
        "jewelry_item_type": "What type of jewelry is it (ring, necklace, bracelet, earring, pendant, etc.)?",
        "carat": "What is the center-stone carat weight (for example, 1.20 ct)?",
        "shape": "What shape is the center stone (round, oval, emerald, princess, etc.)?",
        "color": "What color grade do you know (D to Z)?",
        "clarity": "What clarity grade do you know (IF, VVS1, VS1, SI1, etc.)?",
        "cut": "What cut grade do you know (Ideal, Excellent, Very Good, or Good)?",
        "fluorescence": "Do you know fluorescence (None, Faint, Medium, Strong, Very Strong)?",
        "condition": "How’s the overall condition (Excellent, Like New, Good, or Fair)?",
        "metal": "What metal is it made of (white gold, yellow gold, rose gold, dual tone, platinum)?",
        "purity": "What is the purity (10K, 12K, 14K, 16K, 18K, 22K, PT950)?",
        "metal_weight_grams": "Do you know the approx metal weight in grams?",
        "brand_selection": "Is this branded or unbranded/unknown?",
        "side_stone_present": "Does this jewelry have side stones?",
        "side_stones": "Please share side-stone details like quantity and total carat weight (TCW), for example: 20 side stones, tcw 0.40 ct.",
    }
    return prompts.get(field_key, f"Could you share {_friendly_label(field_key)}?")


def _is_greeting(msg: str) -> bool:
    t = _norm(msg).lower().strip()
    greetings = {"hi", "hello", "hey", "hii", "yo", "good morning", "good evening", "good afternoon"}
    return t in greetings or any(t.startswith(g + " ") for g in greetings)


def _grouped_missing_text(keys: List[str]) -> str:
    labels = {
        "carat": "carat",
        "shape": "shape",
        "color": "color",
        "clarity": "clarity",
        "cut": "cut",
        "fluorescence": "fluorescence",
        "condition": "condition",
        "metal": "metal",
        "purity": "purity",
        "metal_weight_grams": "metal weight (grams)",
        "side_stone_present": "whether it has side stones",
        "side_stones": "side stone details (quantity + total carat weight/TCW)",
        "brand_selection": "brand info",
    }
    items = [labels.get(k, _friendly_label(k)) for k in keys]
    if not items:
        return ""
    if len(items) == 1:
        return items[0]
    if len(items) == 2:
        return f"{items[0]} and {items[1]}"
    return f"{', '.join(items[:-1])}, and {items[-1]}"


def _conversation_followup(user_msg: str, profile: Dict, missing: List[str], ai_data: Dict) -> str:
    t = _norm(user_msg).lower()
    off_topic = bool((ai_data or {}).get("off_topic"))

    if off_topic:
        return (
            "I may not know that part, but I can definitely help you get a strong diamond valuation. "
            "Share your specs in one line and I’ll price it fast."
        )

    if _is_greeting(user_msg):
        return (
            "Hi! Happy to help. Tell me what you want to sell and share whatever specs you know "
            "(carat, shape, color, clarity, cut, condition)."
        )

    jt = profile.get("jewelry_type")
    if not jt:
        return (
            "Great — I can help with that. Is this a loose diamond or diamond jewelry? "
            "If you already know specs, paste them in one line and I’ll pick them up."
        )

    diamond_core = ["carat", "shape", "color", "clarity", "cut", "fluorescence", "condition"]
    core_missing = [k for k in diamond_core if k in missing]

    if jt == "Loose Diamond":
        if core_missing:
            if len(core_missing) >= 3:
                return (
                    "Perfect. For a quick estimate, share these in one message: "
                    f"{_grouped_missing_text(core_missing)}. Rough details are totally fine."
                )
            return f"Got it. Could you share {_grouped_missing_text(core_missing)}?"

    if jt == "Diamond Jewelry":
        if core_missing:
            return (
                "Great start. Please share center-stone specs in one line: "
                f"{_grouped_missing_text(core_missing)}."
            )

        metal_group = [k for k in ["metal", "purity", "metal_weight_grams"] if k in missing]
        if metal_group:
            return (
                "Nice. Now share jewelry metal details in one go: "
                f"{_grouped_missing_text(metal_group)}."
            )

        if "side_stone_present" in missing:
            return "Does this piece have any side stones? (yes/no)"
        if "side_stones" in missing:
            return (
                "Please share side-stone specs in one line: quantity and total carat weight (TCW). "
                "If you know side-stone color, shape, or clarity, add those too."
            )
        if "brand_selection" in missing:
            return "Is this branded or unbranded/unknown?"

    # Fallback
    return _next_question_text(missing[0], profile)


def _user_done_intent(msg: str) -> bool:
    t = _norm(msg).lower()
    phrases = [
        "that is all", "that's all", "thats all", "no more", "no thats all",
        "no that's all", "all detail i have", "all details i have", "that's it",
        "thats it", "this is all", "nothing else", "thats all i have",
    ]
    return any(p in t for p in phrases)


def _unknown_intent(msg: str) -> bool:
    t = _norm(msg).lower()
    phrases = [
        "i dont know", "i don't know", "dont know", "don't know",
        "not sure", "im not sure", "i am not sure", "no clue",
        "unknown", "na", "n/a", "not available", "no idea", "dk", "idk",
    ]
    if any(p in t for p in phrases):
        return True
    return bool(re.match(r"^\s*(no|nah|n)\s*$", t))


def _run_estimate_and_message(profile: Dict, rapnet_token: Optional[str]) -> Tuple[Dict, str]:
    payload = _build_user_input(profile)
    res = run_pricing_pipeline(payload, rapnet_token, "Enabled" if ENABLE_AI else "Disabled")
    fp = res.get("final_price") or {}
    low = float(fp.get("low") or 0)
    high = float(fp.get("high") or 0)
    msg = (
        f"Perfect — I’ve generated your valuation range: **${low:,.0f} to ${high:,.0f}**. "
        "You can refine more details anytime and I’ll re-estimate instantly."
    )
    return res, msg


st.set_page_config(page_title="Jewelry Pricing Concierge (Demo)", page_icon="💎", layout="wide")
st.title("Jewelry Pricing Concierge (Demo)")
st.caption("AI-first conversational valuation demo with natural intent understanding.")

left_top, right_top = st.columns([1, 1])
with left_top:
    st.link_button("Switch To Form Estimator", FORM_ESTIMATOR_URL)
with right_top:
    if st.button("Start New Chat"):
        st.session_state.clear()
        st.rerun()

if "messages" not in st.session_state:
    st.session_state.messages = [{
        "role": "assistant",
        "content": (
            "Hi, I’m your jewelry pricing assistant 👋\n\n"
            "Describe your item (carat, shape, metal, etc.), and I’ll estimate its value for you.\n\n"
            "You can keep it simple — even rough details work. For example:\n"
            "- Example (loose diamond): `2 ct loose diamond, color H, VVS1 clarity, excellent condition`\n"
            "- Example (jewelry): `18K white gold ring, 1.5 ct center stone, color H, VVS1 clarity, excellent condition`"
        )
    }]
if "profile" not in st.session_state:
    st.session_state.profile = _default_profile()
if "last_asked" not in st.session_state:
    st.session_state.last_asked = None
if "result" not in st.session_state:
    st.session_state.result = None
if "assumptions" not in st.session_state:
    st.session_state.assumptions = []
if "whatif" not in st.session_state:
    st.session_state.whatif = None

rapnet_token = None
if USE_RAPNET:
    rapnet_token = st.text_input("RapNet Bearer Token", type="password")

left, right = st.columns([1.8, 1])

with left:
    for m in st.session_state.messages:
        with st.chat_message(m["role"]):
            st.markdown(m["content"])

    user_msg = st.chat_input("Type your jewelry details...")
    if user_msg:
        st.session_state.messages.append({"role": "user", "content": user_msg})

        profile = st.session_state.profile
        missing = _required_fields(profile)
        ai_data = _ai_turn(user_msg, profile, missing, st.session_state.last_asked)
        updates = ai_data.get("updates") if isinstance(ai_data, dict) else {}
        unknown_fields = ai_data.get("unknown_fields") if isinstance(ai_data, dict) else []
        if not isinstance(updates, dict):
            updates = {}
        if not isinstance(unknown_fields, list):
            unknown_fields = []

        # Regex safety net for missing obvious fields/typos.
        fallback = _regex_fallback(user_msg, st.session_state.last_asked)
        for k, v in fallback.items():
            if updates.get(k) in (None, "", []):
                updates[k] = v

        # Guardrail: never accept hallucinated side-stone groups unless user explicitly provided qty+TCW.
        if isinstance(updates.get("side_stones"), list) and updates.get("side_stones"):
            if not _has_explicit_side_stone_specs(user_msg):
                updates.pop("side_stones", None)
                if updates.get("side_stone_present") is None:
                    updates["side_stone_present"] = True

        # Guardrail: for jewelry flow, don't let model silently set side-stone presence
        # unless the user explicitly said yes/no or provided side-stone specs.
        if updates.get("jewelry_type") == "Diamond Jewelry" or profile.get("jewelry_type") == "Diamond Jewelry":
            explicit_side_presence = _explicit_side_stone_presence(user_msg)
            if explicit_side_presence is None:
                updates.pop("side_stone_present", None)
            else:
                updates["side_stone_present"] = explicit_side_presence

        profile = _merge_profile(profile, updates)

        # Global unknown-intent handling: if user says idk/not sure/no idea, default current field and move on.
        if _unknown_intent(user_msg) and st.session_state.last_asked:
            asked = st.session_state.last_asked
            if asked == "side_stones":
                updates["side_stones"] = []
                updates["side_stone_present"] = False
            elif asked == "side_stone_present":
                updates["side_stone_present"] = False
            elif asked in {"brand_selection", "brand"}:
                updates["brand_selection"] = "Other / Unknown"
                updates["brand"] = None
                updates["brand_proof"] = "No"
            elif asked == "brand_proof":
                updates["brand_proof"] = "No"
            else:
                if asked not in unknown_fields:
                    unknown_fields.append(asked)

        # Apply any late unknown-intent update overrides to profile.
        profile = _merge_profile(profile, updates)

        profile = _apply_defaults(profile, unknown_fields, st.session_state.assumptions)
        profile = _infer_stone_structure(profile, user_msg, st.session_state.last_asked)

        if _user_done_intent(user_msg):
            before_missing = _required_fields(profile)
            profile = _apply_defaults(profile, before_missing, st.session_state.assumptions)

        st.session_state.profile = profile

        missing_after = _required_fields(profile)
        st.session_state.last_asked = missing_after[0] if missing_after else None

        if not missing_after:
            try:
                res, assistant_reply = _run_estimate_and_message(profile, rapnet_token)
                st.session_state.result = res
            except Exception:
                assistant_reply = "I have enough details now. Tap **Estimate Now** to generate your valuation."
        else:
            assistant_reply = _conversation_followup(user_msg, profile, missing_after, ai_data if isinstance(ai_data, dict) else {})

        st.session_state.messages.append({"role": "assistant", "content": assistant_reply})
        st.rerun()

    user_turns = sum(1 for m in st.session_state.messages if m.get("role") == "user")
    if user_turns > 0:
        profile = st.session_state.profile
        has_carat = float(profile.get("carat") or 0.0) > 0
        if has_carat:
            c1, c2 = st.columns(2)
            if c1.button("Estimate Now", use_container_width=True):
                try:
                    res, msg = _run_estimate_and_message(profile, rapnet_token)
                    st.session_state.result = res
                    st.session_state.messages.append({
                        "role": "assistant",
                        "content": msg
                    })
                except Exception as exc:
                    st.session_state.result = {"error": str(exc)}
                    st.session_state.messages.append({"role": "assistant", "content": "I hit an issue while estimating. Please retry once."})
                st.rerun()

            if c2.button("I’m Not Sure", use_container_width=True):
                missing = _required_fields(st.session_state.profile)
                if missing:
                    st.session_state.profile = _apply_defaults(
                        st.session_state.profile,
                        missing[:1],
                        st.session_state.assumptions,
                    )
                    missing_after = _required_fields(st.session_state.profile)
                    st.session_state.last_asked = missing_after[0] if missing_after else None
                    if missing_after:
                        next_q = _conversation_followup("", st.session_state.profile, missing_after, {"off_topic": False})
                        st.session_state.messages.append(
                            {
                                "role": "assistant",
                                "content": f"No problem, I’ll use a smart default for that. {next_q}",
                            }
                        )
                    else:
                        st.session_state.messages.append(
                            {
                                "role": "assistant",
                                "content": "Great, that’s enough detail now. Tap **Estimate Now** to generate your valuation.",
                            }
                        )
                else:
                    st.session_state.messages.append(
                        {
                            "role": "assistant",
                            "content": "All good, we already have enough to proceed. Tap **Estimate Now** whenever you’re ready.",
                        }
                    )
                st.rerun()
        else:
            st.caption("Share at least the carat value to unlock instant estimate.")

with right:
    got, total, pct = _progress(st.session_state.profile)
    st.caption("Conversation Progress")
    st.progress(pct / 100)
    st.write(f"**Specs captured:** {got}/{total} ({pct}%)")

    p = st.session_state.profile
    st.caption("Captured details")
    st.json({
        "Type": p.get("jewelry_type"),
        "Item Type": p.get("jewelry_item_type"),
        "Carat": p.get("carat"),
        "Shape": p.get("shape"),
        "Color": p.get("color"),
        "Clarity": p.get("clarity"),
        "Cut": p.get("cut"),
        "Fluorescence": p.get("fluorescence"),
        "Condition": p.get("condition"),
        "Metal": p.get("metal"),
        "Purity": p.get("purity"),
        "Metal Weight (g)": p.get("metal_weight_grams"),
        "Side Groups": p.get("side_stones"),
    })

    if st.session_state.assumptions:
        st.info("Assumptions used: " + ", ".join(st.session_state.assumptions[-5:]))

    result = st.session_state.result
    if result:
        st.subheader("Latest Price Output")
        if result.get("error"):
            st.error(str(result.get("error")))
        else:
            fp = result.get("final_price") or {}
            low = float(fp.get("low") or 0)
            high = float(fp.get("high") or 0)
            c1, c2 = st.columns(2)
            c1.metric("Low", f"${low:,.2f}")
            c2.metric("High", f"${high:,.2f}")

            conf_score = (result.get("anchor_confidence") or {}).get("score")
            conf = int((float(conf_score) if conf_score is not None else 0.65) * 100)
            st.caption("Estimate Confidence")
            st.progress(conf / 100)
            st.write(f"**{conf}%** confidence")

            story = _price_story(result)
            st.markdown("### Price Story")
            st.write(f"Similar products with your specs are typically listed around **${story['low']:,.0f}-${story['high']:,.0f}**.")
            st.write(f"Premium listings can reach **${story['premium_top']:,.0f}** when demand and documentation align.")
            st.write(f"Fast-sale target: **${story['sell_fast']:,.0f}** | Max-value target: **${story['max_value']:,.0f}**")

            mode = st.radio("Result framing", ["Sell Fast", "Max Value"], horizontal=True)
            if mode == "Sell Fast":
                st.info(f"Suggested fast-sale listing: **${story['sell_fast']:,.0f}**")
            else:
                st.info(f"Suggested max-value listing: **${story['max_value']:,.0f}**")

            st.markdown("### What-if Simulator")
            w1, w2, w3 = st.columns(3)
            if w1.button("Add Brand Proof"):
                st.session_state.whatif = "brand"
            if w2.button("Condition Like New"):
                st.session_state.whatif = "condition"
            if w3.button("Sell in 2 Weeks"):
                st.session_state.whatif = "timing"
            if st.session_state.whatif:
                wl, wh = _what_if(low, high, st.session_state.whatif, p)
                st.success(f"Scenario range: **${wl:,.0f}-${wh:,.0f}**")

            with st.expander("Center Stone Details"):
                st.json(result.get("diamond_anchor") or {})
            with st.expander("Side Stones Details"):
                st.json(result.get("side_stones_breakdown") or [])
            with st.expander("Metal Details"):
                st.json({
                    "metal": p.get("metal"),
                    "purity": p.get("purity"),
                    "metal_weight_grams": p.get("metal_weight_grams"),
                    "metal_value_usd": result.get("metal_value"),
                })

            comps = _sort_comps(result.get("comparables") or [])
            if comps:
                rows = []
                for c in comps[:10]:
                    price = None
                    if isinstance(c.get("price"), dict):
                        price = ((c.get("price") or {}).get("USD") or {}).get("price")
                    if price is None:
                        price = c.get("price_usd")
                    slug = c.get("slug")
                    url = c.get("url") or c.get("product_url")
                    if not url and slug:
                        url = f"https://www.gemgem.com/product/{str(slug).strip('/')}"
                    rows.append({
                        "Similarity Weight": c.get("similarity_weight") or c.get("weight"),
                        "Listing ID": c.get("listing_id") or c.get("id") or "N/A",
                        "Name": c.get("name") or "N/A",
                        "Price (USD)": price,
                        "Product URL": url or "N/A",
                    })
                st.markdown("### Comparable Diamonds Used")
                st.dataframe(
                    rows,
                    hide_index=True,
                    use_container_width=True,
                    column_config={"Product URL": st.column_config.LinkColumn("Product URL")}
                )

            st.markdown("---")
            st.markdown(
                f"""
**Guided Valuation Note**

Based on your specs, similar products are typically listed around **${low:,.0f}-${high:,.0f}**, and can go higher depending on live demand, proof, and buyer intent.

For the most accurate quote, our valuation specialist can review your photos and docs and share a near-final estimate.
"""
            )
            if st.button("Connect to Human Valuation Expert", type="primary", use_container_width=True):
                st.success("Agent handoff initiated. (Demo button)")
