from dotenv import load_dotenv
load_dotenv()

import json
import os
import re
from typing import Dict, Optional, Tuple

import streamlit as st

from pricing_ai_for_ui import run_pricing_pipeline


def get_env(key, default=None):
    return os.getenv(key) or st.secrets.get(key, default)


PRICE_SOURCE = (get_env("PRICE_SOURCE", "gemgem")).lower()
USE_RAPNET = PRICE_SOURCE == "rapnet"
ENABLE_AI = (get_env("ENABLE_AI", "false")).lower() == "true"
OPENAI_API_KEY = get_env("OPENAI_API_KEY")

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
    return None


def _extract_with_regex(text: str) -> Dict:
    t = _normalize_text(text).lower()
    out = {}

    inferred_type = _canonical_jewelry_type(t)
    if inferred_type:
        out["jewelry_type"] = inferred_type
    item_tokens = {
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
    for token, item in item_tokens.items():
        if token in t:
            out["jewelry_item_type"] = item
            break

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
        cut_aliases = {
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
        tokens = re.findall(r"\b[a-z]+\b", t)
        for tk in tokens:
            if tk in cut_aliases:
                out["cut"] = cut_aliases[tk]
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

    side_qty_match = re.search(r"(\d+)\s*(?:side\s*stones?|stones)\b", t)
    if side_qty_match:
        out["side_stone_present"] = True
        out["side_stone_quantity"] = int(side_qty_match.group(1))

    side_tcw_match = re.search(
        r"(?:side\s*stones?.*?(?:total|tcw|carat)|tcw)\D*(\d+(?:\.\d+)?)\s*(?:ct|carat)?",
        t,
    )
    if side_tcw_match:
        out["side_stone_present"] = True
        out["side_stone_total_carat_weight"] = float(side_tcw_match.group(1))

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
) -> Tuple[Dict, bool]:
    if not OPENAI_API_KEY:
        return {}, False
    try:
        from openai import OpenAI
    except Exception:
        return {}, False

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
        '  "unknown_intent_for_last_asked_key": boolean\n'
        "}\n"
        "Do not infer unspecified fields. If user did not explicitly provide a value, return null for that field.\n"
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
            max_tokens=180,
            response_format={"type": "json_object"},
        )
        data = json.loads(resp.choices[0].message.content or "{}")
        if isinstance(data, dict):
            # backward-compat: if model returns flat dict, treat as fields
            if "fields" not in data:
                return data, bool(data.get("unknown_intent_for_last_asked_key", False))
            fields = data.get("fields") or {}
            unknown_intent = bool(data.get("unknown_intent_for_last_asked_key", False))
            return fields if isinstance(fields, dict) else {}, unknown_intent
    except Exception:
        return {}, False
    return {}, False


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


def _next_question(profile: Dict, turn_seed: int) -> Tuple[Optional[str], Optional[str]]:
    required = [
        "jewelry_type",
        "carat",
        "shape",
        "color",
        "clarity",
        "cut",
        "fluorescence",
        "condition",
    ]
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
    no_tokens = ["no", "nope", "n", "without", "just center", "only center"]
    if any(tok in t for tok in yes_tokens):
        return True
    if any(tok in t for tok in no_tokens):
        return False
    return None


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
    if p.get("cut") and p["cut"] not in CUTS:
        for c in CUTS:
            if c.lower() in p["cut"].lower():
                p["cut"] = c
                break
    if p.get("condition") and p["condition"] not in CONDITIONS:
        condition_aliases = {
            "almost new": "Like New",
            "like-new": "Like New",
            "minor wear": "Good",
            "good/minor wear": "Good",
            "needs repair": "Fair",
            "noticeable wear": "Fair",
        }
        alias = condition_aliases.get(str(p["condition"]).strip().lower())
        if alias:
            p["condition"] = alias
    if p.get("condition") and p["condition"] not in CONDITIONS:
        for c in CONDITIONS:
            if c.lower() in p["condition"].lower():
                p["condition"] = c
                break
    if p.get("condition") and p["condition"] not in CONDITIONS:
        p["condition"] = None
    if p.get("metal") and p["metal"] not in METALS:
        m = p["metal"].lower()
        for k, v in METAL_LOOKUP.items():
            if k in m:
                p["metal"] = v
                break
    if p.get("fluorescence") and p["fluorescence"] not in FLUORESCENCE:
        f = str(p["fluorescence"]).lower()
        for k, v in FLUORESCENCE_LOOKUP.items():
            if k in f:
                p["fluorescence"] = v
                break
    if p.get("fluorescence") and p["fluorescence"] not in FLUORESCENCE:
        p["fluorescence"] = None
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
    return p


def _build_user_input(profile: Dict) -> Dict:
    side_stones = []
    if (
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


def _friendly_bot_price_response(result: Dict, assumptions: Optional[list] = None) -> str:
    if result.get("error"):
        return (
            "I couldn’t confidently price that yet. "
            "Please tweak specs slightly (especially carat/clarity/color) and I’ll try again."
        )
    fp = result.get("final_price") or {}
    low = fp.get("low")
    high = fp.get("high")
    if low is None or high is None:
        return "I found the specs, but couldn't build a final range. Please try again."
    msg = (
        f"Great news! Based on your specs and current market signals, a strong listing range is "
        f"**${low:,.0f} - ${high:,.0f}**. "
        "This is a competitive zone to attract buyers while protecting your value."
    )
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
    }
    st.json(snapshot)


st.set_page_config(page_title="Jewelry Pricing Chatbot MVP", page_icon="💬", layout="wide")
st.title("Jewelry Pricing Chatbot MVP")
st.caption("Conversational estimator powered by your existing pricing engine.")

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
        if last_asked_key == "side_stone_present":
            yn = _parse_yes_no(user_msg)
            if yn is not None:
                profile["side_stone_present"] = yn
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
        llm_updates, llm_unknown_intent = _extract_with_llm(user_msg, profile, last_asked_key)
        llm_updates = {
            k: v
            for k, v in llm_updates.items()
            if _llm_field_is_explicit(k, user_msg, last_asked_key)
        }
        merged_updates = dict(regex_updates)
        merged_updates.update({k: v for k, v in llm_updates.items() if v not in (None, "")})
        profile = _merge_profile(profile, merged_updates)
        profile = _sanitize_profile(profile)

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
                            "content": (
                                f"No worries, I’ll use a standard estimate for `{asked_key}` "
                                "and continue."
                            ),
                        }
                    )
        st.session_state["assumptions_used"] = assumptions_used
        st.session_state["last_asked_key"] = asked_key
        if q:
            bot_msg = f"Nice, got it. {q}"
            st.session_state["chat_messages"].append({"role": "assistant", "content": bot_msg})
            st.rerun()

        if USE_RAPNET and not rapnet_token:
            st.session_state["chat_messages"].append(
                {"role": "assistant", "content": "Please add your RapNet token so I can fetch market anchors."}
            )
            st.rerun()

        user_input = _build_user_input(profile)
        ai_layer = "Enabled" if ENABLE_AI else "Disabled"
        try:
            result = run_pricing_pipeline(user_input, rapnet_token, ai_layer)
        except Exception as exc:
            result = {"error": str(exc)}

        st.session_state["last_result"] = result
        st.session_state["chat_messages"].append(
            {"role": "assistant", "content": _friendly_bot_price_response(result, assumptions_used)}
        )
        st.rerun()

with right:
    _render_profile_snapshot(st.session_state["profile"])
    res = st.session_state.get("last_result")
    if res:
        st.subheader("Latest Price Output")
        if res.get("error"):
            st.error(res["error"])
        else:
            fp = res.get("final_price", {})
            c1, c2 = st.columns(2)
            c1.metric("Low", f"${fp.get('low', 0):,.2f}")
            c2.metric("High", f"${fp.get('high', 0):,.2f}")
            st.caption("Tip: you can edit details in chat and I’ll re-price instantly.")
