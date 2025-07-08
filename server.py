from flask import Flask, request, jsonify, render_template
from flask_cors import CORS
from threading import Thread
from scraper import Scraper

app = Flask(__name__)
CORS(app)
scraper = Scraper()

@app.route("/api/messages", methods=["GET"])
def get_messages():
    return jsonify(
        scraper.store.load('searchResult')
    )

@app.route("/api/cart", methods=["GET"])
def get_cart():
    return jsonify(scraper.store.load("cart"))

@app.route("/api/cart", methods=["PUT"])
def put_cart():
    cart_data = request.get_json(force=True)
    scraper.put_cart(cart_data)
    return jsonify({"code": "success"})

@app.route("/api/cart/<cart_id>", methods=["DELETE"])
def delete_cart(cart_id):
    print(f"car_id = {cart_id}")
    try:
        scraper.delete_cart(cart_id)
        return jsonify({"code": "success"})
    except Exception as e:
        return jsonify({"code": f"server error:\n{e}"}), 400

@app.route("/api/settings", methods=["GET"])
def get_settings():
    response = {
        "username": "com.dennis.parkiesoft",
        "location": scraper.store.get('location'),
        "equipment": scraper.store.get('equipment'),
        "interval": scraper.store.get('interval'),
        "date_range": scraper.store.get('days'),
        "hostname": "localhost",
    }

    return jsonify(response)

@app.route("/api/settings", methods=["PUT"])
def save_settings():
    """
    Save search settings
    """
    try:
        data = request.get_json(force=True)
    except Exception:
        return jsonify({"error": "Invalid JSON"}), 400

    try:
        location = data.get("location")
        equipment = data.get("equipment")
        days = data.get("date_range")
        interval = data.get("interval")
        scraper.update_setting(location, equipment, days, interval)
        return jsonify({"code": 200, "msg": "Saved Success!"})
    except:  # noqa: E722
        return jsonify({"code": "400", "msg": "Data Format Error!"}), 400

@app.route("/api/token", methods=["PUT"])
def set_token():
    try:
        data = request.get_json(force=True)
    except Exception:
        return jsonify({"error": "Invalid JSON"}), 400

    token = data.get("token", "Nothing")

    scraper.set_fcm_token(token)

    return jsonify({"code": "success"})

def run_scraper():
    scraper.start()  # set-interval function

if __name__ == "__main__":
    # Start scraper in a background thread
    scraper_thread = Thread(target=run_scraper, daemon=True)
    scraper_thread.start()
    # Start Flask app
    app.run(host="0.0.0.0", port=5000)
