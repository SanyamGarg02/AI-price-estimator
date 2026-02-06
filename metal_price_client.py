import requests
import os
METAL_PRICE_API_URL = "https://api.metalpriceapi.com/v1/latest"
METAL_API_KEY = os.getenv("METAL_PRICE_API_KEY")

if not METAL_API_KEY:
    raise RuntimeError("METAL_PRICE_API_KEY not set in environment")


TROY_OUNCE_TO_GRAMS = 31.1035

PURITY_FACTORS = {
    "24K": 1.00,
    "22K": 0.916,
    "18K": 0.75,
    "14K": 0.585,
    "PT950": 0.95
}


def fetch_metal_prices():
    params = {
        "api_key": METAL_API_KEY,
        "base": "USD",
        "currencies": "XAU,XPT"
    }

    response = requests.get(METAL_PRICE_API_URL, params=params, timeout=10)
    response.raise_for_status()
    return response.json()

def normalize_metal_type(metal_str: str) -> str:
    metal_str = metal_str.lower().strip()

    if "gold" in metal_str:
        return "gold"
    if "platinum" in metal_str or "pt" in metal_str:
        return "platinum"

    raise ValueError(f"Unsupported metal type: {metal_str}")


def compute_metal_value(metal_type: str, purity: str, weight_grams: float) -> float:
    metal_type = normalize_metal_type(metal_type)
    purity = purity.upper().strip()

    data = fetch_metal_prices()
    rates = data["rates"]

    if metal_type == "gold":
        usd_per_oz = rates["USDXAU"]
    elif metal_type == "platinum":
        usd_per_oz = rates["USDXPT"]
    else:
        raise ValueError(f"Unsupported metal type: {metal_type}")

    usd_per_gram = usd_per_oz / TROY_OUNCE_TO_GRAMS

    purity_factor = PURITY_FACTORS.get(purity)
    if purity_factor is None:
        raise ValueError(f"Unsupported purity: {purity}")

    metal_value = usd_per_gram * purity_factor * weight_grams
    return round(metal_value, 2)
