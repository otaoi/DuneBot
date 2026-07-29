from datetime import datetime, timedelta, timezone
import os
import re
import sys
import requests

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
    "1405": "Cineplex Cinemas Langley"
}

FILM_ID = "37998"  # Exact Dune film ID provided
DAYS_AHEAD = 2    # 2 days till 18th
START_DATE = datetime(2026, 12, 17)  # Starting  on Dec 17, 2026

# Dune Seat Rules
MIN_CONTIGUOUS_SEATS = 1
BAD_ROWS = []  # No entire rows ignored

# Specific seats to ignore 
DISABLED_SEATS = {
    "E": [5, 7, 23, 25]
}

# Seat Number Range Filter (Set to None if you want to disable either limit)
MIN_SEAT_NUMBER = None
MAX_SEAT_NUMBER = None


def fetch_dune_showtimes():
    """Fetches showtimes for Dune using the exact Film ID over the 14-day window."""
    base_url = "https://apis.cineplex.com/prod/cpx/theatrical/api/v1/showtimes"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
        "Accept": "application/json",
        "Ocp-Apim-Subscription-Key": CINEPLEX_SUB_KEY,
    }

    showtimes = []

    for location_id, theatre_name in THEATRES.items():
        print(f"\n Searching for Dune (ID: {FILM_ID}) at {theatre_name} starting Dec 17, 2026...")

        for day_offset in range(DAYS_AHEAD):
            target_date = START_DATE + timedelta(days=day_offset)
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
                                    movie_title = movie.get("name", "Dune")
                                    
                                    for exp in movie.get("experiences", []):
                                        exp_types = exp.get("experienceTypes", [])
                                        fmt = " + ".join(exp_types) if exp_types else "Regular"
                                        
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
                                                    "movie_title": movie_title,
                                                    "format": fmt,
                                                    "url": f"https://www.cineplex.com/ticketing/preview?theatreId={location_id}&showtimeId={session_id}&dbox=false"
                                                })
                                                print(f" Found: {movie_title} ({fmt}) on {date_str} @ {pretty_time}")
                elif res.status_code == 401:
                    print(" HTTP 401: Invalid or missing Ocp-Apim-Subscription-Key!")
                    break
            except Exception as err:
                print(f" Failed to fetch showtimes for {date_str}: {err}")

    print(f"\n Total Dune screenings found: {len(showtimes)}\n")
    return showtimes


def find_adjacent_seat_groups(available_seats_by_row):
    """Finds available seats across valid rows."""
    matched_groups = {}
    bad_rows_upper = [r.upper() for r in BAD_ROWS]

    for row, seats in available_seats_by_row.items():
        if row.upper() in bad_rows_upper:
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
                if len(current_group) >= MIN_CONTIGUOUS_SEATS:
                    row_groups.append(current_group)
                current_group = [seat]

        if len(current_group) >= MIN_CONTIGUOUS_SEATS:
            row_groups.append(current_group)

        if row_groups:
            matched_groups[row] = row_groups

    return matched_groups

def analyze_screening_seats(showtime):
    """Fetches seat availability, filtering out-of-range and blacklisted seats."""
    print(f" Checking [{showtime['movie_title']}] | {showtime['theatre']} | {showtime['date']} @ {showtime['time']}...")
    
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
                        # Skip specific blacklisted handicap seats
                        if row_letter in DISABLED_SEATS and seat_num in DISABLED_SEATS[row_letter]:
                            continue
                            
                        # Filter by seat number range (inclusive)
                        if MIN_SEAT_NUMBER is not None and seat_num < MIN_SEAT_NUMBER:
                            continue
                        if MAX_SEAT_NUMBER is not None and seat_num > MAX_SEAT_NUMBER:
                            continue
                            
                        if row_letter not in raw_seats:
                            raw_seats[row_letter] = []
                        raw_seats[row_letter].append(seat_num)
                    
        return find_adjacent_seat_groups(raw_seats)
        
    except Exception as e:
        print(f" Error parsing seat API: {e}")
        return {}



def notify_discord(showtime, seat_groups):
    """Formats and posts alert message to Discord Webhook."""
    if not DISCORD_WEBHOOKS:
        print("DISCORD_WEBHOOKS environment variable not set. Skipping ping.")
        return

    description_lines = []
    total_spots = 0

    sorted_rows = sorted(seat_groups.keys(), reverse=True)

    for row in sorted_rows:
        groups = seat_groups[row]
        for g in groups:
            seat_str = f"{g[0]}–{g[-1]}" if len(g) > 1 else f"{g[0]}"
            count_str = f"{len(g)} together" if len(g) > 1 else "1 seat"
            description_lines.append(f"• **Row {row}**: Seat(s) **{seat_str}** ({count_str})")
            total_spots += len(g)

    payload = {
        "embeds": [
            {
                "title": f"🚨 {total_spots} Seat(s) Available for {showtime['movie_title']}!",
                "color": 14177041,
                "fields": [
                    {
                        "name": "📍 Theatre & Format",
                        "value": f"**{showtime['theatre']}**\nFormat: {showtime['format']}",
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
                        "name": "💺 Available Seats",
                        "value": "\n".join(description_lines) if description_lines else "None",
                        "inline": False,
                    },
                ],
                "footer": {"text": "Dune Ticket Monitor"},
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
        ]
    }

    for webhook_url in DISCORD_WEBHOOKS:
        try:
            requests.post(webhook_url, json=payload, timeout=5)
            print(f" Sent Discord alert to webhook for {showtime['date']} @ {showtime['time']}")
        except Exception as e:
            print(f" Failed to send to a webhook: {e}")




def main():
    showtimes = fetch_dune_showtimes()

    if not showtimes:
        print("No showtimes returned. Exiting.")
        return

    for st in showtimes:
        seat_groups = analyze_screening_seats(st)

        if seat_groups:
            print(f"  Found available seats for {st['movie_title']} @ {st['time']}!")
            notify_discord(st, seat_groups)
        else:
            print(f"  No seats available in the specified range.")

if __name__ == "__main__":
    main()
