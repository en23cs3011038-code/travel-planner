import functools
import json
import os
import sqlite3

import requests
from flask import (Flask, flash, g, redirect, render_template, request,
                   session, url_for)
from werkzeug.security import check_password_hash, generate_password_hash

import init_db
import places as places_service

DB = init_db.DB
SLOTS = ["morning", "afternoon", "evening"]
INTERESTS = ["Adventure", "Food", "History", "Nature", "Relaxation", "Shopping", "Sightseeing"]
MAX_DAYS = 30
MAX_TRAVELERS = 20

# Rough stay + food + local transport cost, per person per day (INR)
DAILY_COST = {"budget": 1500, "standard": 3000, "luxury": 7000}

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "dev-secret-change-me")

init_db.ensure()


# ---------------------------------------------------------------- database / user helpers
def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(DB)
        g.db.row_factory = sqlite3.Row
    return g.db


@app.teardown_appcontext
def close_db(exc):
    db = g.pop("db", None)
    if db is not None:
        db.close()


@app.before_request
def load_user():
    g.user = None
    uid = session.get("user_id")
    if uid:
        g.user = get_db().execute("SELECT * FROM users WHERE id = ?", (uid,)).fetchone()


@app.context_processor
def inject_user():
    return {"user": g.get("user")}


def login_required(view):
    @functools.wraps(view)
    def wrapped(*args, **kwargs):
        if g.user is None:
            flash("Please log in to continue.", "error")
            return redirect(url_for("login", next=request.path))
        return view(*args, **kwargs)
    return wrapped


def safe_next():
    nxt = request.values.get("next", "")
    return nxt if nxt.startswith("/") and not nxt.startswith("//") else url_for("index")


def curated_names():
    rows = get_db().execute("SELECT name FROM destinations ORDER BY name").fetchall()
    return [r["name"] for r in rows]


# ---------------------------------------------------------------- itinerary logic
def generate_itinerary(places, days, interests, style, travelers, budget):
    """Fills morning / afternoon / evening of every day with places matching the interests."""
    by_score = lambda p: -p.get("score", 0)
    preferred = sorted([p for p in places if p["category"] in interests], key=by_score)
    others = sorted([p for p in places if p["category"] not in interests], key=by_score)

    used = set()

    def pick(slot):
        # 1) interest + right time of day   2) interest + any time
        # 3) any place at the right time    4) any remaining place
        for pool, need_slot in ((preferred, True), (preferred, False), (others, True), (others, False)):
            for p in pool:
                if p["id"] in used:
                    continue
                if need_slot and p["best_time"] != slot:
                    continue
                used.add(p["id"])
                return p
        return None

    plan = []
    for d in range(1, days + 1):
        plan.append({"day": d, "slots": [{"slot": s, "place": pick(s)} for s in SLOTS]})

    activity_cost = sum(
        s["place"]["cost"] for day in plan for s in day["slots"] if s["place"]
    ) * travelers
    stay_food_cost = DAILY_COST[style] * days * travelers
    total = activity_cost + stay_food_cost

    return {
        "plan": plan,
        "activity_cost": activity_cost,
        "stay_food_cost": stay_food_cost,
        "total": total,
        "within_budget": total <= budget,
        "difference": abs(budget - total),
    }


# ---------------------------------------------------------------- planner pages
def default_values():
    values = {"destination": "", "days": 3, "travelers": 2, "budget": 25000,
              "style": "standard", "interests": []}
    if g.user:
        values["days"] = g.user["default_days"] or 3
        values["travelers"] = g.user["default_travelers"] or 2
        values["style"] = g.user["default_style"] or "standard"
        values["interests"] = [i for i in (g.user["default_interests"] or "").split(",") if i]
    return values


def form_page(values, error=None):
    return render_template("index.html", values=values, interests=INTERESTS,
                           curated=curated_names(), error=error, max_days=MAX_DAYS)


@app.route("/")
def index():
    return form_page(default_values())


@app.route("/plan", methods=["POST"])
def plan():
    values = default_values()
    values["destination"] = request.form.get("destination", "").strip()
    values["style"] = request.form.get("style", "standard")
    values["interests"] = [i for i in request.form.getlist("interests") if i in INTERESTS]

    try:
        values["days"] = int(request.form["days"])
        values["travelers"] = int(request.form["travelers"])
        values["budget"] = int(request.form["budget"])
    except (KeyError, ValueError):
        return form_page(values, "Please enter valid numbers for days, travelers and budget.")

    if not values["destination"]:
        return form_page(values, "Please enter a destination.")
    if not 1 <= values["days"] <= MAX_DAYS:
        return form_page(values, f"Number of days must be between 1 and {MAX_DAYS}.")
    if not 1 <= values["travelers"] <= MAX_TRAVELERS:
        return form_page(values, f"Number of travelers must be between 1 and {MAX_TRAVELERS}.")
    if values["budget"] < 1000:
        return form_page(values, "Budget must be at least 1000.")
    if values["style"] not in DAILY_COST:
        values["style"] = "standard"

    interests = values["interests"] or INTERESTS  # nothing selected = all interests

    try:
        title, places = places_service.get_places(get_db(), values["destination"])
    except places_service.PlaceError as e:
        return form_page(values, str(e))
    except requests.RequestException:
        return form_page(
            values,
            "Could not reach the online places service. Check your internet connection and "
            "try again, or use one of the built-in cities: " + ", ".join(curated_names()) + ".",
        )

    result = generate_itinerary(places, values["days"], interests, values["style"],
                                values["travelers"], values["budget"])

    trip_id = None
    if g.user:
        db = get_db()
        cur = db.execute(
            "INSERT INTO trips (user_id, destination, days, travelers, budget, style, "
            "interests, total_cost, plan_json) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (g.user["id"], title, values["days"], values["travelers"], values["budget"],
             values["style"], ", ".join(interests), result["total"], json.dumps(result)),
        )
        db.commit()
        trip_id = cur.lastrowid

    return render_template(
        "itinerary.html", dest_name=title, days=values["days"], travelers=values["travelers"],
        budget=values["budget"], style=values["style"], interests=interests,
        result=result, trip_id=trip_id,
    )


@app.route("/trip/<int:trip_id>")
@login_required
def view_trip(trip_id):
    t = get_db().execute(
        "SELECT * FROM trips WHERE id = ? AND user_id = ?", (trip_id, g.user["id"])
    ).fetchone()
    if t is None:
        flash("Trip not found.", "error")
        return redirect(url_for("history"))
    return render_template(
        "itinerary.html", dest_name=t["destination"], days=t["days"], travelers=t["travelers"],
        budget=t["budget"], style=t["style"], interests=t["interests"].split(", "),
        result=json.loads(t["plan_json"]), trip_id=t["id"],
    )


@app.route("/history")
@login_required
def history():
    trips = get_db().execute(
        "SELECT * FROM trips WHERE user_id = ? ORDER BY id DESC", (g.user["id"],)
    ).fetchall()
    return render_template("history.html", trips=trips)


@app.route("/trip/<int:trip_id>/delete", methods=["POST"])
@login_required
def delete_trip(trip_id):
    db = get_db()
    db.execute("DELETE FROM trips WHERE id = ? AND user_id = ?", (trip_id, g.user["id"]))
    db.commit()
    flash("Trip deleted.", "ok")
    return redirect(url_for("history"))


# ---------------------------------------------------------------- user pages
@app.route("/register", methods=["GET", "POST"])
def register():
    error = None
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        if not name or "@" not in email:
            error = "Please enter your name and a valid email."
        elif len(password) < 6:
            error = "Password must be at least 6 characters."
        else:
            db = get_db()
            try:
                cur = db.execute(
                    "INSERT INTO users (name, email, password_hash) VALUES (?, ?, ?)",
                    (name, email, generate_password_hash(password)),
                )
                db.commit()
            except sqlite3.IntegrityError:
                error = "An account with this email already exists."
            else:
                session.clear()
                session["user_id"] = cur.lastrowid
                flash(f"Welcome, {name}! Set your travel preferences below.", "ok")
                return redirect(url_for("profile"))
    return render_template("register.html", error=error)


@app.route("/login", methods=["GET", "POST"])
def login():
    error = None
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        row = get_db().execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
        if row and check_password_hash(row["password_hash"], password):
            session.clear()
            session["user_id"] = row["id"]
            return redirect(safe_next())
        error = "Invalid email or password."
    return render_template("login.html", error=error)


@app.route("/logout")
def logout():
    session.clear()
    flash("You have been logged out.", "ok")
    return redirect(url_for("index"))


@app.route("/profile", methods=["GET", "POST"])
@login_required
def profile():
    if request.method == "POST":
        try:
            days = max(1, min(int(request.form["default_days"]), MAX_DAYS))
            travelers = max(1, min(int(request.form["default_travelers"]), MAX_TRAVELERS))
        except (KeyError, ValueError):
            flash("Please enter valid numbers.", "error")
            return redirect(url_for("profile"))
        style = request.form.get("default_style", "standard")
        if style not in DAILY_COST:
            style = "standard"
        interests = [i for i in request.form.getlist("default_interests") if i in INTERESTS]
        name = request.form.get("name", "").strip() or g.user["name"]

        db = get_db()
        db.execute(
            "UPDATE users SET name = ?, default_days = ?, default_travelers = ?, "
            "default_style = ?, default_interests = ? WHERE id = ?",
            (name, days, travelers, style, ",".join(interests), g.user["id"]),
        )
        db.commit()
        flash("Preferences saved. They will be pre-filled in the planner.", "ok")
        return redirect(url_for("profile"))

    trip_count = get_db().execute(
        "SELECT COUNT(*) AS c FROM trips WHERE user_id = ?", (g.user["id"],)
    ).fetchone()["c"]
    selected = [i for i in (g.user["default_interests"] or "").split(",") if i]
    return render_template("profile.html", interests=INTERESTS, selected=selected,
                           trip_count=trip_count, max_days=MAX_DAYS)


if __name__ == "__main__":
    app.run(debug=True)
