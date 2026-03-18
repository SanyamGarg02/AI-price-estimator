import requests
import json
import time

GEMGEM_URL = "https://admin-li4d5lkr.gemgem.com/api/v1/c2c/shop"

COLOR_ORDER = ["d","e","f","g","h","i","j","k","l","m"]
CLARITY_ORDER = ["if","vvs1","vvs2","vs1","vs2","si1","si2","si3","i1","i2","i3"]
MIN_COMPARABLES_REQUIRED = 3
THIN_DATA_DISCOUNT_BY_COUNT = {
    1: 0.55,
    2: 0.62,
    3: 0.70,
    4: 0.78,
    5: 0.85,
    6: 0.92,
    7: 0.92
}
THIN_DATA_NO_DISCOUNT_MIN_COUNT = 8
GEMGEM_CACHE_TTL_SECONDS = 60 * 60
_GEMGEM_CACHE = {}


def _to_float(value):
    try:
        return float(value)
    except Exception:
        return None


def _extract_color_from_product(product):
    direct = product.get("color") or product.get("diamond_color")
    if direct:
        return str(direct).lower()
    values = (
        product.get("_source", {})
        .get("options", {})
        .get("values", [])
    )
    for val in values:
        sval = str(val).lower()
        if sval in COLOR_ORDER:
            return sval
    return None


def _extract_clarity_from_product(product):
    direct = product.get("clarity") or product.get("diamond_clarity")
    if direct:
        return str(direct).lower()
    values = (
        product.get("_source", {})
        .get("options", {})
        .get("values", [])
    )
    for val in values:
        sval = str(val).lower()
        if sval in CLARITY_ORDER:
            return sval
    return None


def _extract_carat_from_product(product):
    direct = product.get("carat") or product.get("size") or product.get("carat_weight")
    f = _to_float(direct)
    if f is not None:
        return f
    src = product.get("_source", {})
    for key in ("attr_40", "attr_125", "attr_126"):
        val = _to_float(src.get(key))
        if val is not None and 0.05 <= val <= 20:
            return val
    values = (
        src.get("options", {})
        .get("values", [])
    )
    for val in values:
        sval = str(val).lower()
        if "_" in sval:
            head = sval.split("_", 1)[0]
            maybe = _to_float(head)
            if maybe is not None and 0.05 <= maybe <= 20:
                return maybe
    return None


def _compute_similarity_weight(product, target):
    target_carat = _to_float(target.get("carat"))
    target_color = str(target.get("color") or "").lower() or None
    target_clarity = str(target.get("clarity") or "").lower() or None

    comp_carat = _extract_carat_from_product(product)
    comp_color = _extract_color_from_product(product)
    comp_clarity = _extract_clarity_from_product(product)

    carat_penalty = 0.0
    if target_carat is not None and comp_carat is not None:
        carat_penalty = abs(comp_carat - target_carat) / max(target_carat, 0.01)

    color_penalty = 0.0
    if target_color in COLOR_ORDER and comp_color in COLOR_ORDER:
        color_penalty = abs(COLOR_ORDER.index(comp_color) - COLOR_ORDER.index(target_color)) * 0.12

    clarity_penalty = 0.0
    if target_clarity in CLARITY_ORDER and comp_clarity in CLARITY_ORDER:
        clarity_penalty = abs(CLARITY_ORDER.index(comp_clarity) - CLARITY_ORDER.index(target_clarity)) * 0.12

    raw = 1.0 - carat_penalty - color_penalty - clarity_penalty
    return max(0.15, min(1.0, raw))


def _weighted_percentile_price(weighted_prices, q):
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


def _confidence_label(score):
    if score >= 0.8:
        return "high"
    if score >= 0.6:
        return "medium"
    return "low"


def _apply_thin_data_discount_floor(base_multiplier, count, avg_weight, carat_step, expand):
    """
    Reduce over-discounting for high-similarity strict/slight searches.
    """
    if count > 2 or avg_weight < 0.8:
        return base_multiplier

    is_strict = (carat_step == 0 and expand == 0)
    is_slight = (carat_step == 1 and expand <= 1)

    if is_strict:
        floor = 0.85 if count == 1 else 0.90
        return max(base_multiplier, floor)
    if is_slight:
        floor = 0.80 if count == 1 else 0.86
        return max(base_multiplier, floor)
    return base_multiplier

def build_gemgem_payload(center_stone, colors, clarities, carat_from, carat_to):

    params = []

    # clarity
    for i, c in enumerate(clarities):
        params.append((f"options[{i}][attribute_id]", "diamond-clarity"))
        params.append((f"options[{i}][option_id]", c.lower()))

    base_index = len(params)//2

    # color
    for j, col in enumerate(colors):
        idx = base_index + j
        params.append((f"options[{idx}][attribute_id]", "diamond-color-white-options"))
        params.append((f"options[{idx}][option_id]", col.lower()))

    idx += 1
    params.append((f"options[{idx}][attribute_id]", "diamond-shape"))
    params.append((f"options[{idx}][option_id]", center_stone["shape"].lower()))

    idx += 1
    params.append((f"options[{idx}][attribute_id]", "carat-weight"))
    params.append((f"options[{idx}][option_id][0]", round(carat_from, 2)))
    params.append((f"options[{idx}][option_id][1]", round(carat_to, 2)))

    params.append(("category[0]", "diamonds"))
    params.append(("page", 1))
    params.append(("limit", 10))
    params.append(("lang", "en"))

    return params


def _gemgem_cache_key(params):
    # params is list of tuples; stable string key preserves order and values
    return json.dumps(params, sort_keys=False, default=str)


def _get_gemgem_response_with_cache(params):
    key = _gemgem_cache_key(params)
    now = time.time()
    cached = _GEMGEM_CACHE.get(key)
    if cached and now < cached["expires_at"]:
        return cached["data"]

    res = requests.get(GEMGEM_URL, params=params)
    data = res.json()
    # basic cache bound to avoid unbounded growth
    if len(_GEMGEM_CACHE) > 300:
        _GEMGEM_CACHE.clear()
    _GEMGEM_CACHE[key] = {"data": data, "expires_at": now + GEMGEM_CACHE_TTL_SECONDS}
    return data

def get_anchor_with_fallback_gemgem(center_stone):

    color = center_stone.get("color")
    clarity = center_stone.get("clarity")
    carat = center_stone.get("carat")

    # only lower if present
    color = color.lower() if color else None
    clarity = clarity.lower() if clarity else None


    color_idx = COLOR_ORDER.index(color) if color else None
    clarity_idx = CLARITY_ORDER.index(clarity) if clarity else None


    search_levels = [
        # strict
        {"carat_delta": 0.1, "expand_levels": [0], "carat_step": 0},
        # slight relaxation (smaller than regular)
        {"carat_delta": 0.2, "expand_levels": [1], "carat_step": 1},
        # regular relaxation
        {"carat_delta": 0.5, "expand_levels": [0, 1], "carat_step": 2},
    ]
    best_attempt = None

    for level in search_levels:
        carat_min = round(carat - level["carat_delta"], 2)
        carat_max = round(carat + level["carat_delta"], 2)
        carat_step = level["carat_step"]

        for expand in level["expand_levels"]:
            color_step = expand
            clarity_step = expand

            colors = COLOR_ORDER[
                max(0, color_idx-expand): min(len(COLOR_ORDER), color_idx+expand+1)
            ]

            clarities = CLARITY_ORDER[
                max(0, clarity_idx-expand): min(len(CLARITY_ORDER), clarity_idx+expand+1)
            ]

            payload = build_gemgem_payload(center_stone, colors, clarities, carat_min, carat_max)

            print("\n================ GEMGEM REQUEST ================")
            print(payload)
            print("================================================\n")

            try:
                data = _get_gemgem_response_with_cache(payload)

                products = data["data"]["products"]["data"]
                print("GemGem products found:", len(products))

                prices = [
                    p["price"]["USD"]["price"]
                    for p in products
                    if p.get("price") and p["price"]["USD"].get("price")
                ]

                if len(prices) > 0:
                    weighted_prices = []
                    weighted_comparables = []
                    for p in products:
                        price = _to_float(
                            p.get("price", {})
                            .get("USD", {})
                            .get("price")
                        )
                        if price is None:
                            continue
                        weight = _compute_similarity_weight(
                            p,
                            {
                                "carat": carat,
                                "color": color,
                                "clarity": clarity
                            }
                        )
                        weighted_prices.append((price, weight))
                        p_enriched = dict(p)
                        p_enriched["similarity_weight"] = round(weight, 4)
                        weighted_comparables.append(p_enriched)

                    if not weighted_prices:
                        continue

                    weighted_prices.sort(key=lambda x: x[0])
                    p25 = _weighted_percentile_price(weighted_prices, 0.25)
                    p75 = _weighted_percentile_price(weighted_prices, 0.75)
                    if p25 is None or p75 is None:
                        continue

                    weighted_comparables.sort(
                        key=lambda x: _to_float(x.get("similarity_weight")) or 0.0,
                        reverse=True
                    )

                    count = len(weighted_prices)
                    avg_weight = sum(w for _, w in weighted_prices) / count if count else 0.0
                    discount_multiplier = 1.0
                    if count < THIN_DATA_NO_DISCOUNT_MIN_COUNT:
                        discount_multiplier = THIN_DATA_DISCOUNT_BY_COUNT.get(count, 0.55)
                    discount_multiplier = _apply_thin_data_discount_floor(
                        discount_multiplier,
                        count,
                        avg_weight,
                        carat_step,
                        expand
                    )

                    low = round(p25 * discount_multiplier, 2)
                    high = round(p75 * discount_multiplier, 2)
                    expansion_penalty = (max(0.0, level["carat_delta"] - 0.1) * 0.8) + (expand * 0.08) + (expand * 0.08)
                    thin_data_penalty = 0.0 if discount_multiplier == 1.0 else (1.0 - discount_multiplier) * 0.5
                    confidence_score = max(0.05, min(1.0, avg_weight - expansion_penalty - thin_data_penalty))

                    candidate = {
                        "low": low,
                        "high": high,
                        "effective_specs": {
                            "carat_min": carat_min,
                            "carat_max": carat_max,
                            "color": colors,
                            "clarity": clarities,
                            "shape": center_stone["shape"],
                            "cut": center_stone.get("cut"),
                            "lab": center_stone.get("lab")
                        },
                        "fallback_level": {
                            "carat_step": carat_step,
                            "color_step": color_step,
                            "clarity_step": clarity_step
                        },
                        "count": count,
                        "used_fallback": (carat_step != 0 or color_step != 0 or clarity_step != 0),
                        "comparables": weighted_comparables[:5],
                        "insufficient_comparables": count < MIN_COMPARABLES_REQUIRED,
                        "confidence": {
                            "score": round(confidence_score, 2),
                            "label": _confidence_label(confidence_score),
                            "avg_similarity_weight": round(avg_weight, 2),
                            "thin_data_discount_multiplier": round(discount_multiplier, 3),
                            "weighted_method": True
                        },
                        "fallback_expansion": {
                            "carat_delta": level["carat_delta"],
                            "color_expand": expand,
                            "clarity_expand": expand,
                            "lab_broadened": False
                        }
                    }
                    if best_attempt is None or candidate["count"] > best_attempt["count"]:
                        best_attempt = candidate

                    if candidate["count"] >= MIN_COMPARABLES_REQUIRED:
                        return candidate

            except Exception as e:
                print("GemGem request failed:", e)
                continue

    return best_attempt
