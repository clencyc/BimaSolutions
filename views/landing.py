import streamlit as st

st.write("")
st.write("")
st.write("")

st.markdown("<h1 style='text-align: center;'>My Dashboard</h1>", unsafe_allow_html=True)
st.markdown(
    "<p style='text-align: center; opacity: 0.7;'>"
    "Track your data in one place. Clear charts, live records, and simple filters."
    "</p>",
    unsafe_allow_html=True,
)

st.write("")

_, center, _ = st.columns([1, 1, 1])
with center:
    if st.button("Get started", type="primary", use_container_width=True):
        st.switch_page("views/login.py")