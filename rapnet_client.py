import requests
import os
COLOR_ORDER = ["D","E","F","G","H","I","J","K","L","M"]
CLARITY_ORDER = ["IF","VVS1","VVS2","VS1","VS2","SI1","SI2","SI3","I1","I2","I3"]

RAPNET_URL = "https://technet.rapnetapis.com/instant-inventory/api/Diamonds"


TIMEOUT_SECONDS = 15

def build_rapnet_payload(center_stone, color_from=None, color_to=None, clarity_from=None, clarity_to=None, carat_from=None, carat_to=None,fluoro=None):
    shape = center_stone.get("shape")
    carat = center_stone.get("carat")
    color = center_stone.get("color")
    clarity = center_stone.get("clarity")
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
    if fluoro and fluoro.lower() != "none":
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
                "labs": ["GIA"],
                "fluorescence_intensities": fluorescence_filter or ["None"],
                "page_number": "1",
                "page_size": "50",
                "sort_by": "Price",
                "sort_direction": "Asc"
            }
        }
    }
    return payload
def get_anchor_with_fallback(center_stone, rapnet_token,call_rapnet_api, compute_anchor):
    color = center_stone.get("color")
    clarity = center_stone.get("clarity")
    carat = center_stone.get("carat")
    fluorescence = center_stone.get("fluorescence")

    # indexes
    color_idx = COLOR_ORDER.index(color)
    clarity_idx = CLARITY_ORDER.index(clarity)

    carat_ranges = [
        (carat - 0.1, carat + 0.1),
        (carat - 0.5, carat + 0.5)
    ]

    for cr in carat_ranges:
        for color_expand in range(0, 3):
            for clarity_expand in range(0, 3):
                c_from = COLOR_ORDER[max(0, color_idx - color_expand)]
                c_to   = COLOR_ORDER[min(len(COLOR_ORDER)-1, color_idx + color_expand)]

                cl_from = CLARITY_ORDER[max(0, clarity_idx - clarity_expand)]
                cl_to   = CLARITY_ORDER[min(len(CLARITY_ORDER)-1, clarity_idx + clarity_expand)]

                payload = build_rapnet_payload(
                    center_stone,
                    color_from=c_from,
                    color_to=c_to,
                    clarity_from=cl_from,
                    clarity_to=cl_to,
                    carat_from=round(cr[0],2),
                    carat_to=round(cr[1],2),
                    fluoro=fluorescence
                )

                try:
                    res = call_rapnet_api(payload, rapnet_token)
                    anchor = compute_anchor(res)

                    if anchor is not None:

                        return {
                            "low": anchor["low"],
                            "high": anchor["high"],

                            "effective_specs": {
                            "carat_min": round(cr[0], 2),
                            "carat_max": round(cr[1], 2),
                            "color": [c_from, c_to],
                            "clarity": [cl_from, cl_to],
                            "shape": center_stone.get("shape"),
                            "cut": center_stone.get("cut"),
                            "lab": payload["request"]["body"]["labs"][0] if payload["request"]["body"].get("labs") else None
            },

            "result_count": anchor.get("result_count", 0),

            "used_fallback": (color_expand > 0 or clarity_expand > 0 or cr != carat_ranges[0])
    }

                except Exception as e:
                    print("ERROR in anchor compute:", e)
                    continue

    return None





def call_rapnet_api(payload, rapnet_token):
    print("\n================ RAPNET REQUEST ================")
    print(payload)
    print("================================================\n")

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
    return response.json()


def compute_anchor_from_rapnet(rapnet_response):
    diamonds = rapnet_response["response"]["body"]["diamonds"]

    prices = [
        d["total_sales_price"]
        for d in diamonds
        if d.get("total_sales_price") is not None
    ]

    if len(prices) < 1:
        return None

    prices.sort()

    return {
        "low": round(prices[int(len(prices) * 0.25)], 2),
        "high": round(prices[int(len(prices) * 0.75)], 2),
        "result_count": len(prices)
    }
