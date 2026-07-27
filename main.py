import requests
import os
# CINEPLEX TRACKING CONFIGURATION
API_URL = "https://cineplex.com"
DISCORD_WEBHOOK = os.environ["DISCORD_WEBHOOK"] 
BUY_URL = "https://cineplex.com"

def check_seats():
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Accept": "*/*"
    }
    
    try:
        response = requests.get(API_URL, headers=headers, timeout=10)
        
        if response.status_code != 200:
            print(f"Cineplex API returned error status: {response.status_code}")
            return
            
        data = response.json()
        seat_map = data.get("seatAvailabilities", {})
        
        # Pull out any seat keys that explicitly have an "Available" status string
        open_seats = [seat_id for seat_id, status in seat_map.items() if status.strip() == "Available"]
        
        if len(open_seats) > 0:
            message = f"🚨 **DUNE 3 SEAT DROP!** {len(open_seats)} open seat(s) found for IMAX 70mm! Go buy: {BUY_URL}"
            requests.post(DISCORD_WEBHOOK, json={"content": message})
            print(f"Success! Alert sent for open seats: {open_seats}")
        else:
            print("Checked. All seats are strictly Occupied.")
            
    except Exception as e:
        print(f"Script run encountered an error: {e}")

if __name__ == "__main__":
    check_seats()
