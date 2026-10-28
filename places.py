"""Finds places to visit in ANY city of the world.

Data comes from OpenStreetMap (free, no API key):
  * Nominatim  -> converts a city name into coordinates
  * Overpass   -> lists attractions, parks, museums, restaurants ... around those coordinates

The 3 built-in cities (Goa, Jaipur, Manali) are served from our own SQL tables, offline.
Results for other cities are cached in the `api_cache` table for 7 days.
"""
import json
import time

import requests

NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
OVERPASS_URLS = [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
]
HEADERS = {"User-Agent": "TravelItineraryPlanner/1.0 (college project)"}
RADIUS_M = 12000
CACHE_TTL = 7 * 24 * 3600

# Rough cost per person (INR) for places that come from the internet (no real price data)
EST_COST = {
    "Adventure": 1500, "Food": 600, "History": 300, "Nature": 100,
    "Relaxation": 0, "Shopping": 0, "Sightseeing": 200,
}
BEST_TIME = {
    "Adventure": "morning", "History": "morning", "Nature": "morning",
    "Sightseeing": "afternoon", "Relaxation": "evening",
    "Shopping": "evening", "Food": "evening",
}

# (OpenStreetMap tag filter, max results)
FILTERS = [
    ('["tourism"~"^(attraction|viewpoint)$"]["name"]', 50),
    ('["tourism"~"^(museum|gallery)$"]["name"]', 40),
    ('["historic"~"^(monument|castle|fort|palace|ruins|memorial|archaeological_site|city_gate|temple)$"]["name"]', 50),
    ('["natural"~"^(waterfall|peak|beach|hot_spring|cave_entrance)$"]["name"]', 30),
    ('["leisure"~"^(park|garden|nature_reserve|water_park)$"]["name"]', 40),
    ('["tourism"~"^(zoo|theme_park|aquarium)$"]["name"]', 20),
    ('["amenity"~"^(restaurant|cafe)$"]["name"]["cuisine"]', 40),
    ('["amenity"="marketplace"]["name"]', 15),
    ('["shop"~"^(mall|department_store)$"]["name"]', 15),
]


class PlaceError(Exception):
    """A problem the user can fix (wrong city name, nothing found, ...)."""


def geocode(query):
    r = requests.get(
        NOMINATIM_URL,
        params={"q": query, "format": "jsonv2", "limit": 1},
        headers=HEADERS,
        timeout=15,
    )
    r.raise_for_status()
    data = r.json()
    if not data:
        raise PlaceError(
            f"Could not find '{query}'. Check the spelling or try a bigger nearby city."
        )
    d = data[0]
    if d.get("place_rank", 30) < 10:
        raise PlaceError(
            f"'{query}' is a country or a large region. "
            "Please enter a specific city or town, for example Paris, Kyoto or Cape Town."
        )
    return d["display_name"], float(d["lat"]), float(d["lon"])


def build_query(lat, lon):
    around = f"(around:{RADIUS_M},{lat},{lon})"
    parts = ["[out:json][timeout:40];"]
    for tag_filter, limit in FILTERS:
        parts.append(f"(node{tag_filter}{around};way{tag_filter}{around};);out center {limit};")
    return "\n".join(parts)


def fetch_overpass(query):
    last_error = None
    for url in OVERPASS_URLS:
        try:
            r = requests.post(url, data={"data": query}, headers=HEADERS, timeout=60)
            r.raise_for_status()
            return r.json().get("elements", [])
        except (requests.RequestException, ValueError) as e:
            last_error = e
    raise last_error


def classify(tags):
    """Returns (category, label) for an OpenStreetMap element, or None to skip it."""
    amenity, tourism = tags.get("amenity"), tags.get("tourism")
    natural, leisure = tags.get("natural"), tags.get("leisure")

    if amenity in ("restaurant", "cafe"):
        cuisine = tags.get("cuisine", "").split(";")[0].replace("_", " ").title()
        base = "Cafe" if amenity == "cafe" else "Restaurant"
        return "Food", f"{cuisine} {base}".strip()
    if amenity == "marketplace" or tags.get("shop") in ("mall", "department_store"):
        return "Shopping", "Market" if amenity == "marketplace" else "Shopping mall"
    if tourism in ("zoo", "theme_park", "aquarium") or leisure == "water_park":
        return "Adventure", (tourism or leisure).replace("_", " ").title()
    if natural == "beach":
        return "Relaxation", "Beach"
    if natural == "hot_spring":
        return "Relaxation", "Hot spring"
    if natural in ("waterfall", "peak", "cave_entrance") or leisure in ("park", "garden", "nature_reserve"):
        return "Nature", (natural or leisure).replace("_", " ").title()
    if tourism in ("museum", "gallery") or "historic" in tags:
        return "History", (tourism or tags.get("historic", "Historic site")).replace("_", " ").title()
    if tourism in ("attraction", "viewpoint"):
        return "Sightseeing", tourism.title()
    return None


def parse_elements(elements):
    places, seen = [], set()
    for el in elements:
        tags = el.get("tags", {})
        name = tags.get("name:en") or tags.get("name")
        if not name or name.lower() in seen:
            continue
        kind = classify(tags)
        if kind is None:
            continue
        category, label = kind
        seen.add(name.lower())

        best = BEST_TIME[category]
        if tags.get("amenity") == "cafe":
            best = "afternoon"

        score = 2 if ("wikipedia" in tags or "wikidata" in tags) else (1 if "website" in tags else 0)
        description = tags.get("description:en") or tags.get("description") or label
        places.append({
            "id": f"osm-{el.get('type', 'x')[0]}{el.get('id')}",
            "name": name,
            "category": category,
            "cost": EST_COST[category],
            "best_time": best,
            "description": description[:160],
            "score": score,
            "estimated": True,
        })
    return places


def short_title(display_name):
    parts = [p.strip() for p in display_name.split(",")]
    return parts[0] if len(parts) == 1 else f"{parts[0]}, {parts[-1]}"


def curated_places(db, query):
    row = db.execute(
        "SELECT * FROM destinations WHERE lower(name) = lower(?)", (query.strip(),)
    ).fetchone()
    if row is None:
        return None
    rows = db.execute("SELECT * FROM places WHERE destination_id = ?", (row["id"],)).fetchall()
    return f"{row['name']}, {row['state']}", [dict(r) for r in rows]


def get_places(db, query):
    """Returns (title, places) for any destination. Raises PlaceError / requests exceptions."""
    query = " ".join(query.split())
    if not query:
        raise PlaceError("Please enter a destination.")

    local = curated_places(db, query)
    if local:
        return local

    key = query.lower()
    row = db.execute("SELECT * FROM api_cache WHERE key = ?", (key,)).fetchone()
    if row and time.time() - row["created_at"] < CACHE_TTL:
        cached = json.loads(row["payload"])
        return cached["title"], cached["places"]

    display_name, lat, lon = geocode(query)
    places = parse_elements(fetch_overpass(build_query(lat, lon)))
    if not places:
        raise PlaceError(
            f"No tourist places found near '{query}'. Try a larger city nearby."
        )
    title = short_title(display_name)

    db.execute(
        "INSERT OR REPLACE INTO api_cache (key, payload, created_at) VALUES (?, ?, ?)",
        (key, json.dumps({"title": title, "places": places}), time.time()),
    )
    db.commit()
    return title, places
