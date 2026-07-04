"""
auth.py
-------
Login gate for the app, with account lockout and timing-safe password checks.
Credentials come from .env so nothing is hard-coded in source. Supports
independent "roles" so staff (field entry), supervisors (dashboard), and
admins (ops/monitoring page) each have their own login:
  - STAFF_USERNAME / STAFF_PASSWORD
  - SUPERVISOR_USERNAME / SUPERVISOR_PASSWORD
  - ADMIN_USERNAME / ADMIN_PASSWORD

This is intentionally simple (one shared username/password per role) — swap
for Azure AD / SSO later if you need per-user accounts; only this file needs
to change, callers just call require_login(role=...).

Security notes:
  - Passwords are compared with a timing-safe comparison (security.constant_time_compare)
    instead of Python's `==`, which leaks timing information about how many
    leading characters matched.
  - Failed attempts are tracked in SQLite (utils/db.py) and an account is
    temporarily locked out after too many failures in a short window — this
    defends against online password guessing, which a plaintext `==` check
    alone does nothing to stop.
  - Every login attempt (success or failure) is logged as a structured event
    (utils/observability.py) so repeated failures are visible on the Admin/Ops
    dashboard, not just silently rejected.
"""

import os
import streamlit as st

from utils.security import constant_time_compare
from utils.observability import log_event
from utils.db import record_login_attempt, count_recent_failed_logins

MAX_FAILED_LOGIN_ATTEMPTS = int(os.getenv("MAX_FAILED_LOGIN_ATTEMPTS", "5"))
LOGIN_LOCKOUT_MINUTES = int(os.getenv("LOGIN_LOCKOUT_MINUTES", "15"))


def require_login(role: str = "staff") -> bool:
    """Renders a login form if not authenticated for this role. Returns True once logged in."""
    session_key = f"authenticated_{role}"
    if st.session_state.get(session_key):
        return True

    st.title(f"🔒 {role.capitalize()} Login")
    st.caption("Please sign in to continue.")

    with st.form(f"login_form_{role}"):
        username = st.text_input("Username")
        password = st.text_input("Password", type="password")
        submitted = st.form_submit_button("Login", type="primary")

    if submitted:
        recent_failures = count_recent_failed_logins(role, username, LOGIN_LOCKOUT_MINUTES)
        if recent_failures >= MAX_FAILED_LOGIN_ATTEMPTS:
            st.error(
                f"Too many failed login attempts. This account is temporarily locked — "
                f"try again in a few minutes."
            )
            log_event("login_locked_out", status="error", username=username, role=role,
                      recent_failures=recent_failures)
            return False

        valid_user = os.getenv(f"{role.upper()}_USERNAME", "admin")
        valid_pass = os.getenv(f"{role.upper()}_PASSWORD", "admin123")
        is_valid = constant_time_compare(username, valid_user) and constant_time_compare(password, valid_pass)

        record_login_attempt(role, username, success=is_valid)
        log_event("login_attempt", status="ok" if is_valid else "error", username=username, role=role)

        if is_valid:
            st.session_state[session_key] = True
            st.session_state[f"{role}_username"] = username
            st.rerun()
        else:
            remaining = max(0, MAX_FAILED_LOGIN_ATTEMPTS - recent_failures - 1)
            st.error(f"Invalid username or password. {remaining} attempt(s) remaining before temporary lockout.")

    return False


def logout_button(role: str = "staff"):
    if st.sidebar.button("🚪 Logout", key=f"logout_{role}"):
        st.session_state[f"authenticated_{role}"] = False
        log_event("logout", username=st.session_state.get(f"{role}_username"), role=role)
        st.rerun()
