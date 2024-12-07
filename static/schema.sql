-- Create the users table
CREATE TABLE users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username VARCHAR(50) NOT NULL UNIQUE,
    email VARCHAR(100) NOT NULL UNIQUE,
    password_hash VARCHAR(255) NOT NULL,
    first_name VARCHAR(50),
    last_name VARCHAR(50),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    last_login TIMESTAMP,
    is_active BOOLEAN DEFAULT TRUE,
    role TEXT CHECK (role IN ('user', 'admin')) DEFAULT 'user'
);


-- Create the fuel_types table
CREATE TABLE fuel_types (
    code VARCHAR(10) PRIMARY KEY,
    name VARCHAR(50) NOT NULL UNIQUE
);


-- Create the vehicles table
CREATE TABLE vehicles (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    registration VARCHAR(10) NOT NULL UNIQUE,
    fuel_type VARCHAR(10),
    vehicle_type VARCHAR(20) NOT NULL,
    make VARCHAR(20) NOT NULL,
    model VARCHAR(20) NOT NULL,
    year INTEGER NOT NULL,
    odometer INTEGER NOT NULL CHECK (odometer >= 0),
    FOREIGN KEY (user_id) REFERENCES users(id),
    FOREIGN KEY (fuel_type) REFERENCES fuel_types(code)
);


-- Create the log table
CREATE TABLE log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    fuel_code VARCHAR(10),
    date DATE NOT NULL,
    registration VARCHAR(10) NOT NULL,
    receipt_number VARCHAR(50),
    purchased_at VARCHAR(50),
    litres DECIMAL(6,2) NOT NULL CHECK (litres >= 0),
    price_per_litre DECIMAL(5,3) NOT NULL CHECK (price_per_litre >= 0),
    sale_price DECIMAL(6,2) NOT NULL CHECK (sale_price >= 0),
    kilometres INTEGER NOT NULL CHECK (kilometres >= 0),
    comments VARCHAR(150),
    FOREIGN KEY (user_id) REFERENCES users(id),
    FOREIGN KEY (fuel_code) REFERENCES fuel_types(code),
    FOREIGN KEY (registration) REFERENCES vehicles(registration)
);


INSERT INTO fuel_types (code, name) VALUES 
('DL', 'Diesel'),
('U91', 'Unleaded 91'),
('U95', 'Unleaded 95'),
('P98', 'Premium 98'),
('LPG', 'LPG'),
('E10', 'Ethanol');