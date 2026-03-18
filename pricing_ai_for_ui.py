import ollama
import json
import re
from dotenv import load_dotenv
import os
from rapnet_client import get_anchor_with_fallback
load_dotenv()
import streamlit as st
def get_env(key, default=None):
    return os.getenv(key) or st.secrets.get(key, default)
AI_PROVIDER = os.getenv("AI_PROVIDER", "openai").lower()
PRICE_SOURCE = (get_env("PRICE_SOURCE", "gemgem")).lower()
ENABLE_AI = (get_env("ENABLE_AI", "false")).lower() == "true"
USE_RAPNET = PRICE_SOURCE == "rapnet"
OPENAI_API_KEY = get_env("OPENAI_API_KEY")
from rapnet_client import (
    build_rapnet_payload,
    call_rapnet_api,
    compute_anchor_from_rapnet
)
from gemgem_client import get_anchor_with_fallback_gemgem
from metal_price_client import compute_metal_value


# ----------------------------
# OPS ADJUSTMENT RULES
# ----------------------------
OPS_ADJUSTMENTS = {
    "condition": {
        "Excellent": {"min": 0, "max": 0},
        "Like New": {"min": -3, "max": -3},
        "Good": {"min": -10, "max": -10},
        "Fair": {"min": -20, "max": -20}
    },
    "metal_type_and_purity": {
        "10k_gold": {"min": -4, "max": -4},
        "12k_gold": {"min": -2, "max": -2},
        "14k_gold": {"min": 0, "max": 0},
        "16k_gold": {"min": 1, "max": 1},
        "18k_gold": {"min": 3, "max": 3},
        "22k_gold": {"min": 6, "max": 6},
        "platinum_pt950": {"min": 4, "max": 4}
    },
    "brand_premium": {
        "unbranded_or_unknown": {"min": 0, "max": 0},
        "mid_tier_brand": {"min": 0, "max": 0},
        "top_resale_brand_with_proof": {"min": 10, "max": 12},
        "top_resale_brand_without_proof": {"min": 0, "max": 0}
    },
    "quality_factors": {
        "cut": {
            "Heart & Arrow": {"min": 3, "max": 3},
            "Ideal": {"min": 2, "max": 2},
            "Excellent": {"min": 1, "max": 1},
            "Very Good": {"min": 0, "max": 0},
            "Good": {"min": -3, "max": -3},
            "Unknown": {"min": 0, "max": 0}
        },
        "fluorescence": {
            "None": {"min": 0, "max": 0},
            "Faint": {"min": 0, "max": 0},
            "Medium": {"min": -1, "max": -1},
            "Strong": {"min": -3, "max": -3},
            "Very Strong": {"min": -5, "max": -5},
            "Unknown": {"min": 0, "max": 0}
        }
    }
}

GLOBAL_CLAMP = {"min": -30, "max": 40}
TOP_RESALE_BRANDS = {
    "cartier",
    "tiffany & co.",
    "van cleef & arpels",
    "bulgari",
    "harry winston",
    "chopard",
    "graff",
    "boucheron",
    "buccellati",
    "chaumet",
    "piaget"
}

# For very small side stones (melee), API comparables are often sparse.
# We use a bounded fallback USD-per-carat table by per-stone size band.
MELEE_PER_CARAT_TABLE = [
    {"max_per_stone_carat": 0.003, "low": 120, "high": 180},
    {"max_per_stone_carat": 0.005, "low": 180, "high": 260},
    {"max_per_stone_carat": 0.01, "low": 260, "high": 380},
    {"max_per_stone_carat": 0.02, "low": 400, "high": 600},
    {"max_per_stone_carat": 0.03, "low": 550, "high": 800},
    {"max_per_stone_carat": 0.04, "low": 700, "high": 980},
    {"max_per_stone_carat": 0.05, "low": 850, "high": 1200},
    {"max_per_stone_carat": 0.06, "low": 1000, "high": 1450},
    {"max_per_stone_carat": 0.07, "low": 1150, "high": 1650},
    {"max_per_stone_carat": 0.08, "low": 1300, "high": 1850},
    {"max_per_stone_carat": 0.09, "low": 1450, "high": 2100},
]
MELEE_THRESHOLD_PER_STONE_CARAT = 0.09
CONFIDENCE_SHOW_NORMALLY_MIN = 0.75
CONFIDENCE_WARN_MIN = 0.60
CONFIDENCE_REVIEW_MIN = 0.45


# ----------------------------
# PROMPT BUILDER
# ----------------------------
def build_prompt(user_input):
    lines = []

    lines.append(
        "You are selecting a price ADJUSTMENT for second-hand diamond products."
    )

    lines.append(
        "IMPORTANT CONSTRAINTS:\n"
        "- If condition is 'Excellent', adjustment_percent MUST be >= 0.\n"
        "- Missing information MUST NOT cause a negative adjustment.\n"
        "- Brand may be considered as a bounded adjustment factor.\n"
        "- Brand MUST NOT become the primary pricing driver.\n"
        "- Brand must not produce aggressive premium assumptions without strong supporting evidence.\n"
        "- If brand information is uncertain or unverified, treat it as neutral.\n"
        "- Follow the OPS adjustment rules strictly.\n"
        "- You MUST respond with ONLY valid JSON.\n"
        "- Do NOT include explanations or prose.\n"
        "- If unsure, still return JSON with best-guess values."
    )
    lines.append(
        "Condition rule:\n"
        "- Use ONLY these condition keys from OPS: Excellent, Like New, Good, Fair.\n"
        "- Map directly from the input condition string."
    )
    lines.append(
        "Brand adjustment rule:\n"
        "- Use ONLY the provided BRAND_POLICY_KEY.\n"
        "- If BRAND_POLICY_KEY is 'top_resale_brand_with_proof', use that premium band.\n"
        "- If BRAND_POLICY_KEY is 'top_resale_brand_without_proof', use that premium band.\n"
        "- If BRAND_POLICY_KEY is 'unbranded_or_unknown', do not apply brand premium.\n"
        "- Brand must not become the primary pricing driver."
    )
    lines.append(
        "Quality adjustment rules:\n"
        "- Use UI labels directly for cut and fluorescence against OPS.quality_factors tables.\n"
        "- Do NOT add separate polish/symmetry premiums (cut already captures those effects).\n"
        "- Strong/Very Strong fluorescence should imply a moderate discount.\n"
        "- Cut can add only modest premium."
    )

    lines.append(
        "Return JSON in this EXACT format:\n"
        "{\n"
        '  "adjustment_percent": number,\n'
        '  "key_drivers": [string],\n'
        '  "missing_info": [string]\n'
        "}"
    )

    lines.append(f"JEWELRY TYPE: {user_input.get('jewelry_type')}")

    cs = user_input.get("center_stone", {})
    cs_carat = float(cs.get("carat") or 0.0)
    lines.append("CENTER STONE:")
    if cs_carat > 0:
        lines.append(f"- Shape: {cs.get('shape', 'Unknown')}")
        lines.append(f"- Carat: {cs.get('carat', 'Unknown')}")
        lines.append(f"- Color: {cs.get('color', 'Unknown')}")
        lines.append(f"- Clarity: {cs.get('clarity', 'Unknown')}")
        lines.append(f"- Cut: {cs.get('cut', 'Unknown')}")
        lines.append(f"- Polish: {cs.get('polish', 'Unknown')}")
        lines.append(f"- Symmetry: {cs.get('symmetry', 'Unknown')}")
        lines.append(f"- Fluorescence: {cs.get('fluorescence', 'Unknown')}")
    else:
        lines.append("- No center stone in this piece (side-stones-only design).")

    lines.append("OTHER DETAILS:")
    lines.append(f"- Brand: {user_input.get('brand', 'Unbranded')}")
    lines.append(f"- Brand proof available: {user_input.get('brand_proof', 'No')}")
    lines.append(f"- BRAND_POLICY_KEY: {user_input.get('brand_policy_key', 'unbranded_or_unknown')}")
    lines.append(f"- Condition: {user_input.get('condition', 'Unknown')}")
    side_stones = user_input.get("side_stones", [])
    lines.append(f"- Side stones groups: {len(side_stones)}")
    if side_stones:
        for idx, ss in enumerate(side_stones[:5], start=1):
            lines.append(
                f"  Side stone {idx}: qty={ss.get('quantity')}, total_carat={ss.get('total_carat_weight')}, "
                f"shape={ss.get('shape')}, color={ss.get('color')}, clarity={ss.get('clarity')}, cut={ss.get('cut')}"
            )

    if user_input.get("jewelry_type") != "Loose Diamond":
        lines.append("METAL DETAILS:")
        lines.append(f"- Metal: {user_input.get('metal', 'Unknown')}")
        lines.append(f"- Purity: {user_input.get('purity', 'Unknown')}")
        lines.append(
            f"- Approx metal weight: {user_input.get('metal_weight_grams', 'Unknown')} grams"
        )
    else:
        lines.append("This is a LOOSE DIAMOND. No metal or setting is present.")

    lines.append("OPS APPROVED ADJUSTMENT RULES:")
    lines.append(json.dumps(OPS_ADJUSTMENTS, indent=2))

    lines.append("GLOBAL CLAMP:")
    lines.append(json.dumps(GLOBAL_CLAMP, indent=2))

    lines.append(
        "TASK:\n"
        "Determine the final adjustment_percent using the OPS adjustment rules.\n\n"
        "Follow this reasoning order internally:\n"
        "1. Determine the condition adjustment range.\n"
        "2. Determine the brand adjustment if applicable.\n"
        "3. Add the adjustments conservatively.(condition adjustment + brand adjustment)\n"
        "IMPORTANT:\n"
        "- Brand must always remain a secondary adjustment factor.\n"

        "Return ONLY JSON in the specified format."
    )

    return "\n\n".join(lines)


# ----------------------------
# LLaVA CALL
# ----------------------------
def query_llava(prompt, images):

    # ---- USE OPENAI WHEN ENABLED ----
    if OPENAI_API_KEY:
        from openai import OpenAI
        import base64

        client = OpenAI(api_key=OPENAI_API_KEY)

        content = [{"type": "text", "text": prompt}]

        # attach images if present
        for img in images or []:
            if isinstance(img, bytes):
                b64 = base64.b64encode(img).decode("utf-8")
                content.append({
                    "type": "image_url",
                    "image_url": {"url": f"data:image/jpeg;base64,{b64}"}
                })

        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": content}],
            temperature=0.2,
            response_format={"type": "json_object"}
        )

        return response.choices[0].message.content

    # ---- FALLBACK TO OLLAMA (optional) ----
    else:
        response = ollama.chat(
            model="llava:13b",
            messages=[{
                "role": "user",
                "content": prompt,
                "images": images
            }]
        )
        return response["message"]["content"]


def generate_why_this_price_statement(user_input, result_payload):
    """
    Generate a very short, high-impact explanation line for end users.
    Keep token usage low by using compact context and strict length instruction.
    """
    low = result_payload["final_price"]["low"]
    high = result_payload["final_price"]["high"]
    range_text = f"${low:,.0f}-${high:,.0f}"
    fallback = (
        f"This piece sits confidently in the {range_text} range, balancing market reality and quality so you can move forward with clarity."
    )

    if not OPENAI_API_KEY:
        return fallback

    try:
        from openai import OpenAI
        client = OpenAI(api_key=OPENAI_API_KEY)

        cs = user_input.get("center_stone", {})
        cs_carat = float(cs.get("carat") or 0.0)
        conf = result_payload.get("anchor_confidence") or {}
        ai_adj = result_payload.get("ai_adjustment") or {}
        key_drivers = ", ".join((ai_adj.get("key_drivers") or [])[:2]) or "spec match and market comps"
        if cs_carat > 0:
            specs_line = f"Specs: {cs.get('shape')} {cs.get('carat')}ct {cs.get('color')} {cs.get('clarity')}.\n"
        else:
            specs_line = "Specs: side-stones-only diamond jewelry (no center stone).\n"
        prompt = (
            "Write 1 short, persuasive pricing justification (max 24 words). "
            "Use reassuring, emotionally confident language. No hype, no guarantees.\n"
            f"Must include this exact range once: {range_text}.\n"
            "Do NOT mention any single dollar number outside that range.\n"
            f"{specs_line}"
            f"Comparables: {result_payload.get('comparable_count', 0)}.\n"
            f"Confidence: {conf.get('label', 'N/A')}.\n"
            f"Adjustment: {ai_adj.get('adjustment_percent', 0)}%.\n"
            f"Range: {range_text}.\n"
            f"Key drivers: {key_drivers}."
        )

        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.2,
            max_tokens=50
        )
        text = (response.choices[0].message.content or "").strip()
        if range_text not in text:
            text = f"{text.rstrip('.')} Range: {range_text}."
        return text if text else fallback
    except Exception:
        return fallback



# ----------------------------
# SAFETY: PARSE + CLAMP
# ----------------------------
def parse_and_clamp(raw_output, user_input):
    match = re.search(r"\{[\s\S]*\}", raw_output)

    if not match:
        return {
            "adjustment_percent": 0,
            "key_drivers": ["ai_output_not_structured"],
            "missing_info": []
        }

    json_str = match.group(0)

    # 🔧 Fix invalid JSON escapes from LLM
    json_str = re.sub(r'\\(?!["\\/bfnrt])', r'\\\\', json_str)

    try:
        data = json.loads(json_str)
    except json.JSONDecodeError:
        # Absolute fallback (never crash UI)
        return {
            "adjustment_percent": 0,
            "key_drivers": ["ai_json_parse_failed"],
            "missing_info": []
        }

    adj = data.get("adjustment_percent", 0)
    adj = max(GLOBAL_CLAMP["min"], min(GLOBAL_CLAMP["max"], adj))

    condition = (user_input.get("condition") or "").lower()
    if condition == "excellent" and adj < 0:
        adj = 0

    data["adjustment_percent"] = adj
    return data


# ----------------------------
# FINAL PRICE CALC
# ----------------------------
def apply_anchor_and_adjustment(anchor, adjustment_percent):
    factor = 1 + (adjustment_percent / 100)
    return {
        "final_price_low_usd": round(anchor["low"] * factor, 2),
        "final_price_high_usd": round(anchor["high"] * factor, 2)
    }


def _normalize_brand_policy_key(user_input):
    brand_selection = (user_input.get("brand_selection") or "").strip()
    brand_proof = (user_input.get("brand_proof") or "No").strip().lower()

    # Deterministic tiering:
    # - only top-brand dropdown selections can be top tier
    # - "Other / Unknown" is always unbranded_or_unknown for pricing
    selected_is_top = brand_selection and brand_selection != "Other / Unknown"
    is_top = selected_is_top

    if not is_top:
        return "unbranded_or_unknown"
    if brand_proof == "yes":
        return "top_resale_brand_with_proof"
    return "top_resale_brand_without_proof"


def _confidence_action(confidence_payload):
    score = float((confidence_payload or {}).get("score") or 0.0)
    if score >= CONFIDENCE_SHOW_NORMALLY_MIN:
        return "show"
    if score >= CONFIDENCE_WARN_MIN:
        return "warn"
    if score >= CONFIDENCE_REVIEW_MIN:
        return "manual_review"
    return "block"


def _lookup_melee_price_per_carat(per_stone_carat):
    for band in MELEE_PER_CARAT_TABLE:
        if per_stone_carat <= band["max_per_stone_carat"]:
            return {
                "low": band["low"],
                "high": band["high"],
                "band_max_per_stone_carat": band["max_per_stone_carat"]
            }
    # If above configured bands, reuse top configured band as conservative fallback.
    top_band = MELEE_PER_CARAT_TABLE[-1]
    return {"low": top_band["low"], "high": top_band["high"], "band_max_per_stone_carat": None}


def _fetch_anchor_for_stone(stone, rapnet_token):
    if PRICE_SOURCE == "rapnet":
        return get_anchor_with_fallback(
            stone,
            rapnet_token,
            call_rapnet_api,
            compute_anchor_from_rapnet
        )
    if PRICE_SOURCE == "gemgem":
        return get_anchor_with_fallback_gemgem(stone)
    raise Exception(f"Invalid PRICE_SOURCE: {PRICE_SOURCE}")


def _compute_side_stones_value(side_stones, rapnet_token):
    total_low = 0.0
    total_high = 0.0
    details = []
    comparable_groups = []

    for idx, stone in enumerate(side_stones, start=1):
        stone_type = (stone.get("stone_type") or "Diamond").strip().lower()
        if stone_type != "diamond":
            details.append({
                "index": idx,
                "stone_type": stone.get("stone_type"),
                "price_source": "unsupported_gemstone",
                "estimated_value_low": 0.0,
                "estimated_value_high": 0.0
            })
            continue

        quantity = int(stone.get("quantity") or 0)
        total_carat = float(stone.get("total_carat_weight") or 0.0)
        if quantity <= 0 or total_carat <= 0:
            continue

        per_stone_carat = total_carat / quantity
        stone_query = {
            "shape": stone.get("shape") or "Round",
            "carat": round(per_stone_carat, 4),
            "color": stone.get("color") or "G",
            "clarity": stone.get("clarity") or "VS1",
            "cut": stone.get("cut"),
            "polish": stone.get("polish"),
            "symmetry": stone.get("symmetry"),
            "fluorescence": stone.get("fluorescence"),
        }

        used_melee_fallback = per_stone_carat <= MELEE_THRESHOLD_PER_STONE_CARAT
        anchor_result = None if used_melee_fallback else _fetch_anchor_for_stone(stone_query, rapnet_token)

        if anchor_result:
            anchor = anchor_result.get("anchor", anchor_result)
            side_low = float(anchor["low"]) * quantity
            side_high = float(anchor["high"]) * quantity
            price_source_used = "market_comparables"
            group_comparables = anchor_result.get("comparables", [])
        else:
            melee_band = _lookup_melee_price_per_carat(per_stone_carat)
            side_low = melee_band["low"] * total_carat
            side_high = melee_band["high"] * total_carat
            price_source_used = "melee_fallback_table"
            group_comparables = []

        side_low = round(side_low, 2)
        side_high = round(side_high, 2)
        total_low += side_low
        total_high += side_high

        details.append({
            "index": idx,
            "shape": stone_query["shape"],
            "quantity": quantity,
            "total_carat_weight": round(total_carat, 4),
            "per_stone_carat": round(per_stone_carat, 5),
            "color": stone_query["color"],
            "clarity": stone_query["clarity"],
            "cut": stone_query.get("cut"),
            "price_source": price_source_used,
            "comparable_count": len(group_comparables),
            "per_diamond_value_low": round(side_low / quantity, 2),
            "per_diamond_value_high": round(side_high / quantity, 2),
            "estimated_value_low": side_low,
            "estimated_value_high": side_high
        })

        comparable_groups.append({
            "index": idx,
            "price_source": price_source_used,
            "comparable_count": len(group_comparables),
            "comparables": group_comparables
        })

    return {
        "low": round(total_low, 2),
        "high": round(total_high, 2),
        "details": details,
        "comparable_groups": comparable_groups
    }


# ----------------------------
# MAIN PIPELINE (THIS IS WHAT UI CALLS)
# ----------------------------
def run_pricing_pipeline(user_input, rapnet_token, ai_layer="Disabled"):

    # ---- Clean loose diamond inputs ----
    if user_input.get("jewelry_type") == "Loose Diamond":
        user_input.pop("metal", None)
        user_input.pop("purity", None)
        user_input.pop("metal_weight_grams", None)

    # ---- ENSURE MINIMUM REQUIRED FIELDS ----
    cs = user_input.get("center_stone", {})
    center_carat = float(cs.get("carat") or 0.0)
    has_center_stone = center_carat > 0
    side_stones = user_input.get("side_stones", [])
    has_valid_side_stones = any(
        int(stone.get("quantity") or 0) > 0 and float(stone.get("total_carat_weight") or 0.0) > 0
        for stone in side_stones
    )

    if not has_center_stone and not has_valid_side_stones:
        raise Exception(
            "Please provide either center stone carat or at least one valid side-stone group."
        )

    # Apply defaults BEFORE calling any pricing client
    if has_center_stone:
        cs["color"] = cs.get("color") or "G"
        cs["clarity"] = cs.get("clarity") or "VS1"
        cs["shape"] = cs.get("shape") or "Round"
    user_input["brand_policy_key"] = _normalize_brand_policy_key(user_input)

    # ----------------------------
    # PRICE SOURCE SWITCH
    # ----------------------------

    if has_center_stone:
        if PRICE_SOURCE == "rapnet":
            anchor_result = get_anchor_with_fallback(
                cs,
                rapnet_token,
                call_rapnet_api,
                compute_anchor_from_rapnet
            )
        elif PRICE_SOURCE == "gemgem":
            anchor_result = get_anchor_with_fallback_gemgem(cs)
        else:
            raise Exception(f"Invalid PRICE_SOURCE: {PRICE_SOURCE}")
    else:
        anchor_result = {
            "anchor": {"low": 0.0, "high": 0.0},
            "comparables": [],
            "count": 0,
            "used_fallback": False,
            "effective_specs": None,
            "confidence": {
                "score": 1.0,
                "label": "side_stones_only"
            },
            "fallback_expansion": {
                "carat_delta": 0.0,
                "color_expand": 0,
                "clarity_expand": 0,
                "lab_broadened": False
            },
            "insufficient_comparables": False
        }


    # ---- HANDLE NO RESULTS ----
    if not anchor_result:
        return {
            "error": "No comparable diamonds found even after fallback search.",
            "diamond_anchor": None,
            "effective_specs": None,
            "used_fallback": False,
            "comparables": [],
            "comparable_count": 0,
            "base_price": None,
            "metal_value": 0,
            "ai_adjustment": {"adjustment_percent": 0},
            "final_price": None
        }


    # ---- NORMALIZE STRUCTURE ----
    diamond_anchor = anchor_result.get("anchor", anchor_result)
    comparables = anchor_result.get("comparables", [])
    comparable_count = (
        anchor_result.get("count")
        or anchor_result.get("result_count")
        or len(comparables)
    )
    confidence_payload = anchor_result.get("confidence") or {}
    confidence_action = _confidence_action(confidence_payload)

    if confidence_action == "block":
        return {
            "error": "Estimate confidence is too low for a standard user-facing quote. Please request manual review.",
            "diamond_anchor": {
                "low": diamond_anchor["low"],
                "high": diamond_anchor["high"]
            },
            "effective_specs": anchor_result.get("effective_specs"),
            "used_fallback": anchor_result.get("used_fallback", False),
            "anchor_confidence": confidence_payload,
            "fallback_expansion": anchor_result.get("fallback_expansion"),
            "comparables": comparables,
            "comparable_count": comparable_count,
            "insufficient_comparables": anchor_result.get(
                "insufficient_comparables",
                comparable_count < 3
            ),
            "confidence_action": confidence_action
        }

    #

    # ---- Metal pricing ----
    metal_value = 0.0
    if (
        user_input.get("jewelry_type") != "Loose Diamond"
        and user_input.get("metal_weight_grams")
    ):
        try:
            metal_value = compute_metal_value(
                metal_type=user_input["metal"],
                purity=user_input["purity"],
                weight_grams=user_input["metal_weight_grams"]
            )
        except Exception:
            metal_value = 0.0

    # ---- Side stones pricing ----
    side_stone_value = _compute_side_stones_value(side_stones, rapnet_token)

    base_price = {
        "low": diamond_anchor["low"] + metal_value + side_stone_value["low"],
        "high": diamond_anchor["high"] + metal_value + side_stone_value["high"]
    }

    # ---- AI adjustment ----
    if ai_layer == "Enabled":
        prompt = build_prompt(user_input)
        raw = query_llava(prompt, user_input.get("images", []))
        ai_result = parse_and_clamp(raw, user_input)
    else:
        ai_result = {"adjustment_percent": 0.0}

    # ---- Final price ----
    final_price = apply_anchor_and_adjustment(
        base_price,
        ai_result["adjustment_percent"]
    )

    result_payload = {
        "diamond_anchor": {
            "low": diamond_anchor["low"],
            "high": diamond_anchor["high"]
        },
        "effective_specs": anchor_result.get("effective_specs"),
        "used_fallback": anchor_result.get("used_fallback", False),
        "anchor_confidence": anchor_result.get("confidence"),
        "fallback_expansion": anchor_result.get("fallback_expansion"),
        "base_price": base_price,
        "metal_value": metal_value,
        "side_stones_value": {
            "low": side_stone_value["low"],
            "high": side_stone_value["high"]
        },
        "side_stones_breakdown": side_stone_value["details"],
        "side_stones_comparables": side_stone_value.get("comparable_groups", []),
        "ai_adjustment": ai_result,
        "brand_policy_key": user_input.get("brand_policy_key"),
        "confidence_action": confidence_action,
        "final_price": {
            "low": final_price["final_price_low_usd"],
            "high": final_price["final_price_high_usd"]
        },
        "comparables": comparables,
        "comparable_count": comparable_count,
        "insufficient_comparables": anchor_result.get(
            "insufficient_comparables",
            comparable_count < 3
        )
    }
    result_payload["why_this_price"] = generate_why_this_price_statement(user_input, result_payload)

    return result_payload




# ----------------------------
# LOCAL TEST (OPTIONAL)
# ----------------------------
if __name__ == "__main__":
    test_input = {
        "images": ["diamond.jpg"],
        "jewelry_type": "Loose Diamond",
        "center_stone": {
            "shape": "Round",
            "carat": 1.01,
            "color": "G",
            "clarity": "SI1",
            "cut": "Excellent"
        },
        "brand": None,
        "condition": "Excellent"
    }

    print(json.dumps(run_pricing_pipeline(test_input), indent=2))
