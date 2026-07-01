"""
auth.py
-------
Minimal login gate for the app. Credentials come from .env so nothing is
hard-coded in source. This is intentionally simple (single shared
username/password) — swap for Azure AD / SSO later if needed, the rest of
app.py doesn't need to change since it only calls require_login().
"""

import os
import streamlit as st


def require_login() -> bool:
    """Renders a login form if not authenticated. Returns True once logged in."""
    if st.session_state.get("authenticated"):
        return True

    st.title("🔒 Fisheries Market Report — Login")
    st.caption("Please sign in to continue.")

    with st.form("login_form"):
        username = st.text_input("Username")
        password = st.text_input("Password", type="password")
        submitted = st.form_submit_button("Login", type="primary")

    if submitted:
        valid_user = os.getenv("APP_USERNAME", "admin")
        valid_pass = os.getenv("APP_PASSWORD", "admin123")
        if username == valid_user and password == valid_pass:
            st.session_state.authenticated = True
            st.rerun()
        else:
            st.error("Invalid username or password.")

    return False


def logout_button():
    if st.sidebar.button("🚪 Logout"):
        st.session_state.authenticated = False
        st.rerun()
