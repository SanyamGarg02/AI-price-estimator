# Expert Review Report (Jewelry Market Validation)

## Purpose
This report highlights the pricing components that now work in MVP and where expert jewelry-market review is required before production confidence.

## What Was Updated
- OPS quality factor rules were aligned to exact UI labels for `cut`, `polish`, `symmetry`, and `fluorescence`.
- Deterministic brand policy flow is active (top-brand dropdown + proof logic).
- Weighted comparable anchor + thin-data discount + confidence/fallback signals are active (RapNet and GemGem).
- Side-stone pricing supports market path + melee fallback table.
- Metal valuation now includes a configurable jewelry fabrication/resale multiplier.

## Priority Review Areas (Needs Expert Input)

### 1) Melee Price Table (Very Small Side Stones)
- File: `pricing_ai_for_ui.py`
- Section: `MELEE_PER_CARAT_TABLE`, `MELEE_THRESHOLD_PER_STONE_CARAT`
- Why expert review is needed:
  - These are currently policy defaults, not market-benchmarked by SKU/region.
- Validate:
  - Correct USD-per-carat bands for sizes <= 0.03 ct per stone.
  - Whether threshold should remain `0.03` or be adjusted.
  - Whether ranges should differ by color/clarity buckets.

### 2) OPS Adjustment Bands (Condition / Metal / Brand / Quality)
- File: `pricing_ai_for_ui.py`
- Section: `OPS_ADJUSTMENTS`
- Why expert review is needed:
  - Current ranges are calibrated heuristically; need resale-grounded values.
- Validate:
  - Condition ranges for `Excellent`, `Like New`, `Good`, `Fair`.
  - Metal uplift ranges by purity (`10K/12K/14K/16K/18K/22K/PT950`).
  - Brand premiums for top brands with/without proof.
  - Quality factor ranges for:
    - Cut: `Heart & Arrow`, `Ideal`, `Excellent`, `Very Good`, `Good`
    - Polish/Symmetry: `Ideal`, `Excellent`, `Very Good`, `Good`
    - Fluorescence: `None`, `Faint`, `Medium`, `Strong`, `Very Strong`

### 3) Top Brand List (Deterministic Tiering)
- Files: `ui.py`, `pricing_ai_for_ui.py`
- Why expert review is needed:
  - Tier policy is now deterministic and sensitive to brand list quality.
- Validate:
  - Final top-brand list for your market segment.
  - Whether any brands should be removed/added.
  - Whether no-proof premium should be reduced further.

### 4) Metal Jewelry Multiplier (Scrap -> Resale)
- File: `metal_price_client.py`
- Section: `JEWELRY_FABRICATION_MULTIPLIER` (env configurable)
- Why expert review is needed:
  - Multiplier currently defaults to `1.7` and may vary by category and region.
- Validate:
  - Appropriate multiplier band (e.g., 1.5-2.0) by product type/brand.
  - Whether fixed multiplier should become category-based (ring/necklace/bracelet).

### 5) Thin-Data Discount Multipliers (Anchor Stabilization)
- Files: `rapnet_client.py`, `gemgem_client.py`
- Section: `THIN_DATA_DISCOUNT_BY_COUNT`
- Why expert review is needed:
  - Current discounts (0.60-0.67 for low counts) are conservative defaults.
- Validate:
  - Whether this discount strength matches observed transaction data.
  - Whether separate curves are needed for RapNet vs GemGem.

### 6) Confidence Signal Interpretation
- Files: `rapnet_client.py`, `gemgem_client.py`, `ui.py`
- Why expert review is needed:
  - Confidence score combines similarity + fallback expansion + thin-data penalties.
- Validate:
  - What should be considered actionable thresholds for manual review (e.g., `low` confidence).
  - Whether UI should block or warn more aggressively below a score threshold.

## Recommended Expert Review Outputs
Please request the expert to provide:
1. Final approved numeric ranges for all OPS tables.
2. Approved melee per-carat table and threshold.
3. Approved top-brand list and no-proof policy.
4. Approved metal multiplier policy (single value or per-category matrix).
5. Approved confidence thresholds for review/override workflow.

## Notes
- Caching and fallback logic are implemented for performance and robustness.
- Non-diamond side-stone pricing is intentionally not enabled (in development).
