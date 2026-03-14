"""
app.py – LogGuard AI frontend (Streamlit)

Three tabs:
  📡 Live Logs  – real-time log stream polled from the backend,
                  severity filter, text search, stats cards, AI snapshot
  🤖 AI Chat    – multi-turn conversation with Claude about your logs
  ⚙️  Config     – connect / disconnect SSH, API key, log source list

The frontend never touches SSH or the Claude API directly.
Everything goes through http://localhost:5000 (backend_api.py).
"""

import time
import requests
import streamlit as st

BACKEND = "http://localhost:5000"

st.set_page_config(page_title="LogGuard AI", layout="wide", page_icon="🛡️")

st.markdown("""
<style>
[data-testid="metric-container"] {
    background: rgba(0,0,0,0.03);
    border-radius: 8px;
    padding: 10px 14px;
}
</style>
""", unsafe_allow_html=True)

# ── Session state ──────────────────────────────────────────────────────────────
for k, v in [
    ("chat_history",      []),
    ("api_key",           ""),
    ("connected",         False),
    ("prev_threat_count", 0),
]:
    if k not in st.session_state:
        st.session_state[k] = v

# ── Helper ─────────────────────────────────────────────────────────────────────
def backend(method: str, path: str, **kwargs):
    try:
        r = getattr(requests, method)(f"{BACKEND}{path}", timeout=10, **kwargs)
        r.raise_for_status()
        return r.json(), None
    except Exception as exc:
        return None, str(exc)

def get_logs() -> list:
    data, _ = backend("get", "/logs")
    return data if isinstance(data, list) else []

def severity_icon(level: str) -> str:
    return {"danger": "🔴", "warning": "🟡", "info": "⚪"}.get(level, "⚪")

# ── Sidebar ────────────────────────────────────────────────────────────────────
with st.sidebar:
    st.title("🛡️ LogGuard AI")
    status_data, _ = backend("get", "/status")
    if status_data and status_data.get("connected"):
        st.success(f"Connected to **{status_data['host']}**")
        st.session_state.connected = True
    else:
        st.warning("Not connected")
        st.session_state.connected = False
    st.divider()
    st.caption("Configure SSH and API key in the ⚙️ Config tab")

tab_live, tab_chat, tab_config = st.tabs(["📡 Live Logs", "🤖 AI Chat", "⚙️ Config"])

# ── TAB 1: LIVE LOGS ───────────────────────────────────────────────────────────
with tab_live:
    st.subheader("Live Log Stream")

    if not st.session_state.connected:
        st.info("Connect to a VM in the ⚙️ Config tab to start receiving logs.")

    all_logs = get_logs()
    threats  = [l for l in all_logs if l["level"] == "danger"]
    warns    = [l for l in all_logs if l["level"] == "warning"]
    infos    = [l for l in all_logs if l["level"] == "info"]

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Total Events", len(all_logs))
    c2.metric("🔴 Threats",   len(threats))
    c3.metric("🟡 Warnings",  len(warns))
    c4.metric("⚪ Info",      len(infos))

    new_threats = len(threats) - st.session_state.prev_threat_count
    if new_threats > 0:
        st.error(f"⚠️ {new_threats} new threat event(s) since last refresh!")
    st.session_state.prev_threat_count = len(threats)

    st.divider()

    col_a, col_b = st.columns([3, 1])
    with col_a:
        search = st.text_input("🔍 Search logs", placeholder="e.g. sshd, 192.168, sudo")
    with col_b:
        sev_filter = st.multiselect(
            "Severity",
            ["🔴 Threat", "🟡 Warning", "⚪ Info"],
            default=["🔴 Threat", "🟡 Warning", "⚪ Info"],
        )

    level_map = {"🔴 Threat": "danger", "🟡 Warning": "warning", "⚪ Info": "info"}
    allowed   = {level_map[s] for s in sev_filter}

    filtered = [
        l for l in all_logs
        if l["level"] in allowed and (not search or search.lower() in l["raw"].lower())
    ]

    lines = [f"{e['ts']}  {severity_icon(e['level'])}  {e['raw']}" for e in filtered[-200:]]
    st.code("\n".join(lines) if lines else "No logs match your filters.", language=None)

    st.divider()
    st.markdown("**🤖 AI Threat Snapshot**")

    if not st.session_state.api_key:
        st.caption("Add your Claude API key in ⚙️ Config to enable AI analysis.")
    else:
        if st.button("Analyze last 100 lines with Claude"):
            with st.spinner("Analyzing…"):
                result, err = backend(
                    "post", "/analyze",
                    json={"api_key": st.session_state.api_key, "lines": 100},
                )
            if err:
                st.error(f"Backend error: {err}")
            elif result and "error" in result:
                st.error(result["error"])
            elif result:
                st.markdown(result.get("analysis", ""))

    st.divider()
    auto = st.toggle("Auto-refresh every 5 s", value=True)
    if auto and st.session_state.connected:
        time.sleep(5)
        st.rerun()

# ── TAB 2: AI CHAT ─────────────────────────────────────────────────────────────
with tab_chat:
    st.subheader("AI Security Chat")
    st.caption("Ask anything about your logs. Claude has the last 50 lines as context.")

    if not st.session_state.api_key:
        st.warning("Set your Claude API key in ⚙️ Config to use the chat.")
    else:
        for msg in st.session_state.chat_history:
            with st.chat_message(msg["role"]):
                st.markdown(msg["content"])

        if prompt := st.chat_input("Ask about your logs…"):
            with st.chat_message("user"):
                st.markdown(prompt)
            st.session_state.chat_history.append({"role": "user", "content": prompt})

            with st.chat_message("assistant"):
                with st.spinner("Thinking…"):
                    result, err = backend(
                        "post", "/chat",
                        json={
                            "api_key":  st.session_state.api_key,
                            "messages": st.session_state.chat_history,
                        },
                    )
                if err:
                    reply = f"Error: {err}"
                elif result and "error" in result:
                    reply = f"Error: {result['error']}"
                else:
                    reply = result.get("reply", "") if result else "No response"
                st.markdown(reply)

            st.session_state.chat_history.append({"role": "assistant", "content": reply})

        if st.session_state.chat_history:
            if st.button("🗑️ Clear conversation"):
                st.session_state.chat_history = []
                st.rerun()

# ── TAB 3: CONFIG ──────────────────────────────────────────────────────────────
with tab_config:
    st.subheader("Configuration")

    st.markdown("#### Claude API Key")
    api_input = st.text_input(
        "API key", value=st.session_state.api_key,
        type="password", placeholder="sk-ant-…",
        help="Get yours at console.anthropic.com",
    )
    if api_input != st.session_state.api_key:
        st.session_state.api_key = api_input
        st.success("API key saved for this session.")

    st.divider()
    st.markdown("#### SSH Connection")
    st.caption("The app SSHes into your VM and tails logs directly. No agent needed on the remote machine.")

    col1, col2 = st.columns([3, 1])
    with col1:
        host = st.text_input("VM IP / Hostname", placeholder="192.168.1.50")
    with col2:
        port = st.number_input("SSH Port", value=22, min_value=1, max_value=65535)

    col3, col4 = st.columns(2)
    with col3:
        username = st.text_input("Username", placeholder="ubuntu")
    with col4:
        password = st.text_input("Password", type="password",
                                  help="Leave blank if using an SSH key file")

    key_path = st.text_input(
        "SSH key path (optional)", placeholder="/root/.ssh/id_rsa",
        help="Path inside the container to a private key file",
    )

    col_btn1, col_btn2, _ = st.columns([1, 1, 3])
    with col_btn1:
        if st.button("🔌 Connect", type="primary", disabled=not host or not username):
            with st.spinner(f"Connecting to {host}…"):
                result, err = backend(
                    "post", "/connect",
                    json={"host": host, "port": port,
                          "username": username, "password": password,
                          "key_path": key_path},
                )
            if err:
                st.error(f"Could not reach backend: {err}")
            elif result and result.get("connected"):
                st.success(f"Connected to {host}")
                st.rerun()
            else:
                st.error(result.get("error", "Connection failed") if result else "No response")

    with col_btn2:
        if st.button("⏹ Disconnect", disabled=not st.session_state.connected):
            backend("post", "/disconnect")
            st.session_state.connected = False
            st.rerun()

    st.divider()
    st.markdown("#### Log sources tailed on the remote machine")
    st.code("/var/log/auth.log\n/var/log/syslog\n/var/log/kern.log", language=None)
    st.caption(
        "Edit `LOG_SOURCES` in backend_api.py to add firewall logs, "
        "custom application logs, etc."
    )

    st.divider()
    st.markdown("#### Persisted log file")
    if st.button("🗑️ Clear shared_logs.log"):
        backend("post", "/disconnect")
        try:
            open("shared_logs.log", "w").close()
            st.success("Cleared.")
        except Exception as e:
            st.error(str(e))
