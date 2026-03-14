"""
backend_api.py  —  LogGuard AI
SSH into the target VM and stream logs into shared_logs.log.
No agent needed on the remote machine.
"""

from flask import Flask, request, jsonify
import threading
import os
import time
import paramiko

app = Flask(__name__)

_sessions: dict = {}
_lock = threading.Lock()

LOG_FILE  = "/app/shared_logs.log"
MAX_BYTES = 5 * 1024 * 1024   # rotate at 5 MB
LOG_PATHS = ["/var/log/auth.log", "/var/log/syslog"]


def _rotate_if_needed():
    try:
        if os.path.exists(LOG_FILE) and os.path.getsize(LOG_FILE) > MAX_BYTES:
            with open(LOG_FILE, "r") as f:
                lines = f.readlines()
            with open(LOG_FILE, "w") as f:
                f.writelines(lines[-2000:])
    except Exception:
        pass


def _write_log(line: str):
    _rotate_if_needed()
    with open(LOG_FILE, "a") as f:
        f.write(line + "\n")


def _ssh_tail_worker(sid: str, host: str, port: int,
                     username: str, password: str, stop: threading.Event):
    backoff = 5
    while not stop.is_set():
        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        try:
            client.connect(
                host, port=port, username=username, password=password,
                timeout=15, banner_timeout=20, auth_timeout=20,
            )
            _set_status(sid, "connected")
            backoff = 5

            files = " ".join(LOG_PATHS)
            channel = client.get_transport().open_session()
            channel.exec_command(f"tail -F -n 100 {files} 2>/dev/null")

            buf = ""
            while not stop.is_set():
                if channel.recv_ready():
                    chunk = channel.recv(8192).decode("utf-8", errors="replace")
                    buf += chunk
                    lines = buf.split("\n")
                    buf = lines[-1]
                    for line in lines[:-1]:
                        line = line.strip()
                        if line:
                            _write_log(line)
                elif channel.exit_status_ready():
                    break
                else:
                    time.sleep(0.05)

            channel.close()

        except paramiko.AuthenticationException:
            _set_status(sid, "auth_error")
            stop.set()
            return

        except Exception as e:
            _set_status(sid, f"error: {e}")

        finally:
            try:
                client.close()
            except Exception:
                pass

        if not stop.is_set():
            _set_status(sid, f"reconnecting in {backoff}s")
            time.sleep(backoff)
            backoff = min(backoff * 2, 60)


def _set_status(sid: str, status: str):
    with _lock:
        if sid in _sessions:
            _sessions[sid]["status"] = status


# ── Routes ─────────────────────────────────────────────────────────────────────

@app.route("/connect", methods=["POST"])
def connect():
    data = request.get_json(force=True)
    required = ["host", "username", "password", "session_id"]
    if not all(k in data for k in required):
        return jsonify({"status": "error", "message": "Missing fields"}), 400

    sid = data["session_id"]

    # Stop existing session for this sid
    with _lock:
        if sid in _sessions:
            _sessions[sid]["stop"].set()

    stop = threading.Event()
    t = threading.Thread(
        target=_ssh_tail_worker,
        args=(sid, data["host"], int(data.get("port", 22)),
              data["username"], data["password"], stop),
        daemon=True,
    )
    with _lock:
        _sessions[sid] = {"thread": t, "stop": stop, "status": "connecting"}
    t.start()

    return jsonify({"status": "ok", "session_id": sid})


@app.route("/disconnect", methods=["POST"])
def disconnect():
    data = request.get_json(force=True)
    sid = data.get("session_id")
    with _lock:
        if sid in _sessions:
            _sessions[sid]["stop"].set()
            del _sessions[sid]
    return jsonify({"status": "ok"})


@app.route("/status/<sid>")
def status(sid):
    with _lock:
        s = _sessions.get(sid)
    if not s:
        return jsonify({"status": "not_found"})
    return jsonify({"status": s["status"]})


@app.route("/logs")
def get_logs():
    n = int(request.args.get("n", 200))
    if not os.path.exists(LOG_FILE):
        return jsonify({"lines": []})
    with open(LOG_FILE, "r") as f:
        lines = f.readlines()
    return jsonify({"lines": [l.rstrip() for l in lines[-n:]]})


@app.route("/health")
def health():
    return jsonify({"ok": True})


if __name__ == "__main__":
    os.makedirs("/app", exist_ok=True)
    app.run(host="0.0.0.0", port=5000, threaded=True)
