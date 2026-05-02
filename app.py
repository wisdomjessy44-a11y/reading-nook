# app.py
import os
from flask import (Flask, render_template, request, redirect,
                   url_for, session, flash, send_from_directory, jsonify)
import database

app = Flask(__name__)
app.secret_key = "your-secret-reading-nook-2024"

# ── Where uploaded PDFs are stored ──
UPLOAD_FOLDER = os.path.join(os.path.dirname(__file__), "uploads")
os.makedirs(UPLOAD_FOLDER, exist_ok=True)   # Create the folder if it doesn't exist
ALLOWED_EXTENSIONS = {"pdf"}                # Only PDFs for now

app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER
app.config["MAX_CONTENT_LENGTH"] = 50 * 1024 * 1024  # 50 MB max upload size


def allowed_file(filename):
    """Check that the uploaded file ends in .pdf"""
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


def safe_filename(filename):
    """
    Make the filename safe to save on disk.
    e.g. "My Book (2).pdf" → "My_Book_2_.pdf"
    We write our own simple version to avoid needing an extra library.
    """
    import re
    # Keep only letters, numbers, dots, dashes, underscores
    filename = re.sub(r"[^\w.\-]", "_", filename)
    return filename


def current_user_id():
    return session.get("user_id")


def login_required(f):
    from functools import wraps
    @wraps(f)
    def decorated(*args, **kwargs):
        if not current_user_id():
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return decorated


# ──────────────────────────────────────────────
# EXISTING ROUTES (unchanged except add_book)
# ──────────────────────────────────────────────

@app.route("/")
def index():
    if current_user_id():
        return redirect(url_for("dashboard"))
    return redirect(url_for("login"))


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "").strip()
        user = database.get_user_by_username(username)
        if user and user["password"] == password:
            session["user_id"] = user["id"]
            session["username"] = user["username"]
            flash(f"Welcome back, {user['username']}! 📖", "success")
            return redirect(url_for("dashboard"))
        else:
            flash("Wrong username or password. Try again.", "error")
    return render_template("login.html")


@app.route("/logout")
def logout():
    session.clear()
    flash("You've been logged out. See you soon! 👋", "info")
    return redirect(url_for("login"))


@app.route("/dashboard")
@login_required
def dashboard():
    uid = current_user_id()
    all_users = database.get_all_users()
    user_data = []
    for user in all_users:
        streak = database.calculate_streak(user["id"])
        assignments = database.get_assignments_for_user(user["id"])
        user_data.append({
            "id": user["id"],
            "username": user["username"],
            "streak": streak,
            "assignments": assignments,
        })
    recent_logs = database.get_logs_with_reactions(limit=15)
    return render_template(
        "dashboard.html",
        user_data=user_data,
        recent_logs=recent_logs,
        current_user_id=uid,
        current_username=session.get("username"),
        emoji_options=["❤️", "🔥", "😮", "💡", "👏"]
    )


@app.route("/books")
@login_required
def books():
    all_books = database.get_all_books()
    all_users = database.get_all_users()
    return render_template(
        "books.html",
        books=all_books,
        all_users=all_users,
        current_user_id=current_user_id(),
        current_username=session.get("username")
    )


@app.route("/books/add", methods=["POST"])
@login_required
def add_book():
    """
    Now handles both the text fields AND an optional PDF file upload.
    Flask's request.files gives us access to uploaded files.
    """
    title  = request.form.get("title", "").strip()
    author = request.form.get("author", "").strip()
    link   = request.form.get("link", "").strip()

    if not title or not author:
        flash("Title and author are required!", "error")
        return redirect(url_for("books"))

    filename = None  # Will stay None if no file is uploaded

    # Check if a file was included in the form submission
    uploaded_file = request.files.get("pdf_file")
    if uploaded_file and uploaded_file.filename:
        if allowed_file(uploaded_file.filename):
            # Make the filename safe, then save it to the uploads/ folder
            filename = safe_filename(uploaded_file.filename)
            # If a file with the same name exists, add the book id prefix later
            # For now, save directly
            save_path = os.path.join(app.config["UPLOAD_FOLDER"], filename)
            uploaded_file.save(save_path)
            flash(f'PDF uploaded successfully! 📄', "success")
        else:
            flash("Only PDF files are allowed.", "error")
            return redirect(url_for("books"))

    database.add_book(title, author, link or None, filename, current_user_id())
    flash(f'"{title}" added to the library! 📚', "success")
    return redirect(url_for("books"))


@app.route("/books/assign", methods=["POST"])
@login_required
def assign_book():
    book_id    = request.form.get("book_id")
    user_id    = request.form.get("user_id")
    total_pages = request.form.get("total_pages", 0)
    if not book_id or not user_id:
        flash("Please select a book and a reader.", "error")
        return redirect(url_for("books"))
    database.assign_book(int(book_id), int(user_id),
                         int(total_pages) if total_pages else 0, current_user_id())
    flash("Book assigned! Time to start reading 🎉", "success")
    return redirect(url_for("dashboard"))


@app.route("/log", methods=["GET", "POST"])
@login_required
def log_reading():
    uid = current_user_id()
    if request.method == "POST":
        book_id    = request.form.get("book_id")
        pages_read = request.form.get("pages_read", 0)
        note       = request.form.get("note", "").strip()
        if not book_id or not pages_read:
            flash("Please select a book and enter pages read.", "error")
        else:
            database.add_reading_log(uid, int(book_id), int(pages_read), note or None)
            flash("Reading logged! Keep it up 🌟", "success")
            return redirect(url_for("dashboard"))
    my_assignments = database.get_assignments_for_user(uid)
    return render_template("log.html", assignments=my_assignments,
                           current_username=session.get("username"))


@app.route("/react", methods=["POST"])
@login_required
def react():
    log_id   = request.form.get("log_id")
    reaction = request.form.get("reaction")
    if log_id and reaction:
        database.add_reaction(int(log_id), current_user_id(), reaction)
    return redirect(request.referrer or url_for("dashboard"))


@app.route("/book/<int:book_id>")
@login_required
def book_detail(book_id):
    book = database.get_book(book_id)
    if not book:
        flash("Book not found.", "error")
        return redirect(url_for("books"))
    all_users  = database.get_all_users()
    user_logs  = []
    for user in all_users:
        logs            = database.get_book_logs(book_id, user["id"])
        total_pages_read = sum(log["pages_read"] for log in logs)
        assignments      = database.get_assignments_for_user(user["id"])
        total_pages      = 0
        for a in assignments:
            if a["book_id"] == book_id:
                total_pages = a["total_pages"]
                break
        progress = 0
        if total_pages > 0:
            progress = min(100, int((total_pages_read / total_pages) * 100))
        user_logs.append({
            "username": user["username"],
            "user_id": user["id"],
            "logs": logs,
            "total_pages_read": total_pages_read,
            "total_pages": total_pages,
            "progress": progress,
        })
    return render_template("book_detail.html", book=book, user_logs=user_logs,
                           current_username=session.get("username"))


# ──────────────────────────────────────────────
# NEW ROUTES — PDF Reader
# ──────────────────────────────────────────────

@app.route("/uploads/<filename>")
@login_required
def serve_pdf(filename):
    """
    Serve a PDF file from the uploads/ folder.
    This route lets the browser fetch the PDF so PDF.js can display it.
    Only logged-in users can access uploaded files.
    """
    return send_from_directory(app.config["UPLOAD_FOLDER"], filename)


@app.route("/read/<int:book_id>")
@login_required
def read_book(book_id):
    """
    Open the in-app PDF reader for a book.
    Looks up where this user last left off and passes that to the reader page.
    """
    book = database.get_book(book_id)
    if not book:
        flash("Book not found.", "error")
        return redirect(url_for("books"))

    if not book["filename"]:
        flash("This book doesn't have a PDF uploaded yet.", "error")
        return redirect(url_for("book_detail", book_id=book_id))

    uid       = current_user_id()
    last_page = database.get_last_page(book_id, uid)

    # Build the URL to the PDF so PDF.js can load it
    pdf_url = url_for("serve_pdf", filename=book["filename"])

    return render_template(
        "reader.html",
        book=book,
        pdf_url=pdf_url,
        last_page=last_page,
        book_id=book_id,
        current_username=session.get("username")
    )


@app.route("/save-page", methods=["POST"])
@login_required
def save_page():
    """
    Called automatically by JavaScript every time the user turns a page.
    Receives JSON data: { book_id: 3, page: 42 }
    Returns JSON: { ok: true }

    This is an "API endpoint" — it doesn't return an HTML page,
    just a small JSON response that JavaScript reads.
    """
    data     = request.get_json()
    book_id  = data.get("book_id")
    page_num = data.get("page")

    if book_id and page_num:
        database.save_last_page(int(book_id), current_user_id(), int(page_num))

    return jsonify({"ok": True})


# ──────────────────────────────────────────────
# START
# ──────────────────────────────────────────────

if __name__ == "__main__":
    database.init_db()
    print("✅ Database ready!")
    print("🚀 Starting app... visit http://127.0.0.1:5000 in your browser")
    app.run(debug=True)
