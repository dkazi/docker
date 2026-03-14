import streamlit as st
import time

# --- Ρυθμίσεις Σελίδας ---
st.set_page_config(
    page_title="LogGuard AI - Security Dashboard",
    page_icon="🛡️",
    layout="wide"
)

# --- Custom CSS για εμφάνιση ---
st.markdown("""
    <style>
    .main {
        background-color: #f5f7f9;
    }
    .stChatFloatingInputContainer {
        bottom: 20px;
    }
    </style>
    """, unsafe_allow_html=True)

# --- SIDEBAR: Credentials & Logs ---
with st.sidebar:
    st.title("🛡️ LogGuard AI")
    st.subheader("Στοιχεία Πρόσβασης VM")

    # Τα πεδία που ζήτησες
    vm_ip = st.text_input("IP Διεύθυνση VM", placeholder="π.χ. 192.168.1.100")
    vm_user = st.text_input("Ubuntu Username", placeholder="π.χ. ubuntu")
    vm_password = st.text_input("Ubuntu Password", type="password", help="Ο κωδικός πρόσβασης για το VM σας")

    st.divider()

    st.subheader("Αρχεία Logs")
    uploaded_file = st.file_uploader("Ανεβάστε ένα αρχείο log για ανάλυση", type=['log', 'txt', 'csv'])

    if uploaded_file:
        st.success("Το αρχείο φορτώθηκε!")

    st.divider()
    st.info("Συμβουλή: Ρωτήστε το chatbot αν υπάρχουν ύποπτες προσπάθειες login ή SQL injection στα logs σας.")

# --- ΚΥΡΙΩΣ INTERFACE: Chatbot ---
st.title("🤖 Security Analysis Chat")
st.caption("Αναλύστε τα logs του Ubuntu VM σας για πιθανές απειλές σε πραγματικό χρόνο.")

# Αρχικοποίηση ιστορικού μηνυμάτων (Session State)
if "messages" not in st.session_state:
    st.session_state.messages = []

# Εμφάνιση παλαιότερων μηνυμάτων από το ιστορικό
for message in st.session_state.messages:
    with st.chat_message(message["role"]):
        st.markdown(message["content"])

# Λογική Chat Input
if prompt := st.chat_input("Πληκτρολογήστε την ερώτησή σας (π.χ. 'Δέχομαι επίθεση αυτή τη στιγμή;')..."):

    # 1. Εμφάνιση μηνύματος χρήστη
    with st.chat_message("user"):
        st.markdown(prompt)
    st.session_state.messages.append({"role": "user", "content": prompt})

    # 2. Απάντηση Assistant
    with st.chat_message("assistant"):
        message_placeholder = st.empty()

        # Έλεγχος αν ο χρήστης έδωσε κωδικό
        if not vm_password:
            full_response = "⚠️ Παρακαλώ εισάγετε τον κωδικό του Ubuntu VM στο sidebar για να μπορέσω να προχωρήσω στην ανάλυση."
        else:
            # Εδώ θα γινόταν η κλήση στο δικό σου logic/LLM
            # Για τώρα, χρησιμοποιούμε μια mock απάντηση
            full_response = f"Αναλύω τα logs του χρήστη **{vm_user}**. "
            if "επίθεση" in prompt.lower() or "attack" in prompt.lower():
                full_response += "Εντοπίστηκαν 5 αποτυχημένες προσπάθειες σύνδεσης (Brute Force) από την IP 185.x.x.x τα τελευταία 10 λεπτά. Συνιστάται έλεγχος του firewall."
            else:
                full_response += "Τα logs φαίνονται καθαρά. Δεν εντοπίστηκαν ύποπτα patterns στις τελευταίες εγγραφές."

        # Εφέ "γραψίματος" (Typing effect)
        temp_response = ""
        for chunk in full_response.split():
            temp_response += chunk + " "
            time.sleep(0.05)
            message_placeholder.markdown(temp_response + "▌")

        message_placeholder.markdown(full_response)

    # Αποθήκευση απάντησης στο ιστορικό
    st.session_state.messages.append({"role": "assistant", "content": full_response})