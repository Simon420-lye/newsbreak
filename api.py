import json
import os
import atexit
from apscheduler.schedulers.background import BackgroundScheduler
import fetch

from flask import Flask, jsonify, request, send_from_directory

APP_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_FILE = os.path.join(APP_DIR, "news_data.json")

app = Flask(__name__, static_folder="static", static_url_path="")

REFRESH_HOURS = [7, 18]     # server local time

def refresh():
    try:
        fetch.run(DATA_FILE)
    except Exception as e:
        print(f"[refresh failed] {e}")

# cold start: on a fresh host there's no JSON yet, so don't serve an empty site
if not os.path.exists(DATA_FILE):
    refresh()

scheduler = BackgroundScheduler(daemon=True)
scheduler.add_job(refresh, "cron", hour=",".join(map(str, REFRESH_HOURS)))
scheduler.start()
atexit.register(scheduler.shutdown)

def load_data():
    if not os.path.exists(DATA_FILE):
        return None
    with open(DATA_FILE, encoding="utf-8") as f:
        return json.load(f)


@app.route("/api/news")
def news():
    data = load_data()
    if data is None:
        return jsonify({"error": "No data yet — run fetch.py first."}), 404

    topic = request.args.get("topic")
    limit = request.args.get("limit", type=int)

    stories = data.get("stories", [])
    if topic:
        stories = [s for s in stories if topic in s.get("topics", [])]
    if limit:
        stories = stories[:limit]

    return jsonify({
        "generated_at": data["generated_at"],
        "topics": data.get("topics", {}),
        "count": len(stories),
        "stories": stories,
    })

@app.route("/")
def index():
    return send_from_directory("static", "index.html")

@app.route("/api/debug")
def debug():
    info = {
        "data_file": DATA_FILE,
        "exists": os.path.exists(DATA_FILE),
        "fetch_has_cluster": hasattr(fetch, "cluster"),   # proves new fetch.py is deployed
        "feed_count": len(getattr(fetch, "FEEDS", [])),
    }
    if info["exists"]:
        info["size_bytes"] = os.path.getsize(DATA_FILE)
        try:
            with open(DATA_FILE, encoding="utf-8") as f:
                d = json.load(f)
            info["keys"] = list(d)
            info["story_count"] = len(d.get("stories", []))
            info["article_count"] = len(d.get("articles", []))
            info["generated_at"] = d.get("generated_at")
        except Exception as e:
            info["read_error"] = str(e)
    return jsonify(info)


@app.route("/api/refresh")
def manual_refresh():
    try:
        payload = fetch.run(DATA_FILE)
        return jsonify({"ok": True, "stories": len(payload.get("stories", []))})
    except Exception as e:
        return jsonify({"ok": False, "error": f"{type(e).__name__}: {e}"}), 500


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))