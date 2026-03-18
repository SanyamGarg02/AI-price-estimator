from dotenv import load_dotenv
load_dotenv()
import os
import streamlit as st


def _nested_get(data, path, default=None):
    current = data
    for key in path:
        if isinstance(current, dict) and key in current:
            current = current[key]
        else:
            return default
    return current


def _build_product_url(comp):
    direct_url = comp.get("url") or comp.get("product_url")
    if direct_url:
        return direct_url
    slug = comp.get("slug")
    if slug:
        slug = str(slug).strip().lstrip("/")
        if slug.startswith("http://") or slug.startswith("https://"):
            return slug
        return f"https://www.gemgem.com/product/{slug}"
    return "N/A"


def _extract_comparable_specs(comp):
    listing_id = (
        comp.get("listing_id")
        or comp.get("id")
        or _nested_get(comp, ["diamond_id"])
        or _nested_get(comp, ["stock_num"])
    )
    name = (
        comp.get("name")
        or _nested_get(comp, ["title"])
        or _nested_get(comp, ["description"])
        or "N/A"
    )
    price_usd = (
        _nested_get(comp, ["price", "USD", "price"])
        or comp.get("total_sales_price")
        or comp.get("price_usd")
    )

    return {
        "Listing ID": listing_id if listing_id is not None else "N/A",
        "Name": name,
        "Price (USD)": price_usd if price_usd is not None else "N/A",
        "Product URL": _build_product_url(comp)
    }


def _display_comparables(result):
    comparable_count = result.get("comparable_count", 0)
    comparables = result.get("comparables", [])
    insufficient = result.get("insufficient_comparables", False)

    with st.expander(f"Comparable Diamonds Used ({comparable_count}) - Click to view specs"):
        if not comparables:
            st.write("No comparable references available.")
            return

        rows = []
        for comp in comparables:
            row = _extract_comparable_specs(comp)
            if any(value is not None for value in row.values()):
                rows.append(row)

        if rows:
            st.dataframe(
                rows,
                hide_index=True,
                use_container_width=True,
                column_config={
                    "Product URL": st.column_config.LinkColumn("Product URL")
                }
            )
        else:
            st.write("Comparable references were found, but no standard spec fields were available.")
            st.json(comparables)

    if insufficient:
        st.warning(
            "Fewer than 3 comparables were found after fallback and slight relaxation."
        )


def _build_result_for_display(result):
    display_result = dict(result)
    comparables = result.get("comparables", [])
    simplified = []
    for comp in comparables:
        row = _extract_comparable_specs(comp)
        simplified.append({
            "listing_id": row.get("Listing ID"),
            "name": row.get("Name"),
            "price_usd": row.get("Price (USD)"),
            "product_url": row.get("Product URL")
        })
    display_result["comparables"] = simplified
    return display_result


def _fmt_usd(value):
    try:
        return f"${float(value):,.2f}"
    except Exception:
        return "N/A"


def _render_min_max_block(title, low, high):
    st.markdown(f"**{title}**")
    col1, col2 = st.columns(2)
    col1.metric("Min", _fmt_usd(low))
    col2.metric("Max", _fmt_usd(high))


def _render_final_result_ui(result):
    if result.get("error"):
        st.error(result["error"])
        return

    center = result.get("diamond_anchor") or {}
    side = result.get("side_stones_value") or {"low": 0, "high": 0}
    metal_value = float(result.get("metal_value") or 0.0)
    ai_adjust = result.get("ai_adjustment") or {"adjustment_percent": 0}
    final_price = result.get("final_price") or {"low": 0, "high": 0}
    confidence_action = result.get("confidence_action")

    st.subheader("Final Result")
    if confidence_action == "warn":
        st.warning("Confidence is moderate. Review comparable details before final pricing decisions.")
    elif confidence_action == "manual_review":
        st.warning("Confidence is low. Manual review is recommended before using this estimate.")

    _render_min_max_block(
        "Diamond Value (Center + Side Stones)",
        (center.get("low") or 0) + (side.get("low") or 0),
        (center.get("high") or 0) + (side.get("high") or 0)
    )
    _render_min_max_block("Metal Value", metal_value, metal_value)
    _render_min_max_block("Total Price Range (After All Adjustments)", final_price.get("low"), final_price.get("high"))

    why_this_price = result.get("why_this_price")
    if why_this_price:
        st.info(f"Why this price: {why_this_price}")

    with st.expander("Center Stone Details"):
        _render_min_max_block("Center Stone Value", center.get("low"), center.get("high"))
        eff = result.get("effective_specs")
        conf = result.get("anchor_confidence")
        expansion = result.get("fallback_expansion")
        if eff:
            st.write(f"Shape: {eff.get('shape') or 'N/A'}")
            st.write(f"Carat Range: {eff.get('carat_min')} - {eff.get('carat_max')}")
            st.write(f"Color Range: {eff.get('color')}")
            st.write(f"Clarity Range: {eff.get('clarity')}")
            st.write(f"Lab: {eff.get('lab') or eff.get('labs') or 'N/A'}")
        if conf:
            st.write(f"Anchor Confidence: {conf.get('label', 'N/A')} ({conf.get('score', 'N/A')})")
            st.write(f"Thin-Data Discount Multiplier: {conf.get('thin_data_discount_multiplier', 'N/A')}")
        if expansion:
            st.write(
                "Fallback Expansion: "
                f"carat_delta={expansion.get('carat_delta')}, "
                f"color_expand={expansion.get('color_expand')}, "
                f"clarity_expand={expansion.get('clarity_expand')}, "
                f"lab_broadened={expansion.get('lab_broadened')}"
            )

    with st.expander("Side Stones Details"):
        _render_min_max_block("Side Stones Value", side.get("low"), side.get("high"))
        breakdown = result.get("side_stones_breakdown", [])
        if breakdown:
            st.dataframe(breakdown, hide_index=True, use_container_width=True)
        else:
            st.write("No side stones added.")

    with st.expander("Metal Details"):
        _render_min_max_block("Metal Value", metal_value, metal_value)
        st.write({
            "metal_value_usd": _fmt_usd(metal_value)
        })

    st.markdown("**AI Adjustment**")
    st.write(f"Adjustment Percent: {ai_adjust.get('adjustment_percent', 0)}%")
    if ai_adjust.get("key_drivers"):
        st.write(f"Key Drivers: {', '.join(ai_adjust.get('key_drivers', []))}")
    if ai_adjust.get("missing_info"):
        st.write(f"Missing Info: {', '.join(ai_adjust.get('missing_info', []))}")


def get_env(key, default=None):
    # prefer OS env (local .env), else Streamlit secrets, else default
    return os.getenv(key) or st.secrets.get(key, default)


PRICE_SOURCE = (get_env("PRICE_SOURCE", "gemgem")).lower()
ENABLE_AI = (get_env("ENABLE_AI", "false")).lower() == "true"
USE_RAPNET = PRICE_SOURCE == "rapnet"
from pricing_ai_for_ui import run_pricing_pipeline  # your main function
SHAPES = [
"Round",
"Pear",
"Oval",
"Marquise",
"Heart",
"Radiant",
"Princess",
"Emerald",
"Triangle",
"Asscher",
"Cushion",
"Baguette",
"Tapered Baguette",
"Trilliant",
"Hexagonal",
"Pentagonal",
"Octagonal",
"Other"
]

COLORS = [
"D","E","F","G","H",
"I","J","K","L","M",
"N","O","P","Q","R",
"S","T","U","V","W",
"X","Y","Z"
]

CLARITIES = [
"FL",
"IF",
"VVS1",
"VVS2",
"VS1",
"VS2",
"SI1",
"SI2",
"SI3",
"I1",
"I2",
"I3"
]

CUTS = [
"Heart & Arrow",
"Ideal",
"Excellent",
"Very Good",
"Good"
]

POLISH = [
"Ideal",
"Excellent",
"Very Good",
"Good"
]

SYMMETRY = [
"Ideal",
"Excellent",
"Very Good",
"Good"
]

FLUORESCENCE = [
"None",
"Faint",
"Medium",
"Strong",
"Very Strong"
]

TOP_RESALE_BRANDS = [
"Cartier",
"Tiffany & Co.",
"Van Cleef & Arpels",
"Bulgari",
"Harry Winston",
"Chopard",
"Graff",
"Boucheron",
"Buccellati",
"Chaumet",
"Piaget"
]

st.title("AI Price Estimation MVP")
if "side_stone_count" not in st.session_state:
    st.session_state["side_stone_count"] = 0

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

cut = st.selectbox("Cut", ["Unknown"] + CUTS)
polish = st.selectbox("Polish", ["Unknown"] + POLISH)
symmetry = st.selectbox("Symmetry", ["Unknown"] + SYMMETRY)
fluorescence = st.selectbox(
    "Fluorescence",
    ["Unknown"] + FLUORESCENCE
)

side_stones_form = []
if jewelry_type == "Diamond Jewelry":
    st.subheader("Side Stones (Optional)")
    st.caption("Add up to 30 side-stone groups. Per-stone carat is auto-calculated as total carat weight / quantity.")
    side_ctl_col_1, side_ctl_col_2 = st.columns(2)
    with side_ctl_col_1:
        if st.button("Add Side Stone"):
            st.session_state["side_stone_count"] = min(30, st.session_state["side_stone_count"] + 1)
    with side_ctl_col_2:
        if st.button("Remove Last Side Stone"):
            st.session_state["side_stone_count"] = max(0, st.session_state["side_stone_count"] - 1)

    SIDE_STONE_TYPES = ["Diamond", "Ruby", "Sapphire", "Emerald", "Other Gemstone"]
    for idx in range(st.session_state["side_stone_count"]):
        i = idx + 1
        with st.expander(f"Side Stone Group {i}", expanded=False):
            ss_stone_type = st.selectbox(
                f"Stone Type (Group {i})",
                SIDE_STONE_TYPES,
                key=f"ss_stone_type_{idx}"
            )
            ss_qty = st.number_input(
                f"Quantity (Group {i})",
                min_value=1,
                step=1,
                key=f"ss_qty_{idx}"
            )
            ss_total_carat = st.number_input(
                f"Total Carat Weight (Group {i})",
                min_value=0.0,
                step=0.01,
                key=f"ss_total_carat_{idx}"
            )
            ss_shape = st.selectbox(
                f"Shape (Group {i})",
                ["Unknown"] + SHAPES,
                key=f"ss_shape_{idx}"
            )
            ss_color = st.selectbox(
                f"Color (Group {i})",
                ["Unknown"] + COLORS,
                key=f"ss_color_{idx}"
            )
            ss_clarity = st.selectbox(
                f"Clarity (Group {i})",
                ["Unknown"] + CLARITIES,
                key=f"ss_clarity_{idx}"
            )
            ss_cut = st.selectbox(
                f"Cut (Group {i})",
                ["Unknown"] + CUTS,
                key=f"ss_cut_{idx}"
            )
            ss_polish = st.selectbox(
                f"Polish (Optional, Group {i})",
                ["Unknown"] + POLISH,
                key=f"ss_polish_{idx}"
            )
            ss_symmetry = st.selectbox(
                f"Symmetry (Optional, Group {i})",
                ["Unknown"] + SYMMETRY,
                key=f"ss_symmetry_{idx}"
            )
            ss_fluorescence = st.selectbox(
                f"Fluorescence (Optional, Group {i})",
                ["Unknown"] + FLUORESCENCE,
                key=f"ss_fluorescence_{idx}"
            )

            side_stones_form.append({
                "stone_type": ss_stone_type,
                "quantity": ss_qty,
                "total_carat_weight": ss_total_carat,
                "shape": None if ss_shape == "Unknown" else ss_shape,
                "color": None if ss_color == "Unknown" else ss_color,
                "clarity": None if ss_clarity == "Unknown" else ss_clarity,
                "cut": None if ss_cut == "Unknown" else ss_cut,
                "polish": None if ss_polish == "Unknown" else ss_polish,
                "symmetry": None if ss_symmetry == "Unknown" else ss_symmetry,
                "fluorescence": None if ss_fluorescence == "Unknown" else ss_fluorescence
            })

condition = st.selectbox(
    "Condition",
    ["Excellent", "Like New", "Good", "Fair"]
)


metal = purity = metal_weight = None
brand_selection = None
brand_other_text = None
brand_proof = None
if jewelry_type == "Diamond Jewelry":
    brand_selection = st.selectbox(
        "Brand",
        TOP_RESALE_BRANDS + ["Other / Unknown"]
    )
    if brand_selection == "Other / Unknown":
        brand_other_text = st.text_input(
            "Brand Name (optional)",
            placeholder="Enter brand name or leave blank"
        )
    brand_proof = st.selectbox(
        "Brand proof available?",
        ["No", "Yes"]
    )

if jewelry_type == "Diamond Jewelry":
    st.subheader("Jewelry Details")
    metal_choice = st.selectbox(
        "Metal",
        ["White Gold", "Yellow Gold", "Rose Gold", "Dual Tone Gold", "Platinum", "Other / Unknown"]
    )
    metal_other = None
    if metal_choice == "Other / Unknown":
        metal_other = st.text_input(
            "Other Metal Name (optional)",
            placeholder="e.g. Yellow Gold, Platinum Alloy"
        )
    metal = metal_other if (metal_choice == "Other / Unknown" and metal_other) else metal_choice
    purity = st.selectbox("Purity", ["10K", "12K", "14K", "16K", "18K", "22K", "PT950"])
    metal_weight = st.number_input("Approx Metal Weight (grams)", min_value=0.0)

if st.button("Get Price Estimate"):
    # 🚫 If AI layer is enabled → stop here
    
    if USE_RAPNET and not rapnet_token:
        st.error("RapNet token is required for RapNet pricing")
        st.stop()

    invalid_side_stone = next(
        (
            idx + 1 for idx, ss in enumerate(side_stones_form)
            if ss.get("quantity", 0) <= 0 or ss.get("total_carat_weight", 0) <= 0
        ),
        None
    )
    if invalid_side_stone is not None:
        st.error(f"Side Stone Group {invalid_side_stone}: quantity and total carat weight are required.")
        st.stop()

    has_center_stone = float(carat or 0.0) > 0
    has_valid_side_stones = any(
        float(ss.get("total_carat_weight") or 0.0) > 0 and int(ss.get("quantity") or 0) > 0
        for ss in side_stones_form
    )
    if not has_center_stone and not has_valid_side_stones:
        st.error("Please provide either center stone carat or at least one valid side-stone group.")
        st.stop()

    non_diamond_group = next(
        (
            idx + 1 for idx, ss in enumerate(side_stones_form)
            if (ss.get("stone_type") or "").lower() != "diamond"
        ),
        None
    )
    if non_diamond_group is not None:
        st.warning(
            f"Side Stone Group {non_diamond_group}: only Diamond side stones are allowed right now. "
            "Other gemstone price calculation is in development."
        )
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
            "fluorescence": None if fluorescence == "Unknown" else fluorescence
        },
        "condition": condition,
        "metal": metal,
        "purity": purity,
        "metal_weight_grams": metal_weight,
        "side_stones": side_stones_form,
        "brand_selection": brand_selection,
        "brand": (
            brand_selection
            if brand_selection != "Other / Unknown"
            else (brand_other_text if brand_other_text else None)
        ),
        "brand_proof": brand_proof if brand_proof else None
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

    _render_final_result_ui(result)
    _display_comparables(result)
