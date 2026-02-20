import ollama
import json
import re
from dotenv import load_dotenv
import os
from rapnet_client import get_anchor_with_fallback
load_dotenv()
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
        "excellent_like_new": {"min": 5, "max": 10},
        "good_minor_wear": {"min": 0, "max": 0},
        "noticeable_wear": {"min": -10, "max": -5},
        "needs_repair": {"min": -30, "max": -15}
    },
    "metal_type_and_purity": {
        "14k_gold": {"min": 5, "max": 5},
        "18k_gold": {"min": 5, "max": 10},
        "platinum_pt950": {"min": 10, "max": 15}
    },
    "brand_premium": {
        "unbranded_or_unknown": {"min": 0, "max": 0},
        "mid_tier_brand": {"min": 0, "max": 0},
        "top_resale_brand_with_proof": {"min": 10, "max": 15},
        "top_resale_brand_without_proof": {"min": 5, "max": 5}
    }
}

GLOBAL_CLAMP = {"min": -30, "max": 40}


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
        "- If condition is 'Excellent' or 'Like New', adjustment_percent MUST be >= 0.\n"
        "- Missing information MUST NOT cause a negative adjustment.\n"
        "- You MUST respond with ONLY valid JSON.\n"
        "- Do NOT include explanations or prose.\n"
        "- If unsure, still return JSON with best-guess values."
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
    lines.append("CENTER STONE:")
    lines.append(f"- Shape: {cs.get('shape', 'Unknown')}")
    lines.append(f"- Carat: {cs.get('carat', 'Unknown')}")
    lines.append(f"- Color: {cs.get('color', 'Unknown')}")
    lines.append(f"- Clarity: {cs.get('clarity', 'Unknown')}")
    lines.append(f"- Cut: {cs.get('cut', 'Unknown')}")

    lines.append("OTHER DETAILS:")
    lines.append(f"- Brand: {user_input.get('brand', 'Unbranded')}")
    lines.append(f"- Condition: {user_input.get('condition', 'Unknown')}")

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
        "Choose a TOTAL adjustment percentage.\n"
        "Return JSON ONLY."
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
    if condition in ["excellent", "like new"] and adj < 0:
        adj = 0

    brand = (user_input.get("brand") or "").lower()
    if (not brand or brand == "unbranded") and adj < 0:
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
    cs = user_input["center_stone"]

    # Carat must exist
    if not cs.get("carat"):
        raise Exception("Carat is required to estimate price")

    # Apply defaults BEFORE calling any pricing client
    cs["color"] = cs.get("color") or "G"
    cs["clarity"] = cs.get("clarity") or "VS1"
    cs["shape"] = cs.get("shape") or "Round"

    # ----------------------------
    # PRICE SOURCE SWITCH
    # ----------------------------

    if PRICE_SOURCE == "rapnet":

        diamond_anchor = get_anchor_with_fallback(
            cs,  # ✅ pass normalized object
            rapnet_token,
            call_rapnet_api,
            compute_anchor_from_rapnet
        )

    elif PRICE_SOURCE == "gemgem":

        diamond_anchor = get_anchor_with_fallback_gemgem(
            cs   # ✅ pass normalized object
        )

    else:
        raise Exception(f"Invalid PRICE_SOURCE: {PRICE_SOURCE}")

    # ---- HANDLE NO RESULTS SAFELY ----
    if not diamond_anchor:
        return {
            "error": "No comparable diamonds found even after fallback search.",
            "diamond_anchor": None,
            "effective_specs": None,
            "used_fallback": False,
            "base_price": None,
            "metal_value": 0,
            "ai_adjustment": {"adjustment_percent": 0},
            "final_price": None
        }

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

    base_price = {
        "low": diamond_anchor["low"] + metal_value,
        "high": diamond_anchor["high"] + metal_value
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

    return {
        "diamond_anchor": {
            "low": diamond_anchor["low"],
            "high": diamond_anchor["high"]
        },
        "effective_specs": diamond_anchor.get("effective_specs"),
        "used_fallback": diamond_anchor.get("used_fallback", False),
        "base_price": base_price,
        "metal_value": metal_value,
        "ai_adjustment": ai_result,
        "final_price": {
            "low": final_price["final_price_low_usd"],
            "high": final_price["final_price_high_usd"]
        }
    }




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
