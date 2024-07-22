import os

from cs50 import SQL
from flask import Flask, flash, redirect, render_template, request, session, url_for
from flask_session import Session
from werkzeug.security import check_password_hash, generate_password_hash
from email_validator import validate_email, EmailNotValidError
from datetime import date, datetime

from helpers import login_required

# Configure application
app = Flask(__name__)

app.secret_key = os.getenv('SECRET_KEY', 'default_secret_key')

# Configure session to use filesystem (instead of signed cookies)
app.config["SESSION_PERMANENT"] = False
app.config["SESSION_TYPE"] = "filesystem"
Session(app)

# Configure CS50 Library to use SQLite database
db = SQL("sqlite:///flogr.db")


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

        # Remember which user has logged in
        session["user_id"] = rows[0]["id"]

        # Update last_login in db
        db.execute("""
            UPDATE users
            SET last_login = CURRENT_TIMESTAMP
            WHERE id = ?
            """, session["user_id"])

        # Redirect user to home page after successful login
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

    return render_template("index.html", vehicles=vehicles, fuel_types=fuel_types, today_date=today_date)


@app.route("/new_record", methods=["POST"])
@login_required
def new_record():
    user_id = session["user_id"]
    registration = request.form.get("registration")
    fuel_code = request.form.get("fuel_type")
    receipt_number = request.form.get("receipt_number")
    purchased_at = request.form.get("purchased_at")
    litres = request.form.get("litres")
    price_per_litre = request.form.get("price_per_litre")
    kilometres = request.form.get("kilometres")
    comments = request.form.get("comments")
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

        # Insert into the database
        db.execute("""
            INSERT INTO log
                   (user_id,
                   fuel_code,
                   date,
                   registration,
                   receipt_number,
                   purchased_at,
                   litres,
                   price_per_litre,
                   sale_price,
                   kilometres,
                   comments)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, user_id, fuel_code, log_date, registration, receipt_number, purchased_at, litres, price_per_litre, sale_price, kilometres, comments)

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
    

if __name__ == "__main__":
    app.run(debug=True)
