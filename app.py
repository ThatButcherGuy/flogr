import os
import sqlite3
import csv
import secrets

from cs50 import SQL
from flask import Flask, flash, redirect, render_template, request, session, url_for, Response, jsonify
from flask_session import Session
from werkzeug.security import check_password_hash, generate_password_hash
from email_validator import validate_email, EmailNotValidError
from datetime import date, datetime
from io import StringIO

from helpers import login_required, get_or_create_user
import pyotp
try:
    from authlib.integrations.flask_client import OAuth
except Exception:  # pragma: no cover - OIDC client optional at import time
    OAuth = None

# -------------------------
# Flask Application Setup
# -------------------------
app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY", "default_secret_key")

# Session config
app.config["SESSION_PERMANENT"] = False
app.config["SESSION_TYPE"] = "filesystem"
Session(app)

# -------------------------
# Authentik OIDC configuration
# -------------------------
AUTHENTIK_CLIENT_ID = os.getenv("AUTHENTIK_CLIENT_ID", "")
AUTHENTIK_CLIENT_SECRET = os.getenv("AUTHENTIK_CLIENT_SECRET", "")
AUTHENTIK_ISSUER_URL = os.getenv("AUTHENTIK_ISSUER_URL", "")

# -------------------------
# OIDC / Authentik client setup
# -------------------------
oauth = None
OIDC_REGISTERED = False
if OAuth is not None and AUTHENTIK_CLIENT_ID and AUTHENTIK_CLIENT_SECRET and AUTHENTIK_ISSUER_URL:
    try:
        oauth = OAuth(app)
        oauth.register(
            name="authentik",
            client_id=AUTHENTIK_CLIENT_ID,
            client_secret=AUTHENTIK_CLIENT_SECRET,
            server_metadata_url=f"{AUTHENTIK_ISSUER_URL.rstrip('/')}/.well-known/openid-configuration",
            client_kwargs={"scope": "openid profile email"},
        )
        OIDC_REGISTERED = True
    except Exception:
        OIDC_REGISTERED = False

# Expose oidc flag to templates
app.jinja_env.globals["oidc_enabled"] = OIDC_REGISTERED

# -------------------------
# Database Setup
# -------------------------

DB_PATH = os.getenv(
    "DATABASE_PATH",
    os.path.join(os.path.dirname(__file__), "data", "flogr.db")
)
DB_DIR = os.path.dirname(DB_PATH)
SCHEMA_PATH = os.path.join(os.path.dirname(__file__), "static", "schema.sql")

# Ensure DB directory exists
os.makedirs(DB_DIR, exist_ok=True)

# Create DB file if it doesn't exist
if not os.path.exists(DB_PATH):
    print(f"Creating new SQLite database at {DB_PATH}")
    sqlite3.connect(DB_PATH).close()

# Apply SQLite PRAGMAs
def setup_sqlite(path):
    conn = sqlite3.connect(path)
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA foreign_keys=ON;")
    conn.close()

setup_sqlite(DB_PATH)

# Initialize CS50 SQL wrapper
db = SQL(f"sqlite:///{DB_PATH}")

# -------------------------
# Initialize DB from schema
# -------------------------

# Check if database is empty (no tables)
tables = db.execute(
    "SELECT name FROM sqlite_master WHERE type='table';"
)

# Initialize empty database from schema BEFORE running any migrations so
# the users table exists for the ALTER/UPDATE statements below.
if not tables:
    print("Database is empty — initializing from schema.sql")
    if not os.path.exists(SCHEMA_PATH):
        raise FileNotFoundError(f"Schema file not found: {SCHEMA_PATH}")

    with open(SCHEMA_PATH, "r") as f:
        sql_statements = f.read()

    try:
        # sqlite3 connection for executing multiple statements
        conn = sqlite3.connect(DB_PATH)
        conn.executescript(sql_statements)
        conn.close()
        print("Database initialized successfully from schema.sql")
    except sqlite3.Error as e:
        print(f"Error initializing database: {e}")
        exit(1)

for column in ["two_factor_secret", "two_factor_enabled", "recovery_codes", "oidc_enabled"]:
    try:
        db.execute(f"ALTER TABLE users ADD COLUMN {column} TEXT")
    except Exception:
        pass

# Set oidc_enabled default for existing users who have it NULL
# Default to enabled so existing users get the OIDC option
db.execute(
    "UPDATE users SET oidc_enabled = 1 WHERE oidc_enabled IS NULL"
)


# ---------------------------------------------------------------------------
# Purchased-at location database (user-managed stores + suburbs)
# ---------------------------------------------------------------------------
# Creates the `locations` table (if absent), adds `log.location_id`, and
# backfills existing free-text `purchased_at` rows into the reference list.
# Best-effort split of free text "Retailer Suburb" -> retailer/suburb on the
# last space, so "Costco Majura" -> retailer=Costco, suburb=Majura.
def migrate_locations():
    # Use a native sqlite3 connection for DDL/introspection (the cs50 SQL
    # wrapper returns a bool for PRAGMA and can't run CREATE TABLE IF NOT
    # EXISTS cleanly).
    raw = sqlite3.connect(DB_PATH)

    # 1) Ensure the locations table exists
    # Case-insensitive uniqueness is enforced in app queries (SQLite doesn't
    # allow LOWER() inside a UNIQUE constraint).
    raw.execute("""
        CREATE TABLE IF NOT EXISTS locations (
            id       INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id  INTEGER NOT NULL,
            retailer VARCHAR(100) NOT NULL,
            suburb   VARCHAR(100) NOT NULL,
            UNIQUE (user_id, retailer, suburb),
            FOREIGN KEY (user_id) REFERENCES users(id)
        )
    """)

    # 2) Add log.location_id if missing
    log_cols = [row[1] for row in raw.execute("PRAGMA table_info(log)")]
    column_was_missing = "location_id" not in log_cols
    if column_was_missing:
        raw.execute("ALTER TABLE log ADD COLUMN location_id INTEGER")
    raw.commit()

    # 3) One-time backfill of free-text purchased_at into locations.
    #    This runs ONLY on the first boot where location_id is freshly added
    #    (i.e. on upgrading from pre-3.x to the location database). On every
    #    later boot the column already exists, so we skip it entirely. This
    #    prevents the migration from re-creating "rogue" locations each time
    #    the app starts after the user has cleaned up their location list.
    if not column_was_missing:
        raw.close()
        return  # migration already applied on a prior boot

    cols = [row[1] for row in raw.execute("PRAGMA table_info(log)")]
    if "purchased_at" not in cols:
        raw.close()
        return  # no legacy column to migrate

    distinct = db.execute("""
        SELECT l.user_id, TRIM(l.purchased_at) AS value
        FROM log l
        INNER JOIN users u ON u.id = l.user_id
        WHERE l.purchased_at IS NOT NULL AND TRIM(l.purchased_at) != ''
        GROUP BY l.user_id, TRIM(l.purchased_at)
    """)
    for row in distinct:
        value = row["value"]
        # Split "Retailer Suburb" on the last space; if no space, all goes to retailer.
        if " " in value:
            retailer, suburb = value.rsplit(" ", 1)
        else:
            retailer, suburb = value, ""
        retailer = retailer.strip()
        suburb = suburb.strip()
        # Already exists for this user? (case-insensitive)
        existing = db.execute(
            "SELECT id FROM locations WHERE user_id = ? AND LOWER(retailer) = LOWER(?) AND LOWER(suburb) = LOWER(?)",
            row["user_id"], retailer, suburb,
        )
        try:
            if existing:
                location_id = existing[0]["id"]
            else:
                db.execute(
                    "INSERT INTO locations (user_id, retailer, suburb) VALUES (?, ?, ?)",
                    row["user_id"], retailer, suburb,
                )
                location_id = db.execute(
                    "SELECT id FROM locations WHERE user_id = ? AND LOWER(retailer) = LOWER(?) AND LOWER(suburb) = LOWER(?)",
                    row["user_id"], retailer, suburb,
                )[0]["id"]

            # Backfill log rows that still point at the raw text (no location yet)
            db.execute(
                "UPDATE log SET location_id = ? WHERE user_id = ? AND TRIM(purchased_at) = ? AND (location_id IS NULL OR location_id = '')",
                location_id, row["user_id"], value,
            )
        except ValueError:
            # A single anomalous row (e.g. an orphaned FK) must not crash boot.
            # Log and skip it; the app keeps running and other rows migrate.
            print(f"[migrate_locations] WARNING: skipping un-migratable location "
                  f"user={row['user_id']!r} value={value!r}")
            continue

    raw.close()


migrate_locations()


def location_label(user_id, location_id):
    """Resolve a location_id to its 'Retailer Suburb' display string, or None."""
    if not location_id:
        return None
    row = db.execute(
        "SELECT retailer, suburb FROM locations WHERE id = ? AND user_id = ?",
        location_id, user_id,
    )
    if not row:
        return None
    return f"{row[0]['retailer']} {row[0]['suburb']}".strip()


def user_locations(user_id):
    """List a user's locations as 'Retailer Suburb', ordered for the dropdown."""
    return db.execute("""
        SELECT id, retailer, suburb
        FROM locations
        WHERE user_id = ?
        ORDER BY LOWER(retailer), LOWER(suburb)
    """, user_id)


def resolve_log_locations(logs, user_id):
    """Override each log's purchased_at with the LIVE location label so renames
    propagate to displayed views. Rows without a location keep their stored text."""
    for log in logs:
        if log.get("location_id"):
            label = location_label(user_id, log["location_id"])
            if label:
                log["purchased_at"] = label
    return logs

# -------------------------
# Debug: verify tables
# -------------------------
print("Tables in DB:", db.execute(
    "SELECT name FROM sqlite_master WHERE type='table';"
))

@app.after_request
def after_request(response):
    """Ensure responses aren't cached"""
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    response.headers["Expires"] = 0
    response.headers["Pragma"] = "no-cache"
    return response


@app.route("/login", methods=["GET", "POST"])
def login():
    """Log user in - test {'username': 'test', 'password': '123'}"""

    # User reached route via POST (as by submitting a form via POST)
    if request.method == "POST":
        # Forget any user_id
        session.clear()

        username = request.form.get("username").lower()
        password = request.form.get("password")

        # Ensure username was submitted
        if not username:
            flash('Pease enter a username.', 'danger')
            print('Please enter a username.')
            return redirect(url_for("login"))

        # Ensure password was submitted
        elif not password:
            flash('Incorrect password.', 'danger')
            print('Incorrect password.')
            return redirect(url_for("login"))

        # Query database for username
        rows = db.execute("""
            SELECT *
            FROM users
            WHERE username = ?
            """, username)

        # Ensure username exists and password is correct
        if len(rows) != 1 or not check_password_hash(rows[0]["password_hash"], password):
            flash('Invalid username or password.', 'danger')
            print('Invalid username or password.')
            return redirect(url_for("login"))

        user_id = rows[0]["id"]
        user = db.execute("SELECT * FROM users WHERE id = ?", user_id)[0]
        if user.get("two_factor_enabled") and user.get("two_factor_secret"):
            session["temp_user_id"] = user_id
            return redirect(url_for("mfa_challenge", next=url_for("index")))
        session["user_id"] = user_id
        db.execute(
            "UPDATE users SET last_login = CURRENT_TIMESTAMP WHERE id = ?",
            user_id,
        )
        return redirect(url_for("index"))

    # User reached route via GET (as by clicking a link or via redirect)
    else:
        return render_template("login.html")


@app.route("/logout")
def logout():
    """Log user out"""

    # Forget any user_id
    session.clear()

    # Redirect user to login form
    return redirect("/")


# ------------------------------------------------------------------
# OIDC / Authentik authentication
# ------------------------------------------------------------------
@app.route("/login/oidc", methods=["GET"])
def login_oidc():
    if not OIDC_REGISTERED or oauth is None:
        flash("OIDC login is not configured.", "danger")
        return redirect(url_for("login"))
    assert oauth is not None
    return oauth.authentik.authorize_redirect(
        url_for("login_oidc_callback", _external=True, _scheme="https")
    )


@app.route("/login/oidc/callback", methods=["GET", "POST"])
def login_oidc_callback():
    if not OIDC_REGISTERED or oauth is None:
        flash("OIDC login is not configured.", "danger")
        return redirect(url_for("login"))
    assert oauth is not None
    try:
        token = oauth.authentik.authorize_access_token()
        claims = token.get("userinfo")
        if claims is None:
            claims = oauth.authentik.userinfo()
    except Exception as e:
        flash(
            "Authentik is unreachable. Use your password to log in instead. "
            f"({e})",
            "warning",
        )
        return redirect(url_for("login"))

    username = claims.get("preferred_username")
    email = claims.get("email", "")
    if not username:
        flash("No username received from OIDC provider.", "danger")
        return redirect(url_for("login"))

    user = get_or_create_user(db, username, email)
    if user is None:
        flash("Unable to log in via OIDC.", "danger")
        return redirect(url_for("login"))

    session.clear()
    session["user_id"] = user["id"]
    db.execute(
        "UPDATE users SET last_login = CURRENT_TIMESTAMP WHERE id = ?", user["id"]
    )
    flash("Logged in via Authentik.", "success")
    return redirect(url_for("index"))


@app.route("/register", methods=["GET", "POST"])
def register():
    """Register user"""
    if request.method == "GET":

        return render_template("register.html")

    if request.method == "POST":
        username = request.form.get("username").lower()
        email = request.form.get("email")
        password = request.form.get("password")
        confirmation = request.form.get("confirmation")

        # Validate email
        try:
            valid = validate_email(email)
            email = valid.email

        except EmailNotValidError as e:
            flash(str(e), 'danger')

            return redirect(url_for('register'))

        # Validate other fields
        if not username or not password or not confirmation:
            flash('Please fill out all fields.', 'danger')

            return redirect(url_for('register'))

        if password != confirmation:
            flash('Passwords do not match.', 'danger')

            return redirect(url_for('register'))

        # Update SQL user table if validation passes
        try:
            hash = generate_password_hash(password)
            db.execute("""
                INSERT INTO users
                (username,
                email,
                password_hash)
                VALUES(?, ?, ?)
                """, username, email, hash)
            rows = db.execute("""
                SELECT *
                FROM users
                WHERE username = ?
                """, username)
            session["user_id"] = rows[0]["id"]

            return redirect("/add_vehicle")

        except ValueError:
            flash('Username or email already exists.', 'danger')

            return redirect(url_for('register'))


@app.route("/")
@login_required
def index():
    user_id = session["user_id"]
    vehicles = db.execute("""
        SELECT
            vehicles.registration,
            vehicles.make,
            vehicles.model,
            vehicles.fuel_type,
            fuel_types.name AS fuel_name
        FROM vehicles
        INNER JOIN fuel_types
        ON vehicles.fuel_type = fuel_types.code
        WHERE user_id = ?
        """, user_id)

    fuel_types = db.execute("""
        SELECT *
        FROM fuel_types
        """)

    # Get today's date
    today_date = date.today().isoformat()

    return render_template("index.html", vehicles=vehicles, fuel_types=fuel_types, today_date=today_date,
                           locations=user_locations(user_id))


@app.route("/new_record", methods=["POST"])
@login_required
def new_record():
    user_id = session["user_id"]
    registration = request.form.get("registration")
    fuel_code = request.form.get("fuel_type")
    receipt_number = request.form.get("receipt_number")
    purchased_at = request.form.get("purchased_at")
    location_id = request.form.get("location_id") or None
    litres = request.form.get("litres")
    price_per_litre = request.form.get("price_per_litre")
    kilometres = request.form.get("kilometres")
    comments = request.form.get("comments") or ""
    log_date_str = request.form.get("date")

    try:
        # Perform validation before inserting into the database
        litres = float(litres)
        price_per_litre = float(price_per_litre)
        kilometres = int(kilometres)

        if litres < 0 or price_per_litre < 0 or kilometres < 0:
            flash("Invalid input: Negative values not allowed for litres, price per litre, or kilometres.", "danger")

            return redirect(url_for("index"))

        # Check the length of comments field
        if len(comments) > 150:
            flash("Invalid input: Comments must be less than 150 characters", "danger")

            return redirect(url_for("index"))

        # Validate date
        log_date = datetime.strptime(log_date_str, "%Y-%m-%d").date()

        if log_date > date.today():
            flash("Date must not be in the future.", "danger")

            return redirect(url_for("index"))

        # Check vehicle is in the database
        registration_lookup = db.execute("""
            SELECT registration
            FROM vehicles
            WHERE registration = ?
            AND user_id = ?""",
            registration, user_id)[0]["registration"]

        if registration_lookup is None:
            flash("Vehicle registration not found in the database.", "danger")

            return redirect(url_for("index"))

        # Calculate sale price and round it to 2 decimal places
        sale_price = round((litres * price_per_litre), 2)

        # Resolve location: prefer the FK; keep purchased_at in sync as the
        # display string for back-compat with existing views.
        if location_id:
            resolved = db.execute(
                "SELECT id FROM locations WHERE id = ? AND user_id = ?",
                location_id, user_id,
            )
            if not resolved:
                flash("Selected location not found. Choose a valid location.", "danger")
                return redirect(url_for("index"))
            purchased_at = location_label(user_id, location_id)
        else:
            purchased_at = None

        # Insert into the database
        db.execute("""
            INSERT INTO log
                   (user_id,
                   fuel_code,
                   date,
                   registration,
                   receipt_number,
                   purchased_at,
                   location_id,
                   litres,
                   price_per_litre,
                   sale_price,
                   kilometres,
                   comments)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, user_id, fuel_code, log_date, registration, receipt_number, purchased_at, location_id, litres, price_per_litre, sale_price, kilometres, comments)

        # Update odometer in the vehicles table
        odometer = db.execute("""
            SELECT odometer
            FROM vehicles
            WHERE registration = ?
            AND user_id = ?
            """, registration, user_id)[0]["odometer"]

        odometer = odometer + kilometres

        db.execute("""
            UPDATE vehicles
            SET odometer = ?
            WHERE registration = ?
            AND user_id = ?
            """, odometer, registration, user_id)

        flash("Record added successfully!", "success")

        return redirect(url_for("view_log"))

    except ValueError:
        flash("Invalid input: Ensure all numeric fields are valid numbers.", "danger")

        return redirect(url_for("index"))


@app.route("/view_log", methods=["GET", "POST"])
@login_required
def view_log():
    user_id = session["user_id"]
    selected_registration = request.form.get("registration")

    if request.method == "POST" and selected_registration:
        logs = db.execute("""
            SELECT *
            FROM log
            WHERE user_id = ?
            AND registration = ?
            """, user_id, selected_registration)
    else:
        logs = db.execute("""
            SELECT *
            FROM log
            WHERE user_id = ?
            """, user_id,)

    # Calculate Litres/100km
    for log in logs:
        if log["kilometres"] > 0:
            log["litres_per_100km"] = (log["litres"] / log["kilometres"]) * 100
        else:
            log["litres_per_100km"] = 0.0

    # Show live location labels so renames propagate to display
    resolve_log_locations(logs, user_id)

    # Get registrations for the dropdown
    registrations = db.execute("""
        SELECT
            registration,
            make,
            model
        FROM vehicles
        WHERE user_id = ?
        """, user_id,)

    return render_template("view_log.html", logs=logs, registrations=registrations, selected_registration=selected_registration)

@app.route("/log/<int:log_id>/edit", methods=["GET", "POST"])
@login_required
def edit_log(log_id):
    user_id = session["user_id"]

    # Fetch vehicles and fuel types
    vehicles = db.execute("""
        SELECT
            vehicles.registration,
            vehicles.make,
            vehicles.model,
            vehicles.fuel_type,
            fuel_types.name AS fuel_name
        FROM vehicles
        INNER JOIN fuel_types
        ON vehicles.fuel_type = fuel_types.code
        WHERE user_id = ?
    """, user_id)

    fuel_types = db.execute("SELECT * FROM fuel_types")

    # Fetch the log entry for this user
    log_list = db.execute("""
        SELECT *
        FROM log
        WHERE id = ? AND user_id = ?
    """, log_id, user_id)

    if not log_list:
        flash("Log entry not found or access denied.", "warning")
        return redirect(url_for("view_log"))

    log = dict(log_list[0])  # mutable

    if request.method == "POST":

        # DELETE button clicked
        if "delete" in request.form:
            # Fetch the log entry to get kilometres and registration
            log_entry = db.execute("""
                SELECT kilometres, registration
                FROM log
                WHERE id = ? AND user_id = ?
            """, log_id, user_id)

            if log_entry:
                log_data = log_entry[0]
                km_to_remove = log_data["kilometres"]
                registration = log_data["registration"]

                # Fetch current odometer for the vehicle
                vehicle = db.execute("""
                    SELECT odometer
                    FROM vehicles
                    WHERE registration = ? AND user_id = ?
                """, registration, user_id)

                if vehicle:
                    current_odometer = vehicle[0]["odometer"]
                    new_odometer = max(current_odometer - km_to_remove, 0)  # ensure odometer doesn't go negative

                    # Update vehicle odometer
                    db.execute("""
                        UPDATE vehicles
                        SET odometer = ?
                        WHERE registration = ? AND user_id = ?
                    """, new_odometer, registration, user_id)

                # Delete the log entry
                db.execute("DELETE FROM log WHERE id = ? AND user_id = ?", log_id, user_id)
                flash("Record deleted successfully, odometer updated.", "success")
            else:
                flash("Log entry not found.", "warning")

            return redirect(url_for("view_log"))

        # Extract form data
        registration = request.form.get("registration")
        fuel_code = request.form.get("fuel_code")
        receipt_number = request.form.get("receipt_number")
        purchased_at = request.form.get("purchased_at")
        location_id = request.form.get("location_id") or None
        litres = request.form.get("litres")
        price_per_litre = request.form.get("price_per_litre")
        kilometres = request.form.get("kilometres")
        comments = request.form.get("comments") or ""
        log_date_str = request.form.get("date")

        try:
            # Validate numeric fields
            litres = float(litres)
            price_per_litre = float(price_per_litre)
            kilometres = int(kilometres)

            if litres < 0 or price_per_litre < 0 or kilometres < 0:
                flash("Invalid input: Negative values not allowed for litres, price per litre, or kilometres.", "danger")
                return redirect(url_for("edit_log", log_id=log_id))

            # Validate comments length
            if len(comments) > 150:
                flash("Comments must be less than 150 characters.", "danger")
                return redirect(url_for("edit_log", log_id=log_id))

            # Validate date
            log_date = datetime.strptime(log_date_str, "%Y-%m-%d").date()
            if log_date > date.today():
                flash("Date must not be in the future.", "danger")
                return redirect(url_for("edit_log", log_id=log_id))

            # Check vehicle exists
            vehicle_lookup = db.execute("""
                SELECT registration, odometer
                FROM vehicles
                WHERE registration = ? AND user_id = ?
            """, registration, user_id)

            if not vehicle_lookup:
                flash("Vehicle registration not found.", "danger")
                return redirect(url_for("edit_log", log_id=log_id))

            vehicle = vehicle_lookup[0]

            # Resolve location: prefer FK; keep purchased_at in sync for back-compat
            if location_id:
                resolved = db.execute(
                    "SELECT id FROM locations WHERE id = ? AND user_id = ?",
                    location_id, user_id,
                )
                if not resolved:
                    flash("Selected location not found. Choose a valid location.", "danger")
                    return redirect(url_for("edit_log", log_id=log_id))
                purchased_at = location_label(user_id, location_id)
            else:
                purchased_at = None

            # Calculate sale price
            sale_price = round(litres * price_per_litre, 2)

            # Update log
            db.execute("""
                UPDATE log
                SET date = ?, registration = ?, fuel_code = ?, receipt_number = ?,
                    purchased_at = ?, location_id = ?, litres = ?, price_per_litre = ?,
                    sale_price = ?, kilometres = ?, comments = ?
                WHERE id = ? AND user_id = ?
            """, log_date, registration, fuel_code, receipt_number,
                 purchased_at, location_id, litres, price_per_litre, sale_price,
                 kilometres, comments, log_id, user_id)

            # Adjust odometer
            old_km = log['kilometres']
            current_odometer = vehicle['odometer']
            new_odometer = current_odometer - old_km + kilometres

            db.execute("""
                UPDATE vehicles
                SET odometer = ?
                WHERE registration = ? AND user_id = ?
            """, new_odometer, registration, user_id)

            flash("Record updated successfully!", "success")
            return redirect(url_for("view_log"))

        except ValueError:
            flash("Invalid input: Ensure all numeric fields are valid numbers.", "danger")
            return redirect(url_for("edit_log", log_id=log_id))

    # Precompute Litres/100km
    log["litres_per_100km"] = (log["litres"] / log["kilometres"] * 100) if log["kilometres"] > 0 else 0.0

    return render_template("edit_log.html", log=log, vehicles=vehicles, fuel_types=fuel_types,
                           locations=user_locations(user_id))

@app.route("/stats")
@login_required
def stats():
    user_id = session["user_id"]

    try:
        # Fetch user's vehicles
        vehicles_result = db.execute("""
            SELECT *
            FROM vehicles
            WHERE user_id = ?
            """, user_id)

        vehicles = vehicles_result if vehicles_result else []

        # Fetch the latest log for the user
        last_log_result = db.execute("""
            SELECT *
            FROM log
            WHERE user_id = ?
            ORDER BY date DESC
            LIMIT 1
            """, user_id)

        # Calculate Litres/100km
        for log in last_log_result:
            if log["kilometres"] > 0:
                log["litres_per_100km"] = (log["litres"] / log["kilometres"]) * 100
            else:
                log["litres_per_100km"] = 0.0

        # Show live location label so renames propagate to display
        last_log_result = resolve_log_locations(last_log_result, user_id)

        last_log = last_log_result[0] if last_log_result else None

        # Fetch the username of the logged-in user
        username_result = db.execute("""
            SELECT username
            FROM users
            WHERE id = ?
            """, user_id)

        username = username_result[0]["username"] if username_result else None

        # Check if the data exists
        if not vehicles:
            flash(f"No vehicles found for {username}. Create a vehicle in the Garage", "info")
            return redirect(url_for("garage"))

        if not last_log:
            flash(f"No logs found for {username}. Please enter a log first", "info")
            return redirect(url_for("index"))

        if not username:
            flash("You need to log in before viewing statistics", "danger")
            return redirect(url_for("login"))

        # Calculate days since last fill
        last_fill_date = datetime.strptime(last_log['date'], "%Y-%m-%d").date()
        days_since_last_fill = (date.today() - last_fill_date).days

        # Calculate global stats
        global_stats = db.execute("""
            SELECT
                SUM(sale_price) AS total_sale_price,
                AVG(price_per_litre) AS avg_price_per_litre,
                SUM(litres) AS total_litres,
                AVG(kilometres) AS avg_kilometres,
                SUM(kilometres) AS total_kilometres
            FROM log
            WHERE user_id = ?
            """, user_id)

        total_sale_price = global_stats[0]["total_sale_price"] if global_stats[0]["total_sale_price"] else 0.0
        avg_price_per_litre = global_stats[0]["avg_price_per_litre"] if global_stats[0]["avg_price_per_litre"] else 0.0
        total_litres = global_stats[0]["total_litres"] if global_stats[0]["total_litres"] else 0.0
        avg_kilometres = global_stats[0]["avg_kilometres"] if global_stats[0]["avg_kilometres"] else 0.0
        total_kilometres = global_stats[0]["total_kilometres"] if global_stats[0]["total_kilometres"] else 0.0

        # Calculate GLobal Litres per 100km
        combined_litres_per_100km = (total_litres / total_kilometres) * 100

        return render_template("stats.html",
                               vehicles=vehicles,
                               last_log=last_log,
                               username=username,
                               days_since_last_fill=days_since_last_fill,
                               total_sale_price=total_sale_price,
                               avg_price_per_litre=avg_price_per_litre,
                               total_litres=total_litres,
                               avg_kilometres=avg_kilometres,
                               total_kilometres=total_kilometres,
                               combined_litres_per_100km=combined_litres_per_100km)

    except Exception as e:
        flash(f"An error occurred: {e}", "danger")
        return redirect(url_for("index"))


@app.route("/vehicle_stats/<registration>")
@login_required
def vehicle_stats(registration):
    user_id = session["user_id"]

    try:
        # Fetch vehicle details
        vehicle = db.execute("""
            SELECT *
            FROM vehicles
            WHERE user_id = ?
            AND registration = ?
            """, user_id, registration)

        if not vehicle:
            flash("Vehicle not found or you don't have permission to access it.", "danger")
            return redirect(url_for("stats"))

        # Fetch log for vehicle, sorted by date descending
        vehicle_log = db.execute("""
            SELECT *
            FROM log
            WHERE user_id = ?
            AND registration = ?
            ORDER BY date DESC
            LIMIT 20
            """, user_id, registration)

        for log in vehicle_log:
            if log["kilometres"] > 0:
                log["litres_per_100km"] = (log["litres"] / log["kilometres"]) * 100
            else:
                log["litres_per_100km"] = 0.0

        # Show live location label so renames propagate to display
        vehicle_log = resolve_log_locations(vehicle_log, user_id)

        # Fetch the earliest date from the log table for the user
        earliest_date_result = db.execute("""
            SELECT MIN(date) AS earliest_date
            FROM log
            WHERE user_id = ?
            """, user_id)

        # Default start date to the earliest date available or today's date
        earliest_date = earliest_date_result[0]["earliest_date"] if earliest_date_result[0]["earliest_date"] else date.today()

        # Fetch start and end dates from query parameters or default to today
        start_date_str = request.args.get('start_date', earliest_date)
        end_date_str = request.args.get('end_date', date.today().strftime('%Y-%m-%d'))

        # Convert date strings to datetime objects
        start_date = datetime.strptime(start_date_str, '%Y-%m-%d')
        end_date = datetime.strptime(end_date_str, '%Y-%m-%d')

        # Fetch vehicle-specific global stats for the given date range
        vehicle_stats = db.execute("""
            SELECT
                SUM(sale_price) AS vehicle_total_sale_price,
                AVG(price_per_litre) AS vehicle_avg_price_per_litre,
                SUM(litres) AS vehicle_total_litres,
                AVG(kilometres) AS vehicle_avg_kilometres,
                SUM(kilometres) AS vehicle_total_kilometres
            FROM log
            WHERE user_id = ?
            AND registration = ?
            AND date >= ?
            AND date <= ?
            """, user_id, registration, start_date.date(), end_date.date())

        vehicle_total_sale_price = vehicle_stats[0]["vehicle_total_sale_price"] or 0.0
        vehicle_avg_price_per_litre = vehicle_stats[0]["vehicle_avg_price_per_litre"] or 0.0
        vehicle_total_litres = vehicle_stats[0]["vehicle_total_litres"] or 0.0
        vehicle_avg_kilometres = vehicle_stats[0]["vehicle_avg_kilometres"] if vehicle_stats[0]["vehicle_avg_kilometres"] else 0.0
        vehicle_total_kilometres = vehicle_stats[0]["vehicle_total_kilometres"] if vehicle_stats[0]["vehicle_total_kilometres"] else 0.0

        # Calculate litres per hundred
        mileage = (vehicle_total_litres / vehicle_total_kilometres) * 100

        return render_template("vehicle_stats.html", vehicle=vehicle[0],
                               vehicle_total_sale_price=vehicle_total_sale_price,
                               vehicle_avg_price_per_litre=vehicle_avg_price_per_litre,
                               vehicle_total_litres=vehicle_total_litres,
                               vehicle_avg_kilometres=vehicle_avg_kilometres,
                               vehicle_total_kilometres=vehicle_total_kilometres,
                               mileage=mileage,
                               start_date=start_date_str, end_date=end_date_str,
                               vehicle_log=vehicle_log)

    except Exception as e:
        flash(f"An error occurred: {e}", "danger")
        return redirect(url_for("stats"))

@app.route("/export_log")
@login_required
def export_log():
    user_id = session["user_id"]
    registration_filter = request.args.get("registration")  # optional

    # Fetch logs with optional filter
    if registration_filter:
        logs = db.execute("""
            SELECT *
            FROM log
            WHERE user_id = ? AND registration = ?
            ORDER BY date DESC
        """, user_id, registration_filter)
    else:
        logs = db.execute("""
            SELECT *
            FROM log
            WHERE user_id = ?
            ORDER BY date DESC
        """, user_id)

    # Compute litres_per_100km (rounded to 2 decimal places)
    for log in logs:
        lpk = (log["litres"] / log["kilometres"]) * 100 if log["kilometres"] > 0 else 0.0
        log["litres_per_100km"] = round(lpk, 2)

    # Create CSV in memory
    si = StringIO()
    cw = csv.writer(si)

    # Write headers including new calculated column
    if logs:
        headers = list(logs[0].keys())
        cw.writerow(headers)

        for log in logs:
            cw.writerow([log[h] for h in headers])

    return Response(
        si.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": "attachment;filename=log_export.csv"}
    )

@app.route("/garage")
@login_required
def garage():
    user_id = session["user_id"]

    # Get vehicle details
    vehicles = db.execute("""
        SELECT
            vehicles.registration,
            vehicles.make,
            vehicles.model,
            vehicles.fuel_type,
            vehicles.vehicle_type,
            vehicles.year,
            vehicles.odometer,
            fuel_types.name AS fuel_name
        FROM vehicles
        INNER JOIN fuel_types
        ON vehicles.fuel_type = fuel_types.code
        WHERE user_id = ?
        """, user_id)

    return render_template("garage.html", vehicles=vehicles)


@app.route("/locations")
@login_required
def locations():
    user_id = session["user_id"]

    # All user's locations, with usage count per location
    locations_list = db.execute("""
        SELECT
            l.id,
            l.retailer,
            l.suburb,
            COUNT(log.id) AS usage_count
        FROM locations l
        LEFT JOIN log ON log.location_id = l.id
        WHERE l.user_id = ?
        GROUP BY l.id
        ORDER BY LOWER(l.retailer), LOWER(l.suburb)
    """, user_id)

    return render_template("locations.html", locations=locations_list)


@app.route("/locations/add", methods=["POST"])
@login_required
def add_location():
    user_id = session["user_id"]
    retailer = request.form.get("retailer", "").strip()
    suburb = request.form.get("suburb", "").strip()
    ajax = request.headers.get("X-Requested-With") == "XMLHttpRequest"

    def json_out(ok, label=None, location_id=None, error=None):
        return jsonify({"ok": ok, "label": label, "location_id": location_id, "error": error})

    if not retailer or not suburb:
        if ajax:
            return json_out(False, error="Both retailer and suburb are required."), 400
        flash("Both retailer and suburb are required.", "danger")
        return redirect(url_for("locations"))

    # Check for existing (case-insensitive) before inserting
    existing = db.execute(
        "SELECT id FROM locations WHERE user_id = ? AND LOWER(retailer) = LOWER(?) AND LOWER(suburb) = LOWER(?)",
        user_id, retailer, suburb,
    )
    if existing:
        loc_id = existing[0]["id"]
        label = f"{retailer} {suburb}"
        if ajax:
            return json_out(True, label=label, location_id=loc_id, error="already_exists")
        flash(f"Location '{retailer} {suburb}' already exists.", "warning")
        return redirect(url_for("locations"))

    db.execute(
        "INSERT INTO locations (user_id, retailer, suburb) VALUES (?, ?, ?)",
        user_id, retailer, suburb,
    )
    new_id = db.execute(
        "SELECT id FROM locations WHERE user_id = ? AND LOWER(retailer) = LOWER(?) AND LOWER(suburb) = LOWER(?)",
        user_id, retailer, suburb,
    )[0]["id"]

    if ajax:
        return json_out(True, label=f"{retailer} {suburb}", location_id=new_id)

    flash("Location added successfully.", "success")
    return redirect(url_for("locations"))


@app.route("/locations/<int:location_id>/edit", methods=["POST"])
@login_required
def edit_location(location_id):
    user_id = session["user_id"]
    retailer = request.form.get("retailer", "").strip()
    suburb = request.form.get("suburb", "").strip()

    if not retailer or not suburb:
        flash("Both retailer and suburb are required.", "danger")
        return redirect(url_for("locations"))

    # Duplicate check against a *different* id
    dup = db.execute(
        "SELECT id FROM locations WHERE user_id = ? AND LOWER(retailer) = LOWER(?) AND LOWER(suburb) = LOWER(?) AND id != ?",
        user_id, retailer, suburb, location_id,
    )
    if dup:
        flash(f"Location '{retailer} {suburb}' already exists.", "warning")
        return redirect(url_for("locations"))

    db.execute(
        "UPDATE locations SET retailer = ?, suburb = ? WHERE id = ? AND user_id = ?",
        retailer, suburb, location_id, user_id,
    )
    # Because log rows reference this location by id, editing automatically
    # propagates the new name to every existing log entry.
    flash("Location updated — applies to all existing log entries.", "success")
    return redirect(url_for("locations"))


@app.route("/locations/<int:location_id>/delete", methods=["POST"])
@login_required
def delete_location(location_id):
    user_id = session["user_id"]

    # Verify the location belongs to this user
    loc = db.execute(
        "SELECT id FROM locations WHERE id = ? AND user_id = ?", location_id, user_id)
    if not loc:
        flash("Location not found.", "danger")
        return redirect(url_for("locations"))

    # Check if it's referenced by any log entry
    in_use = db.execute(
        "SELECT COUNT(*) AS n FROM log WHERE location_id = ?", location_id)
    if in_use[0]["n"] > 0:
        flash(
            f"Cannot delete — this location is still used by {in_use[0]['n']} log "
            f"entr{'y' if in_use[0]['n'] == 1 else 'ies'}. Edit it instead, or reassign those entries first.",
            "danger",
        )
        return redirect(url_for("locations"))

    db.execute("DELETE FROM locations WHERE id = ? AND user_id = ?", location_id, user_id)
    flash("Location deleted.", "success")
    return redirect(url_for("locations"))


@app.route("/vehicle/<registration>")
@login_required
def vehicle_details(registration):
    user_id = session["user_id"]

    # Get selected vehicle details
    vehicle = db.execute("""
        SELECT
            vehicles.*,
            fuel_types.name AS fuel_name
        FROM vehicles
        INNER JOIN fuel_types
        ON vehicles.fuel_type = fuel_types.code
        WHERE registration = ?
        AND user_id = ?
        """, registration, user_id)

    if not vehicle:
        flash('Vehicle not found.', 'danger')

        return redirect(url_for('garage'))

    return render_template("vehicle_details.html", vehicle=vehicle[0])


@app.route("/add_vehicle", methods=["GET", "POST"])
@login_required
def add_vehicle():
    vehicle_types = ["Car", "4wd",  "Truck", "Motorcycle",
                     "Hot Air Balloon", "Aircraft", "Boat", "Other"]
    if request.method == "GET":
        fuel_types = db.execute("SELECT * FROM fuel_types")
        years = list(range(2024, 1959, -1))

        return render_template("add_vehicle.html", fuel_types=fuel_types, vehicle_types=vehicle_types, years=years)

    if request.method == "POST":
        user_id = session["user_id"]
        registration = request.form.get("registration").upper()
        fuel_type = request.form.get("fuel_type")
        vehicle_type = request.form.get("vehicle_type")
        make = request.form.get("make")
        model = request.form.get("model")
        year = request.form.get("year")
        odometer = request.form.get("odometer")

        # Validate user input
        if not (registration and fuel_type and vehicle_type and make and model and year and odometer):
            flash('Please complete all fields.', 'danger')

            return redirect(url_for('add_vehicle'))

        if not odometer.isdigit():
            flash('Please enter only numbers in the Odometer field.', 'danger')

            return redirect(url_for('add_vehicle'))

        if not year.isdigit():
            flash('Please enter only numbers in the Year field.', 'danger')

            return redirect(url_for('add_vehicle'))

        # Get fuel codes
        fuel_codes = db.execute("SELECT code FROM fuel_types")
        fuel_codes_list = [code['code'] for code in fuel_codes]

        # Validate user input for fuel type
        if fuel_type not in fuel_codes_list:
            flash('Please enter correct fuel type.', 'danger')

            return redirect(url_for('add_vehicle'))

        # Validate user input for vehicle type
        if vehicle_type not in vehicle_types:
            flash('Please enter correct vehicle type.', 'danger')

            return redirect(url_for('add_vehicle'))

        # Ensure registration does not already exist for user
        registrations = db.execute("""
            SELECT UPPER(registration)
            AS registration
            FROM vehicles WHERE user_id = ?
            """, user_id)
        registration_list = [registration['registration'] for registration in registrations]

        if registration in registration_list:
            flash('Vehicle is already in your Garage.', 'danger')

            return redirect(url_for('add_vehicle'))

        # Add vehicle to garage
        db.execute("""
            INSERT INTO vehicles
                   (user_id,
                   registration,
                   fuel_type,
                   vehicle_type,
                   make,
                   model,
                   year,
                   odometer)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, user_id, registration, fuel_type, vehicle_type, make, model, year, odometer)

        flash('Vehicle added successfully!', 'success')

        return redirect(url_for("garage"))

@app.route("/edit_vehicle/<registration>", methods=["GET", "POST"])
@login_required
def edit_vehicle(registration):
    user_id = session["user_id"]

    vehicle_list = db.execute("""
        SELECT v.*, f.name AS fuel_name
        FROM vehicles v
        INNER JOIN fuel_types f ON v.fuel_type = f.code
        WHERE v.user_id = ? AND v.registration = ?
    """, user_id, registration)

    if not vehicle_list:
        flash("Vehicle not found or access denied.", "warning")
        return redirect(url_for("garage"))

    vehicle = dict(vehicle_list[0])

    fuel_types = db.execute("SELECT * FROM fuel_types")
    vehicle_types = ["Car", "4wd", "Truck", "Motorcycle", "Hot Air Balloon", "Aircraft", "Boat", "Other"]
    years = list(range(2024, 1959, -1))

    if request.method == "POST":
        if "delete" in request.form:
            db.execute("DELETE FROM vehicles WHERE user_id = ? AND registration = ?", user_id, registration)
            flash(f"Vehicle {registration} deleted successfully.", "success")
            return redirect(url_for("garage"))

        # Otherwise, update
        fuel_type = request.form.get("fuel_type")
        vehicle_type = request.form.get("vehicle_type")
        make = request.form.get("make")
        model = request.form.get("model")
        year = request.form.get("year")
        odometer = request.form.get("odometer")

        if not (fuel_type and vehicle_type and make and model and year and odometer):
            flash("Please complete all fields.", "danger")
            return redirect(url_for("edit_vehicle", registration=registration))

        if not odometer.isdigit() or not year.isdigit():
            flash("Year and Odometer must be numbers.", "danger")
            return redirect(url_for("edit_vehicle", registration=registration))

        db.execute("""
            UPDATE vehicles
            SET fuel_type = ?, vehicle_type = ?, make = ?, model = ?, year = ?, odometer = ?
            WHERE user_id = ? AND registration = ?
        """, fuel_type, vehicle_type, make, model, year, odometer, user_id, registration)

        flash("Vehicle updated successfully!", "success")
        return redirect(url_for("garage"))

    return render_template("edit_vehicle.html", vehicle=vehicle, fuel_types=fuel_types,
                           vehicle_types=vehicle_types, years=years)
    

# ------------------------------------------------------------------
# Two-factor authentication
# ------------------------------------------------------------------
@app.route("/settings")
@login_required
def settings():
    """Settings page: appearance + account/security + data links"""
    user_id = session["user_id"]
    user = db.execute("SELECT * FROM users WHERE id = ?", user_id)[0]
    two_factor = bool(user.get("two_factor_enabled"))
    user_oidc = bool(int(user.get("oidc_enabled") or 0))
    return render_template(
        "settings.html",
        user=user,
        two_factor=two_factor,
        user_oidc_enabled=user_oidc,
        oidc_globally_enabled=OIDC_REGISTERED,
    )


@app.route("/account")
@login_required
def account():
    """Legacy alias so old links/bookmarks still work."""
    return redirect(url_for("settings"))


@app.route("/account/oidc/toggle", methods=["POST"])
@login_required
def account_oidc_toggle():
    """Toggle whether OIDC/Authentik login is preferred for this user"""
    user_id = session["user_id"]
    user = db.execute("SELECT oidc_enabled FROM users WHERE id = ?", user_id)[0]
    current = int(user.get("oidc_enabled") or 0)
    new_val = 1 if not current else 0
    db.execute("UPDATE users SET oidc_enabled = ? WHERE id = ?", str(new_val), user_id)
    flash(
        "Authentik login " + ("enabled." if new_val else "disabled."),
        "success",
    )
    return redirect(url_for("account"))


@app.route("/account/mfa", methods=["GET", "POST"])
@login_required
def account_mfa():
    user_id = session["user_id"]
    user = db.execute("SELECT * FROM users WHERE id = ?", user_id)[0]
    if request.method == "POST":
        secret = request.form.get("secret")
        code = request.form.get("code", "").strip().replace(" ", "")
        if user.get("two_factor_secret"):
            flash("Two-factor authentication is already enabled.", "info")
            return redirect(url_for("index"))
        if not secret:
            flash("Invalid setup.", "danger")
            return redirect(url_for("account_mfa"))
        totp = pyotp.TOTP(secret)
        if not totp.verify(code):
            flash("Invalid verification code.", "danger")
            uri = totp.provisioning_uri(name=user["username"], issuer_name="fLOGr")
            return render_template("mfa_setup.html", secret=secret, provisioning_uri=uri)
        recovery_codes = [secrets.token_hex(4).upper() for _ in range(10)]
        db.execute(
            "UPDATE users SET two_factor_secret = ?, two_factor_enabled = 1, recovery_codes = ? WHERE id = ?",
            secret,
            ",".join(recovery_codes),
            user_id,
        )
        # NOTE: TOTP secrets and recovery codes are stored plaintext.
        # For improved security, encrypt these fields at rest (e.g., via an
        # application-level encryption key or KMS) in a future iteration.
        flash("Two-factor authentication enabled.", "success")
        return render_template(
            "mfa_setup.html",
            secret=secret,
            recovery_codes=recovery_codes,
            done=True,
        )
    secret = pyotp.random_base32()
    totp = pyotp.TOTP(secret)
    uri = totp.provisioning_uri(name=user["username"], issuer_name="fLOGr")
    return render_template("mfa_setup.html", secret=secret, provisioning_uri=uri)

@app.route("/mfa", methods=["GET", "POST"])
def mfa_challenge():
    tmp = session.get("temp_user_id")
    if not tmp:
        return redirect(url_for("login"))
    user = db.execute("SELECT * FROM users WHERE id = ?", tmp)[0]
    if request.method == "POST":
        code = request.form.get("code", "").strip().replace(" ", "")
        recovery_code = request.form.get("recovery_code", "").strip().upper()
        if code:
            totp = pyotp.TOTP(user.get("two_factor_secret") or "")
            if totp.verify(code):
                session.clear()
                session["user_id"] = user["id"]
                db.execute(
                    "UPDATE users SET last_login = CURRENT_TIMESTAMP WHERE id = ?",
                    user["id"],
                )
                return redirect(url_for("index"))
        if recovery_code:
            stored = (user.get("recovery_codes") or "").split(",")
            if recovery_code in stored:
                stored.remove(recovery_code)
                db.execute(
                    "UPDATE users SET recovery_codes = ? WHERE id = ?",
                    ",".join(stored),
                    user["id"],
                )
                session.clear()
                session["user_id"] = user["id"]
                db.execute(
                    "UPDATE users SET last_login = CURRENT_TIMESTAMP WHERE id = ?",
                    user["id"],
                )
                flash("Logged in with recovery code. Consider generating new ones.", "warning")
                return redirect(url_for("index"))
        flash("Invalid verification code or recovery code.", "danger")
    return render_template("mfa_challenge.html")

@app.route("/account/mfa/disable", methods=["POST"])
@login_required
def disable_mfa():
    user_id = session["user_id"]
    code = request.form.get("code", "").strip().replace(" ", "")
    user = db.execute("SELECT two_factor_secret, id FROM users WHERE id = ?", user_id)[0]
    if not user.get("two_factor_secret"):
        return redirect(url_for("index"))
    totp = pyotp.TOTP(user["two_factor_secret"])
    if not totp.verify(code):
        flash("Invalid verification code.", "danger")
        return redirect(url_for("index"))
    db.execute(
        "UPDATE users SET two_factor_secret = NULL, two_factor_enabled = 0 WHERE id = ?",
        user_id,
    )
    flash("Two-factor authentication disabled.", "success")
    return redirect(url_for("account"))

if __name__ == "__main__":
    app.run(debug=True)
