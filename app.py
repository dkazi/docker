"""
app.py  —  LogGuard AI  (Streamlit front-end)
Uses OpenAI API for log analysis.
API key is hardcoded via OPENAI_API_KEY env var (set in docker-compose.yml).
"""

import streamlit as st
import requests
import uuid
import os
import re
import time
from datetime import datetime

st.set_page_config(
    page_title="LogGuard AI",
    page_icon="🛡️",
    layout="wide",
    initial_sidebar_state="expanded",
)

BACKEND      = os.getenv("BACKEND_URL", "http://localhost:5000")
OPENAI_API   = "https://api.openai.com/v1/chat/completions"
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o")
OPENAI_KEY   = os.getenv("OPENAI_API_KEY", "")

# ── Session state defaults ─────────────────────────────────────────────────────
for k, v in {
    "session_id":    str(uuid.uuid4()),
    "connected":     False,
    "conn_status":   "disconnected",
    "chat_messages": [],
    "active_tab":    "live",
}.items():
    if k not in st.session_state:
        st.session_state[k] = v

# ── Severity classification ────────────────────────────────────────────────────
_RULES = [
    ("critical", re.compile(
        r"(failed password|invalid user|authentication failure"
        r"|ufw block|reject|drop|exploit|brute.?force|root login"
        r"|intrusion|attack|malware)", re.I)),
    ("warning", re.compile(
        r"(sudo|permission denied|connection refused|timeout"
        r"|rate.?limit|disk.?full|oom|certificate)", re.I)),
    ("info", re.compile(
        r"(started|stopped|accepted|connected|opened|closed)", re.I)),
]
_BADGE = {"critical": "🔴", "warning": "🟡", "info": "🔵", "normal": "⚪"}
_COLOR = {"critical": "#ff4b4b", "warning": "#ffa600", "info": "#4da6ff", "normal": "#b0b0b0"}


def classify(line: str) -> str:
    for lvl, pat in _RULES:
        if pat.search(line):
            return lvl
    return "normal"


# ── Backend helpers ────────────────────────────────────────────────────────────
def fetch_logs(n=300) -> list:
    try:
        r = requests.get(f"{BACKEND}/logs", params={"n": n}, timeout=3)
        if r.ok:
            return r.json().get("lines", [])
    except Exception:
        pass
    return []


def poll_status() -> str:
    try:
        r = requests.get(
            f"{BACKEND}/status/{st.session_state.session_id}", timeout=3)
        if r.ok:
            return r.json().get("status", "unknown")
    except Exception:
        pass
    return "backend_unreachable"


def do_connect(host, port, user, pwd) -> tuple[bool, str]:
    try:
        r = requests.post(f"{BACKEND}/connect", json={
            "host": host, "port": int(port), "username": user,
            "password": pwd, "session_id": st.session_state.session_id,
        }, timeout=8)
        if r.ok and r.json().get("status") == "ok":
            return True, ""
        return False, r.json().get("message", "Unknown error")
    except Exception as e:
        return False, str(e)


def do_disconnect():
    try:
        requests.post(f"{BACKEND}/disconnect",
                      json={"session_id": st.session_state.session_id},
                      timeout=4)
    except Exception:
        pass
    st.session_state.connected   = False
    st.session_state.conn_status = "disconnected"


def call_openai(system: str, messages: list) -> str:
    if not OPENAI_KEY:
        raise ValueError("OPENAI_API_KEY is not set in environment.")
    payload = {
        "model": OPENAI_MODEL,
        "messages": [{"role": "system", "content": system}] + messages,
        "max_tokens": 1024,
        "temperature": 0.2,
    }
    r = requests.post(
        OPENAI_API,
        headers={"Authorization": f"Bearer {OPENAI_KEY}",
                 "Content-Type": "application/json"},
        json=payload,
        timeout=30,
    )
    r.raise_for_status()
    return r.json()["choices"][0]["message"]["content"]


# ── Sidebar ────────────────────────────────────────────────────────────────────
with st.sidebar:
    st.markdown("## 🛡️ LogGuard AI")
    st.divider()

    st.markdown("### VM Connection")
    vm_host = st.text_input("Host / IP",  placeholder="192.168.1.10")
    vm_port = st.number_input("SSH Port", value=22, min_value=1, max_value=65535)
    vm_user = st.text_input("Username",   placeholder="ubuntu")
    vm_pass = st.text_input("Password",   type="password")

    st.divider()

    if not st.session_state.connected:
        if st.button("🔌 Connect", use_container_width=True, type="primary"):
            if not all([vm_host, vm_user, vm_pass]):
                st.error("Fill in host, username and password.")
            else:
                with st.spinner("Connecting…"):
                    ok, err = do_connect(vm_host, int(vm_port), vm_user, vm_pass)
                if ok:
                    st.session_state.connected   = True
                    st.session_state.conn_status = "connecting"
                    st.rerun()
                else:
                    st.error(f"Connection failed: {err}")
    else:
        live = poll_status()
        st.session_state.conn_status = live
        badge = {"connected": "🟢", "connecting": "🟡"}.get(live, "🔴")
        st.markdown(f"**Status:** {badge} `{live}`")

        if live == "auth_error":
            st.error("Authentication failed. Check username/password.")

        if st.button("⏏ Disconnect", use_container_width=True):
            do_disconnect()
            st.rerun()

    st.divider()
    if not OPENAI_KEY:
        st.warning("⚠️ OPENAI_API_KEY not set.\nSet it in docker-compose.yml.")
    else:
        st.success("✅ OpenAI API key loaded.")
    st.caption("Logs stream automatically after connecting.")


# ── Tabs ───────────────────────────────────────────────────────────────────────
tab_live, tab_chat, tab_about = st.tabs(
    ["📡 Live Logs", "🤖 AI Analysis", "ℹ️ How it works"])


# ════════════════════════════ TAB 1 — LIVE LOGS ═══════════════════════════════
with tab_live:

    if not st.session_state.connected:
        st.info("👈 Enter your VM credentials in the sidebar and click **Connect**.")

    else:
        # Status warning if not yet fully connected
        status = st.session_state.conn_status
        if status == "connecting":
            st.warning("⏳ SSH connection in progress… logs will appear shortly.")
        elif status not in ("connected",):
            st.error(f"SSH status: `{status}`")

        logs_raw = fetch_logs(300)

        # Metrics
        counts = {"critical": 0, "warning": 0, "info": 0, "normal": 0}
        for ln in logs_raw:
            counts[classify(ln)] += 1

        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Total events", len(logs_raw))
        c2.metric("🔴 Threats",   counts["critical"])
        c3.metric("🟡 Warnings",  counts["warning"])
        c4.metric("🔵 Info",      counts["info"])
        st.divider()

        # Filters
        fc1, fc2 = st.columns([3, 1])
        with fc1:
            search = st.text_input(
                "Filter", placeholder="e.g. sshd  192.168  sudo",
                label_visibility="collapsed")
        with fc2:
            levels = st.multiselect(
                "Levels",
                ["🔴 critical", "🟡 warning", "🔵 info", "⚪ normal"],
                default=["🔴 critical", "🟡 warning", "🔵 info", "⚪ normal"],
                label_visibility="collapsed")
        selected = {lbl.split()[1] for lbl in levels}

        # Build log rows
        rows = []
        for ln in logs_raw:
            lvl = classify(ln)
            if lvl not in selected:
                continue
            if search and search.lower() not in ln.lower():
                continue
            safe = (ln.replace("&", "&amp;")
                      .replace("<", "&lt;")
                      .replace(">", "&gt;"))
            rows.append(
                f'<div style="font-family:monospace;font-size:12px;'
                f'padding:2px 6px;color:{_COLOR[lvl]}">'
                f'{_BADGE[lvl]}&nbsp;{safe}</div>'
            )

        body = "".join(rows[-150:]) if rows else (
            '<div style="color:#555;font-size:12px;padding:8px;">'
            + ("No logs yet — waiting for SSH stream…"
               if not logs_raw else "No lines match your filters.")
            + "</div>"
        )

        st.html(
            '<div style="background:#0e1117;border-radius:8px;padding:12px;'
            'height:420px;overflow-y:auto;border:1px solid #2a2a2a;">'
            + body
            + '<div id="logbottom"></div></div>'
            + '<script>'
            + 'var b=document.getElementById("logbottom");'
            + 'if(b)b.scrollIntoView();'
            + '</script>'
        )

        # Refresh controls — NO sleep() here, use a form-based trigger instead
        rcol1, rcol2, rcol3 = st.columns([1, 1, 3])
        with rcol1:
            if st.button("🔄 Refresh now"):
                st.rerun()
        with rcol2:
            auto = st.toggle("Auto (5 s)", value=False,
                             help="Enables 5-second auto-refresh. "
                                  "Turn off when using AI Analysis tab.")
        with rcol3:
            st.caption(
                f"{len(rows)} shown · {len(logs_raw)} total · "
                f"{datetime.now().strftime('%H:%M:%S')}"
            )

        if auto:
            time.sleep(5)
            st.rerun()


# ════════════════════════════ TAB 2 — AI ANALYSIS ════════════════════════════
with tab_chat:
    SYSTEM = (
        "You are a senior security analyst. Analyze Linux VM and firewall logs. "
        "Identify threats, brute-force patterns, privilege escalations, and anomalies. "
        "Be concise. Use bullet points. Quote the exact log fragment that triggered each finding. "
        "If nothing suspicious is found, say so clearly."
    )

    if not OPENAI_KEY:
        st.error("OPENAI_API_KEY is not configured. Set it in docker-compose.yml and rebuild.")
    else:
        # Quick-analyze button
        if st.session_state.connected:
            if st.button("⚡ Analyze last 100 log lines", type="primary"):
                lines = fetch_logs(100)
                if not lines:
                    st.warning("No logs available yet.")
                else:
                    with st.spinner("Analyzing with OpenAI…"):
                        try:
                            ans = call_openai(SYSTEM, [{
                                "role": "user",
                                "content": (
                                    "Analyze these system logs for security threats:\n"
                                    f"```\n{chr(10).join(lines)}\n```"
                                ),
                            }])
                            st.session_state.chat_messages.append(
                                {"role": "assistant", "content": ans})
                        except Exception as e:
                            st.error(f"OpenAI API error: {e}")
        else:
            st.info("Connect to a VM first to enable auto-analysis.")

        st.divider()

        # Chat history
        for msg in st.session_state.chat_messages:
            with st.chat_message(msg["role"]):
                st.markdown(msg["content"])

        # Chat input
        if prompt := st.chat_input("Ask about your logs or describe a threat…"):
            st.session_state.chat_messages.append({"role": "user", "content": prompt})
            with st.chat_message("user"):
                st.markdown(prompt)

            # On first user message, inject log context automatically
            first_turn = sum(1 for m in st.session_state.chat_messages
                             if m["role"] == "user") == 1
            if first_turn and st.session_state.connected:
                lines = fetch_logs(80)
                msgs_to_send = [{
                    "role": "user",
                    "content": (
                        f"Current logs for context:\n```\n{chr(10).join(lines)}\n```\n\n"
                        f"Question: {prompt}"
                    ),
                }]
            else:
                msgs_to_send = [
                    m for m in st.session_state.chat_messages
                    if m["role"] in ("user", "assistant")
                ]

            with st.chat_message("assistant"):
                with st.spinner("Thinking…"):
                    try:
                        reply = call_openai(SYSTEM, msgs_to_send)
                        st.markdown(reply)
                        st.session_state.chat_messages.append(
                            {"role": "assistant", "content": reply})
                    except Exception as e:
                        st.error(f"OpenAI API error: {e}")


# ════════════════════════════ TAB 3 — HOW IT WORKS ════════════════════════════
with tab_about:
    st.markdown("""
## How LogGuard AI works

### Architecture

```
Your VM / Firewall
  /var/log/auth.log
  /var/log/syslog
        │  SSH (paramiko — runs inside Docker)
        ▼
 ┌──────────────────────────────┐
 │   Docker container           │
 │   Flask  :5000  (internal)   │  ← SSH tail → shared_logs.log
 │   Streamlit :8501            │  ← reads logs, calls OpenAI API
 └──────────────────────────────┘
        │  HTTPS
        ▼
   OpenAI API  (key set in docker-compose.yml)
```

### Setup

```bash
# 1. Add your OpenAI key to docker-compose.yml (OPENAI_API_KEY)
# 2. Run:
docker compose up --build
# 3. Open http://localhost:8501
# 4. Enter your VM's SSH credentials and click Connect
```

### Monitored log files
- `/var/log/auth.log` — SSH logins, sudo, PAM events
- `/var/log/syslog`   — kernel, firewall (UFW), service events

### Requirements on the monitored VM
- SSH must be enabled
- The user account needs read access to the log files:
  `sudo usermod -aG adm <username>`
""")
