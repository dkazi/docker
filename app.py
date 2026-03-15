"""
app.py  —  LogGuard AI
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
OPENAI_MODEL = "gpt-4o"

for k, v in {
    "session_id":    str(uuid.uuid4()),
    "connected":     False,
    "conn_status":   "disconnected",
    "chat_messages": [],
    "refresh_count": 0,
    "last_log_hash": "",
}.items():
    if k not in st.session_state:
        st.session_state[k] = v


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
            "host": host, "port": int(port),
            "username": user, "password": pwd,
            "session_id": st.session_state.session_id,
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


def call_openai(api_key: str, system: str, messages: list) -> str:
    r = requests.post(
        OPENAI_API,
        headers={"Authorization": f"Bearer {api_key}",
                 "Content-Type": "application/json"},
        json={
            "model": OPENAI_MODEL,
            "messages": [{"role": "system", "content": system}] + messages,
            "max_tokens": 1024,
            "temperature": 0.2,
        },
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
            st.error("Authentication failed. Check credentials.")
        if st.button("⏏ Disconnect", use_container_width=True):
            do_disconnect()
            st.rerun()

    st.divider()
    st.caption("LogGuard AI — SSH log streaming")


# ── Tabs ───────────────────────────────────────────────────────────────────────
tab_live, tab_chat = st.tabs(["📡 Live Logs", "🤖 AI Analysis"])


# ════════════════════════════ TAB 1 — LIVE LOGS ═══════════════════════════════
with tab_live:

    if not st.session_state.connected:
        st.info("👈 Enter your VM credentials in the sidebar and click **Connect**.")

    else:
        status = st.session_state.conn_status
        now_str = datetime.now().strftime("%H:%M:%S")

        # ── Live indicator ─────────────────────────────────────────────────────
        if status == "connected":
            st.html(f"""
<style>
@keyframes pulse {{
  0%,100% {{ opacity:1; transform:scale(1); }}
  50%      {{ opacity:0.35; transform:scale(0.8); }}
}}
</style>
<div style="display:flex;align-items:center;gap:10px;
            background:#0e1117;border:1px solid #1a3a1a;
            border-radius:8px;padding:8px 14px;margin-bottom:8px;">
  <div style="width:10px;height:10px;border-radius:50%;background:#00e676;
              flex-shrink:0;animation:pulse 1.4s ease-in-out infinite;"></div>
  <span style="color:#00e676;font-size:13px;font-weight:600;
               font-family:monospace;">LIVE</span>
  <span style="color:#555;font-size:12px;font-family:monospace;">
    last update: {now_str} &nbsp;·&nbsp; refresh #{st.session_state.refresh_count}
  </span>
</div>
""")
        elif status == "connecting":
            st.warning("⏳ SSH connecting… logs will appear shortly.")
        else:
            st.error(f"SSH status: `{status}`")

        # ── Fetch logs ─────────────────────────────────────────────────────────
        logs_raw = fetch_logs(300)

        new_hash = str(len(logs_raw)) + (logs_raw[-1] if logs_raw else "")
        st.session_state.last_log_hash = new_hash

        # ── Search filter only — no severity, no colors ────────────────────────
        search = st.text_input(
            "Filter logs",
            placeholder="Type to filter… e.g. sshd, 192.168, sudo",
            label_visibility="visible")

        filtered = [
            ln for ln in logs_raw
            if not search or search.lower() in ln.lower()
        ]

        # ── Plain terminal window ──────────────────────────────────────────────
        rows_html = []
        for ln in filtered[-150:]:
            safe = (ln.replace("&", "&amp;")
                      .replace("<", "&lt;")
                      .replace(">", "&gt;"))
            rows_html.append(
                f'<div style="font-family:monospace;font-size:12px;'
                f'padding:1px 4px;color:#c8c8c8;">{safe}</div>'
            )

        empty_msg = (
            "No logs yet — waiting for SSH stream…"
            if not logs_raw
            else "No lines match your filter."
        )
        body = "".join(rows_html) if rows_html else (
            f'<div style="color:#555;font-size:12px;padding:8px;">{empty_msg}</div>'
        )

        st.html(
            '<div style="background:#0e1117;border-radius:8px;padding:12px;'
            'height:480px;overflow-y:auto;border:1px solid #2a2a2a;">'
            + body
            + '<div id="lb"></div></div>'
            + '<script>document.getElementById("lb")?.scrollIntoView({behavior:"smooth"});</script>'
        )

        # ── Refresh controls ───────────────────────────────────────────────────
        rc1, rc2, rc3 = st.columns([1, 1, 4])
        with rc1:
            if st.button("🔄 Refresh"):
                st.session_state.refresh_count += 1
                st.rerun()
        with rc2:
            auto = st.toggle("Auto (4 s)", value=False,
                             help="Turn OFF when typing in the AI tab.")
        with rc3:
            st.caption(f"{len(filtered)} lines shown · {len(logs_raw)} total")

        if auto:
            time.sleep(4)
            st.session_state.refresh_count += 1
            st.rerun()


# ════════════════════════════ TAB 2 — AI ANALYSIS ════════════════════════════
with tab_chat:

    SYSTEM = (
        "You are a senior security analyst. You will be given Linux system logs "
        "from a VM or firewall. Analyze them carefully and tell the user if there "
        "is anything they should be concerned about — threats, brute-force attempts, "
        "privilege escalations, unusual connections, or any other anomalies. "
        "Be concise. Use bullet points. Quote the exact log line for each finding. "
        "If everything looks normal, say so clearly."
    )

    # API key input — stored in session so user only types it once per session
    if "openai_key" not in st.session_state:
        st.session_state.openai_key = ""

    key_input = st.text_input(
        "OpenAI API Key",
        type="password",
        placeholder="sk-…  (required to use AI analysis)",
        value=st.session_state.openai_key,
    )
    if key_input:
        st.session_state.openai_key = key_input

    api_key = st.session_state.openai_key

    st.divider()

    # ── Send current logs to AI ────────────────────────────────────────────────
    if st.session_state.connected:
        sc1, sc2 = st.columns([1, 3])
        with sc1:
            n_lines = st.selectbox("Lines to send", [50, 100, 200], index=1,
                                   label_visibility="collapsed")
        with sc2:
            if st.button(f"⚡ Analyze last {n_lines} log lines", type="primary",
                         disabled=not api_key):
                lines = fetch_logs(n_lines)
                if not lines:
                    st.warning("No logs available yet.")
                else:
                    with st.spinner("Analyzing…"):
                        try:
                            ans = call_openai(api_key, SYSTEM, [{
                                "role": "user",
                                "content": (
                                    f"Here are the last {n_lines} log lines. "
                                    f"Is there anything I should be concerned about?\n"
                                    f"```\n{chr(10).join(lines)}\n```"
                                ),
                            }])
                            st.session_state.chat_messages.append(
                                {"role": "assistant", "content": ans})
                        except Exception as e:
                            st.error(f"OpenAI error: {e}")
    else:
        st.info("Connect to a VM first, then you can send logs for analysis.")

    st.divider()

    # ── Chat history ───────────────────────────────────────────────────────────
    for msg in st.session_state.chat_messages:
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])

    # ── Chat input ─────────────────────────────────────────────────────────────
    if prompt := st.chat_input(
        "Ask anything… e.g. 'Are there failed SSH logins?'",
        disabled=not api_key,
    ):
        st.session_state.chat_messages.append({"role": "user", "content": prompt})
        with st.chat_message("user"):
            st.markdown(prompt)

        # First turn: attach log context automatically
        first_turn = sum(
            1 for m in st.session_state.chat_messages if m["role"] == "user"
        ) == 1

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
                    reply = call_openai(api_key, SYSTEM, msgs_to_send)
                    st.markdown(reply)
                    st.session_state.chat_messages.append(
                        {"role": "assistant", "content": reply})
                except Exception as e:
                    st.error(f"OpenAI API error: {e}")

    if st.session_state.chat_messages:
        if st.button("🗑️ Clear chat"):
            st.session_state.chat_messages = []
            st.rerun()
