from flask import Flask, request, jsonify

app = Flask(__name__)

@app.route("/api/mt5/sync", methods=["POST"])
def mt5_sync():
    print("🔥 RAW DATA:", request.data)
    print("🔥 JSON:", request.get_json(silent=True))
    return jsonify({"status": "ok"}), 200

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)