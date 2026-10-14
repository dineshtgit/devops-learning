from flask import Flask
import os, socket

app = Flask(__name__)

@app.route("/")
def home():
    env = os.getenv("APP_ENV", "dev")
    return f"Hello from {socket.gethostname()} | env={env} | version=v4\n"
@app.route("/health")
def health():
    return "OK\n"

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
