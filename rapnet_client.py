import requests

RAPNET_URL = "https://technet.rapnetapis.com/instant-inventory/api/Diamonds"

RAPNET_BEARER_TOKEN ="eyJhbGciOiJSUzI1NiIsInR5cCI6IkpXVCIsImtpZCI6Ik16aERRMFExTURFeVJqSTNRa0k0TTBGRVJUZzFNekUzTWtOQ09UTXhNREZDTVVZM1JURkNNZyJ9.eyJodHRwOi8vcmFwYXBvcnQuY29tL3VzZXIiOnsiYWNjb3VudElkIjoxMDY4OTAsImNvbnRhY3RJZCI6MjYxNTAsInNmTWFzdGVyQWNjb3VudE51bWJlciI6IkE4MTQzIiwic2ZNYXN0ZXJDb250YWN0TnVtYmVyIjoiQzMxNjEifSwiaHR0cDovL3JhcGFwb3J0LmNvbS9zY29wZSI6WyJwcmljZUxpc3RXZWVrbHkiLCJpbnN0YW50SW52ZW50b3J5IiwibWFuYWdlTGlzdGluZ3MiXSwiaHR0cDovL3JhcGFwb3J0LmNvbS9hcGlrZXkiOnsiaHR0cHM6Ly9pbnN0YW50aW52ZW50b3J5LnJhcG5ldGFwaXMuY29tIjoiRzJ5cXM3dm1IdTl0aGUxTEZDQkFNNzFMUzJJZ0NsSG05cjNQOTNpTCIsImh0dHBzOi8vbWVkaWF1cGxvYWQucmFwbmV0YXBpcy5jb20iOiJxOG5iTFhBTkdOOE9WbTlmejFVclhhb1U5ZFNlZjZ0YzRybTJWaFJuIiwiaHR0cHM6Ly9wcmljZWxpc3QucmFwbmV0YXBpcy5jb20iOiJiaHp5cjhpbWdaMkxSRkY4SndXZXg2dDdtbjlYaG9TQTJCNDY4S1p2IiwiaHR0cHM6Ly91cGxvYWRsb3RzLnJhcG5ldGFwaXMuY29tIjoiWU52R09JVnRKTDJKaHVZelczTkdmOXRJbWxLUGl1aGk0VjB3dHZYYiJ9LCJodHRwOi8vcmFwYXBvcnQuY29tL2F1ZGllbmNlIjpbImh0dHBzOi8vcHJpY2VsaXN0LnJhcG5ldGFwaXMuY29tIiwiaHR0cHM6Ly9pbnN0YW50aW52ZW50b3J5LnJhcG5ldGFwaXMuY29tIiwiaHR0cHM6Ly91cGxvYWRsb3RzLnJhcG5ldGFwaXMuY29tIiwiaHR0cHM6Ly9tZWRpYXVwbG9hZC5yYXBuZXRhcGlzLmNvbSIsImh0dHBzOi8vYXBpZ2F0ZXdheS5yYXBuZXRhcGlzLmNvbSJdLCJodHRwOi8vcmFwYXBvcnQuY29tL21ldGFkYXRhIjpudWxsLCJodHRwOi8vcmFwYXBvcnQuY29tL3Blcm1pc3Npb25zIjp7InJhcG5ldGFwaXMtYXBpZ2F0ZXdheSI6WyJtZW1iZXJEaXJlY3RvcnkiLCJzZWFyY2giLCJpbnN0YW50SW52ZW50b3J5U2V0dXAiLCJtYW5hZ2VMaXN0aW5nc0ZpbGUiLCJwcmljZUxpc3RXZWVrbHkiLCJwcmljZUxpc3RNb250aGx5IiwicmFwbmV0UHJpY2VMaXN0V2Vla2x5IiwicmFwbmV0RGVhbGVyIiwiYmFzaWMiLCJyYXBuZXRQcmljZUxpc3RNb250aGx5IiwiYnV5UmVxdWVzdHNBZGQiLCJnZW1zVXBsb2FkIiwiaXRlbVNoYXJlZCIsInRyYWRlQ2VudGVyIiwibXlDb250YWN0cyIsIm1lbWJlclJhdGluZyIsImdlbXMiLCJjaGF0IiwiaW5zdGFudEludmVudG9yeSIsIm1hbmFnZUxpc3RpbmdzIiwibGVhZHMiLCJhZG1pbiIsImJ1eVJlcXVlc3RzIl19LCJpc3MiOiJodHRwczovL3JhcGFwb3J0LmF1dGgwLmNvbS8iLCJzdWIiOiJMUmRTUnA4Q3o2WkdsYldNS0xMMkM1VnRxaXVPZGtoQUBjbGllbnRzIiwiYXVkIjoiaHR0cHM6Ly9hcGlnYXRld2F5LnJhcG5ldGFwaXMuY29tIiwiaWF0IjoxNzcwMjY2Nzg2LCJleHAiOjE3NzAzNTMxODYsInNjb3BlIjoiYXBpR2F0ZXdheSIsImd0eSI6ImNsaWVudC1jcmVkZW50aWFscyIsImF6cCI6IkxSZFNScDhDejZaR2xiV01LTEwyQzVWdHFpdU9ka2hBIn0.l1ozN8GuKP6SzB-t-XQwB3svVPSoNzk7wd7uQV35VkOqXomfBCq0kv5saQkXQjJ2XBC6yX0KUDy9U6D5I3QTo-WWibV4ZPMLZs7hZF760COWZn4IA9JDpBbnNhOYA58UTAWhJ1CX5m_c7y7i4KWsHiNo5okcdM3Q5Om-MbusPzpgROVM-w8EtvVcoSOn8KNNjQabPW7EYKH3IPq02LJVe9gf_8Ib0TlN8BNfwnqD2_SYV6uLD0je58C0dvYQ-M4yUWVpqLn-MWfXNeM2nOitegHAzg-woLwIjpmiOKCc66ZJUOdtoU5pprB9psLGEhLuUEL_xacZ9m0mi6Czte2USA"
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
            "header": {},
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

