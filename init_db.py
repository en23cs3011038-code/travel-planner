"""Creates the SQLite database and loads the built-in (curated) cities.

Run: python init_db.py
(Re-running refreshes the curated cities only; users and saved trips are kept.)
"""
import os
import sqlite3

DB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "travel.db")

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    email TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    default_days INTEGER DEFAULT 3,
    default_travelers INTEGER DEFAULT 2,
    default_style TEXT DEFAULT 'standard',
    default_interests TEXT DEFAULT '',
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS destinations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    state TEXT NOT NULL,
    description TEXT
);

CREATE TABLE IF NOT EXISTS places (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    destination_id INTEGER NOT NULL,
    name TEXT NOT NULL,
    category TEXT NOT NULL,      -- Adventure / Food / History / Nature / Relaxation / Shopping / Sightseeing
    cost INTEGER NOT NULL,       -- entry / activity cost per person (INR)
    best_time TEXT NOT NULL,     -- morning / afternoon / evening
    description TEXT,
    FOREIGN KEY (destination_id) REFERENCES destinations(id)
);

CREATE TABLE IF NOT EXISTS trips (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    destination TEXT NOT NULL,
    days INTEGER NOT NULL,
    travelers INTEGER NOT NULL,
    budget INTEGER NOT NULL,
    style TEXT NOT NULL,
    interests TEXT NOT NULL,
    total_cost INTEGER NOT NULL,
    plan_json TEXT NOT NULL,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(id)
);

-- Cache of places fetched online, so the same city is not downloaded again and again
CREATE TABLE IF NOT EXISTS api_cache (
    key TEXT PRIMARY KEY,
    payload TEXT NOT NULL,
    created_at REAL NOT NULL
);
"""

DROP_ALL = """
DROP TABLE IF EXISTS trips;
DROP TABLE IF EXISTS places;
DROP TABLE IF EXISTS destinations;
DROP TABLE IF EXISTS users;
DROP TABLE IF EXISTS api_cache;
"""

DESTINATIONS = [
    ("Goa", "Goa, India", "Beaches, nightlife, Portuguese heritage and seafood."),
    ("Jaipur", "Rajasthan, India", "The Pink City: forts, palaces and colourful bazaars."),
    ("Manali", "Himachal Pradesh, India", "Mountain valleys, adventure sports and cafes."),
]

# (destination_name, place, category, cost in INR, best_time, description)
PLACES = [
    # ---- Goa ----
    ("Goa", "Fort Aguada", "History", 0, "morning", "17th-century Portuguese fort with sea views."),
    ("Goa", "Basilica of Bom Jesus", "History", 0, "morning", "UNESCO World Heritage church in Old Goa."),
    ("Goa", "Chapora Fort Sunset", "History", 0, "evening", "Hilltop fort, perfect for sunset views."),
    ("Goa", "Dudhsagar Waterfall", "Nature", 500, "morning", "Giant four-tiered waterfall, reached by jeep safari."),
    ("Goa", "Spice Plantation Tour", "Nature", 600, "morning", "Guided walk through spice farms, lunch included."),
    ("Goa", "Water Sports at Calangute", "Adventure", 1500, "afternoon", "Parasailing, jet ski and banana boat rides."),
    ("Goa", "Scuba at Grande Island", "Adventure", 2500, "morning", "Beginner-friendly scuba diving."),
    ("Goa", "Goan Fish Thali", "Food", 500, "afternoon", "Traditional Goan seafood thali."),
    ("Goa", "Dinner at Fisherman's Wharf", "Food", 900, "evening", "Riverside seafood dinner."),
    ("Goa", "Baga Beach", "Relaxation", 0, "evening", "Beach shacks, music and sunset."),
    ("Goa", "Palolem Beach", "Relaxation", 0, "afternoon", "Calm, less crowded beach in South Goa."),
    ("Goa", "Anjuna Flea Market", "Shopping", 0, "afternoon", "Handicrafts, clothes and souvenirs."),
    ("Goa", "Mandovi River Sunset Cruise", "Sightseeing", 400, "evening", "Evening boat ride with live music."),
    # ---- Jaipur ----
    ("Jaipur", "Amber Fort", "History", 500, "morning", "Hilltop fort with the famous Sheesh Mahal."),
    ("Jaipur", "Hawa Mahal", "History", 200, "morning", "Iconic palace with 953 small windows."),
    ("Jaipur", "City Palace", "History", 700, "afternoon", "Royal palace complex and museum."),
    ("Jaipur", "Jantar Mantar", "History", 200, "afternoon", "UNESCO site with giant 18th-century astronomical instruments."),
    ("Jaipur", "Albert Hall Museum", "History", 300, "afternoon", "Rajasthani art and artifacts."),
    ("Jaipur", "Rawat Kachori & Lassi", "Food", 300, "morning", "Jaipur's famous breakfast."),
    ("Jaipur", "Dinner at Chokhi Dhani", "Food", 900, "evening", "Rajasthani village theme with folk dance."),
    ("Jaipur", "Nahargarh Fort Sunset", "Nature", 200, "evening", "Panoramic view of the whole city."),
    ("Jaipur", "Jaigarh Fort Jeep Safari", "Adventure", 800, "afternoon", "Jeep ride and one of the world's largest cannons."),
    ("Jaipur", "Jal Mahal Viewpoint", "Relaxation", 0, "evening", "Palace in the middle of a lake."),
    ("Jaipur", "Johari Bazaar", "Shopping", 0, "evening", "Jewellery and gemstone market."),
    ("Jaipur", "Bapu Bazaar", "Shopping", 0, "afternoon", "Mojari shoes, textiles and handicrafts."),
    ("Jaipur", "Panna Meena Ka Kund", "Sightseeing", 0, "morning", "Beautiful 16th-century stepwell near Amber."),
    # ---- Manali ----
    ("Manali", "Hadimba Devi Temple", "History", 0, "morning", "Wooden temple inside a deodar forest."),
    ("Manali", "Tibetan Monastery", "History", 0, "afternoon", "Peaceful monastery with local handicrafts."),
    ("Manali", "Manu Temple", "History", 0, "morning", "Ancient temple in Old Manali."),
    ("Manali", "Rohtang Pass", "Nature", 1500, "morning", "Snow-covered mountain pass (permit required)."),
    ("Manali", "Jogini Waterfall Trek", "Nature", 0, "afternoon", "Easy trek to a beautiful waterfall."),
    ("Manali", "Paragliding at Solang Valley", "Adventure", 3000, "morning", "Fly over the Himalayas."),
    ("Manali", "River Rafting in Kullu", "Adventure", 1200, "afternoon", "White-water rafting on the Beas river."),
    ("Manali", "Old Manali Cafe Hopping", "Food", 600, "afternoon", "Cozy cafes with live music."),
    ("Manali", "Siddu & Trout Dinner", "Food", 700, "evening", "Himachali siddu and fresh trout."),
    ("Manali", "Vashisht Hot Springs", "Relaxation", 0, "afternoon", "Natural hot-water springs."),
    ("Manali", "Beas Riverside Walk", "Relaxation", 0, "evening", "Relaxing evening walk by the river."),
    ("Manali", "Mall Road", "Shopping", 0, "evening", "Woollens, shawls and street food."),
    ("Manali", "Atal Tunnel Viewpoint", "Sightseeing", 0, "afternoon", "World's longest highway tunnel above 10,000 ft."),
]


def seed(conn):
    """Reload the built-in cities (users and trips are not touched)."""
    conn.execute("DELETE FROM places")
    conn.execute("DELETE FROM destinations")
    ids = {}
    for name, state, desc in DESTINATIONS:
        cur = conn.execute(
            "INSERT INTO destinations (name, state, description) VALUES (?, ?, ?)",
            (name, state, desc),
        )
        ids[name] = cur.lastrowid
    for dest, name, cat, cost, best, desc in PLACES:
        conn.execute(
            "INSERT INTO places (destination_id, name, category, cost, best_time, description) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (ids[dest], name, cat, cost, best, desc),
        )


def init(reset=False):
    conn = sqlite3.connect(DB)
    if reset:
        conn.executescript(DROP_ALL)
    conn.executescript(SCHEMA)
    seed(conn)
    conn.commit()
    conn.close()


def ensure():
    """Create the database if missing, or rebuild it if it is from an older version."""
    rebuild = not os.path.exists(DB)
    if not rebuild:
        conn = sqlite3.connect(DB)
        cols = [r[1] for r in conn.execute("PRAGMA table_info(trips)")]
        conn.close()
        rebuild = "user_id" not in cols  # old version of the project
    if rebuild:
        init(reset=True)


if __name__ == "__main__":
    ensure()
    init()
    print("Database ready:", DB)
