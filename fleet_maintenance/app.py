from flask import Flask, render_template, request, redirect, url_for, session, flash
import sqlite3
import os
from uuid import uuid4
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename

app = Flask(__name__)
app.secret_key = "fleet-maintenance-secret-key"

DATABASE = "fleet.db"
UPLOAD_FOLDER = "static/uploads"

app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER

os.makedirs(UPLOAD_FOLDER, exist_ok=True)


# =========================
# DATABASE
# =========================

def get_db():
    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_db()

    conn.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL,
            name TEXT NOT NULL,
            role TEXT NOT NULL
        )
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS trucks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            truck_number TEXT NOT NULL,
            plate_number TEXT NOT NULL,
            driver_id INTEGER
        )
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS inspection_requests (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            truck_id INTEGER NOT NULL,
            driver_id INTEGER NOT NULL,
            date TEXT NOT NULL,
            mileage TEXT,
            issue TEXT NOT NULL,
            photo TEXT,
            status TEXT DEFAULT 'Pending'
        )
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS maintenance_records (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            request_id INTEGER NOT NULL,
            mechanic_id INTEGER NOT NULL,
            maintenance_date TEXT,
            notes TEXT,
            status TEXT DEFAULT 'In Maintenance'
        )
    """)

    # Default accounts
    admin_exists = conn.execute(
        "SELECT * FROM users WHERE username = ?",
        ("admin",)
    ).fetchone()

    if not admin_exists:
        conn.execute("""
            INSERT INTO users (username, password, name, role)
            VALUES (?, ?, ?, ?)
        """, (
            "admin",
            generate_password_hash("admin123"),
            "System Administrator",
            "admin"
        ))

    mechanic_exists = conn.execute(
        "SELECT * FROM users WHERE username = ?",
        ("mechanic",)
    ).fetchone()

    if not mechanic_exists:
        conn.execute("""
            INSERT INTO users (username, password, name, role)
            VALUES (?, ?, ?, ?)
        """, (
            "mechanic",
            generate_password_hash("mechanic123"),
            "Main Mechanic",
            "mechanic"
        ))

    driver_exists = conn.execute(
        "SELECT * FROM users WHERE username = ?",
        ("driver",)
    ).fetchone()

    if not driver_exists:
        conn.execute("""
            INSERT INTO users (username, password, name, role)
            VALUES (?, ?, ?, ?)
        """, (
            "driver",
            generate_password_hash("driver123"),
            "Truck Driver",
            "driver"
        ))

    # Sample truck
    truck_exists = conn.execute(
        "SELECT * FROM trucks"
    ).fetchone()

    if not truck_exists:
        driver = conn.execute(
            "SELECT id FROM users WHERE username = ?",
            ("driver",)
        ).fetchone()

        conn.execute("""
            INSERT INTO trucks
            (truck_number, plate_number, driver_id)
            VALUES (?, ?, ?)
        """, (
            "TRK-001",
            "ABC-1234",
            driver["id"]
        ))

    conn.commit()
    conn.close()


# =========================
# HELPERS
# =========================

def save_photo(file):
    """Store an uploaded image and return its filename.

    A short random prefix is added so two uploads that share an
    original filename (e.g. photo.jpg) cannot overwrite each other.
    """

    if not file or not file.filename:
        return None

    original = secure_filename(file.filename)

    if not original:
        return None

    stored = f"{uuid4().hex[:8]}_{original}"

    file.save(os.path.join(app.config["UPLOAD_FOLDER"], stored))

    return stored


# =========================
# LOGIN
# =========================

@app.route("/", methods=["GET", "POST"])
def login():

    if request.method == "POST":

        username = request.form["username"]
        password = request.form["password"]

        conn = get_db()

        user = conn.execute(
            "SELECT * FROM users WHERE username = ?",
            (username,)
        ).fetchone()

        conn.close()

        if user and check_password_hash(user["password"], password):

            session["user_id"] = user["id"]
            session["name"] = user["name"]
            session["role"] = user["role"]

            return redirect(url_for("dashboard"))

        flash("Invalid username or password.", "error")

    return render_template("login.html")


# =========================
# REGISTER
# =========================

@app.route("/register", methods=["GET", "POST"])
def register():

    if request.method == "POST":

        name = request.form["name"]
        username = request.form["username"]
        password = request.form["password"]
        role = request.form["role"]

        if role not in ["driver", "mechanic"]:
            flash("Invalid account type.", "error")
            return redirect(url_for("register"))

        conn = get_db()

        try:

            conn.execute("""
                INSERT INTO users
                (username, password, name, role)
                VALUES (?, ?, ?, ?)
            """, (
                username,
                generate_password_hash(password),
                name,
                role
            ))

            conn.commit()

            flash("Account created successfully. You can now login.", "success")

            return redirect(url_for("login"))

        except sqlite3.IntegrityError:

            flash("Username already exists.", "error")

        finally:

            conn.close()

    return render_template("register.html")


# =========================
# DASHBOARD
# =========================

@app.route("/dashboard")
def dashboard():

    if "user_id" not in session:
        return redirect(url_for("login"))

    conn = get_db()

    total_trucks = conn.execute(
        "SELECT COUNT(*) FROM trucks"
    ).fetchone()[0]

    pending_requests = conn.execute(
        "SELECT COUNT(*) FROM inspection_requests WHERE status = 'Pending'"
    ).fetchone()[0]

    maintenance_count = conn.execute(
        "SELECT COUNT(*) FROM inspection_requests WHERE status = 'In Maintenance'"
    ).fetchone()[0]

    completed_count = conn.execute(
        "SELECT COUNT(*) FROM inspection_requests WHERE status = 'Completed'"
    ).fetchone()[0]

    cancelled_count = conn.execute(
        "SELECT COUNT(*) FROM inspection_requests WHERE status = 'Cancelled'"
    ).fetchone()[0]

    conn.close()

    return render_template(
        "dashboard.html",
        total_trucks=total_trucks,
        pending_requests=pending_requests,
        maintenance_count=maintenance_count,
        completed_count=completed_count,
        cancelled_count=cancelled_count
    )


# =========================
# DRIVER INSPECTION
# =========================

@app.route("/inspection", methods=["GET", "POST"])
def inspection():

    if "user_id" not in session:
        return redirect(url_for("login"))

    if session["role"] != "driver":
        flash("Only drivers can submit inspection requests.", "error")
        return redirect(url_for("dashboard"))

    conn = get_db()

    truck = conn.execute("""
        SELECT * FROM trucks
        WHERE driver_id = ?
    """, (session["user_id"],)).fetchone()

    if request.method == "POST":

        date = request.form["date"]
        mileage = request.form["mileage"]
        issue = request.form["issue"]

        photo_name = save_photo(request.files.get("photo"))

        conn.execute("""
            INSERT INTO inspection_requests
            (truck_id, driver_id, date, mileage, issue, photo)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (
            truck["id"],
            session["user_id"],
            date,
            mileage,
            issue,
            photo_name
        ))

        conn.commit()
        conn.close()

        flash("Inspection request submitted successfully.", "success")

        return redirect(url_for("dashboard"))

    conn.close()

    return render_template(
        "inspection.html",
        truck=truck
    )


# =========================
# REQUESTS
# =========================

@app.route("/requests")
def requests():

    if "user_id" not in session:
        return redirect(url_for("login"))

    conn = get_db()

    if session["role"] == "driver":

        requests = conn.execute("""
            SELECT
                inspection_requests.*,
                trucks.truck_number,
                trucks.plate_number
            FROM inspection_requests
            JOIN trucks
            ON inspection_requests.truck_id = trucks.id
            WHERE inspection_requests.driver_id = ?
            ORDER BY inspection_requests.id DESC
        """, (session["user_id"],)).fetchall()

    else:

        requests = conn.execute("""
            SELECT
                inspection_requests.*,
                trucks.truck_number,
                trucks.plate_number,
                users.name AS driver_name
            FROM inspection_requests
            JOIN trucks
            ON inspection_requests.truck_id = trucks.id
            JOIN users
            ON inspection_requests.driver_id = users.id
            ORDER BY inspection_requests.id DESC
        """).fetchall()

    conn.close()

    return render_template(
        "requests.html",
        requests=requests
    )


# =========================
# ACCEPT MAINTENANCE
# =========================

@app.route("/accept/<int:request_id>", methods=["POST"])
def accept_request(request_id):

    if "user_id" not in session:
        return redirect(url_for("login"))

    if session["role"] != "mechanic":
        flash("Only mechanics can accept requests.", "error")
        return redirect(url_for("requests"))

    conn = get_db()

    item = conn.execute(
        "SELECT status FROM inspection_requests WHERE id = ?",
        (request_id,)
    ).fetchone()

    if not item or item["status"] != "Pending":
        conn.close()
        flash("Only pending requests can be accepted.", "error")
        return redirect(url_for("requests"))

    conn.execute("""
        UPDATE inspection_requests
        SET status = 'In Maintenance'
        WHERE id = ?
    """, (request_id,))

    conn.execute("""
        INSERT INTO maintenance_records
        (request_id, mechanic_id, maintenance_date, notes, status)
        VALUES (?, ?, date('now'), ?, ?)
    """, (
        request_id,
        session["user_id"],
        "Maintenance request accepted.",
        "In Maintenance"
    ))

    conn.commit()
    conn.close()

    flash("Maintenance request accepted.", "success")

    return redirect(url_for("requests"))


# =========================
# COMPLETE MAINTENANCE
# =========================

@app.route("/complete/<int:request_id>", methods=["POST"])
def complete_request(request_id):

    if "user_id" not in session:
        return redirect(url_for("login"))

    if session["role"] != "mechanic":
        return redirect(url_for("requests"))

    notes = request.form.get("notes", "")

    conn = get_db()

    item = conn.execute(
        "SELECT status FROM inspection_requests WHERE id = ?",
        (request_id,)
    ).fetchone()

    if not item or item["status"] != "In Maintenance":
        conn.close()
        flash("Only requests in maintenance can be completed.", "error")
        return redirect(url_for("requests"))

    conn.execute("""
        UPDATE inspection_requests
        SET status = 'Completed'
        WHERE id = ?
    """, (request_id,))

    conn.execute("""
        UPDATE maintenance_records
        SET status = 'Completed',
            notes = ?
        WHERE request_id = ?
    """, (
        notes,
        request_id
    ))

    conn.commit()
    conn.close()

    flash("Maintenance marked as completed.", "success")

    return redirect(url_for("requests"))


# =========================
# DRIVER TRUCK DETAILS
# =========================

@app.route("/truck", methods=["GET", "POST"])
def truck():

    if "user_id" not in session:
        return redirect(url_for("login"))

    if session["role"] != "driver":
        flash("Only drivers can edit their truck details.", "error")
        return redirect(url_for("dashboard"))

    conn = get_db()

    truck = conn.execute(
        "SELECT * FROM trucks WHERE driver_id = ?",
        (session["user_id"],)
    ).fetchone()

    if request.method == "POST":

        truck_number = request.form["truck_number"].strip()
        plate_number = request.form["plate_number"].strip()

        if not truck:
            flash("No truck is assigned to your account yet.", "error")

        elif not truck_number or not plate_number:
            flash("Truck number and plate number are both required.", "error")

        else:
            conn.execute("""
                UPDATE trucks
                SET truck_number = ?,
                    plate_number = ?
                WHERE id = ? AND driver_id = ?
            """, (
                truck_number,
                plate_number,
                truck["id"],
                session["user_id"]
            ))

            conn.commit()
            conn.close()

            flash("Truck details updated.", "success")

            return redirect(url_for("truck"))

    conn.close()

    return render_template("truck.html", truck=truck)


# =========================
# ADMIN EDIT REQUEST
# =========================

@app.route("/admin/request/<int:request_id>/edit", methods=["GET", "POST"])
def edit_request(request_id):

    if "user_id" not in session:
        return redirect(url_for("login"))

    if session["role"] != "admin":
        flash("Only administrators can edit requests.", "error")
        return redirect(url_for("requests"))

    conn = get_db()

    item = conn.execute(
        "SELECT * FROM inspection_requests WHERE id = ?",
        (request_id,)
    ).fetchone()

    if not item:
        conn.close()
        flash("Request not found.", "error")
        return redirect(url_for("requests"))

    if request.method == "POST":

        truck_id = request.form["truck_id"]
        date = request.form["date"].strip()
        mileage = request.form["mileage"].strip()
        issue = request.form["issue"].strip()

        valid_truck = conn.execute(
            "SELECT id FROM trucks WHERE id = ?",
            (truck_id,)
        ).fetchone()

        if not date or not issue:
            flash("Date and issue description are both required.", "error")

        elif not valid_truck:
            flash("Please choose a valid truck.", "error")

        else:
            new_photo = save_photo(request.files.get("photo"))

            if new_photo:
                conn.execute("""
                    UPDATE inspection_requests
                    SET truck_id = ?,
                        date = ?,
                        mileage = ?,
                        issue = ?,
                        photo = ?
                    WHERE id = ?
                """, (
                    truck_id,
                    date,
                    mileage,
                    issue,
                    new_photo,
                    request_id
                ))
            else:
                conn.execute("""
                    UPDATE inspection_requests
                    SET truck_id = ?,
                        date = ?,
                        mileage = ?,
                        issue = ?
                    WHERE id = ?
                """, (
                    truck_id,
                    date,
                    mileage,
                    issue,
                    request_id
                ))

            conn.commit()
            conn.close()

            flash("Request updated.", "success")

            return redirect(url_for("requests"))

    trucks = conn.execute(
        "SELECT * FROM trucks ORDER BY truck_number"
    ).fetchall()

    driver = conn.execute(
        "SELECT name FROM users WHERE id = ?",
        (item["driver_id"],)
    ).fetchone()

    conn.close()

    return render_template(
        "request_edit.html",
        item=item,
        trucks=trucks,
        driver_name=driver["name"] if driver else "Unknown"
    )


# =========================
# ADMIN CANCEL / REOPEN
# =========================

@app.route("/admin/request/<int:request_id>/cancel", methods=["POST"])
def cancel_request(request_id):

    if "user_id" not in session:
        return redirect(url_for("login"))

    if session["role"] != "admin":
        flash("Only administrators can cancel requests.", "error")
        return redirect(url_for("requests"))

    conn = get_db()

    item = conn.execute(
        "SELECT status FROM inspection_requests WHERE id = ?",
        (request_id,)
    ).fetchone()

    if not item:
        conn.close()
        flash("Request not found.", "error")
        return redirect(url_for("requests"))

    if item["status"] == "Completed":
        conn.close()
        flash("Completed requests cannot be cancelled.", "error")
        return redirect(url_for("requests"))

    conn.execute("""
        UPDATE inspection_requests
        SET status = 'Cancelled'
        WHERE id = ?
    """, (request_id,))

    conn.execute("""
        UPDATE maintenance_records
        SET status = 'Cancelled'
        WHERE request_id = ?
    """, (request_id,))

    conn.commit()
    conn.close()

    flash("Request cancelled. It no longer appears in the mechanic queue.", "success")

    return redirect(url_for("requests"))


@app.route("/admin/request/<int:request_id>/reopen", methods=["POST"])
def reopen_request(request_id):

    if "user_id" not in session:
        return redirect(url_for("login"))

    if session["role"] != "admin":
        flash("Only administrators can reopen requests.", "error")
        return redirect(url_for("requests"))

    conn = get_db()

    item = conn.execute(
        "SELECT status FROM inspection_requests WHERE id = ?",
        (request_id,)
    ).fetchone()

    if not item:
        conn.close()
        flash("Request not found.", "error")
        return redirect(url_for("requests"))

    if item["status"] != "Cancelled":
        conn.close()
        flash("Only cancelled requests can be reopened.", "error")
        return redirect(url_for("requests"))

    conn.execute("""
        UPDATE inspection_requests
        SET status = 'Pending'
        WHERE id = ?
    """, (request_id,))

    # Drop the abandoned repair so accepting again starts a clean record.
    conn.execute("""
        DELETE FROM maintenance_records
        WHERE request_id = ?
    """, (request_id,))

    conn.commit()
    conn.close()

    flash("Request reopened and returned to pending.", "success")

    return redirect(url_for("requests"))


# =========================
# LOGOUT
# =========================

@app.route("/logout")
def logout():

    session.clear()

    return redirect(url_for("login"))


# =========================
# RUN APPLICATION
# =========================

if __name__ == "__main__":

    init_db()

    app.run(
        debug=True
    )
