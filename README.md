# fLOGr

## Video Demo: <https://youtu.be/Uuhjj5j36YQ>

## docker-compose.yml
```yml
services:
  flogr:
    image: docker.io/thatbutcherguy/flogr-docker:latest
    container_name: flogr
    ports:
      - "15001:8080" # Map port 15001 on the host to 8080 in the container
    volumes:
      - /mnt/tank/appdata/flogr/data:/flask-app/data # Persist database
    environment:
      - FLASK_ENV=production # Optional: Set environment variables as needed
      - DATABASE_PATH=/flask-app/data/flogr.db
      - PUID=568
      - PGID=568
      - TZ=Australia/Canberra
      # Optional: Authentik OIDC — set these to enable SSO login
      # - AUTHENTIK_CLIENT_ID=********
      # - AUTHENTIK_CLIENT_SECRET=********
      # - AUTHENTIK_ISSUER_URL=https://auth.example.com/application/o/flogr/
    restart: unless-stopped # Ensure the container restarts automatically unless explicitly stopped
    networks:
      - flogr # Attach the service to the custom network

networks:
  flogr:
    external: true  # Use the existing external network
```

## Description

fLOGr is a web-based fuel logging application intended to capture data from the pump each refuel of your vehicle. This data is stored into a SQLite3 database with Python crunching the data to be displayed in fLOGr using Flask and Jinga.

fLOGr has been developed by Brenden Taylor (GitHub user: ThatButcherGuy) as the final project for the Harvard CS50x class of 2024.

### Theming & Branding

- **Light / dark / auto themes** — the navbar 🌙/☀️/🖥️ toggle cycles Light, Dark and Auto (follows your system). Manage it from **Settings**. Your choice is saved in `localStorage` (`flogr-theme`) and remembered across sessions; the saved theme is applied before page render to avoid a flash of the wrong theme.

---

### Authentication

fLOGr supports two authentication methods, switchable in the **Settings** page (`/settings`):

| Method | Description |
|--------|-------------|
| **Password login** | Default — username + password, hashed with Werkzeug |
| **Authentik (OIDC)** | SSO via Authentik — optional, configured via environment variables |

#### Login Fallback Order

1. **Authentik (OIDC)** — preferred when enabled and available
2. **Password + 2FA** — fallback if Authentik is offline
3. **Password only** — if 2FA is disabled

If Authentik is unreachable, the login page shows a clear warning and the user can use their password instead.

#### Two-Factor Authentication (TOTP)

Users can enable TOTP-based 2FA from the Settings page:

1. Navigate to **Settings** in the navbar
2. Click **Enable Two-Factor Authentication**
3. Scan the secret into your authenticator app (Authy, Google Authenticator, 1Password, etc.)
4. Enter the verification code to confirm
5. **Save the 10 recovery codes** — each can be used once if you lose access to your authenticator app

Users with 2FA enabled will be prompted for a TOTP code after entering their password. 2FA is only enforced for password login — Authentik handles its own MFA.

#### Settings Page

The `/settings` page (linked in the navbar when logged in) shows:

- Username and email
- Authentik (OIDC) status — enable/disable per-user
- Two-Factor Authentication status — enable/disable
- Login fallback order explanation
- Quick-action buttons for enabling/disabling 2FA and logging in via Authentik

---

### Login

This is the first landing page for fLOGr.

Existing users can enter their credentials to gain access to their account. Credentials are validated against the database and, if successful, the user is granted access and user session information is stored in the cookie. If the validation is not successful, then an error message is displayed, and the user is prompted to try again. This incorporates client-side and server-side validation.

The Login page and route have been adapted from the CS50x Finance problem set. A register button has been added for new users and JavaScript has been included to ensure that the username is always entered in lowercase. The decision to force lowercase was a learning moment for myself as I wanted to understand how JavaScript could be implemented to achieve this. It also allows the data to be easily validated prior to being stored in the database. It is likely that this feature will be removed in a future iteration in favour of a smoother user experience that gives more freedom to the user.

---

### Register

The Register page allows new users to register for fLOGr. The validation of this data occurs similarly to the Login page however instead of comparing against the database, once validated the data is committed to the database as a new user.

#### Add New Vehicle

When a user registers, they are redirected to the `add_vehicle` page. Adding a vehicle to the users Garage is required to utilise the functionality of fLOGr.

##### Fields

Registration:
This is the registration number for the vehicle.

The registration field is used as the unique identifier for each vehicle in the users Garage.

- Requirements
  - `VARCHAR(10) NOT NULL UNIQUE`

Fuel Type:

This is the fuel type default for the vehicle. This will determine what the default value is applied when entering a new fuel record.

The fuel type consists of a `code` and a `name`. The code is unique for each fuel type.

This is a predetermined list of fuel types:

- `DL`: `Diesel`
- `U91`: `Unleaded 91`
- `U95`: `Unleaded 95`
- `P98`: `Premium 98`
- `LPG`: `LPG`
- `E10`: `Ethanol`
- `OTHER`: `Other`

Select the fuel type from the dropdown menu.

- Requirements
  - Not editable by the user.

Vehicle Type:

This is the type of vehicle the user is adding to their Garage.

This is a predetermined list of vehicle types:

- Car
- 4wd
- Truck
- Motorcycle
- Hot Air Balloon
- Aircraft
- Boat
- Other

Select the vehicle type from the dropdown menu.

- Requirements
  - Not editable by the user.

Make:

This is the make or manufacturer of the vehicle.

- Requirements
  - `VARCHAR(20) NOT NULL`

Model:

This is the model of the vehicle.

- Requirements
  - `VARCHAR(20) NOT NULL`

Year:

This is the year of manufacture of the vehicle.

- Requirements
  - `INTEGER NOT NULL`

Odometer:

This is the current odometer reading of the vehicle. The displayed unit of measure is currently kilometres.

This cannot be less than or equal to zero.

- Requirements
  - `INTEGER NOT NULL CHECK (odometer >= 0)`

---

### Enter a Record (Index Page)

This is the Index page for fLOGr. If a current user logs in, they are then directed to this page. This allows fast access to be able to enter a fuel record while on the go.

**For the maths to work with the data logging, users need to ensure that they fill the tank up to the same level each refuel. It is reccommended to fill each tank to the fullest possible point as this is very repeatable.**

**It is important to ensure that there is no missing data. fLOGr requires every refuel for a vehicle to be logged to maintain data accuracy. If details of a refuel are lost before logging, a near enough guess is better than not logging anything at all.**

#### Fields

Select Vehicle:

This is a dropdown menu of vehicles in the users Garage. The user must select the vehicle for this fuel log.

- Requirements
  - Not editable by the user.

Fuel Type:

This field is defaults to the fuel recorded against the selected vehicle. This can be changed to any other fuel using the dropdown menu. This allows for dual fuel vehicles or different grades of unleaded fuel to be logged to one vehicle.

- Requirements
  - Not editable by the user.

Date:

This is the date the transaction takes place. This date cannot be in the future and defaults to today's date.

- Requirements
  - `DATE NOT NULL`

Receipt Number:

This is the receipt number off the receipt for the sale.

This field is optional.

- Requirements
  - `VARCHAR(50)`

Purchased At:

This is the location the fuel was purchased at, shown as `Retailer Suburb` (e.g. `Costco Majura`).

Locations are managed in a **user-editable location database** (see the *Locations* page). Choose an existing location from the dropdown, or add a new one inline without losing the rest of the form. Storing each purchase as a reusable location keeps data consistent (one value per store) and enables per-location statistics in future versions.

This field is optional.

- Requirements
  - `retailer VARCHAR(100)` + `suburb VARCHAR(100)` in the `locations` table
  - `log.location_id` references the chosen `locations.id`

Litres:

This is the amount of litres purchased to two decimal places i.e. 128.68 Litres.

This cannot be less than or equal to zero.

- Requirements
  - `DECIMAL(6,2) NOT NULL CHECK (litres >= 0)`

Price Per Litre:

This is the price per litre paid for the fuel. This value must include any discounts received at checkout to maintain data accuracy.

The format for this value is to three decimal places i.e. $1.897 which represents 1 dollar, 89 cents decimal 7.

This cannot be less than or equal to zero.

- Requirements
  - `DECIMAL(5,3) NOT NULL CHECK (price_per_litre >= 0)`

Kilometres:

This is the amount of kilometres travelled for the vehicle with the previous tank of fuel.

This value needs to be rounded by the user to the nearest whole number. This value is added to the vehicles Odometer value.

This cannot be less than or equal to zero.

- Requirements
  - `INTEGER NOT NULL CHECK (kilometres >= 0)`

Comments:

This is a free text field for the user to add any comments relating to this log, for example, the type of driving that occurred immediately prior to this fill up or any changes made to the vehicle that could affect fuel consumption.

This field is optional.

- Requirements
  - `VARCHAR(150)`

  ---

### View Log

The View Log page allows the user to view all logs made on their account. This defaults to sorting descending from the newest log entered.

This table can be sorted by any column and can also be filtered by vehicles in your Garage. If there is no log available for a selected vehicle the user will be presented an error message to try again with a different vehicle.

The View Log page contains two calculated fields:

- Sale Price = Price Per Litre x Litres
- Litres per 100km (L/100km) = (Litres / Kilometres) x 100

---

### Stats

The Stats page contains read-only statistics generated from the user's logs, presented as summary cards plus tables.

The **Last Fill** card block summarises the most recent log entry (date, days since, economy, price, cost, location).

The **Global Stats** table summarises all logs made by the user across all vehicles in their Garage (total spend, litres, distance, averages, and combined L/100km).

The **Vehicle Comparison** section compares each vehicle's fuel economy (L/100km), cost per 100km, and average range per tank.

The **Fuel Price History** section shows the average $/L per year, highlighting your cheapest and most expensive years.

The **Location Insights** section shows your most-spent-at location and the cheapest average $/L location.

The **Monthly Spend** section shows the last 12 months of total spend as a bar summary.

The **Vehicles** table lists the vehicles in your Garage where the user can dive into more detailed statistics per vehicle.

### Reports

The **Reports** page (linked in the navbar, and via "Open Reports &amp; Charts" on the Stats page) provides **interactive, graphical** analysis of your logs using Chart.js:

- **Filters** — by vehicle, location, and a from/to date range. Charts and summary cards update instantly (client-side).
- **Fuel economy (L/100km)** and **price-per-litre** over time (monthly-aggregated line charts)
- **Litres purchased** over time (bar chart)
- **Spend by location** (doughnut chart)
- **Fuel price history** — average $/L by year (bar chart)
- **Monthly spend** — last 12 months (bar chart)
- **Vehicle comparison** — economy and cost/100km side by side (bar chart)
- **Summary cards** — total spend, litres, distance, average economy, average price, avg cost/tank, cost per 100km

Data is served from the `/api/stats` JSON endpoint.

#### Vehicle Stats

The Vehicle Stats page is accessed by clicking on the registration link on the Stats page. This allows the user to dive deeper into the log statistics for specific vehicles.

There are three tables on the Vehicle Stats page.

The Vehicle Details table contains the details of the selected vehicle including the current calculated odometer.

The Vehicle Stats table briefly summarises all logs made for the selected vehicle. This table can be filtered to a desired date range so the user can analyse their fuel usage for the selected vehicle.

The Recent Log table shows the last 20 log entries for the selected vehicle.

---

### Garage

The Garage page show information on the vehicles currently in the users Garage.

This is also where the user can add a new vehicle to their Garage.

On smaller devices, the table on the Garage page will not show all the available information for each vehicle.

Clicking on the Registration will take the user to the vehicle details page.

#### Vehicle Details

The Vehicle Details page will display all the information recorded against the selected vehicle.

This page is useful for users on a smaller device where the Garage page does not show all the information in the table.

The Vehicle Details page can be accessed by clicking on the Registration of the desired vehicle on the Garage page.

---

### SQLite3 Database Structure

The SQLite3 Database contains five tables:

- `users`
- `fuel_types`
- `vehicles`
- `log`
- `locations`

`users`:

This table contains an `id` field to uniquely identify all `users` who register on fLOGr. This `id` is used across the `vehicles` and `log` tables to ensure the correct data is displayed for the logged in user.

Auth-related columns added in v2.1:
  - `two_factor_secret` — TOTP secret key (set when 2FA is enabled)
  - `two_factor_enabled` — `1` if 2FA is active, `NULL` otherwise
  - `recovery_codes` — comma-separated recovery codes (10 codes, each usable once)
  - `oidc_enabled` — `1` if the user has Authentik/OIDC login enabled, `0` otherwise

`fuel_types`:

This table contains the `code` and `name` of fuel types used in fLOGr. The `code` column is a key used in the `vehicles` and `log` tables and allows looking up of the name or description of the fuel used across fLOGr.

`vehicles`:

This table contains the details of each vehicle in the users garage. the `odometer` value is updated with each log. Each entry is linked to a `user_id` and `fuel_type` `FOREIGN KEY`

`log`:

This table is where most data is stored for fLOGr and contains every logged record made on the Enter a Record (Index) page.

Each entry is linked back to a vehicle `registration` and `user_id`.

The `location_id` column references the `locations` table (added in the location-database feature). Displayed location names are resolved from `locations` so renaming a location propagates to existing log entries.

`locations`:

This table stores the user-managed purchase locations as `retailer` + `suburb` (displayed as `Retailer Suburb`, e.g. `Costco Majura`). Each location is owned by a `user_id`. Log rows reference a location via `log.location_id`; deleting a location that is still referenced by log rows is blocked.

---

### Future Enhancements (wish list)

- Force login password requirements for account security.
- Create viewable/editable user accounts.
  - Incorporate the use of email and the `is_active` field in the users db table.
  - Consider email notifications and marketing.
  - Allow users to be able to reset their password.
  - Add a `forgot password` feature.
- *✅ Allow users to edit and delete records they have logged.*
- *✅ Allow users to edit and delete vehicles in their Garage.*
- Export logs
  - *✅ Allow users to be able to export their logs as `.csv` data file.*
  - Consider allowing users to export their log into a formatted `.pdf` file.
  - *✅ Allow users to be able to filter their logs by date or registration (or other fields) before exporting.*
  - Consider `.pdf` exports of reports that contain infographs and stats.
- Unit of measure (UoM)
  - UoM to consider:
    - Kilometres
    - Miles
    - Hours/Minutes
    - Litres
    - Gallons
    - L/100km
    - MPG
    - Dollars
    - Other currencies?
- Auto rounding of Kilometres when creating a log.
- Data Analysis
  - Consider diving deeper into the data collected in the logs e.g. what is the most frequented location?, Which location consistently has the better price? etc.
  - Consider adding graphs of price per litre, L/100km and kilometres travelled to help show trends and better inform the user.
  - Implement a vehicle comparison tool to allow users to compare statistics between the vehicles in their Garage.
- Consider adding a service module to track vehicle servicing.
- Vehicle profiles
  - Consider building out the vehicle profiles to include additions for modified vehicles i.e. 4wd mods like winch, driving lights radios etc. Incldue date of install.
  - Consider adding a picture gallery so users can document their vehicles.
  - This logged information could assist with insurance claims if required.


