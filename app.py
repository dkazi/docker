import streamlit as st
import os
import time
import requests
from datetime import datetime

st.set_page_config(page_title="LogGuard AI", page_icon="🛡️", layout="wide")

WATCH_DIR    = "/data_to_monitor"
OPENAI_API   = "https://api.openai.com/v1/chat/completions"
OPENAI_MODEL = "gpt-4o"

for k, v in {
    "chat_messages": [],
    "openai_key":    "",
    "refresh_count": 0,
}.items():
    if k not in st.session_state:
        st.session_state[k] = v


def discover_files() -> list[str]:
    found = []
    if not os.path.exists(WATCH_DIR):
        return found
    for root, _, filenames in os.walk(WATCH_DIR):
        for fname in filenames:
            rel = os.path.relpath(os.path.join(root, fname), WATCH_DIR)
            found.append(rel)
    return sorted(found)


def read_last_n_lines(filepath: str, n: int) -> list[str]:
    """Reads only the last N lines — never loads the whole file."""
    try:
        with open(filepath, "rb") as f:
            f.seek(0, 2)
            size = f.tell()
            if size == 0:
                return []
            chunk = min(size, n * 250)
            f.seek(-chunk, 2)
            data = f.read().decode("utf-8", errors="replace")
        return data.splitlines()[-n:]
    except Exception as e:
        return [f"[error: {e}]"]


def call_openai(api_key: str, messages: list) -> str:
    system = (
        "You are a senior security analyst. Analyze Linux system logs. "
        "Tell the user if there is anything to be concerned about — threats, "
        "brute-force, privilege escalation, anomalies. Be concise, use bullet "
        "points, quote the exact log line for each finding. "
        "If everything looks normal, say so clearly."
    )
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

    all_files = discover_files()

    if not all_files:
        st.error(f"No files found in `{WATCH_DIR}`.\nCheck your volume mount.")
        selected_files = []
    else:
        st.markdown("### Log Files")
        selected_files = st.multiselect(
            "Select files to monitor:",
            options=all_files,
            default=all_files[:3],
            label_visibility="collapsed",
        )

    st.divider()
    n_lines = st.slider("Lines to show per file", 50, 500, 150, step=50)
    st.divider()
    st.caption(f"{len(all_files)} files found in `{WATCH_DIR}`")


# ── Tabs ───────────────────────────────────────────────────────────────────────
tab_live, tab_chat = st.tabs(["📡 Live Logs", "🤖 AI Analysis"])


# ════════════════════ TAB 1 — LIVE LOGS ════════════════════════════════════════
with tab_live:
    if not selected_files:
        st.info(f"Select files from the sidebar to start monitoring.")
    else:
        now_str = datetime.now().strftime("%H:%M:%S")

        st.html(f"""
<style>
@keyframes pulse {{
  0%,100% {{ opacity:1; transform:scale(1); }}
  50%      {{ opacity:0.35; transform:scale(0.8); }}
}}
</style>
<div style="display:flex;align-items:center;gap:10px;background:#0e1117;
            border:1px solid #1a3a1a;border-radius:8px;padding:8px 14px;
            margin-bottom:8px;">
  <div style="width:10px;height:10px;border-radius:50%;background:#00e676;
              flex-shrink:0;animation:pulse 1.4s ease-in-out infinite;"></div>
  <span style="color:#00e676;font-size:13px;font-weight:600;
               font-family:monospace;">LIVE</span>
  <span style="color:#555;font-size:12px;font-family:monospace;">
    {now_str} &nbsp;·&nbsp; refresh #{st.session_state.refresh_count}
  </span>
</div>
""")

        search = st.text_input(
            "Filter", placeholder="e.g. sshd, 192.168, sudo",
            label_visibility="collapsed")

        for rel_path in selected_files:
            full_path = os.path.join(WATCH_DIR, rel_path)
            lines = read_last_n_lines(full_path, n_lines)
            if search:
                lines = [l for l in lines if search.lower() in l.lower()]

            with st.expander(f"📄 {rel_path}  ({len(lines)} lines)", expanded=True):
                if not lines:
                    st.caption("No lines match your filter.")
                else:
                    rows = "".join(
                        f'<div style="font-family:monospace;font-size:12px;'
                        f'padding:1px 4px;color:#c8c8c8;">'
                        f'{l.replace("&","&amp;").replace("<","&lt;").replace(">","&gt;")}'
                        f'</div>'
                        for l in lines
                    )
                    st.html(
                        '<div style="background:#0e1117;border-radius:6px;padding:10px;'
                        'max-height:350px;overflow-y:auto;border:1px solid #2a2a2a;">'
                        + rows + '</div>'
                    )

        st.divider()
        c1, c2, c3 = st.columns([1, 1, 4])
        with c1:
            if st.button("🔄 Refresh"):
                st.session_state.refresh_count += 1
                st.rerun()
        with c2:
            auto = st.toggle("Auto (4 s)", value=False,
                             help="Turn off when using the AI tab.")
        with c3:
            st.caption(f"Last {n_lines} lines per file · {now_str}")

        if auto:
            time.sleep(4)
            st.session_state.refresh_count += 1
            st.rerun()


# ════════════════════ TAB 2 — AI ANALYSIS ══════════════════════════════════════
with tab_chat:
    key_input = st.text_input(
        "OpenAI API Key",
        type="password",
        placeholder="sk-…",
        value=st.session_state.openai_key,
    )
    if key_input:
        st.session_state.openai_key = key_input
    api_key = st.session_state.openai_key

    st.divider()

    if selected_files:
        c1, c2 = st.columns([1, 3])
        with c1:
            n_send = st.selectbox("Lines", [50, 100, 200], index=1,
                                  label_visibility="collapsed")
        with c2:
            if st.button(f"⚡ Analyze last {n_send} lines", type="primary",
                         disabled=not api_key):
                all_lines = []
                for rel in selected_files:
                    chunk = read_last_n_lines(os.path.join(WATCH_DIR, rel), n_send)
                    if chunk:
                        all_lines += [f"--- {rel} ---"] + chunk
                if not all_lines:
                    st.warning("No logs available yet.")
                else:
                    with st.spinner("Analyzing…"):
                        try:
                            ans = call_openai(api_key, [{
                                "role": "user",
                                "content": (
                                    "Is there anything I should be concerned about?\n"
                                    f"```\n{chr(10).join(all_lines)}\n```"
                                ),
                            }])
                            st.session_state.chat_messages.append(
                                {"role": "assistant", "content": ans})
                        except Exception as e:
                            st.error(f"OpenAI error: {e}")
    else:
        st.info("Select log files in the sidebar first.")

    st.divider()

    for msg in st.session_state.chat_messages:
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])

    if prompt := st.chat_input("Ask about your logs…", disabled=not api_key):
        st.session_state.chat_messages.append({"role": "user", "content": prompt})
        with st.chat_message("user"):
            st.markdown(prompt)

        first_turn = sum(
            1 for m in st.session_state.chat_messages if m["role"] == "user"
        ) == 1

        if first_turn and selected_files:
            all_lines = []
            for rel in selected_files:
                chunk = read_last_n_lines(os.path.join(WATCH_DIR, rel), 80)
                if chunk:
                    all_lines += [f"--- {rel} ---"] + chunk
            msgs_to_send = [{
                "role": "user",
                "content": (
                    f"Logs:\n```\n{chr(10).join(all_lines)}\n```\n\nQuestion: {prompt}"
                ),
            }]
        else:
            msgs_to_send = [m for m in st.session_state.chat_messages
                            if m["role"] in ("user", "assistant")]

        with st.chat_message("assistant"):
            with st.spinner("Thinking…"):
                try:
                    reply = call_openai(api_key, msgs_to_send)
                    st.markdown(reply)
                    st.session_state.chat_messages.append(
                        {"role": "assistant", "content": reply})
                except Exception as e:
                    st.error(f"OpenAI error: {e}")

    if st.session_state.chat_messages:
        if st.button("🗑️ Clear chat"):
            st.session_state.chat_messages = []
            st.rerun()
