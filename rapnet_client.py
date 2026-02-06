import requests
import os

RAPNET_URL = "https://technet.rapnetapis.com/instant-inventory/api/Diamonds"

RAPNET_BEARER_TOKEN = os.getenv("RAPNET_BEARER_TOKEN")

if not RAPNET_BEARER_TOKEN:
    raise RuntimeError("RAPNET_BEARER_TOKEN not set in environment")
TIMEOUT_SECONDS = 15

def build_rapnet_payload(center_stone):
    body = {
        "search_type": "White",
        "shapes": [center_stone.get("shape", "Round")],
        "size_from": max(center_stone.get("carat", 0.9) - 0.15, 0.01),
        "size_to": center_stone.get("carat", 1.0) + 0.15,
        "page_number": 1,
        "page_size": 50,
        "sort_by": "Price",
        "sort_direction": "Asc",
        "labs": ["GIA"],
        "fluorescence_intensities": ["None"]
    }

    # ✅ Color filter only if known
    color = center_stone.get("color")
    if isinstance(color, str) and len(color) == 1:
        body["color_from"] = color
        body["color_to"] = chr(ord(color) + 1)  # G → H

    # ✅ Clarity filter only if known
    clarity = center_stone.get("clarity")
    if isinstance(clarity, str):
        body["clarity_from"] = clarity
        body["clarity_to"] = clarity

    return {
        "request": {
            "header": {
                "Authorization": f"Bearer {RAPNET_BEARER_TOKEN}",
                "Content-Type": "application/json"
            },
            "body": body
        }
    }




def call_rapnet_api(payload):
    headers = {
        "Authorization": f"Bearer {RAPNET_BEARER_TOKEN}",
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

    if len(prices) < 3:
        return None  # <-- IMPORTANT

    prices.sort()

    return {
        "low": round(prices[int(len(prices) * 0.25)], 2),
        "high": round(prices[int(len(prices) * 0.75)], 2)
    }

