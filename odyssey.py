from datetime import datetime, timedelta, timezone
import os
import re
import sys
import requests
import json

#from dotenv import load_dotenv
#load_dotenv()

webhooks_raw = os.environ.get("DISCORD_WEBHOOKS", "")
if not webhooks_raw:
    single_hook = os.environ.get("DISCORD_WEBHOOK", "")
    DISCORD_WEBHOOKS = [single_hook] if single_hook else []
else:
    DISCORD_WEBHOOKS = [url.strip() for url in webhooks_raw.split(",") if url.strip()]
    
CINEPLEX_SUB_KEY = os.environ.get("CINEPLEX_SUB_KEY")
THEATRES = {
    "1409": "SilverCity Riverport",
    "1405": "Cineplex Cinemas Langley"
}

FILM_ID = "37617"  # The Odyssey film ID
DAYS_AHEAD = 4

# Seat Rules
MIN_CONTIGUOUS_SEATS = 1
BAD_ROWS = ["A", "B", "C", "D", "E"]



def update_github_variable(repo, token, var_name, new_value):
    """Updates a GitHub repository variable via the REST API."""
    if not token or not repo:
        return
    url = f"https://api.github.com/repos/{repo}/actions/variables/{var_name}"
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28"
    }
    try:
        requests.patch(url, headers=headers, json={"name": var_name, "value": str(new_value)}, timeout=5)
    except Exception as e:
        print(f"Failed to update GitHub variable: {e}")



def fetch_showtimes():
    """Fetches 70mm IMAX showtimes for The Odyssey across the next 14 days."""
    base_url = "https://apis.cineplex.com/prod/cpx/theatrical/api/v1/showtimes"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
        "Accept": "application/json",
        "Ocp-Apim-Subscription-Key": CINEPLEX_SUB_KEY,
    }

    showtimes = []
    today = datetime.now()

    for location_id, theatre_name in THEATRES.items():
        print(f"\n Searching 70mm IMAX showtimes for {theatre_name} (ID: {location_id})...")

        for day_offset in range(DAYS_AHEAD):
            target_date = today + timedelta(days=day_offset)
            date_str = f"{target_date.month}/{target_date.day}/{target_date.year}"

            params = {
                "language": "en",
                "locationId": location_id,
                "date": date_str,
                "filmId": FILM_ID,
            }

            try:
                res = requests.get(base_url, params=params, headers=headers, timeout=10)
                if res.status_code == 200:
                    data = res.json()
                    
                    for theatre in data:
                        for dates in theatre.get("dates", []):
                            for movie in dates.get("movies", []):
                                if str(movie.get("id")) == FILM_ID:
                                    for exp in movie.get("experiences", []):
                                        exp_types = exp.get("experienceTypes", [])
                                        
                                        if "70mm" in exp_types and "IMAX" in exp_types:
                                            for session in exp.get("sessions", []):
                                                session_id = session.get("vistaSessionId")
                                                raw_time = session.get("showStartDateTime")
                                                
                                                if session_id and raw_time:
                                                    dt = datetime.fromisoformat(raw_time)
                                                    pretty_time = dt.strftime("%I:%M %p")
                                                    
                                                    showtimes.append({
                                                        "date": date_str,
                                                        "time": pretty_time,
                                                        "id": str(session_id),
                                                        "theatre": theatre_name, 
                                                        "theatre_id": location_id,
                                                        "url": f"https://www.cineplex.com/ticketing/preview?theatreId={location_id}&showtimeId={session_id}&dbox=false"
                                                    })
                                                    print(f"  Found: {date_str} @ {pretty_time}")
                elif res.status_code == 401:
                    print("❌ HTTP 401: Invalid or missing Ocp-Apim-Subscription-Key!")
                    break
            except Exception as err:
                print(f" Failed to fetch showtimes for {date_str}: {err}")

    print(f"\n Total 70mm IMAX screenings found: {len(showtimes)}\n")
    return showtimes



def find_adjacent_seat_groups(available_seats_by_row, min_required_seats=2):
    """Finds continuous blocks of seats in valid rows."""
    matched_groups = {}

    for row, seats in available_seats_by_row.items():
        if row.upper() in BAD_ROWS:
            continue

        sorted_seats = sorted(seats)
        row_groups = []
        current_group = []

        for seat in sorted_seats:
            if not current_group:
                current_group.append(seat)
            elif seat == current_group[-1] + 1:
                current_group.append(seat)
            else:
                if len(current_group) >= min_required_seats:
                    row_groups.append(current_group)
                current_group = [seat]

        if len(current_group) >= min_required_seats:
            row_groups.append(current_group)

        if row_groups:
            matched_groups[row] = row_groups

    return matched_groups



def analyze_screening_seats(showtime):
    """Fetches seat availability and dynamically maps backend rows to real letters."""
    print(f"🎟️ Checking {showtime['theatre']} | {showtime['date']} @ {showtime['time']}...")
    
    is_august_second = False
    try:
        parts = showtime['date'].split('/')
        if len(parts) == 3 and int(parts[0]) == 8 and int(parts[1]) == 2 and int(parts[2]) == 2026:
            is_august_second = True
    except Exception:
        pass

    # Allow 1 contiguous seat for August 2nd, otherwise fallback to standard minimum requirement
    min_seats = 1 if is_august_second else MIN_CONTIGUOUS_SEATS
    
    seat_api_url = f"https://apis.cineplex.com/prod/ticketing/api/v1/theatre/{showtime['theatre_id']}/showtime/{showtime['id']}/seat-availability" 
    
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
        "Accept": "application/json",
        "Ocp-Apim-Subscription-Key": CINEPLEX_SUB_KEY,
    }
    
    try:
        res = requests.get(seat_api_url, headers=headers, timeout=5)
        if res.status_code != 200:
            print(f" Failed to fetch seats (HTTP {res.status_code})")
            return {}
            
        data = res.json()
        availabilities = data.get("seatAvailabilities", {})
        
        unique_row_indices = set()
        for seat_key in availabilities.keys():
            parts = seat_key.split('_')
            if len(parts) == 3:
                unique_row_indices.add(int(parts[1]))
                
        # Sort Highest to Lowest to map screen-closest row to 'A'
        sorted_indices = sorted(list(unique_row_indices), reverse=True)
        alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
        row_map = {idx: alphabet[i] for i, idx in enumerate(sorted_indices)}
        
        raw_seats = {}
        
        for seat_key, status in availabilities.items():
            if status == "Available":
                parts = seat_key.split('_')
                if len(parts) == 3:
                    row_idx = int(parts[1])
                    seat_num = int(parts[2])
                    
                    row_letter = row_map.get(row_idx)
                    
                    if row_letter:
                        if row_letter not in raw_seats:
                            raw_seats[row_letter] = []
                        raw_seats[row_letter].append(seat_num)
                    
        return find_adjacent_seat_groups(raw_seats, min_seats)
        
    except Exception as e:
        print(f" Error parsing seat API: {e}")
        return {}



def notify_discord(showtime, seat_groups):
    """Deletes previous alerts and posts new ones across all configured webhooks."""
    if not DISCORD_WEBHOOKS:
        print("DISCORD_WEBHOOKS environment variable not set. Skipping ping.")
        return
        
    gh_token = os.environ.get("GH_PAT")
    repo_name = os.environ.get("GITHUB_REPOSITORY")
    
    # Load the dictionary of old message IDs
    old_msg_ids_raw = os.environ.get("LAST_DISCORD_MSG_IDS", "{}")
    try:
        old_msg_ids = json.loads(old_msg_ids_raw)
    except Exception:
        old_msg_ids = {}

    description_lines = []
    total_spots = 0

    sorted_rows = sorted(seat_groups.keys(), reverse=True)

    for row in sorted_rows:
        groups = seat_groups[row]
        for g in groups:
            seat_str = f"{g[0]}–{g[-1]}" if len(g) > 1 else f"{g[0]}"
            description_lines.append(f"• **Row {row}**: Seats **{seat_str}** ({len(g)} together)")
            total_spots += len(g)

    payload = {
        "embeds": [
            {
                "title": f"🚨 {total_spots} IMAX 70mm Seats Available for The Odyssey!",
                "color": 3066993,
                "fields": [
                    {
                        "name": "📍 Theatre",
                        "value": showtime['theatre'],
                        "inline": False,
                    },
                    {
                        "name": "📅 Date & Time",
                        "value": f"{showtime['date']} @ {showtime['time']}",
                        "inline": True,
                    },
                    {
                        "name": "🎟️ Direct Checkout",
                        "value": f"[Preview & Buy Seats Here]({showtime['url']})",
                        "inline": True,
                    },
                    {
                        "name": "💺 Good Seats",
                        "value": "\n".join(description_lines) if description_lines else "None",
                        "inline": False,
                    },
                ],
                "footer": {"text": "The Odyssey 70mm Monitor"},
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
        ]
    }

    new_msg_ids = {}

    for webhook_url in DISCORD_WEBHOOKS:
        try:
            # 1. Delete the previous message for this specific webhook
            old_msg_id = old_msg_ids.get(webhook_url)
            if old_msg_id:
                delete_url = f"{webhook_url}/messages/{old_msg_id}"
                requests.delete(delete_url, timeout=5)

            # 2. Send the new message using ?wait=true so Discord returns the new message ID
            send_url = f"{webhook_url}?wait=true"
            res = requests.post(send_url, json=payload, timeout=5)
            
            if res.status_code in [200, 201]:
                data = res.json()
                new_msg_ids[webhook_url] = data.get("id")
                print(f" Sent Discord alert to webhook for {showtime['date']} @ {showtime['time']}")
            else:
                print(f" Failed to post to webhook (HTTP {res.status_code})")
        except Exception as e:
            print(f" Failed to send to a webhook: {e}")

    # 3. Save the new message IDs back to GitHub Variables for the next run
    if new_msg_ids and gh_token and repo_name:
        update_github_variable(repo_name, gh_token, "LAST_DISCORD_MSG_IDS", json.dumps(new_msg_ids))



def main():
    showtimes = fetch_showtimes()

    if not showtimes:
        print("No showtimes returned. Exiting.")
        return

    for st in showtimes:
        seat_groups = analyze_screening_seats(st)

        if seat_groups:
            print(f" Found matches for {st['date']} @ {st['time']}!")
            notify_discord(st, seat_groups)
        else:
            print(f" No valid seat pairs in good rows.")

if __name__ == "__main__":
    main()
