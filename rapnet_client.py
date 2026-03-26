import requests
import os
import json
import time
COLOR_ORDER = ["D","E","F","G","H","I","J","K","L","M"]
CLARITY_ORDER = ["IF","VVS1","VVS2","VS1","VS2","SI1","SI2","SI3","I1","I2","I3"]

RAPNET_URL = "https://technet.rapnetapis.com/instant-inventory/api/Diamonds"


TIMEOUT_SECONDS = 15
MIN_COMPARABLES_REQUIRED = 3
MIN_RESULTS_TO_KEEP_GIA_ONLY = 5
LABS_PRIMARY = ["GIA"]
LABS_FALLBACK = ["GIA", "IGI", "AGS", "EGL", "HRD"]
THIN_DATA_DISCOUNT_BY_COUNT = {
    1: 0.78,
    2: 0.84,
    3: 0.89,
    4: 0.93,
    5: 0.96,
    6: 0.98,
    7: 0.98
}
THIN_DATA_NO_DISCOUNT_MIN_COUNT = 8
RAPNET_CACHE_TTL_SECONDS = 60 * 60
_RAPNET_CACHE = {}


def _to_float(value):
    try:
        return float(value)
    except Exception:
        return None


def _get_color_index(value):
    if not value:
        return None
    color = str(value).upper().strip()
    return COLOR_ORDER.index(color) if color in COLOR_ORDER else None


def _get_clarity_index(value):
    if not value:
        return None
    clarity = str(value).upper().strip()
    return CLARITY_ORDER.index(clarity) if clarity in CLARITY_ORDER else None


def _extract_diamond_color(d):
    return (
        d.get("color")
        or d.get("Color")
        or d.get("diamond_color")
    )


def _extract_diamond_clarity(d):
    return (
        d.get("clarity")
        or d.get("Clarity")
        or d.get("diamond_clarity")
    )


def _extract_diamond_carat(d):
    return (
        _to_float(d.get("size"))
        or _to_float(d.get("carat"))
        or _to_float(d.get("carat_weight"))
    )


def _compute_carat_penalty(target_carat, comp_carat):
    """
    Use a softer non-linear penalty for near-size comps and cap the maximum
    influence so a single larger/smaller comp does not dominate the anchor.
    """
    if target_carat is None or comp_carat is None:
        return 0.0
    relative_delta = abs(comp_carat - target_carat) / max(target_carat, 0.01)
    softened_penalty = (relative_delta ** 0.8) * 0.45
    return min(0.35, softened_penalty)


def _compute_similarity_weight(diamond, target):
    """
    Similarity weighting so relaxed comps influence anchor less.
    Higher is better; minimum floor keeps sparse data usable.
    """
    target_carat = _to_float(target.get("carat"))
    target_color_idx = _get_color_index(target.get("color"))
    target_clarity_idx = _get_clarity_index(target.get("clarity"))

    comp_carat = _extract_diamond_carat(diamond)
    comp_color_idx = _get_color_index(_extract_diamond_color(diamond))
    comp_clarity_idx = _get_clarity_index(_extract_diamond_clarity(diamond))

    carat_penalty = _compute_carat_penalty(target_carat, comp_carat)

    color_penalty = 0.0
    if target_color_idx is not None and comp_color_idx is not None:
        color_penalty = abs(comp_color_idx - target_color_idx) * 0.12

    clarity_penalty = 0.0
    if target_clarity_idx is not None and comp_clarity_idx is not None:
        clarity_penalty = abs(comp_clarity_idx - target_clarity_idx) * 0.12

    raw = 1.0 - carat_penalty - color_penalty - clarity_penalty
    return max(0.15, min(1.0, raw))


def _weighted_percentile_price(weighted_prices, q):
    """
    weighted_prices: list[(price, weight)] sorted by price asc.
    q in [0,1].
    """
    if not weighted_prices:
        return None
    total_w = sum(w for _, w in weighted_prices)
    if total_w <= 0:
        return None

    threshold = total_w * q
    running = 0.0
    for price, weight in weighted_prices:
        running += weight
        if running >= threshold:
            return price
    return weighted_prices[-1][0]

def build_rapnet_payload(
    center_stone,
    color_from=None,
    color_to=None,
    clarity_from=None,
    clarity_to=None,
    carat_from=None,
    carat_to=None,
    fluoro=None,
    labs=None
):
    shape = center_stone.get("shape")
    carat = center_stone.get("carat")
    color = center_stone.get("color")
    clarity = center_stone.get("clarity")
    if fluoro is None:
        fluoro = center_stone.get("fluorescence")

    # fallback defaults
    if carat_from is None:
        carat_from = round(carat - 0.1, 2)
    if carat_to is None:
        carat_to = round(carat + 0.1, 2)

    if color_from is None:
        color_from = color
    if color_to is None:
        color_to = color
    if fluoro and str(fluoro).lower() not in ("none", "unknown"):
        fluorescence_filter = [fluoro]
    else:
        fluorescence_filter = None

    if clarity_from is None:
        clarity_from = clarity
    if clarity_to is None:
        clarity_to = clarity

    payload = {
        "request": {
            "header": {},
            "body": {
                "search_type": "White",
                "shapes": [shape],
                "size_from": str(carat_from),
                "size_to": str(carat_to),
                "color_from": color_from,
                "color_to": color_to,
                "clarity_from": clarity_from,
                "clarity_to": clarity_to,
                "labs": labs or LABS_PRIMARY,
                "page_number": "1",
                "page_size": "50",
                "sort_by": "Price",
                "sort_direction": "Asc"
            }
        }
    }
    # Do not force fluorescence=None filter when value is unknown/missing.
    if fluorescence_filter:
        payload["request"]["body"]["fluorescence_intensities"] = fluorescence_filter
    return payload

    
def get_anchor_with_fallback(center_stone, rapnet_token,call_rapnet_api, compute_anchor):
    color = (center_stone.get("color") or "G").upper()
    clarity = (center_stone.get("clarity") or "VS1").upper()
    carat = center_stone.get("carat")
    fluorescence = center_stone.get("fluorescence")

    # indexes
    color_idx = COLOR_ORDER.index(color) if color in COLOR_ORDER else COLOR_ORDER.index("G")
    clarity_idx = CLARITY_ORDER.index(clarity) if clarity in CLARITY_ORDER else CLARITY_ORDER.index("VS1")

    search_levels = [
        # strict search
        {"carat_delta": 0.1, "color_expand": [0], "clarity_expand": [0], "is_regular": False},
        # slight relaxation (smaller than regular)
        {"carat_delta": 0.2, "color_expand": [1], "clarity_expand": [1], "is_regular": False},
        # regular relaxation
        {"carat_delta": 0.5, "color_expand": [0, 1, 2], "clarity_expand": [0, 1, 2], "is_regular": True},
    ]
    best_attempt = None

    for level in search_levels:
        carat_delta = level["carat_delta"]
        carat_from = round(carat - carat_delta, 2)
        carat_to = round(carat + carat_delta, 2)

        for color_expand in level["color_expand"]:
            for clarity_expand in level["clarity_expand"]:
                c_from = COLOR_ORDER[max(0, color_idx - color_expand)]
                c_to   = COLOR_ORDER[min(len(COLOR_ORDER)-1, color_idx + color_expand)]

                cl_from = CLARITY_ORDER[max(0, clarity_idx - clarity_expand)]
                cl_to   = CLARITY_ORDER[min(len(CLARITY_ORDER)-1, clarity_idx + clarity_expand)]

                lab_sets = [LABS_PRIMARY, LABS_FALLBACK]
                for current_labs in lab_sets:
                    payload = build_rapnet_payload(
                        center_stone,
                        color_from=c_from,
                        color_to=c_to,
                        clarity_from=cl_from,
                        clarity_to=cl_to,
                        carat_from=carat_from,
                        carat_to=carat_to,
                        fluoro=fluorescence,
                        labs=current_labs
                    )

                    try:
                        res = call_rapnet_api(payload, rapnet_token)
                        anchor_data = compute_anchor(
                            res,
                            target_stone=center_stone,
                            search_meta={
                                "carat_delta": carat_delta,
                                "color_expand": color_expand,
                                "clarity_expand": clarity_expand,
                                "labs": current_labs,
                            }
                        )

                        if anchor_data is not None:
                            diamonds = res.get("response", {}).get("body", {}).get("diamonds", [])
                            comparable_count = int(anchor_data.get("count") or len(diamonds))
                            anchor = anchor_data.get("anchor", anchor_data)

                            candidate = {
                                "low": anchor["low"],
                                "high": anchor["high"],
                                "comparables": anchor_data.get("comparables", diamonds[:5]),
                                "count": comparable_count,
                                "effective_specs": {
                                    "carat_min": carat_from,
                                    "carat_max": carat_to,
                                    "color": [c_from, c_to],
                                    "clarity": [cl_from, cl_to],
                                    "shape": center_stone.get("shape"),
                                    "cut": center_stone.get("cut"),
                                    "labs": current_labs
                                },
                                "confidence": anchor_data.get("confidence"),
                                "fallback_expansion": anchor_data.get("fallback_expansion"),
                                "used_fallback": (
                                    carat_delta > 0.1
                                    or color_expand > 0
                                    or clarity_expand > 0
                                    or current_labs != LABS_PRIMARY
                                ),
                                "insufficient_comparables": comparable_count < MIN_COMPARABLES_REQUIRED,
                            }

                            if best_attempt is None or comparable_count > best_attempt["count"]:
                                best_attempt = candidate

                            if comparable_count >= MIN_COMPARABLES_REQUIRED:
                                return candidate

                            # If GIA-only already has a healthy sample, skip broader lab query.
                            if current_labs == LABS_PRIMARY and comparable_count >= MIN_RESULTS_TO_KEEP_GIA_ONLY:
                                break

                    except Exception as e:
                        print("ERROR in anchor compute:", e)
                        continue

    return best_attempt





def call_rapnet_api(payload, rapnet_token):
    print("\n================ RAPNET REQUEST ================")
    print(payload)
    print("================================================\n")

    cache_key = json.dumps(
        {"payload": payload, "token_suffix": str(rapnet_token)[-8:]},
        sort_keys=True,
        default=str
    )
    now = time.time()
    cached = _RAPNET_CACHE.get(cache_key)
    if cached and now < cached["expires_at"]:
        return cached["data"]

    headers = {
        "Authorization": f"Bearer {rapnet_token}",
        "Content-Type": "application/json"
    }

    response = requests.post(
        RAPNET_URL,
        headers=headers,
        json=payload,
        timeout=TIMEOUT_SECONDS
    )

    response.raise_for_status()
    data = response.json()
    if len(_RAPNET_CACHE) > 300:
        _RAPNET_CACHE.clear()
    _RAPNET_CACHE[cache_key] = {"data": data, "expires_at": now + RAPNET_CACHE_TTL_SECONDS}
    return data


def _confidence_label(score):
    if score >= 0.8:
        return "high"
    if score >= 0.6:
        return "medium"
    return "low"


def _apply_thin_data_discount_floor(
    base_multiplier,
    count,
    avg_weight,
    carat_delta,
    color_expand,
    clarity_expand,
    lab_broadened
):
    """
    Reduce over-discounting for high-quality, low-relaxation thin-data cases.
    """
    if count > 2 or avg_weight < 0.8:
        return base_multiplier

    is_strict = (
        carat_delta <= 0.1
        and color_expand == 0
        and clarity_expand == 0
        and not lab_broadened
    )
    is_slight = (
        not is_strict
        and carat_delta <= 0.2
        and color_expand <= 1
        and clarity_expand <= 1
        and not lab_broadened
    )

    if is_strict:
        floor = 0.85 if count == 1 else 0.90
        return max(base_multiplier, floor)
    if is_slight:
        floor = 0.80 if count == 1 else 0.86
        return max(base_multiplier, floor)
    return base_multiplier


def compute_anchor_from_rapnet(rapnet_response, target_stone=None, search_meta=None):

    diamonds = rapnet_response["response"]["body"]["diamonds"]

    weighted_prices = []
    weighted_comparables = []
    for d in diamonds:
        price = _to_float(d.get("total_sales_price"))
        if price is None:
            continue
        weight = _compute_similarity_weight(d, target_stone or {}) if target_stone else 1.0
        weighted_prices.append((price, weight))
        d_enriched = dict(d)
        d_enriched["similarity_weight"] = round(weight, 4)
        weighted_comparables.append(d_enriched)

    if len(weighted_prices) < 1:
        return None

    weighted_prices.sort(key=lambda x: x[0])
    p25 = _weighted_percentile_price(weighted_prices, 0.25)
    p75 = _weighted_percentile_price(weighted_prices, 0.75)
    if p25 is None or p75 is None:
        return None

    count = len(weighted_prices)
    carat_delta = (search_meta or {}).get("carat_delta", 0.1)
    color_expand = (search_meta or {}).get("color_expand", 0)
    clarity_expand = (search_meta or {}).get("clarity_expand", 0)
    lab_broadened = (search_meta or {}).get("labs", LABS_PRIMARY) != LABS_PRIMARY
    avg_weight = sum(w for _, w in weighted_prices) / count if count else 0.0

    discount_multiplier = 1.0
    if count < THIN_DATA_NO_DISCOUNT_MIN_COUNT:
        discount_multiplier = THIN_DATA_DISCOUNT_BY_COUNT.get(count, 0.55)
    discount_multiplier = _apply_thin_data_discount_floor(
        discount_multiplier,
        count,
        avg_weight,
        carat_delta,
        color_expand,
        clarity_expand,
        lab_broadened
    )

    anchor = {
        "low": round(p25 * discount_multiplier, 2),
        "high": round(p75 * discount_multiplier, 2)
    }

    expansion_penalty = (max(0.0, carat_delta - 0.1) * 0.8) + (color_expand * 0.08) + (clarity_expand * 0.08) + (0.08 if lab_broadened else 0.0)
    thin_data_penalty = 0.0 if discount_multiplier == 1.0 else (1.0 - discount_multiplier) * 0.5
    confidence_score = max(0.05, min(1.0, avg_weight - expansion_penalty - thin_data_penalty))

    weighted_comparables.sort(
        key=lambda x: (_to_float(x.get("similarity_weight")) or 0.0),
        reverse=True
    )

    return {
        "anchor": anchor,
        "comparables": weighted_comparables[:5],  # highest-weight comps first
        "count": len(weighted_comparables),
        "confidence": {
            "score": round(confidence_score, 2),
            "label": _confidence_label(confidence_score),
            "avg_similarity_weight": round(avg_weight, 2),
            "thin_data_discount_multiplier": round(discount_multiplier, 3),
            "weighted_method": True
        },
        "fallback_expansion": {
            "carat_delta": carat_delta,
            "color_expand": color_expand,
            "clarity_expand": clarity_expand,
            "lab_broadened": lab_broadened
        }
    }
