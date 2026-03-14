from flask import Flask, request
import os

app = Flask(__name__)


@app.route("/receive-logs", methods=["POST"])
def receive_logs():
    if "log_file" not in request.files:
        return {"status": "error", "message": "No file"}, 400

    file = request.files["log_file"]
    logs = file.read().decode()

    # Αποθήκευση σε ένα αρχείο που μπορεί να διαβάσει το Streamlit
    with open("shared_logs.log", "a") as f:
        f.write(logs + "\n")

    print("Logs saved to shared_logs.log")
    return {"status": "ok"}


if __name__ == "__main__":
    app.run(port=5000)  # Τρέχει σε διαφορετικό port από το Streamlit