from flask import redirect, session
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
# Potential OIDC/2FA integration entry points.
# Current implementation assumes local Flask-Session auth; for Authentik,
# add an OAuth client and map Authentik claims to the local user row here.
