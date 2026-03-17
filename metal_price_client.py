import requests
import os
import time
METAL_PRICE_API_URL = "https://api.metalpriceapi.com/v1/latest"
import os

try:
    import streamlit as st
    METAL_PRICE_API_KEY = st.secrets.get("METAL_PRICE_API_KEY")
    _JEWELRY_FABRICATION_MULTIPLIER_RAW = st.secrets.get("JEWELRY_FABRICATION_MULTIPLIER")
except Exception:
    METAL_PRICE_API_KEY = os.getenv("METAL_PRICE_API_KEY")
    _JEWELRY_FABRICATION_MULTIPLIER_RAW = None


if not METAL_PRICE_API_KEY:
    raise RuntimeError("METAL_PRICE_API_KEY not set in environment")


TROY_OUNCE_TO_GRAMS = 31.1035
METAL_PRICE_CACHE_TTL_SECONDS = 12 * 60 * 60
JEWELRY_FABRICATION_MULTIPLIER = float(
    _JEWELRY_FABRICATION_MULTIPLIER_RAW
    or os.getenv("JEWELRY_FABRICATION_MULTIPLIER", "1.45")
)

PURITY_FACTORS = {
    "10K": 0.417,
    "12K": 0.500,
    "24K": 1.00,
    "22K": 0.916,
    "18K": 0.75,
    "16K": 0.667,
    "14K": 0.585,
    "PT950": 0.95
}
_METAL_PRICE_CACHE = {"value": None, "expires_at": 0.0}


def fetch_metal_prices():
    now = time.time()
    if _METAL_PRICE_CACHE["value"] is not None and now < _METAL_PRICE_CACHE["expires_at"]:
        return _METAL_PRICE_CACHE["value"]

    params = {
        "api_key": METAL_PRICE_API_KEY,
        "base": "USD",
        "currencies": "XAU,XPT"
    }

    response = requests.get(METAL_PRICE_API_URL, params=params, timeout=10)
    response.raise_for_status()
    data = response.json()
    _METAL_PRICE_CACHE["value"] = data
    _METAL_PRICE_CACHE["expires_at"] = now + METAL_PRICE_CACHE_TTL_SECONDS
    return data

def normalize_metal_type(metal_str: str) -> str:
    metal_str = metal_str.lower().strip()

    if "gold" in metal_str:
        return "gold"
    if "platinum" in metal_str or "pt" in metal_str:
        return "platinum"

    raise ValueError(f"Unsupported metal type: {metal_str}")


def compute_metal_value(metal_type: str, purity: str, weight_grams: float, apply_jewelry_multiplier: bool = True) -> float:
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
    if apply_jewelry_multiplier:
        metal_value *= JEWELRY_FABRICATION_MULTIPLIER
    return round(metal_value, 2)
