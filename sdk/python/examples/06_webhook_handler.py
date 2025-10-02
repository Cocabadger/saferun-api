"""Receive SafeRun webhook notifications."""
from flask import Flask, request, jsonify

app = Flask(__name__)


@app.post("/webhook/saferun")
def saferun_webhook():
    payload = request.json or {}
    print("Received SafeRun webhook:", payload)
    return jsonify({"status": "ok"})


if __name__ == "__main__":
    app.run(port=8000)
