from dotenv import load_dotenv
load_dotenv()

import json
import os
import re
import difflib
from typing import Dict, Optional, Tuple

import streamlit as st

from pricing_ai_for_ui import run_pricing_pipeline


def get_env(key, default=None):
    env_val = os.getenv(key)
    if env_val is not None and str(env_val).strip() != "":
        return env_val
    try:
        return st.secrets.get(key, default)
    except Exception:
        return default


PRICE_SOURCE = (get_env("PRICE_SOURCE", "gemgem")).lower()
USE_RAPNET = PRICE_SOURCE == "rapnet"
ENABLE_AI = (get_env("ENABLE_AI", "false")).lower() == "true"
OPENAI_API_KEY = get_env("OPENAI_API_KEY")
FORM_ESTIMATOR_URL = get_env(
    "FORM_ESTIMATOR_URL",
    "https://ai-price-estimator-improved.streamlit.app/",
)

SHAPES = [
    "Round", "Pear", "Oval", "Marquise", "Heart", "Radiant", "Princess",
    "Emerald", "Triangle", "Asscher", "Cushion", "Baguette",
    "Tapered Baguette", "Trilliant", "Hexagonal", "Pentagonal", "Octagonal", "Other"
]
COLORS = [
    "D", "E", "F", "G", "H", "I", "J", "K", "L", "M",
    "N", "O", "P", "Q", "R", "S", "T", "U", "V", "W",
    "X", "Y", "Z"
]
CLARITIES = ["FL", "IF", "VVS1", "VVS2", "VS1", "VS2", "SI1", "SI2", "SI3", "I1", "I2", "I3"]
CUTS = ["Heart & Arrow", "Ideal", "Excellent", "Very Good", "Good"]
CONDITIONS = ["Excellent", "Like New", "Good", "Fair"]
METALS = ["White Gold", "Yellow Gold", "Rose Gold", "Dual Tone Gold", "Platinum"]
PURITY = ["10K", "12K", "14K", "16K", "18K", "22K", "PT950"]
FLUORESCENCE = ["None", "Faint", "Medium", "Strong", "Very Strong"]
TOP_RESALE_BRANDS = [
    "Cartier",
    "Tiffany & Co.",
    "Van Cleef & Arpels",
    "Bulgari",
    "Harry Winston",
    "Chopard",
    "Graff",
    "Boucheron",
    "Buccellati",
    "Chaumet",
    "Piaget",
]

SHAPE_LOOKUP = {s.lower(): s for s in SHAPES}
CUT_LOOKUP = {c.lower(): c for c in CUTS}
COND_LOOKUP = {c.lower(): c for c in CONDITIONS}
CLARITY_LOOKUP = {c.lower(): c for c in CLARITIES}
METAL_LOOKUP = {m.lower(): m for m in METALS}
FLUORESCENCE_LOOKUP = {f.lower(): f for f in FLUORESCENCE}
BRAND_LOOKUP = {b.lower(): b for b in TOP_RESALE_BRANDS}

CUT_ALIASES = {
    "id": "Ideal",
    "ideal": "Ideal",
    "ex": "Excellent",
    "exc": "Excellent",
    "excellent": "Excellent",
    "vg": "Very Good",
    "very good": "Very Good",
    "gd": "Good",
    "good": "Good",
}

CLARITY_ALIASES = {
    "fl": "FL",
    "if": "IF",
    "vvs1": "VVS1",
    "vvs2": "VVS2",
    "vs1": "VS1",
    "vs2": "VS2",
    "si1": "SI1",
    "si2": "SI2",
    "si3": "SI3",
    "i1": "I1",
    "i2": "I2",
    "i3": "I3",
}

ITEM_TYPE_TOKENS = {
    "ring": "ring",
    "necklace": "necklace",
    "chain": "chain",
    "pendant": "pendant",
    "earring": "earring",
    "bracelet": "bracelet",
    "bangle": "bangle",
    "anklet": "anklet",
    "brooch": "brooch",
}


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
        "side_stone_quantity": None,
        "side_stone_total_carat_weight": None,
        "side_stone_shape": None,
        "side_stone_color": None,
        "side_stone_clarity": None,
        "side_stone_cut": None,
    }


def _normalize_text(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip())


def _canonical_jewelry_type(value: Optional[str]) -> Optional[str]:
    if not value:
        return None
    t = str(value).strip().lower()
    loose_tokens = [
        "loose",
        "loose diamond",
        "single stone",
        "stone only",
    ]
    jewelry_tokens = [
        "ring",
        "necklace",
        "chain",
        "pendant",
        "earring",
        "bracelet",
        "bangle",
        "anklet",
        "brooch",
        "jewelry",
        "jewellery",
        "diamond jewelry",
        "diamond jewellery",
    ]
    if any(tok in t for tok in loose_tokens):
        return "Loose Diamond"
    if any(tok in t for tok in jewelry_tokens):
        return "Diamond Jewelry"
    # Fuzzy rescue for typos like "neckalce", "braclet", "earing".
    words = re.findall(r"[a-z]+", t)
    for w in words:
        if difflib.get_close_matches(w, jewelry_tokens, n=1, cutoff=0.82):
            return "Diamond Jewelry"
    # Strong jewelry intent signals (avoid broad "g " false positives).
    if any(x in t for x in ["gold", "platinum", "pt950", "gram", "grams"]):
        return "Diamond Jewelry"
    if re.search(r"\b\d+(?:\.\d+)?\s*(?:g|gram|grams)\b", t):
        return "Diamond Jewelry"
    return None


def _extract_with_regex(text: str) -> Dict:
    t = _normalize_text(text).lower()
    out = {}

    inferred_type = _canonical_jewelry_type(t)
    if inferred_type:
        out["jewelry_type"] = inferred_type
    for token, item in ITEM_TYPE_TOKENS.items():
        if token in t:
            out["jewelry_item_type"] = item
            break

    center_terms = [
        "center stone",
        "centre stone",
        "main stone",
        "primary stone",
        "solitaire",
        "single stone",
    ]
    explicit_no_center = any(
        p in t
        for p in [
            "no center stone",
            "without center stone",
            "center stone not present",
            "only side stone",
            "only side stones",
            "side stones only",
        ]
    )

    carat_match = re.search(r"(\d+(?:\.\d+)?)\s*(?:ct|carat)", t)
    if carat_match:
        out["carat"] = float(carat_match.group(1))

    for shape_l, shape in SHAPE_LOOKUP.items():
        if shape_l in t:
            out["shape"] = shape
            break

    color_match = re.search(r"(?:color|colour)\s*[:\-]?\s*([d-z])\b", t, re.IGNORECASE)
    if color_match:
        c = color_match.group(1).upper()
        if c in COLORS:
            out["color"] = c
    else:
        # Support casual replies like "e", "maybe e", "probably h"
        isolated = re.findall(r"\b([d-z])\b", _normalize_text(text), flags=re.IGNORECASE)
        for c in isolated:
            cu = c.upper()
            if cu in COLORS:
                out["color"] = cu
                break

    for key, val in CLARITY_LOOKUP.items():
        if re.search(rf"\b{re.escape(key)}\b", t):
            out["clarity"] = val
            break

    for key, val in CUT_LOOKUP.items():
        if key in t:
            out["cut"] = val
            break
    if "cut" not in out:
        tokens = re.findall(r"\b[a-z]+\b", t)
        for tk in tokens:
            if tk in CUT_ALIASES:
                out["cut"] = CUT_ALIASES[tk]
                break

    for key, val in FLUORESCENCE_LOOKUP.items():
        if key in t:
            out["fluorescence"] = val
            break

    for key, val in COND_LOOKUP.items():
        if key in t:
            out["condition"] = val
            break
    if "condition" not in out:
        if "almost new" in t or "like-new" in t:
            out["condition"] = "Like New"

    purity_match = re.search(r"\b(10k|12k|14k|16k|18k|22k|pt950)\b", t)
    if purity_match:
        out["purity"] = purity_match.group(1).upper()

    if "yellow gold" in t:
        out["metal"] = "Yellow Gold"
    elif "white gold" in t:
        out["metal"] = "White Gold"
    elif "rose gold" in t:
        out["metal"] = "Rose Gold"
    elif "dual tone" in t:
        out["metal"] = "Dual Tone Gold"
    elif "platinum" in t:
        out["metal"] = "Platinum"

    wt_match = re.search(r"(\d+(?:\.\d+)?)\s*(?:g|gram|grams)", t)
    if wt_match:
        out["metal_weight_grams"] = float(wt_match.group(1))

    side_groups = []
    pair_pattern = re.compile(
        r"(\d+)\s*(?:side\s*stones?|stones)\b[^\d]{0,24}"
        r"(?:tcw|total\s*carat(?:\s*weight)?|carat(?:\s*weight)?)\s*(?:is\s*)?"
        r"(\d+(?:\.\d+)?)\s*(?:ct|carat)?"
    )
    for m in pair_pattern.finditer(t):
        qty = int(m.group(1))
        tcw = float(m.group(2))
        if qty > 0 and tcw > 0:
            side_groups.append(
                {"stone_type": "Diamond", "quantity": qty, "total_carat_weight": tcw}
            )

    side_qty_match = re.search(r"(\d+)\s*(?:side\s*stones?|stones)\b", t)
    side_tcw_match = re.search(
        r"(?:side\s*stones?.*?(?:total|tcw|carat)|tcw)\D*(\d+(?:\.\d+)?)\s*(?:ct|carat)?",
        t,
    )
    if side_groups:
        out["side_stones"] = side_groups
        out["side_stone_present"] = True
        out["side_stone_quantity"] = sum(g["quantity"] for g in side_groups)
        out["side_stone_total_carat_weight"] = round(sum(g["total_carat_weight"] for g in side_groups), 4)
    else:
        if side_qty_match:
            out["side_stone_present"] = True
            out["side_stone_quantity"] = int(side_qty_match.group(1))
        if side_tcw_match:
            out["side_stone_present"] = True
            out["side_stone_total_carat_weight"] = float(side_tcw_match.group(1))

    if (
        "carat" in out
        and ("tcw" in t or "side stone" in t or "side stones" in t or "total carat" in t)
        and not any(term in t for term in center_terms)
    ):
        out["carat"] = None

    if explicit_no_center and out.get("side_stone_present") is True:
        out["carat"] = None

    for key, val in BRAND_LOOKUP.items():
        if key in t:
            out["brand_selection"] = val
            out["brand"] = val
            break
    if any(x in t for x in ["unbranded", "unknown brand", "no brand", "other brand"]):
        out["brand_selection"] = "Other / Unknown"
        out["brand"] = None

    return out


def _extract_with_llm(
    message: str, existing: Dict, last_asked_key: Optional[str] = None
) -> Tuple[Dict, bool, Dict]:
    if not OPENAI_API_KEY:
        return {}, False, {"no_side_stones_intent": False, "answer_confidence": 0.0}
    try:
        from openai import OpenAI
    except Exception:
        return {}, False, {"no_side_stones_intent": False, "answer_confidence": 0.0}

    client = OpenAI(api_key=OPENAI_API_KEY)
    prompt = (
        "Extract jewelry fields from user message and detect if user means 'unknown' for the last asked field.\n"
        "Return strict JSON only in this format:\n"
        "{\n"
        '  "fields": {\n'
        '    "jewelry_type": null|string,\n'
        '    "carat": null|number,\n'
        '    "shape": null|string,\n'
        '    "color": null|string,\n'
        '    "clarity": null|string,\n'
        '    "cut": null|string,\n'
        '    "fluorescence": null|string,\n'
        '    "condition": null|string,\n'
        '    "metal": null|string,\n'
        '    "purity": null|string,\n'
        '    "metal_weight_grams": null|number,\n'
        '    "side_stone_present": null|boolean,\n'
        '    "side_stone_quantity": null|number,\n'
        '    "side_stone_total_carat_weight": null|number\n'
        "  },\n"
        '  "unknown_intent_for_last_asked_key": boolean,\n'
        '  "no_side_stones_intent": boolean,\n'
        '  "answer_confidence": number\n'
        "}\n"
        "Do not infer unspecified fields. If user did not explicitly provide a value, return null for that field.\n"
        "Set no_side_stones_intent=true when user says there are no side stones, even indirectly.\n"
        "Set answer_confidence between 0 and 1 for how confidently this message answered the asked field.\n"
        "Set unknown_intent_for_last_asked_key=true when user indicates uncertainty "
        "(e.g., not sure, no clue, idk, unknown, cannot say), specifically for the asked field.\n"
        f"Current known values: {json.dumps(existing)}\n"
        f"Last asked key: {last_asked_key}\n"
        f"Message: {message}"
    )
    try:
        resp = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            temperature=0,
            max_tokens=260,
            response_format={"type": "json_object"},
        )
        data = json.loads(resp.choices[0].message.content or "{}")
        if isinstance(data, dict):
            # backward-compat: if model returns flat dict, treat as fields
            if "fields" not in data:
                meta = {
                    "no_side_stones_intent": bool(data.get("no_side_stones_intent", False)),
                    "answer_confidence": float(data.get("answer_confidence") or 0.0),
                }
                return data, bool(data.get("unknown_intent_for_last_asked_key", False)), meta
            fields = data.get("fields") or {}
            unknown_intent = bool(data.get("unknown_intent_for_last_asked_key", False))
            meta = {
                "no_side_stones_intent": bool(data.get("no_side_stones_intent", False)),
                "answer_confidence": float(data.get("answer_confidence") or 0.0),
            }
            return fields if isinstance(fields, dict) else {}, unknown_intent, meta
    except Exception:
        return {}, False, {"no_side_stones_intent": False, "answer_confidence": 0.0}
    return {}, False, {"no_side_stones_intent": False, "answer_confidence": 0.0}


def _merge_profile(profile: Dict, updates: Dict) -> Dict:
    for k, v in updates.items():
        if k not in profile:
            continue
        if v is None or v == "":
            continue
        if k in ("carat", "metal_weight_grams", "side_stone_total_carat_weight"):
            try:
                profile[k] = float(v)
            except Exception:
                continue
        elif k in ("side_stone_quantity",):
            try:
                profile[k] = int(v)
            except Exception:
                continue
        elif k in ("side_stone_present",):
            if isinstance(v, bool):
                profile[k] = v
            elif str(v).strip().lower() in ("yes", "y", "true", "1"):
                profile[k] = True
            elif str(v).strip().lower() in ("no", "n", "false", "0"):
                profile[k] = False
        elif k in ("color", "clarity", "purity"):
            profile[k] = str(v).upper().strip()
        elif k in (
            "shape",
            "cut",
            "fluorescence",
            "condition",
            "metal",
            "jewelry_type",
            "jewelry_item_type",
            "side_stone_shape",
            "side_stone_color",
            "side_stone_clarity",
            "side_stone_cut",
        ):
            profile[k] = str(v).strip()
        else:
            profile[k] = v
    return profile


def _coerce_enum(value: Optional[str], allowed: list, aliases: Optional[dict] = None) -> Optional[str]:
    if value in (None, ""):
        return None
    s = str(value).strip()
    if not s:
        return None
    if s in allowed:
        return s
    s_lower = s.lower()
    alias_map = aliases or {}
    if s_lower in alias_map:
        v = alias_map[s_lower]
        return v if v in allowed else None
    allowed_l = {a.lower(): a for a in allowed}
    if s_lower in allowed_l:
        return allowed_l[s_lower]
    # fuzzy rescue for typos like "whte gold", "vvs-1", etc.
    match = difflib.get_close_matches(s_lower, list(allowed_l.keys()), n=1, cutoff=0.84)
    if match:
        return allowed_l[match[0]]
    return None


def _llm_field_is_explicit(key: str, message: str, last_asked_key: Optional[str]) -> bool:
    t = _normalize_text(message).lower()
    if last_asked_key == key:
        return True
    if key == "condition":
        condition_phrases = [
            "condition",
            "like new",
            "almost new",
            "minor wear",
            "noticeable wear",
            "needs repair",
            "fair condition",
            "good condition",
            "excellent condition",
        ]
        return any(p in t for p in condition_phrases)
    if key == "brand_selection":
        return any(
            p in t
            for p in [
                "brand",
                "branded",
                "unbranded",
                "no brand",
                "unknown brand",
                "cartier",
                "tiffany",
                "bulgari",
                "harry winston",
                "van cleef",
            ]
        )
    return True


QUESTION_VARIANTS = {
    "jewelry_type": [
        "What are you pricing today: **Loose Diamond** or **Diamond Jewelry**?",
        "Quick one: is this a **Loose Diamond** or a **Diamond Jewelry** piece?",
    ],
    "carat": [
        "What’s the center stone carat? (example: `1.20 ct`)",
        "Could you share the center stone weight in carats? (like `1.2 ct`)",
    ],
    "shape": [
        "What shape is the center stone? (Round, Oval, Princess, Emerald, etc.)",
        "Which shape best matches the center stone?",
    ],
    "color": [
        "What color grade do you know? (D to Z)",
        "Do you know the color grade? (D–Z)",
    ],
    "clarity": [
        "What clarity is it? (IF, VVS1, VS1, SI1, etc.)",
        "Can you share the clarity grade? (VS1/SI1/VVS2...)",
    ],
    "cut": [
        "What’s the cut grade? (Ideal / Excellent / Very Good / Good)",
        "Do you know the cut grade? (Ideal, Excellent, Very Good, Good)",
    ],
    "fluorescence": [
        "Do you know fluorescence? (None / Faint / Medium / Strong / Very Strong)",
        "Any fluorescence noted on report? (None, Faint, Medium, Strong, Very Strong)",
    ],
    "condition": [
        "How would you describe condition? (Excellent / Like New / Good / Fair)",
        "Condition check: Excellent, Like New, Good, or Fair?",
    ],
    "metal": [
        "What metal is the piece made of? (White/Yellow/Rose Gold, Dual Tone, Platinum)",
        "What metal should I use for valuation?",
    ],
    "purity": [
        "What purity is it? (10K/12K/14K/16K/18K/22K/PT950)",
        "Could you share the metal purity? (14K, 18K, PT950...)",
    ],
    "metal_weight_grams": [
        "Approx metal weight in grams? (example: `4.2 g`)",
        "Do you know the metal weight? (just a rough grams estimate is fine)",
    ],
    "side_stone_present": [
        "Any side stones in the piece? (yes/no)",
        "Does it include side stones or just center stone? (yes/no)",
    ],
    "side_stone_quantity": [
        "How many side stones are there? (number only)",
        "About how many side stones should I consider?",
    ],
    "side_stone_total_carat_weight": [
        "Total side-stone carat weight? (example: `0.40 ct`)",
        "What’s the combined side-stone weight in carats?",
    ],
    "brand_selection": [
        "Is this a branded piece? (yes/no). If yes, you can also type the brand name.",
        "Is it branded? (yes/no). You can mention brand name if known.",
    ],
    "brand_proof": [
        "Do you have brand proof/invoice/certificate? (yes/no)",
        "Brand proof available? (yes/no)",
    ],
}


def _question_for(key: str, turn_seed: int) -> str:
    variants = QUESTION_VARIANTS.get(key, [f"Please share: {key}"])
    idx = turn_seed % len(variants)
    return variants[idx]


FUN_ACK_TEMPLATES = [
    "Love it.",
    "Perfect.",
    "Great, thanks.",
    "Nice one.",
    "Awesome.",
]

FUN_LOW_CONF_TEMPLATES = [
    "Quick check: I might have missed that detail in your last message.",
    "Tiny clarification so I can be more accurate.",
    "Let’s lock one detail to keep your estimate sharp.",
    "I want to avoid guessing here, one quick confirmation.",
]

FUN_ASSUMPTION_TEMPLATES = [
    "No stress, I’ll use a standard assumption for `{field}` and keep moving.",
    "All good, I’ll use a common default for `{field}` for now.",
    "Got you. I’ll apply a practical default for `{field}` and continue.",
]

FUN_PRICE_TEMPLATES = [
    "Great signal so far. A strong listing range is **${low:,.0f} - ${high:,.0f}**.",
    "You’re in a healthy market zone. I’d list around **${low:,.0f} - ${high:,.0f}**.",
    "Nice setup. A competitive resale window is **${low:,.0f} - ${high:,.0f}**.",
]


def _pick_template(templates: list, seed: int) -> str:
    if not templates:
        return ""
    return templates[seed % len(templates)]


def _extraction_confidence(
    user_msg: str,
    regex_updates: Dict,
    llm_updates: Dict,
    last_asked_key: Optional[str],
    llm_unknown_intent: bool,
) -> float:
    merged = dict(regex_updates)
    merged.update({k: v for k, v in llm_updates.items() if v not in (None, "")})
    merged_count = len(merged)
    token_count = len(re.findall(r"[a-zA-Z0-9]+", user_msg or ""))

    score = 0.0
    if merged_count == 0:
        score = 0.15
    elif merged_count == 1:
        score = 0.45
    elif merged_count == 2:
        score = 0.62
    else:
        score = 0.78

    if last_asked_key and merged.get(last_asked_key) not in (None, ""):
        score += 0.15
    if llm_unknown_intent and last_asked_key:
        score += 0.1
    if token_count <= 2 and merged_count == 0:
        score -= 0.1
    return max(0.0, min(1.0, score))


def _next_question(profile: Dict, turn_seed: int) -> Tuple[Optional[str], Optional[str]]:
    has_center_stone = float(profile.get("carat") or 0.0) > 0
    has_side_groups = isinstance(profile.get("side_stones"), list) and len(profile.get("side_stones")) > 0
    has_valid_side_stones = (
        has_side_groups
        or (
            profile.get("side_stone_present") is True
            and int(profile.get("side_stone_quantity") or 0) > 0
            and float(profile.get("side_stone_total_carat_weight") or 0.0) > 0
        )
    )

    required = ["jewelry_type", "condition"]
    if has_center_stone:
        required.extend(["carat", "shape", "color", "clarity", "cut", "fluorescence"])
    elif not has_valid_side_stones:
        required.append("carat")
    if profile.get("jewelry_type") == "Diamond Jewelry":
        required.extend(
            [
                "metal",
                "purity",
                "metal_weight_grams",
                "brand_selection",
                "side_stone_present",
            ]
        )
        if profile.get("side_stone_present") is True:
            required.extend(["side_stone_quantity", "side_stone_total_carat_weight"])

    for key in required:
        if profile.get(key) in (None, ""):
            return key, _question_for(key, turn_seed)
    return None, None


def _is_unknown_reply(text: str) -> bool:
    t = _normalize_text(text).lower()
    signals = [
        "dk",
        "idk",
        "i dk",
        "i dont know",
        "i don't know",
        "dunno",
        "dont know",
        "don't know",
        "do not know",
        "not sure",
        "no idea",
        "unknown",
        "skip",
        "na",
        "n/a",
    ]
    return any(s in t for s in signals)


def _message_implies_side_stones_only(text: str) -> bool:
    t = _normalize_text(text).lower()
    negative_center = [
        "no center stone",
        "without center stone",
        "center stone not present",
        "only side stone",
        "only side stones",
        "side stones only",
    ]
    has_negative_center = any(p in t for p in negative_center)
    has_side_signal = any(p in t for p in ["tcw", "side stone", "side stones"])
    has_center_signal = any(
        p in t for p in ["center stone", "centre stone", "main stone", "solitaire", "single stone"]
    )
    return has_negative_center or (has_side_signal and not has_center_signal)


def _default_metal_weight(item_type: Optional[str]) -> float:
    default_by_item = {
        "ring": 4.0,
        "earring": 3.0,
        "pendant": 5.0,
        "necklace": 12.0,
        "chain": 10.0,
        "bracelet": 10.0,
        "bangle": 18.0,
        "anklet": 8.0,
        "brooch": 7.0,
    }
    return float(default_by_item.get((item_type or "").lower(), 6.0))


def _default_for_missing_key(key: str, profile: Optional[Dict] = None):
    defaults = {
        "cut": "Excellent",
        "color": "G",
        "clarity": "VS1",
        "condition": "Excellent",
        "fluorescence": "None",
        "shape": "Round",
        "metal": "White Gold",
        "purity": "14K",
        "side_stone_present": False,
        "brand_selection": "Other / Unknown",
        "brand_proof": "No",
    }
    if key == "metal_weight_grams":
        return _default_metal_weight((profile or {}).get("jewelry_item_type"))
    return defaults.get(key)


def _parse_yes_no(text: str):
    t = _normalize_text(text).lower()
    yes_tokens = ["yes", "yep", "yeah", "y", "has", "with side", "includes"]
    no_tokens = [
        "no",
        "nope",
        "n",
        "without",
        "just center",
        "only center",
        "does not have",
        "doesn't have",
        "dont have",
        "don't have",
        "no side stone",
        "no side stones",
        "without side stone",
        "without side stones",
    ]
    if any(tok in t for tok in yes_tokens):
        return True
    if any(tok in t for tok in no_tokens):
        return False
    return None


def _no_side_stone_intent_rule(text: str) -> bool:
    t = _normalize_text(text).lower()
    patterns = [
        "no side stone",
        "no side stones",
        "without side stone",
        "without side stones",
        "does not have side stone",
        "doesn't have side stone",
        "no side diamonds",
        "without side diamonds",
        "only center stone",
        "single center stone",
        "center stone only",
    ]
    return any(p in t for p in patterns)


def _sanitize_profile(profile: Dict) -> Dict:
    p = dict(profile)
    normalized_type = _canonical_jewelry_type(p.get("jewelry_type"))
    if normalized_type:
        p["jewelry_type"] = normalized_type
    elif p.get("jewelry_type") not in ("Loose Diamond", "Diamond Jewelry", None, ""):
        p["jewelry_type"] = None
    if p.get("shape") and p["shape"] not in SHAPES:
        for s in SHAPES:
            if s.lower() in p["shape"].lower():
                p["shape"] = s
                break
    if p.get("shape") and p["shape"] not in SHAPES:
        p["shape"] = _coerce_enum(p.get("shape"), SHAPES)
    if p.get("shape") not in SHAPES:
        p["shape"] = None

    if p.get("color"):
        c = str(p["color"]).strip().upper().replace(" ", "")
        p["color"] = c if c in COLORS else None

    p["clarity"] = _coerce_enum(p.get("clarity"), CLARITIES, CLARITY_ALIASES)
    p["cut"] = _coerce_enum(p.get("cut"), CUTS, CUT_ALIASES)
    if p.get("condition") and p["condition"] not in CONDITIONS:
        condition_aliases = {
            "almost new": "Like New",
            "like-new": "Like New",
            "minor wear": "Good",
            "good/minor wear": "Good",
            "needs repair": "Fair",
            "noticeable wear": "Fair",
            "ex": "Excellent",
            "exc": "Excellent",
        }
        alias = condition_aliases.get(str(p["condition"]).strip().lower())
        if alias:
            p["condition"] = alias
    p["condition"] = _coerce_enum(p.get("condition"), CONDITIONS, {
        "almost new": "Like New",
        "like-new": "Like New",
        "minor wear": "Good",
        "good/minor wear": "Good",
        "needs repair": "Fair",
        "noticeable wear": "Fair",
        "ex": "Excellent",
        "exc": "Excellent",
    })
    if p.get("metal") and p["metal"] not in METALS:
        m = str(p["metal"]).lower()
        for k, v in METAL_LOOKUP.items():
            if k in m:
                p["metal"] = v
                break
    p["metal"] = _coerce_enum(p.get("metal"), METALS)
    if p.get("fluorescence") and p["fluorescence"] not in FLUORESCENCE:
        f = str(p["fluorescence"]).lower()
        for k, v in FLUORESCENCE_LOOKUP.items():
            if k in f:
                p["fluorescence"] = v
                break
    p["fluorescence"] = _coerce_enum(p.get("fluorescence"), FLUORESCENCE)
    if p.get("brand_selection"):
        b = str(p["brand_selection"]).strip().lower()
        if b in ("yes", "y", "true", "1", "branded"):
            p["brand_selection"] = "Other / Unknown"
            if not p.get("brand"):
                p["brand"] = "Branded (unspecified)"
        elif b in ("no", "n", "false", "0", "unbranded", "unknown"):
            p["brand_selection"] = "Other / Unknown"
            p["brand"] = None
            p["brand_proof"] = "No"
        elif b in BRAND_LOOKUP:
            p["brand_selection"] = BRAND_LOOKUP[b]
            p["brand"] = BRAND_LOOKUP[b]
        elif b in ("other / unknown", "other"):
            p["brand_selection"] = "Other / Unknown"
            if not p.get("brand"):
                p["brand"] = None
        else:
            # free-form unknown brand
            p["brand_selection"] = "Other / Unknown"
            if not p.get("brand"):
                p["brand"] = None
    if p.get("brand_proof") not in ("Yes", "No", None, ""):
        bp = str(p["brand_proof"]).strip().lower()
        if bp in ("yes", "y", "true", "1"):
            p["brand_proof"] = "Yes"
        elif bp in ("no", "n", "false", "0"):
            p["brand_proof"] = "No"
        else:
            p["brand_proof"] = None

    # Purity normalization.
    p["purity"] = _coerce_enum(p.get("purity"), PURITY, {
        "950pt": "PT950",
        "pt 950": "PT950",
        "pt-950": "PT950",
        "pt": "PT950",
    })

    # Numeric guards.
    try:
        if p.get("carat") is not None:
            p["carat"] = float(p["carat"])
            if p["carat"] <= 0:
                p["carat"] = None
    except Exception:
        p["carat"] = None
    try:
        if p.get("metal_weight_grams") is not None:
            p["metal_weight_grams"] = float(p["metal_weight_grams"])
            if p["metal_weight_grams"] <= 0:
                p["metal_weight_grams"] = None
    except Exception:
        p["metal_weight_grams"] = None
    try:
        if p.get("side_stone_quantity") is not None:
            p["side_stone_quantity"] = int(p["side_stone_quantity"])
            if p["side_stone_quantity"] <= 0:
                p["side_stone_quantity"] = None
    except Exception:
        p["side_stone_quantity"] = None
    try:
        if p.get("side_stone_total_carat_weight") is not None:
            p["side_stone_total_carat_weight"] = float(p["side_stone_total_carat_weight"])
            if p["side_stone_total_carat_weight"] <= 0:
                p["side_stone_total_carat_weight"] = None
    except Exception:
        p["side_stone_total_carat_weight"] = None

    raw_groups = p.get("side_stones") if isinstance(p.get("side_stones"), list) else []
    cleaned_groups = []
    for g in raw_groups:
        if not isinstance(g, dict):
            continue
        try:
            qty = int(g.get("quantity") or 0)
            tcw = float(g.get("total_carat_weight") or 0.0)
        except Exception:
            continue
        if qty <= 0 or tcw <= 0:
            continue
        cleaned_groups.append(
            {
                "stone_type": "Diamond",
                "quantity": qty,
                "total_carat_weight": tcw,
                "shape": g.get("shape"),
                "color": g.get("color"),
                "clarity": g.get("clarity"),
                "cut": g.get("cut"),
                "polish": g.get("polish"),
                "symmetry": g.get("symmetry"),
                "fluorescence": g.get("fluorescence"),
            }
        )
    p["side_stones"] = cleaned_groups
    if cleaned_groups:
        p["side_stone_present"] = True
        p["side_stone_quantity"] = sum(g["quantity"] for g in cleaned_groups)
        p["side_stone_total_carat_weight"] = round(sum(g["total_carat_weight"] for g in cleaned_groups), 4)

    if p.get("jewelry_type") == "Loose Diamond":
        p["jewelry_item_type"] = None
        p["metal"] = None
        p["purity"] = None
        p["metal_weight_grams"] = None
        p["brand_selection"] = None
        p["brand"] = None
        p["brand_proof"] = None
        p["side_stone_present"] = False
        p["side_stone_quantity"] = None
        p["side_stone_total_carat_weight"] = None
        p["side_stone_shape"] = None
        p["side_stone_color"] = None
        p["side_stone_clarity"] = None
        p["side_stone_cut"] = None

    return p


def _friendly_error_message(err_text: str) -> str:
    t = (err_text or "").lower()
    if "rapnet" in t or "token" in t or "401" in t or "403" in t:
        return "I couldn’t fetch live market data right now. Please check token/access and try again."
    if "index" in t or "not in list" in t or "keyerror" in t or "valueerror" in t:
        return "I understood most details, but one field format wasn’t recognized. Please rephrase once and I’ll continue."
    if "timeout" in t or "connection" in t:
        return "The pricing service timed out. Please retry in a moment."
    return "I couldn’t complete this estimate right now. Please try once more with the same details."


def _nested_get(data, path, default=None):
    cur = data
    for key in path:
        if isinstance(cur, dict) and key in cur:
            cur = cur[key]
        else:
            return default
    return cur


def _build_product_url(comp: Dict) -> str:
    direct_url = comp.get("url") or comp.get("product_url")
    if direct_url:
        return str(direct_url)
    slug = comp.get("slug")
    if slug:
        slug = str(slug).strip().lstrip("/")
        if slug.startswith("http://") or slug.startswith("https://"):
            return slug
        return f"https://www.gemgem.com/product/{slug}"
    return "N/A"


def _extract_comparable_specs(comp: Dict) -> Dict:
    listing_id = (
        comp.get("listing_id")
        or comp.get("id")
        or _nested_get(comp, ["diamond_id"])
        or _nested_get(comp, ["stock_num"])
    )
    name = (
        comp.get("name")
        or _nested_get(comp, ["title"])
        or _nested_get(comp, ["description"])
        or "N/A"
    )
    price_usd = (
        _nested_get(comp, ["price", "USD", "price"])
        or comp.get("total_sales_price")
        or comp.get("price_usd")
        or "N/A"
    )
    return {
        "Listing ID": listing_id if listing_id is not None else "N/A",
        "Name": name,
        "Price (USD)": price_usd,
        "Similarity Weight": comp.get("similarity_weight", "N/A"),
        "Product URL": _build_product_url(comp),
    }


def _sort_comparables_for_display(comparables):
    indexed = list(enumerate(comparables))

    def _weight(comp):
        try:
            v = comp.get("similarity_weight")
            if v in (None, "", "N/A"):
                return None
            return float(v)
        except Exception:
            return None

    def _key(item):
        idx, comp = item
        w = _weight(comp)
        if w is None:
            return (1, 0.0, idx)
        return (0, -w, idx)

    return [comp for _, comp in sorted(indexed, key=_key)]


def _display_comparables_chatbot(result: Dict):
    comparables = result.get("comparables") or []
    count = int(result.get("comparable_count") or len(comparables) or 0)
    with st.expander(f"Comparable Diamonds Used ({count})", expanded=False):
        if not comparables:
            st.write("No comparable references available.")
            return
        rows = [_extract_comparable_specs(c) for c in _sort_comparables_for_display(comparables)]
        st.dataframe(
            rows,
            hide_index=True,
            use_container_width=True,
            column_config={
                "Product URL": st.column_config.LinkColumn("Product URL"),
                "Similarity Weight": st.column_config.NumberColumn("Similarity Weight", format="%.3f"),
            },
        )


def _fmt_usd(value):
    try:
        if value is None:
            return "N/A"
        return f"${float(value):,.2f}"
    except Exception:
        return "N/A"


def _render_min_max_block(title: str, low, high):
    st.markdown(f"**{title}**")
    c1, c2 = st.columns(2)
    c1.metric("Min", _fmt_usd(low))
    c2.metric("Max", _fmt_usd(high))


def _render_chatbot_result_details(result: Dict):
    center = result.get("diamond_anchor") or {}
    side = result.get("side_stones_value") or {"low": 0, "high": 0}
    metal_value = float(result.get("metal_value") or 0.0)
    metal_error = result.get("metal_error")
    ai_adjust = result.get("ai_adjustment") or {"adjustment_percent": 0}
    final_price = result.get("final_price") or {}

    final_low = final_price.get("low")
    final_high = final_price.get("high")
    if final_low is None or final_high is None:
        final_low = (center.get("low") or 0) + (side.get("low") or 0) + metal_value
        final_high = (center.get("high") or 0) + (side.get("high") or 0) + metal_value

    _render_min_max_block(
        "Diamond Value (Center + Side Stones)",
        (center.get("low") or 0) + (side.get("low") or 0),
        (center.get("high") or 0) + (side.get("high") or 0),
    )
    _render_min_max_block("Metal Value", metal_value, metal_value)
    if metal_error:
        st.warning("Metal component could not be fetched from live pricing API; metal value is shown as $0.00.")
    _render_min_max_block("Total Price Range (After All Adjustments)", final_low, final_high)

    with st.expander("Center Stone Details", expanded=False):
        _render_min_max_block("Center Stone Value", center.get("low"), center.get("high"))
        eff = result.get("effective_specs")
        conf = result.get("anchor_confidence")
        expansion = result.get("fallback_expansion")
        if eff:
            st.write(f"Shape: {eff.get('shape') or 'N/A'}")
            st.write(f"Carat Range: {eff.get('carat_min')} - {eff.get('carat_max')}")
            st.write(f"Color Range: {eff.get('color')}")
            st.write(f"Clarity Range: {eff.get('clarity')}")
            st.write(f"Lab: {eff.get('lab') or eff.get('labs') or 'N/A'}")
        if conf:
            st.write(f"Anchor Confidence: {conf.get('label', 'N/A')} ({conf.get('score', 'N/A')})")
            st.write(f"Thin-Data Discount Multiplier: {conf.get('thin_data_discount_multiplier', 'N/A')}")
        if expansion:
            st.write(
                "Fallback Expansion: "
                f"carat_delta={expansion.get('carat_delta')}, "
                f"color_expand={expansion.get('color_expand')}, "
                f"clarity_expand={expansion.get('clarity_expand')}, "
                f"lab_broadened={expansion.get('lab_broadened')}"
            )

    with st.expander("Side Stones Details", expanded=False):
        _render_min_max_block("Side Stones Value", side.get("low"), side.get("high"))
        breakdown = result.get("side_stones_breakdown", [])
        if breakdown:
            st.dataframe(breakdown, hide_index=True, use_container_width=True)
        else:
            st.write("No side stones added.")

        side_comp_groups = result.get("side_stones_comparables", [])
        for group in side_comp_groups:
            if group.get("price_source") != "market_comparables":
                continue
            comp_count = int(group.get("comparable_count") or 0)
            if comp_count <= 0:
                continue
            group_idx = group.get("index")
            with st.expander(f"Side Stone Group {group_idx} Comparables ({comp_count})", expanded=False):
                rows = [_extract_comparable_specs(comp) for comp in _sort_comparables_for_display(group.get("comparables", []))]
                if rows:
                    st.dataframe(
                        rows,
                        hide_index=True,
                        use_container_width=True,
                        column_config={"Product URL": st.column_config.LinkColumn("Product URL")},
                    )
                else:
                    st.write("No comparable references available for this side-stone group.")

    with st.expander("Metal Details", expanded=False):
        _render_min_max_block("Metal Value", metal_value, metal_value)
        st.write({"metal_value_usd": _fmt_usd(metal_value)})

    st.markdown("**AI Adjustment**")
    st.write(f"Adjustment Percent: {ai_adjust.get('adjustment_percent', 0)}%")
    if ai_adjust.get("key_drivers"):
        st.write(f"Key Drivers: {', '.join(ai_adjust.get('key_drivers', []))}")
    if ai_adjust.get("missing_info"):
        st.write(f"Missing Info: {', '.join(ai_adjust.get('missing_info', []))}")

    _display_comparables_chatbot(result)


def _build_user_input(profile: Dict) -> Dict:
    side_stones = []
    explicit_groups = profile.get("side_stones") if isinstance(profile.get("side_stones"), list) else []
    if explicit_groups:
        for g in explicit_groups:
            if not isinstance(g, dict):
                continue
            side_stones.append(
                {
                    "stone_type": "Diamond",
                    "quantity": int(g.get("quantity") or 0),
                    "total_carat_weight": float(g.get("total_carat_weight") or 0.0),
                    "shape": g.get("shape") or profile.get("side_stone_shape") or profile.get("shape"),
                    "color": g.get("color") or profile.get("side_stone_color") or profile.get("color"),
                    "clarity": g.get("clarity") or profile.get("side_stone_clarity") or profile.get("clarity"),
                    "cut": g.get("cut") or profile.get("side_stone_cut") or profile.get("cut"),
                    "polish": g.get("polish"),
                    "symmetry": g.get("symmetry"),
                    "fluorescence": g.get("fluorescence"),
                }
            )
    elif (
        profile.get("side_stone_present") is True
        and profile.get("side_stone_quantity")
        and profile.get("side_stone_total_carat_weight")
    ):
        side_stones = [
            {
                "stone_type": "Diamond",
                "quantity": int(profile.get("side_stone_quantity")),
                "total_carat_weight": float(profile.get("side_stone_total_carat_weight")),
                "shape": profile.get("side_stone_shape") or profile.get("shape"),
                "color": profile.get("side_stone_color") or profile.get("color"),
                "clarity": profile.get("side_stone_clarity") or profile.get("clarity"),
                "cut": profile.get("side_stone_cut") or profile.get("cut"),
                "polish": None,
                "symmetry": None,
                "fluorescence": None,
            }
        ]

    return {
        "images": [],
        "jewelry_type": profile.get("jewelry_type") or "Loose Diamond",
        "center_stone": {
            "shape": profile.get("shape") or "Round",
            "carat": profile.get("carat") or 0.0,
            "color": profile.get("color"),
            "clarity": profile.get("clarity"),
            "cut": profile.get("cut"),
            "polish": None,
            "symmetry": None,
            "fluorescence": profile.get("fluorescence"),
        },
        "condition": profile.get("condition") or "Excellent",
        "metal": profile.get("metal"),
        "purity": profile.get("purity"),
        "metal_weight_grams": profile.get("metal_weight_grams"),
        "side_stones": side_stones,
        "brand_selection": profile.get("brand_selection") or "Other / Unknown",
        "brand": profile.get("brand"),
        "brand_proof": profile.get("brand_proof") or "No",
    }


def _prepare_safe_user_input(profile: Dict) -> Dict:
    # Work on sanitized profile clone.
    p = _sanitize_profile(dict(profile))
    if p.get("jewelry_type") == "Diamond Jewelry":
        if not p.get("metal"):
            p["metal"] = "White Gold"
        if not p.get("purity"):
            p["purity"] = "14K"
        if not p.get("metal_weight_grams"):
            p["metal_weight_grams"] = _default_metal_weight(p.get("jewelry_item_type"))
        if not p.get("brand_selection"):
            p["brand_selection"] = "Other / Unknown"
        if p.get("brand_proof") not in ("Yes", "No"):
            p["brand_proof"] = "No"
    if not p.get("condition"):
        p["condition"] = "Excellent"
    if not p.get("shape"):
        p["shape"] = "Round"
    if not p.get("cut"):
        p["cut"] = "Excellent"
    if not p.get("color"):
        p["color"] = "G"
    if not p.get("clarity"):
        p["clarity"] = "VS1"
    if not p.get("fluorescence"):
        p["fluorescence"] = "None"

    return _build_user_input(p)


def _friendly_bot_price_response(result: Dict, assumptions: Optional[list] = None, turn_seed: int = 0) -> str:
    if result.get("error"):
        err = str(result.get("error") or "").lower()
        anchor = result.get("diamond_anchor") or {}
        if "confidence is too low" in err and anchor.get("low") is not None and anchor.get("high") is not None:
            low = anchor.get("low")
            high = anchor.get("high")
            msg = (
                f"I found a provisional range of ${low:,.0f}-${high:,.0f}, "
                "but confidence is low, so manual review is recommended before quoting."
            )
            if assumptions:
                msg += "\n\nAssumptions used: " + ", ".join(sorted(set(assumptions))) + "."
            return msg
        return (
            "I couldn’t confidently price that yet. "
            "Please tweak specs slightly (especially carat/clarity/color) and I’ll try again."
        )
    fp = result.get("final_price") or {}
    low = fp.get("low")
    high = fp.get("high")
    if low is None or high is None:
        return "I found the specs, but couldn't build a final range. Please try again."
    base = _pick_template(FUN_PRICE_TEMPLATES, turn_seed)
    msg = base.format(low=low, high=high)
    msg += " It’s a solid balance between buyer appeal and seller value."
    if assumptions:
        msg += "\n\nAssumptions used for this estimate: " + ", ".join(sorted(set(assumptions))) + "."
    return msg


def _reset_chat():
    st.session_state["chat_messages"] = [
        {
            "role": "assistant",
            "content": (
                "Hi! I’m your jewelry pricing assistant. Tell me what you want to sell in one line "
                "(example: `1.2ct round H VS1 ring, 14k yellow gold, 4.5g, excellent condition`)."
            ),
        }
    ]
    st.session_state["profile"] = _default_profile()
    st.session_state["last_result"] = None
    st.session_state["ask_counts"] = {}
    st.session_state["assumptions_used"] = []


def _render_profile_snapshot(profile: Dict):
    st.caption("Captured details")
    snapshot = {
        "Type": profile.get("jewelry_type"),
        "Item Type": profile.get("jewelry_item_type"),
        "Carat": profile.get("carat"),
        "Shape": profile.get("shape"),
        "Color": profile.get("color"),
        "Clarity": profile.get("clarity"),
        "Cut": profile.get("cut"),
        "Condition": profile.get("condition"),
        "Fluorescence": profile.get("fluorescence"),
        "Metal": profile.get("metal"),
        "Purity": profile.get("purity"),
        "Metal Weight (g)": profile.get("metal_weight_grams"),
        "Brand Selection": profile.get("brand_selection"),
        "Brand": profile.get("brand"),
        "Brand Proof": profile.get("brand_proof"),
        "Side Stones Present": profile.get("side_stone_present"),
        "Side Stone Qty": profile.get("side_stone_quantity"),
        "Side Stone Total Carat": profile.get("side_stone_total_carat_weight"),
        "Side Stone Groups": profile.get("side_stones"),
    }
    st.json(snapshot)


st.set_page_config(page_title="Jewelry Pricing Chatbot MVP", page_icon="💬", layout="wide")
st.title("Jewelry Pricing Chatbot MVP")
st.caption("Conversational estimator powered by your existing pricing engine.")
if FORM_ESTIMATOR_URL:
    st.link_button("Switch To Form Estimator", FORM_ESTIMATOR_URL)

if "chat_messages" not in st.session_state:
    _reset_chat()
if "last_asked_key" not in st.session_state:
    st.session_state["last_asked_key"] = None
if "ask_counts" not in st.session_state:
    st.session_state["ask_counts"] = {}
if "assumptions_used" not in st.session_state:
    st.session_state["assumptions_used"] = []

if st.button("Start New Chat"):
    _reset_chat()
    st.rerun()

rapnet_token = None
if USE_RAPNET:
    rapnet_token = st.text_input("RapNet Bearer Token", type="password")

left, right = st.columns([1.5, 1])

with left:
    for msg in st.session_state["chat_messages"]:
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])

    user_msg = st.chat_input("Type your jewelry details...")
    if user_msg:
        st.session_state["chat_messages"].append({"role": "user", "content": user_msg})

        profile = st.session_state["profile"]
        assumptions_used = st.session_state.get("assumptions_used", [])

        # If user explicitly says they don't know the last asked field, apply a safe default.
        last_asked_key = st.session_state.get("last_asked_key")
        if last_asked_key == "jewelry_type":
            direct_type = _canonical_jewelry_type(user_msg)
            if direct_type:
                profile["jewelry_type"] = direct_type
        if last_asked_key == "side_stone_present":
            yn = _parse_yes_no(user_msg)
            if yn is not None:
                profile["side_stone_present"] = yn
        if last_asked_key == "carat":
            yn = _parse_yes_no(user_msg)
            has_valid_side_stones = (
                (
                    isinstance(profile.get("side_stones"), list)
                    and len(profile.get("side_stones")) > 0
                )
                or (
                    profile.get("side_stone_present") is True
                    and int(profile.get("side_stone_quantity") or 0) > 0
                    and float(profile.get("side_stone_total_carat_weight") or 0.0) > 0
                )
            )
            if yn is False and has_valid_side_stones:
                profile["carat"] = None
        if last_asked_key in ("side_stone_quantity", "side_stone_total_carat_weight"):
            yn = _parse_yes_no(user_msg)
            if yn is False or _no_side_stone_intent_rule(user_msg):
                profile["side_stone_present"] = False
                profile["side_stone_quantity"] = None
                profile["side_stone_total_carat_weight"] = None
        if last_asked_key == "brand_proof":
            yn = _parse_yes_no(user_msg)
            if yn is not None:
                profile["brand_proof"] = "Yes" if yn else "No"
        if last_asked_key == "brand_selection":
            yn = _parse_yes_no(user_msg)
            if yn is not None:
                profile["brand_selection"] = "Other / Unknown"
                profile["brand"] = "Branded (unspecified)" if yn else None
                if not yn:
                    profile["brand_proof"] = "No"
        if last_asked_key and _is_unknown_reply(user_msg):
            fallback = _default_for_missing_key(last_asked_key, profile)
            if fallback is not None:
                profile[last_asked_key] = fallback
                assumptions_used.append(f"{last_asked_key}={fallback}")

        regex_updates = _extract_with_regex(user_msg)
        llm_updates, llm_unknown_intent, llm_meta = _extract_with_llm(user_msg, profile, last_asked_key)
        llm_updates = {
            k: v
            for k, v in llm_updates.items()
            if _llm_field_is_explicit(k, user_msg, last_asked_key)
        }
        extraction_conf = _extraction_confidence(
            user_msg=user_msg,
            regex_updates=regex_updates,
            llm_updates=llm_updates,
            last_asked_key=last_asked_key,
            llm_unknown_intent=llm_unknown_intent,
        )
        llm_answer_conf = float((llm_meta or {}).get("answer_confidence") or 0.0)
        effective_conf = max(extraction_conf, llm_answer_conf)
        merged_updates = dict(regex_updates)
        merged_updates.update({k: v for k, v in llm_updates.items() if v not in (None, "")})
        profile = _merge_profile(profile, merged_updates)
        profile = _sanitize_profile(profile)
        if (
            _message_implies_side_stones_only(user_msg)
            and profile.get("side_stone_present") is True
            and float(profile.get("side_stone_total_carat_weight") or 0.0) > 0
        ):
            profile["carat"] = None
            profile = _sanitize_profile(profile)
        inferred_type = _canonical_jewelry_type(user_msg)
        if inferred_type and inferred_type != profile.get("jewelry_type"):
            profile["jewelry_type"] = inferred_type
            profile = _sanitize_profile(profile)

        # AI intent override: user indicates no side stones.
        if (llm_meta or {}).get("no_side_stones_intent"):
            profile["side_stone_present"] = False
            profile["side_stone_quantity"] = None
            profile["side_stone_total_carat_weight"] = None

        # Generic AI intent handling: if user intent is "unknown" for asked field, auto-default and continue.
        if last_asked_key and llm_unknown_intent and profile.get(last_asked_key) in (None, ""):
            fallback = _default_for_missing_key(last_asked_key, profile)
            if fallback is not None:
                profile[last_asked_key] = fallback
                assumptions_used.append(f"{last_asked_key}={fallback}")

        st.session_state["profile"] = profile

        asked_key, q = _next_question(profile, len(st.session_state["chat_messages"]))
        # Avoid nagging: if we asked same field already and still missing, auto-assume sensible default.
        if asked_key:
            counts = st.session_state["ask_counts"]
            counts[asked_key] = counts.get(asked_key, 0) + 1
            if counts[asked_key] >= 2 and profile.get(asked_key) in (None, ""):
                fallback = _default_for_missing_key(asked_key, profile)
                if fallback is not None:
                    profile[asked_key] = fallback
                    assumptions_used.append(f"{asked_key}={fallback}")
                    st.session_state["profile"] = profile
                    asked_key, q = _next_question(profile, len(st.session_state["chat_messages"]))
                    st.session_state["chat_messages"].append(
                        {
                            "role": "assistant",
                            "content": _pick_template(
                                FUN_ASSUMPTION_TEMPLATES,
                                len(st.session_state["chat_messages"]),
                            ).format(field=asked_key),
                        }
                    )
        # If user explicitly denied side-stones while being asked side-stone details, acknowledge it.
        if last_asked_key in ("side_stone_quantity", "side_stone_total_carat_weight") and profile.get("side_stone_present") is False:
            st.session_state["chat_messages"].append(
                {
                    "role": "assistant",
                    "content": "Got it, no side stones. I’ll continue with center-stone pricing only.",
                }
            )
        st.session_state["assumptions_used"] = assumptions_used
        st.session_state["last_asked_key"] = asked_key
        if q:
            ack = _pick_template(FUN_ACK_TEMPLATES, len(st.session_state["chat_messages"]))
            # If extraction confidence is low, add a light fallback lead-in.
            if effective_conf < 0.45:
                preface = _pick_template(
                    FUN_LOW_CONF_TEMPLATES,
                    len(st.session_state["chat_messages"]),
                )
                bot_msg = f"{preface} {q}"
            else:
                bot_msg = f"{ack} {q}"
            st.session_state["chat_messages"].append({"role": "assistant", "content": bot_msg})
            st.rerun()

        if USE_RAPNET and not rapnet_token:
            st.session_state["chat_messages"].append(
                {"role": "assistant", "content": "Please add your RapNet token so I can fetch market anchors."}
            )
            st.rerun()

        user_input = _prepare_safe_user_input(profile)
        ai_layer = "Enabled" if ENABLE_AI else "Disabled"
        try:
            result = run_pricing_pipeline(user_input, rapnet_token, ai_layer)
        except Exception as exc:
            result = {"error": _friendly_error_message(str(exc))}

        st.session_state["last_result"] = result
        st.session_state["chat_messages"].append(
            {
                "role": "assistant",
                "content": _friendly_bot_price_response(
                    result,
                    assumptions_used,
                    turn_seed=len(st.session_state["chat_messages"]),
                ),
            }
        )
        st.rerun()

with right:
    _render_profile_snapshot(st.session_state["profile"])
    res = st.session_state.get("last_result")
    if res:
        st.subheader("Latest Price Output")
        if res.get("error"):
            err_text = str(res.get("error") or "")
            anchor = res.get("diamond_anchor") or {}
            if (
                "confidence is too low" in err_text.lower()
                and anchor.get("low") is not None
                and anchor.get("high") is not None
            ):
                st.warning(err_text)
                fp = res.get("final_price") or {"low": anchor.get("low"), "high": anchor.get("high")}
                c1, c2 = st.columns(2)
                c1.metric("Low (Provisional)", f"${(fp.get('low') or 0):,.2f}")
                c2.metric("High (Provisional)", f"${(fp.get('high') or 0):,.2f}")
                _render_chatbot_result_details(res)
                st.caption("Provisional range shown due to low confidence. Manual review recommended.")
            else:
                st.error(err_text)
        else:
            fp = res.get("final_price", {})
            c1, c2 = st.columns(2)
            c1.metric("Low", f"${fp.get('low', 0):,.2f}")
            c2.metric("High", f"${fp.get('high', 0):,.2f}")
            _render_chatbot_result_details(res)
            st.caption("Tip: you can edit details in chat and I’ll re-price instantly.")
