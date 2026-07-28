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

    category = request.args.get("category")
    limit = request.args.get("limit", type=int)

    articles = data["articles"]
    if category:
        articles = [a for a in articles if a["category"] == category]
    if limit:
        articles = articles[:limit]

    return jsonify({
        "generated_at": data["generated_at"],
        "count": len(articles),
        "articles": articles,
    })


@app.route("/")
def index():
    return send_from_directory("static", "index.html")


#if __name__ == "__main__":
    app.run(debug=True, port=5000)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))