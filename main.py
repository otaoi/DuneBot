import sys
import time
import requests
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError

# --- CONFIGURATION ---
SCREENINGS = [
    {
        "name": "Dune 3 - 11pm 17th", 
        "url": "https://www.cineplex.com/ticketing/preview?locationId=1405&showtimeId=528423&dbox=false"
    },
    {
        "name": "Dune 3 - 7pm 17th", 
        "url": "https://www.cineplex.com/ticketing/preview?locationId=1405&showtimeId=528419&dbox=false"
    },
    {
        "name": "test and monsters", 
        "url": "https://www.cineplex.com/ticketing/preview?theatreId=1136&showtimeId=396836&dbox=false"
    }
]

DISCORD_WEBHOOK = os.environ.get("DISCORD_WEBHOOK")

# Handicap companion spots to ignore
HANDICAP_SEATS = ['1_7_5', '1_7_7', '1_7_23', '1_7_25']

def monitor_tickets():
    print(f"Launching headless browser to check {len(SCREENINGS)} screenings...")
    
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/149.0.7827.197 Safari/537.36",
            viewport={'width': 1920, 'height': 1080}
        )
        page = context.new_page()

        for screening in SCREENINGS:
            name = screening["name"]
            frontend_url = screening["url"]
            
            print(f"\nChecking: {name}...")
            print(f"URL: {frontend_url}")
            
            try:
                # Intercept the background API call for this specific showtime
                with page.expect_response(
                    lambda response: "seat-availability" in response.url and response.status == 200, 
                    timeout=20000 
                ) as response_info:
                    page.goto(frontend_url, wait_until="commit")

                # Capture the JSON response
                json_payload = response_info.value.json()
                
                # --- PARSING SEATS ---
                vacant_seats = []
                
                if "seatAvailabilities" in json_payload:
                    seat_layout = json_payload.get("seatAvailabilities", {})
                    for sid, status in seat_layout.items():
                        if status.strip().upper() == "AVAILABLE" and sid not in HANDICAP_SEATS:
                            vacant_seats.append(sid)
                elif isinstance(json_payload, list):
                    for seat in json_payload:
                        sid = str(seat.get('seatId', ''))
                        status = seat.get('status', '').strip().upper()
                        if status == "AVAILABLE" and sid not in HANDICAP_SEATS:
                            vacant_seats.append(sid)

                # --- ALERTING ---
                if len(vacant_seats) > 0:
                    alert_text = f"**TICKETS AVAILABLE:** {name}\nReal seats detected: {vacant_seats}\nBook here: {frontend_url}"
                    
                    webhook_response = requests.post(DISCORD_WEBHOOK, json={"content": alert_text})
                    
                    if webhook_response.status_code == 204:
                        print(f"FOUND SEATS! Alert successfully sent to Discord.")
                    else:
                        print(f"FOUND SEATS, BUT WEBHOOK FAILED Status: {webhook_response.status_code}")
                        print(f"Discord Error: {webhook_response.text}")
                else:
                    print("Checked successfully. Status: 100% Occupied (Handicap seats ignored).")

            except PlaywrightTimeoutError:
                print(f"Timeout for {name}: API never called. Taking a screenshot...")
                
                # safe_filename = name.replace(" ", "_").replace("-", "")
                # page.screenshot(path=f"error_{safe_filename}.png")
                # print(f" Saved picture of the error to error_{safe_filename}.png")
                
            except Exception as e:
                print(f"Error on {name}: {e}. Moving to next...")
            
            time.sleep(3)
            
        print("\n All screenings checked. Closing browser.")
        browser.close()

if __name__ == "__main__":
    monitor_tickets()
