import streamlit as st

st.set_page_config(
    page_title="Flood Risk Dashboard",
    layout="wide",
    initial_sidebar_state="collapsed",
)

if "token" not in st.session_state:
    st.session_state.token = None

landing = st.Page("views/landing.py", title="Home", url_path="", default=True)
login = st.Page("views/login.py", title="Login", url_path="login")
dashboard = st.Page("views/dashboard.py", title="Dashboard", url_path="dashboard", default=True)

if st.session_state.token:
    pg = st.navigation([dashboard], position="hidden")
else:
    pg = st.navigation([landing, login], position="hidden")

pg.run()
