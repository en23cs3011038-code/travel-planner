# Personalized Travel Itinerary Planner

College project: creates a day-by-day travel itinerary for **any city in the world** based on the user's destination, number of days, budget, travel style and interests.

**Tech stack:** Python (Flask), SQLite (SQL), HTML, CSS (Jinja2 templates), OpenStreetMap data

## How to run

```bash
pip install -r requirements.txt
python app.py          # open http://127.0.0.1:5000
```

The database (`travel.db`) is created automatically on first run. An internet connection is needed for cities other than the built-in ones (Goa, Jaipur, Manali).

## Features

- **Any destination:** type any city (Paris, Tokyo, New York ...). Places are fetched from OpenStreetMap (Nominatim for coordinates, Overpass for attractions) and cached in the database for 7 days.
- **Stay duration:** choose 1 to 30 days; every day gets morning, afternoon and evening activities.
- **Interests:** Adventure, Food, History, Nature, Relaxation, Shopping, Sightseeing.
- **Budget check:** activity cost + stay/food estimate, compared with your budget.
- **User accounts:** sign up, log in, log out (passwords are hashed).
- **Profile page:** save default days, travelers, travel style and interests; they pre-fill the planner.
- **My Trips:** every itinerary is saved for the logged-in user and can be reopened or deleted.
- **Print / Save as PDF** from the itinerary page.

## Project structure

```
travel-planner/
├── app.py             # routes, login/profile, itinerary algorithm, budget logic
├── places.py          # finds places for any city (OpenStreetMap + cache)
├── init_db.py         # SQL schema + built-in cities (Goa, Jaipur, Manali)
├── requirements.txt
├── templates/         # base, index, itinerary, history, login, register, profile
└── static/style.css
```

## Database (SQL)

- `users` (id, name, email, password_hash, default_days, default_travelers, default_style, default_interests)
- `trips` (id, user_id, destination, days, travelers, budget, style, interests, total_cost, plan_json, created_at)
- `destinations` and `places`: curated data for the built-in cities
- `api_cache` (key, payload, created_at): cached online results

`trips.user_id` is a foreign key to `users.id`; `places.destination_id` is a foreign key to `destinations.id`.

## Itinerary algorithm

1. Get places for the destination (built-in table, cache, or OpenStreetMap).
2. Rank places that match the user's interests first (well-known places with a Wikipedia entry first).
3. For every day, fill morning, afternoon and evening with an unused place that suits that time of day.
4. If matching places run out, use other places; if nothing is left, show "Free time".
5. Total cost = (activity costs + daily stay/food cost) x travelers, compared with the budget.

## Limitations

- Prices for places found online are rough category-based estimates, shown with "~". All amounts are in INR.
- Very small towns may have few places, so long trips there will show "Free time" slots.
- Enter a city or town, not a whole country.

## Future scope

- Real prices and currency conversion
- Hotel and flight APIs, Google Maps / route optimisation
- Weather forecast for the travel dates
- AI-written descriptions
- PDF download and sharing links
