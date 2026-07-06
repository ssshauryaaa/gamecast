from flask import Flask, render_template, jsonify, request
import requests
import os
from datetime import datetime, timedelta

app = Flask(__name__)
app.config['TEMPLATES_AUTO_RELOAD'] = True
app.jinja_env.auto_reload = True

BSD_BASE    = "https://sports.bzzoiro.com"
BSD_KEY     = "4f537ed8d889e21ae926f255956e0b1722c08c68"
BSD_HEADERS = {"Authorization": f"Token {BSD_KEY}"}

TOP_LEAGUES = [
    "champions league", "world cup", "europa league", "premier league",
    "la liga", "serie a", "bundesliga", "ligue 1",
    "eredivisie", "primeira liga", "brasileirao"
]

FAVORITE_MAP = {"H": "1", "D": "X", "A": "2"}
STATUS_LIVE  = {"1st_half", "2nd_half", "halftime", "inprogress", "extratime", "penalties", "aet"}

def league_priority(name):
    n = (name or "").lower()
    for i, lg in enumerate(TOP_LEAGUES):
        if lg in n:
            return i
    return len(TOP_LEAGUES) + 1


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/predictions")
def predictions():
    try:
        today    = datetime.utcnow().strftime("%Y-%m-%d")
        tomorrow = (datetime.utcnow() + timedelta(days=1)).strftime("%Y-%m-%d")

        res = requests.get(
            f"{BSD_BASE}/api/v2/predictions/",
            headers=BSD_HEADERS,
            params={"status": "upcoming", "date_from": today, "date_to": tomorrow, "limit": 100},
            timeout=12
        )
        res.raise_for_status()
        raw = res.json()

        # BSD may return a paginated envelope {count, results:[...]} or a bare list
        if isinstance(raw, dict):
            raw = raw.get("results", [])

        matches = []
        for pred in raw:
            if not isinstance(pred, dict):
                continue
            event   = pred.get("event", {})
            recs    = pred.get("recommendations", {})
            model   = pred.get("model", {})
            markets = pred.get("markets", {})

            fav        = recs.get("favorite", "")
            fav_prob   = recs.get("favorite_prob") or 0
            confidence = model.get("confidence") or fav_prob
            ev_status  = event.get("status", "notstarted")

            fav_prob_pct = fav_prob if fav_prob > 1.0 else fav_prob * 100
            confidence_pct = (confidence * 100) if confidence <= 1.0 else confidence

            matches.append({
                "id":                    pred.get("id"),
                "event_id":              event.get("id"),
                "home_team":             event.get("home_team", "—"),
                "away_team":             event.get("away_team", "—"),
                "competition_name":      event.get("league_name", "Other"),
                "event_date":            event.get("event_date", ""),
                "status":                ev_status,
                "is_live":               ev_status in STATUS_LIVE,
                "prediction":            FAVORITE_MAP.get(fav, fav),
                "prediction_probability": round(fav_prob_pct, 1),
                "confidence":            round(confidence_pct, 1),
                "markets":               markets,
                "recommendations":       recs,
                "model_version":         model.get("version", ""),
            })

        matches.sort(key=lambda m: (league_priority(m["competition_name"]), -m["confidence"]))
        return jsonify({"matches": matches, "success": True})

    except Exception as e:
        return jsonify({"error": str(e), "success": False}), 500


@app.route("/api/odds/<int:event_id>")
def odds(event_id):
    try:
        res = requests.get(
            f"{BSD_BASE}/api/v2/events/{event_id}/odds/",
            headers=BSD_HEADERS,
            timeout=10
        )
        res.raise_for_status()
        return jsonify({"odds": res.json(), "success": True})
    except Exception as e:
        return jsonify({"error": str(e), "success": False}), 500


@app.route("/api/search")
def search():
    query       = request.args.get("q", "").strip()
    search_type = request.args.get("type", "teams")

    if not query:
        return jsonify({"results": [], "success": True})

    cfg = {
        "teams":   ("/api/v2/teams/",   "name"),
        "players": ("/api/v2/players/", "name"),
        "leagues": ("/api/v2/leagues/", "country"),
    }
    endpoint, param = cfg.get(search_type, cfg["teams"])

    try:
        res = requests.get(
            f"{BSD_BASE}{endpoint}",
            headers=BSD_HEADERS,
            params={param: query, "limit": 20},
            timeout=10
        )
        res.raise_for_status()
        data = res.json()

        # Handle paginated envelope
        if isinstance(data, dict):
            data = data.get("results", [])

        results = []
        for item in data:
            if not isinstance(item, dict):
                continue
            r = {"name": item.get("name", "Unknown"), "type": search_type}
            if search_type == "teams":
                r["sub"] = item.get("country", "")
            elif search_type == "players":
                pos = item.get("position", "")
                nat = item.get("nationality", "")
                r["sub"] = " • ".join(filter(None, [pos, nat]))
            elif search_type == "leagues":
                r["sub"] = item.get("country", "")
            results.append(r)

        return jsonify({"results": results, "success": True})
    except Exception as e:
        return jsonify({"error": str(e), "success": False}), 500


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
