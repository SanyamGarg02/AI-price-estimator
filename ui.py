import streamlit as st
from pricing_ai_for_ui import run_pricing_pipeline  # your main function

st.title("AI Price Estimation MVP")

# Images
uploaded_files = st.file_uploader(
    "Upload up to 3 images",
    type=["jpg", "jpeg", "png"],
    accept_multiple_files=True
)

images = []
if uploaded_files:
    for file in uploaded_files:
        images.append(file.getvalue())  # ✅ convert to bytes


jewelry_type = st.selectbox(
    "Product Type",
    ["Loose Diamond", "Diamond Jewelry"]
)

st.subheader("Center Stone Details")
shape = st.text_input("Shape")
carat = st.number_input("Carat", min_value=0.0, step=0.01)
color = st.text_input("Color (optional)")
clarity = st.text_input("Clarity (optional)")
cut = st.selectbox("Cut", ["Excellent", "Very Good", "Good", "Fair"])
polish = st.selectbox("Polish", ["Excellent", "Very Good", "Good", "Fair"])
symmetry = st.selectbox("Symmetry", ["Excellent", "Very Good", "Good", "Fair"])
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
    user_input = {
        "images": images,
        "jewelry_type": jewelry_type,
        "center_stone": {
            "shape": shape,
            "carat": carat,
            "color": color or None,
            "clarity": clarity or None,
            "cut": cut,
            "polish": polish,
            "symmetry": symmetry,
            "fluorescence": fluorescence
        },
        "condition": condition,
        "metal": metal,
        "purity": purity,
        "metal_weight_grams": metal_weight
    }

    result = run_pricing_pipeline(user_input)

    st.subheader("Result")
    st.json(result)
