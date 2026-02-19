import requests

GEMGEM_URL = "https://admin-li4d5lkr.gemgem.com/api/v1/c2c/shop"

COLOR_ORDER = ["d","e","f","g","h","i","j","k","l","m"]
CLARITY_ORDER = ["if","vvs1","vvs2","vs1","vs2","si1","si2","si3","i1","i2","i3"]

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

def get_anchor_with_fallback_gemgem(center_stone):

    color = center_stone["color"].lower()
    clarity = center_stone["clarity"].lower()
    carat = center_stone["carat"]

    color_idx = COLOR_ORDER.index(color)
    clarity_idx = CLARITY_ORDER.index(clarity)

    carat_ranges = [
        (round(carat - 0.1, 2), round(carat + 0.1, 2), 0),   # strict
        (round(carat - 0.5, 2), round(carat + 0.5, 2), 1)    # relaxed
    ]

    MIN_COMPS = 1

    for carat_min, carat_max, carat_step in carat_ranges:

        for expand in range(0, 2):   # 0 = exact, 1 = relaxed

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
                res = requests.get(GEMGEM_URL, params=payload)
                data = res.json()

                products = data["data"]["products"]["data"]
                print("GemGem products found:", len(products))

                prices = [
                    p["price"]["USD"]["price"]
                    for p in products
                    if p.get("price") and p["price"]["USD"].get("price")
                ]

                if len(prices) >= MIN_COMPS:
                    prices.sort()

                    return {
                        "low": prices[int(len(prices) * 0.25)],
                        "high": prices[int(len(prices) * 0.75)],
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
                        "result_count": len(prices),
                        "used_fallback": (carat_step != 0 or color_step != 0 or clarity_step != 0)
                    }

            except Exception as e:
                print("GemGem request failed:", e)
                continue

    return None
