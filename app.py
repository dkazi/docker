import streamlit as st
import time
import os

st.set_page_config(page_title="LogGuard AI", layout="wide")

# Sidebar Logic (IP, Username, κλπ - όπως το είχες)
with st.sidebar:
    st.title("🛡️ LogGuard AI")
    vm_ip = st.text_input("IP Διεύθυνση VM")
    vm_user = st.text_input("Username")
    vm_password = st.text_input("Password", type="password")


# Συνάρτηση για ανάγνωση των νέων logs
def get_new_logs():
    if os.path.exists("shared_logs.log"):
        with open("shared_logs.log", "r") as f:
            return f.readlines()[-5:]  # Επιστρέφει τις τελευταίες 5 γραμμές
    return []


st.title("🚀 Security Analysis Chat")

# Το Chat Logic σου
if prompt := st.chat_input("Πώς μπορώ να βοηθήσω;"):
    with st.chat_message("user"):
        st.markdown(prompt)

    with st.chat_message("assistant"):
        if not vm_password:
            st.error("Εισάγετε κωδικό!")
        else:
            # Έλεγχος των logs
            logs = get_new_logs()
            if logs:
                st.write("🔍 **Πρόσφατα Logs που εντοπίστηκαν:**")
                for log in logs:
                    st.code(log)
            else:
                st.write("Δεν υπάρχουν νέα logs προς ανάλυση αυτή τη στιγμή.")