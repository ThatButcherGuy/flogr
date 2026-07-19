from flask import flash, redirect, session
from functools import wraps


def login_required(f):
    """
    Decorate routes to require login.

    https://flask.palletsprojects.com/en/latest/patterns/viewdecorators/
    """

    @wraps(f)
    def decorated_function(*args, **kwargs):
        if session.get("user_id") is None:
            return redirect("/login")
        return f(*args, **kwargs)

    return decorated_function


# OIDC / Authentik user claim mapping
def get_or_create_user(db, username, email=None):
    """
    Map Authentik `preferred_username` claim to local user row.
    Creates the user with a random password if not present.
    Returns the user row dict, or None on failure.
    """
    username = username.lower()
    rows = db.execute("SELECT * FROM users WHERE username = ?", username)
    if rows:
        return rows[0]

    email = email or f"{username}@oidc.local"
    password_hash = __import__("secrets").token_hex(32)
    try:
        db.execute(
            "INSERT INTO users (username, email, password_hash) VALUES (?, ?, ?)",
            username,
            email,
            password_hash,
        )
    except Exception:
        flash("Unable to provision user from OIDC.", "danger")
        return None

    rows = db.execute("SELECT * FROM users WHERE username = ?", username)
    return rows[0]
