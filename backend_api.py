"""
backend_api.py – LogGuard AI backend

Responsibilities:
  1. Accept SSH credentials from the UI and open a persistent SSH session
     to the remote VM / firewall.
  2. Tail the relevant log files over SSH and append every new line to a
     local ring-buffer (deque) kept in memory, plus a flat file for
     persistence across UI reloads.
  3. Expose a Server-Sent Events (SSE) endpoint so the Streamlit frontend
     can receive log lines in real-time without polling.
  4. Expose /analyze and /chat endpoints that call the Claude API with
     the current log context.
  5. Expose /status, /connect, /disconnect so the UI can drive the
     SSH lifecycle.

No agent, no watchdog, no shared volume tricks – just SSH from the
container to whatever machine the user points at.
"""

import os
import json
import queue
import threading
import time
from collections import deque
from datetime import datetime

import paramiko
import anthropic
from flask import Flask, Response, request, jsonify, stream_with_context

app = Flask(__name__)

# ── In-memory state ────────────────────────────────────────────────────────────
MAX_LINES = 2000
LOG_FILE  = "shared_logs.log"

log_buffer     = deque(maxlen=MAX_LINES)
sse_clients    = []          # list[queue.Queue]
ssh_thread     = None
ssh_stop_event = threading.Event()
connection_status = {"connected": False, "error": None, "host": None}

lock = threading.Lock()

# ── Log sources to tail on the remote machine ─────────────────────────────────
LOG_SOURCES = [
    "/var/log/auth.log",
    "/var/log/syslog",
    "/var/log/kern.log",
]

DANGER_KEYWORDS = [
    "failed password", "invalid user", "ufw block", "drop",
    "exploit", "attack", "brute", "root login refused",
]
WARNING_KEYWORDS = [
    "sudo", "permission denied", "connection refused",
    "timeout", "rate limit", "warning",
]


# ── Helpers ────────────────────────────────────────────────────────────────────

def classify(line: str) -> str:
    low = line.lower()
    if any(k in low for k in DANGER_KEYWORDS):
        return "danger"
    if any(k in low for k in WARNING_KEYWORDS):
        return "warning"
    return "info"


def make_entry(raw: str) -> dict:
    return {
        "ts":    datetime.now().strftime("%H:%M:%S"),
        "raw":   raw.rstrip(),
        "level": classify(raw),
    }


def broadcast(entry: dict):
    """Push a new log entry to every waiting SSE client queue."""
    payload = json.dumps(entry)
    dead = []
    with lock:
        for q in sse_clients:
            try:
                q.put_nowait(payload)
            except queue.Full:
                dead.append(q)
        for q in dead:
            sse_clients.remove(q)


def append_to_file(entry: dict):
    with open(LOG_FILE, "a") as f:
        f.write(entry["raw"] + "\n")


# ── SSH tail thread ────────────────────────────────────────────────────────────

def ssh_tail(host, port, username, password, key_path, stop):
    """
    Opens an SSH session and runs `tail -F` on all log sources.
    `tail -F` follows log rotation automatically.
    Every new line is written to log_buffer and broadcast via SSE.
    """
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

    try:
        kwargs = dict(
            hostname=host, port=port, username=username,
            timeout=15, allow_agent=False, look_for_keys=False,
        )
        if key_path and os.path.exists(key_path):
            kwargs["key_filename"] = key_path
        else:
            kwargs["password"] = password

        client.connect(**kwargs)

        with lock:
            connection_status.update({"connected": True, "error": None, "host": host})

        # Single command tails all sources; 2>/dev/null silences missing files
        sources = " ".join(LOG_SOURCES)
        cmd = f"sudo tail -F -n 50 {sources} 2>/dev/null"
        _, stdout, _ = client.exec_command(cmd, get_pty=True)

        for raw_line in stdout:
            if stop.is_set():
                break
            raw_line = raw_line.rstrip()
            # tail -F inserts "==> filename <==" headers when following
            # multiple files – skip those
            if not raw_line or raw_line.startswith("==>"):
                continue
            entry = make_entry(raw_line)
            with lock:
                log_buffer.append(entry)
            append_to_file(entry)
            broadcast(entry)

    except Exception as exc:
        with lock:
            connection_status.update({"connected": False, "error": str(exc)})
    finally:
        try:
            client.close()
        except Exception:
            pass
        with lock:
            if connection_status.get("connected"):
                connection_status["connected"] = False


# ── Flask routes ───────────────────────────────────────────────────────────────

@app.route("/status")
def status():
    return jsonify(connection_status)


@app.route("/connect", methods=["POST"])
def connect():
    global ssh_thread, ssh_stop_event

    data     = request.json or {}
    host     = data.get("host", "").strip()
    port     = int(data.get("port", 22))
    username = data.get("username", "").strip()
    password = data.get("password", "")
    key_path = data.get("key_path", "")

    if not host or not username:
        return jsonify({"error": "host and username are required"}), 400

    # Cleanly stop any existing session
    ssh_stop_event.set()
    if ssh_thread and ssh_thread.is_alive():
        ssh_thread.join(timeout=5)

    ssh_stop_event = threading.Event()
    with lock:
        log_buffer.clear()

    ssh_thread = threading.Thread(
        target=ssh_tail,
        args=(host, port, username, password, key_path, ssh_stop_event),
        daemon=True,
    )
    ssh_thread.start()

    # Wait up to 6 s for the connection attempt to resolve
    for _ in range(12):
        time.sleep(0.5)
        with lock:
            if connection_status["connected"] or connection_status["error"]:
                break

    return jsonify(connection_status)


@app.route("/disconnect", methods=["POST"])
def disconnect():
    ssh_stop_event.set()
    with lock:
        connection_status.update({"connected": False, "error": None, "host": None})
    return jsonify({"ok": True})


@app.route("/logs")
def get_logs():
    """Return the full in-memory ring-buffer as JSON (used on page load)."""
    with lock:
        return jsonify(list(log_buffer))


@app.route("/stream")
def stream():
    """
    Server-Sent Events endpoint.

    Each event is a JSON-encoded log entry:
        data: {"ts": "14:23:01", "raw": "Mar 15 sshd ...", "level": "danger"}

    A keepalive comment is sent every 30 s to prevent proxy timeouts.
    """
    q = queue.Queue(maxsize=500)
    with lock:
        sse_clients.append(q)

    @stream_with_context
    def generate():
        # Flush existing buffer so the UI shows history immediately
        with lock:
            snapshot = list(log_buffer)
        for entry in snapshot:
            yield f"data: {json.dumps(entry)}\n\n"

        # Stream live events indefinitely
        while True:
            try:
                payload = q.get(timeout=30)
                yield f"data: {payload}\n\n"
            except queue.Empty:
                yield ": keepalive\n\n"

    def cleanup(_r):
        with lock:
            if q in sse_clients:
                sse_clients.remove(q)

    resp = Response(
        generate(),
        mimetype="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
    resp.call_on_close(lambda: cleanup(resp))
    return resp


@app.route("/analyze", methods=["POST"])
def analyze():
    """
    One-shot log analysis.
    Body:    { "api_key": "sk-ant-…", "lines": 100 }
    Returns: { "analysis": "<markdown text>" }
    """
    data    = request.json or {}
    api_key = data.get("api_key", "").strip()
    n_lines = int(data.get("lines", 100))

    if not api_key:
        return jsonify({"error": "api_key missing"}), 400

    with lock:
        recent = list(log_buffer)[-n_lines:]

    if not recent:
        return jsonify({"analysis": "No logs yet. Connect to a VM first."})

    log_block = "\n".join(e["raw"] for e in recent)

    try:
        ai      = anthropic.Anthropic(api_key=api_key)
        message = ai.messages.create(
            model      = "claude-opus-4-5",
            max_tokens = 1024,
            messages   = [{
                "role": "user",
                "content": (
                    "You are a senior security analyst. Analyze the following system "
                    "logs for threats, brute-force attempts, privilege escalations, "
                    "lateral movement, or unusual behavior. Be concise and actionable. "
                    "Group findings by severity: Critical / Warning / Info.\n\n"
                    f"```\n{log_block}\n```"
                ),
            }],
        )
        return jsonify({"analysis": message.content[0].text})
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


@app.route("/chat", methods=["POST"])
def chat():
    """
    Multi-turn chat with log context injected as system prompt.
    Body:    { "api_key": "…", "messages": [{role, content}, …] }
    Returns: { "reply": "<text>" }
    """
    data     = request.json or {}
    api_key  = data.get("api_key", "").strip()
    messages = data.get("messages", [])

    if not api_key:
        return jsonify({"error": "api_key missing"}), 400

    with lock:
        recent_logs = list(log_buffer)[-50:]

    log_snippet = "\n".join(e["raw"] for e in recent_logs) or "(no logs yet)"

    system_prompt = (
        "You are LogGuard AI, a security analyst embedded in a log monitoring "
        "platform. You have access to the user's recent system logs below. "
        "Answer questions clearly and concisely.\n\n"
        f"Recent logs (last 50 lines):\n```\n{log_snippet}\n```"
    )

    try:
        ai      = anthropic.Anthropic(api_key=api_key)
        message = ai.messages.create(
            model      = "claude-opus-4-5",
            max_tokens = 1024,
            system     = system_prompt,
            messages   = messages,
        )
        return jsonify({"reply": message.content[0].text})
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


if __name__ == "__main__":
    # threaded=True is required – SSE keeps one thread alive per client
    app.run(host="0.0.0.0", port=5000, threaded=True)
