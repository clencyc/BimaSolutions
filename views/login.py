import streamlit as st

from api_client import APIError, AuthenticationError, login

st.write("")
st.write("")

st.markdown(
    "<h1 style='text-align: center;'>Flood Risk Dashboard</h1>",
    unsafe_allow_html=True,
)
st.markdown(
    "<p style='text-align: center; opacity: 0.7;'>"
    "Sign in with your backend account to view portfolio risk and quote data."
    "</p>",
    unsafe_allow_html=True,
)

_, center, _ = st.columns([1, 2, 1])

with center:
    with st.form("login_form"):
        email = st.text_input("Email", placeholder="you@example.com")
        password = st.text_input("Password", type="password")
        submitted = st.form_submit_button(
            "Sign in", type="primary", use_container_width=True
        )

    if submitted:
        if not email or not password:
            st.warning("Enter both email and password.")
        else:
            with st.spinner("Signing in..."):
                try:
                    body = login(email=email, password=password)
                except AuthenticationError:
                    st.error("Invalid email or password.")
                except APIError as exc:
                    st.error(str(exc))
                else:
                    access_token = body.get("access") if isinstance(body, dict) else None
                    if not access_token:
                        st.error("Login succeeded, but the API did not return an access token.")
                    else:
                        st.session_state.token = access_token
                        st.session_state.refresh_token = body.get("refresh")
                        st.session_state.user_email = email
                        st.rerun()
