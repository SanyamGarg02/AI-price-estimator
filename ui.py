from dotenv import load_dotenv
load_dotenv()
import os
import streamlit as st
def get_env(key, default=None):
    # prefer OS env (local .env), else Streamlit secrets, else default
    return os.getenv(key) or st.secrets.get(key, default)


PRICE_SOURCE = (get_env("PRICE_SOURCE", "gemgem")).lower()
ENABLE_AI = (get_env("ENABLE_AI", "false")).lower() == "true"
USE_RAPNET = PRICE_SOURCE == "rapnet"
from pricing_ai_for_ui import run_pricing_pipeline  # your main function
SHAPES = [
    "Round", "Pear", "Princess", "Marquise", "Oval",
    "Radiant", "Emerald", "Heart", "Cushion", "Asscher"
]

COLORS = ["D", "E", "F", "G", "H", "I", "J", "K", "L", "M"]

CLARITIES = [
    "IF", "VVS1", "VVS2", "VS1", "VS2",
    "SI1", "SI2", "SI3", "I1", "I2", "I3"
]

st.title("AI Price Estimation MVP")
rapnet_token = None

if USE_RAPNET:
    rapnet_token = st.text_input(
        "Enter RapNet Bearer Token",
        type="password"
    )

# Images
images = []

if ENABLE_AI:
    uploaded_files = st.file_uploader(
        "Upload up to 3 images",
        type=["jpg", "jpeg", "png"],
        accept_multiple_files=True
    )

    if uploaded_files:
        for file in uploaded_files:
            images.append(file.getvalue())



jewelry_type = st.selectbox(
    "Product Type",
    ["Loose Diamond", "Diamond Jewelry"]
)

st.subheader("Center Stone Details")
carat = st.number_input("Carat", min_value=0.0, step=0.01)
shape = st.selectbox("Shape", SHAPES)

color = st.selectbox(
    "Color",
    options=["Unknown"] + COLORS
)

clarity = st.selectbox(
    "Clarity",
    options=["Unknown"] + CLARITIES
)

cut = st.selectbox("Cut", ["Unknown", "Excellent", "Very Good", "Good", "Fair"])
polish = st.selectbox("Polish", ["Unknown", "Excellent", "Very Good", "Good", "Fair"])
symmetry = st.selectbox("Symmetry", ["Unknown", "Excellent", "Very Good", "Good", "Fair"])
fluorescence = st.selectbox(
    "Fluorescence",
    ["None", "Faint", "Medium", "Strong", "Very Strong"]
)

condition = st.selectbox(
    "Condition",
    ["Excellent", "Like New", "Good", "Fair"]
)


metal = purity = metal_weight = None


if jewelry_type == "Diamond Jewelry":
    st.subheader("Jewelry Details")
    metal = st.text_input("Metal")
    purity = st.selectbox("Purity", ["14K", "18K", "22K", "PT950"])
    metal_weight = st.number_input("Approx Metal Weight (grams)", min_value=0.0)

if st.button("Get Price Estimate"):
    # 🚫 If AI layer is enabled → stop here
    
    if USE_RAPNET and not rapnet_token:
        st.error("RapNet token is required for RapNet pricing")
        st.stop()

    user_input = {
        "images": images,
        "jewelry_type": jewelry_type,
        "center_stone": {
            "shape": shape,
            "carat": carat,
            "color": None if color == "Unknown" else color,
            "clarity": None if clarity == "Unknown" else clarity,
            "cut": None if cut == "Unknown" else cut,
            "polish": None if polish == "Unknown" else polish,
            "symmetry": None if symmetry == "Unknown" else symmetry,
            "fluorescence": fluorescence
        },
        "condition": condition,
        "metal": metal,
        "purity": purity,
        "metal_weight_grams": metal_weight
    }
    

    with st.spinner("Analyzing market comps and relaxing filters if needed..."):
        ai_layer = "Enabled" if ENABLE_AI else "Disabled"

        result = run_pricing_pipeline(user_input, rapnet_token, ai_layer)

    # result = run_pricing_pipeline(user_input, rapnet_token, ai_layer)
    eff = result.get("effective_specs")
    used_fallback = result.get("used_fallback", False)

    if eff and used_fallback:
        st.info(
            f"""
    ⚠️ Exact match not found. Showing closest market comps.

    Results are based on:
    Carat: {eff['carat_min']} – {eff['carat_max']} ct  
    Color: {', '.join(eff['color'])}  
    Clarity: {', '.join(eff['clarity'])}
    """
    )

    st.subheader("Result")
    st.json(result)
