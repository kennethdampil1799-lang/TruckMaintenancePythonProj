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

# Maximum number of photos a driver can attach to one inspection request.
MAX_PHOTOS = 5

app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER
app.config["MAX_CONTENT_LENGTH"] = 5 * 1024 * 1024 * MAX_PHOTOS

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
        CREATE TABLE IF NOT EXISTS request_photos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            request_id INTEGER NOT NULL,
            filename TEXT NOT NULL,
            position INTEGER NOT NULL DEFAULT 0
        )
    """)

    # Move photos from the original single-photo column into the new table
    legacy_photos = conn.execute("""
        SELECT id, photo FROM inspection_requests
        WHERE photo IS NOT NULL AND photo != ''
    """).fetchall()

    for row in legacy_photos:
        already_moved = conn.execute("""
            SELECT 1 FROM request_photos
            WHERE request_id = ? AND filename = ?
        """, (row["id"], row["photo"])).fetchone()

        if not already_moved:
            conn.execute("""
                INSERT INTO request_photos (request_id, filename, position)
                VALUES (?, ?, 0)
            """, (row["id"], row["photo"]))

    conn.execute("""
        CREATE TABLE IF NOT EXISTS notifications (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            request_id INTEGER,
            title TEXT NOT NULL,
            body TEXT,
            created_at TEXT,
            is_read INTEGER DEFAULT 0
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


def save_photos(files, existing_count=0):
    """Store several uploaded images and return the saved filenames.

    At most MAX_PHOTOS images are kept per request, counting the photos
    already attached. Extra files are ignored rather than rejected, so
    an oversized selection still submits with the first MAX_PHOTOS.
    """

    room = MAX_PHOTOS - existing_count

    if room <= 0:
        return []

    saved = []

    for file in files[:room]:
        stored = save_photo(file)

        if stored:
            saved.append(stored)

    return saved


def replace_photos(conn, request_id, files):
    """Swap a request's photos for a new upload, returning the new count."""

    new_photos = save_photos(files)

    if not new_photos:
        return False

    conn.execute(
        "DELETE FROM request_photos WHERE request_id = ?",
        (request_id,)
    )

    conn.executemany("""
        INSERT INTO request_photos (request_id, filename, position)
        VALUES (?, ?, ?)
    """, [
        (request_id, name, position)
        for position, name in enumerate(new_photos)
    ])

    return True


def get_photos(conn, request_id):
    """Return the stored photo filenames for one request, in order."""

    rows = conn.execute("""
        SELECT filename FROM request_photos
        WHERE request_id = ?
        ORDER BY position, id
    """, (request_id,)).fetchall()

    return [row["filename"] for row in rows]


def send_receipt(conn, request_id, notes):
    """Create a completion receipt for the driver who filed the request.

    The receipt records the truck, the work that was carried out, and the
    date it was closed out so the driver can read it back later.
    """

    row = conn.execute("""
        SELECT
            inspection_requests.driver_id,
            inspection_requests.issue,
            trucks.truck_number,
            trucks.plate_number
        FROM inspection_requests
        JOIN trucks ON inspection_requests.truck_id = trucks.id
        WHERE inspection_requests.id = ?
    """, (request_id,)).fetchone()

    if not row:
        return False

    work = (notes or "").strip() or "No maintenance note was recorded."

    conn.execute("""
        INSERT INTO notifications
        (user_id, request_id, title, body, created_at, is_read)
        VALUES (?, ?, ?, ?, date('now'), 0)
    """, (
        row["driver_id"],
        request_id,
        f"Maintenance complete — {row['truck_number']}",
        f"Your truck {row['truck_number']} "
        f"({row['plate_number']}) has finished its maintenance.\n\n"
        f"Reported issue: {row['issue']}\n"
        f"Work carried out: {work}\n\n"
        "The vehicle is ready to return to service.",
    ))

    return True


def mark_receipts_read(conn, user_id):
    """Mark a driver's receipts as read."""

    conn.execute("""
        UPDATE notifications
        SET is_read = 1
        WHERE user_id = ? AND is_read = 0
    """, (user_id,))


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

    # Drivers only ever see figures for their own requests, never the
    # whole fleet's workload.
    if session["role"] == "driver":

        scope_sql = "WHERE driver_id = ?"
        scope_args = (session["user_id"],)

        total_trucks = conn.execute(
            "SELECT COUNT(*) FROM trucks WHERE driver_id = ?",
            (session["user_id"],)
        ).fetchone()[0]

    else:

        scope_sql = ""
        scope_args = ()

        total_trucks = conn.execute(
            "SELECT COUNT(*) FROM trucks"
        ).fetchone()[0]

    def status_count(status):
        if scope_sql:
            return conn.execute(
                f"SELECT COUNT(*) FROM inspection_requests "
                f"{scope_sql} AND status = ?",
                (*scope_args, status)
            ).fetchone()[0]

        return conn.execute(
            "SELECT COUNT(*) FROM inspection_requests WHERE status = ?",
            (status,)
        ).fetchone()[0]

    pending_requests = status_count("Pending")
    maintenance_count = status_count("In Maintenance")
    completed_count = status_count("Completed")
    cancelled_count = status_count("Cancelled")

    receipts = conn.execute("""
        SELECT
            notifications.*,
            trucks.truck_number,
            trucks.plate_number
        FROM notifications
        LEFT JOIN inspection_requests
        ON notifications.request_id = inspection_requests.id
        LEFT JOIN trucks
        ON inspection_requests.truck_id = trucks.id
        WHERE notifications.user_id = ?
        ORDER BY notifications.id DESC
        LIMIT 5
    """, (session["user_id"],)).fetchall()

    unread_count = conn.execute("""
        SELECT COUNT(*) FROM notifications
        WHERE user_id = ? AND is_read = 0
    """, (session["user_id"],)).fetchone()[0]

    if session["role"] == "driver" and unread_count:
        mark_receipts_read(conn, session["user_id"])
        conn.commit()
        unread_count = 0

    conn.close()

    return render_template(
        "dashboard.html",
        total_trucks=total_trucks,
        pending_requests=pending_requests,
        maintenance_count=maintenance_count,
        completed_count=completed_count,
        cancelled_count=cancelled_count,
        receipts=receipts,
        unread_count=unread_count
    )


# =========================
# DRIVER RECEIPTS
# =========================

@app.route("/receipts")
def receipts():

    if "user_id" not in session:
        return redirect(url_for("login"))

    if session["role"] != "driver":
        flash("Only drivers have maintenance receipts.", "error")
        return redirect(url_for("dashboard"))

    conn = get_db()

    receipts = conn.execute("""
        SELECT
            notifications.*,
            trucks.truck_number,
            trucks.plate_number
        FROM notifications
        LEFT JOIN inspection_requests
        ON notifications.request_id = inspection_requests.id
        LEFT JOIN trucks
        ON inspection_requests.truck_id = trucks.id
        WHERE notifications.user_id = ?
        ORDER BY notifications.id DESC
    """, (session["user_id"],)).fetchall()

    unread_count = conn.execute("""
        SELECT COUNT(*) FROM notifications
        WHERE user_id = ? AND is_read = 0
    """, (session["user_id"],)).fetchone()[0]

    mark_receipts_read(conn, session["user_id"])
    conn.commit()

    conn.close()

    return render_template(
        "receipts.html",
        receipts=receipts,
        unread_count=unread_count
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

        uploads = request.files.getlist("photos")

        cursor = conn.execute("""
            INSERT INTO inspection_requests
            (truck_id, driver_id, date, mileage, issue)
            VALUES (?, ?, ?, ?, ?)
        """, (
            truck["id"],
            session["user_id"],
            date,
            mileage,
            issue
        ))

        request_id = cursor.lastrowid

        photo_names = save_photos(uploads)

        if photo_names:
            conn.executemany("""
                INSERT INTO request_photos (request_id, filename, position)
                VALUES (?, ?, ?)
            """, [
                (request_id, name, position)
                for position, name in enumerate(photo_names)
            ])

        conn.commit()
        conn.close()

        message = "Inspection request submitted successfully."

        if len(uploads) > MAX_PHOTOS:
            message = (
                f"Inspection request submitted. Only the first {MAX_PHOTOS} "
                "photos were attached."
            )

        flash(message, "success")

        return redirect(url_for("dashboard"))

    conn.close()

    return render_template(
        "inspection.html",
        truck=truck,
        max_photos=MAX_PHOTOS
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

    photos_by_request = {}

    for row in requests:
        photos_by_request[row["id"]] = get_photos(conn, row["id"])

    conn.close()

    return render_template(
        "requests.html",
        requests=requests,
        photos_by_request=photos_by_request
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

    receipt_sent = send_receipt(conn, request_id, notes)

    conn.commit()
    conn.close()

    if receipt_sent:
        flash(
            "Maintenance marked as completed. The driver has been sent a "
            "completion receipt.",
            "success"
        )
    else:
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

            uploads = request.files.getlist("photos")

            photos_replaced = replace_photos(conn, request_id, uploads)

            conn.commit()
            conn.close()

            if photos_replaced and len(uploads) > MAX_PHOTOS:
                flash(
                    f"Request updated. Only the first {MAX_PHOTOS} photos "
                    "were kept.",
                    "success"
                )
            else:
                flash("Request updated.", "success")

            return redirect(url_for("requests"))

    trucks = conn.execute(
        "SELECT * FROM trucks ORDER BY truck_number"
    ).fetchall()

    driver = conn.execute(
        "SELECT name FROM users WHERE id = ?",
        (item["driver_id"],)
    ).fetchone()

    photos = get_photos(conn, request_id)

    conn.close()

    return render_template(
        "request_edit.html",
        item=item,
        trucks=trucks,
        photos=photos,
        max_photos=MAX_PHOTOS,
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
