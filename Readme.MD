# AI Price Estimator MVP (Diamond Products)

This repository contains an MVP for estimating resale price ranges of **diamond-based products** (Loose Diamonds and Diamond Jewelry).

The system combines:
- **RapNet market pricing** (diamond anchor)
- **Live metal pricing** (gold / platinum)
- **Multimodal AI (images + specs)** for bounded adjustment logic
- **Streamlit UI** for fast internal demos and validation

This is an **internal MVP** focused on correctness, safety, and explainability — not production deployment.

---

## What This MVP Does

✔ Accepts up to 3 product images  
✔ Accepts structured product inputs (diamond specs, condition, metal, etc.)  
✔ Uses RapNet to compute a diamond price anchor  
✔ Adds metal value (for jewelry only)  
✔ Applies AI-based adjustment (bounded, OPS-aligned)  
✔ Returns a **price range**, not a final offer  
✔ Safe fallback behavior (no crashes on AI or API failures)

---

## What This MVP Does NOT Do

❌ Does not provide a binding or final offer  
❌ Does not support colored gemstones  
❌ Does not auto-list or negotiate prices  
❌ Does not deploy the AI model to the cloud  
❌ Does not expose internal pricing sources in the UI  

---

## Tech Stack

- Python 3.10+
- Streamlit (UI)
- RapNet Instant Inventory API
- MetalPriceAPI (gold / platinum pricing)
- Ollama + **LLaVA 13B** (local multimodal AI)

---

## Repository Structure
├── ui.py # Streamlit UI
├── pricing_ai_for_ui.py # Main pricing pipeline
├── rapnet_client.py # RapNet API integration
├── metal_price_client.py # Metal pricing logic
├── requirements.txt
├── README.md
└── .gitignore


---

## Prerequisites

- Python 3.10 or newer
- macOS / Linux (tested on macOS Apple Silicon)
- Internet access (for RapNet + metal pricing APIs)
- Local machine capable of running a ~7GB model

---

## Step 1: Clone the Repository

```bash
git clone <https://github.com/SanyamGarg02/AI-price-estimator.git>
cd ai-price-estimator-Github

Step 2: Create Virtual Environment (Recommended)
python3 -m venv venv
source venv/bin/activate

Step 3: Install Dependencies
pip install -r requirements.txt


Step 4: Set Required API Keys
This project requires two external APIs.
1️⃣ RapNet Bearer Token
You must have access to RapNet Instant Inventory API.
Set the token as an environment variable:
export RAPNET_BEARER_TOKEN="your_rapnet_bearer_token_here"
2️⃣ MetalPriceAPI Key
Used to fetch live gold / platinum prices.
export METAL_PRICE_API_KEY="your_metalpriceapi_key_here"

Step 5: Install Ollama
Ollama is used to run the local multimodal AI model.
macOS (recommended)
brew install ollama

Start Ollama:
ollama serve

Leave this running in a terminal.


Step 6: Install the LLaVA Model (Multimodal AI)
This MVP uses LLaVA 13B, which supports image + text input.
⚠️ Model size is ~7GB.
Run:
ollama pull llava:13b

Verify installation:
ollama list

You should see:
llava:13b

#################################

Step 7: Run the Streamlit UI
streamlit run ui.py

How to Use the UI:  
Upload up to 3 images (JPG / PNG)
Select product type:
Loose Diamond
Diamond Jewelry

Enter diamond specs (4Cs + optional attributes)

Enter metal details (only for jewelry)

Click Get Price Estimate

The UI will display:

Diamond anchor price

Metal value (if applicable)

AI adjustment %

Final price range

Key drivers & missing info

######################################################################

Important Notes for Reviewers

The AI model runs locally and is not deployed due to size constraints.

This is intentional for MVP validation.

Production deployment would use a hosted multimodal AI API.

Pricing logic is deterministic-first, AI-second.

AI cannot override OPS constraints.

######################################################

Known Limitations

Model inference speed depends on local hardware

No GPU acceleration on some machines

Limited to diamond-based products in MVP