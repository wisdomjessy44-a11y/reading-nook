# app.py
import os, re
from flask import (Flask, render_template, request, redirect,
                   url_for, session, flash, send_from_directory, jsonify)
import database

app = Flask(__name__)
app.secret_key = "your-secret-reading-nook-2024"

UPLOAD_FOLDER = os.path.join(os.path.dirname(__file__), "uploads")
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
ALLOWED_EXTENSIONS = {"epub", "pdf", "txt"}

app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER
app.config["MAX_CONTENT_LENGTH"] = 50 * 1024 * 1024  # 50 MB


def allowed_file(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


def safe_filename(filename):
    return re.sub(r"[^\w.\-]", "_", filename)


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


# ── Auth ──

@app.route("/")
def index():
    return redirect(url_for("dashboard") if current_user_id() else url_for("login"))


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
        flash("Wrong username or password.", "error")
    return render_template("login.html")


@app.route("/logout")
def logout():
    session.clear()
    flash("Logged out. See you soon! 👋", "info")
    return redirect(url_for("login"))


# ── Dashboard ──

@app.route("/dashboard")
@login_required
def dashboard():
    uid = current_user_id()
    all_users = database.get_all_users()
    user_data = []
    for user in all_users:
        user_data.append({
            "id": user["id"],
            "username": user["username"],
            "streak": database.calculate_streak(user["id"]),
            "assignments": database.get_assignments_for_user(user["id"]),
        })
    return render_template("dashboard.html",
        user_data=user_data,
        recent_logs=database.get_logs_with_reactions(limit=15),
        current_user_id=uid,
        current_username=session.get("username"),
        emoji_options=["❤️", "🔥", "😮", "💡", "👏"])


# ── Books ──

@app.route("/books")
@login_required
def books():
    return render_template("books.html",
        books=database.get_all_books(),
        all_users=database.get_all_users(),
        current_user_id=current_user_id(),
        current_username=session.get("username"))


@app.route("/books/add", methods=["POST"])
@login_required
def add_book():
    title  = request.form.get("title", "").strip()
    author = request.form.get("author", "").strip()
    link   = request.form.get("link", "").strip()

    if not title or not author:
        flash("Title and author are required!", "error")
        return redirect(url_for("books"))

    filename = None
    uploaded_file = request.files.get("book_file")
    if uploaded_file and uploaded_file.filename:
        if allowed_file(uploaded_file.filename):
            filename = safe_filename(uploaded_file.filename)
            uploaded_file.save(os.path.join(app.config["UPLOAD_FOLDER"], filename))
            flash("File uploaded! 📄", "success")
        else:
            flash("Only EPUB, PDF, or TXT files allowed.", "error")
            return redirect(url_for("books"))

    database.add_book(title, author, link or None, filename, current_user_id())
    flash(f'"{title}" added! 📚', "success")
    return redirect(url_for("books"))


@app.route("/books/assign", methods=["POST"])
@login_required
def assign_book():
    book_id = request.form.get("book_id")
    user_id = request.form.get("user_id")
    total_pages = request.form.get("total_pages", 0)
    if not book_id or not user_id:
        flash("Please select a book and a reader.", "error")
        return redirect(url_for("books"))
    database.assign_book(int(book_id), int(user_id),
                         int(total_pages) if total_pages else 0, current_user_id())
    flash("Book assigned! 🎉", "success")
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
            flash("Reading logged! 🌟", "success")
            return redirect(url_for("dashboard"))
    return render_template("log.html",
        assignments=database.get_assignments_for_user(uid),
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
    all_users = database.get_all_users()
    user_logs = []
    for user in all_users:
        logs = database.get_book_logs(book_id, user["id"])
        total_read = sum(log["pages_read"] for log in logs)
        assignments = database.get_assignments_for_user(user["id"])
        total_pages = next((a["total_pages"] for a in assignments if a["book_id"] == book_id), 0)
        progress = min(100, int((total_read / total_pages) * 100)) if total_pages > 0 else 0
        user_logs.append({
            "username": user["username"], "user_id": user["id"],
            "logs": logs, "total_pages_read": total_read,
            "total_pages": total_pages, "progress": progress,
        })
    return render_template("book_detail.html", book=book, user_logs=user_logs,
                           current_username=session.get("username"))


# ── File serving ──

@app.route("/uploads/<filename>")
@login_required
def serve_file(filename):
    return send_from_directory(app.config["UPLOAD_FOLDER"], filename)


# ── EPUB Reader ──

def parse_epub(filepath):
    """
    Opens an EPUB file and extracts all chapters as a list of dicts:
    [{ "title": "Chapter 1", "html": "<p>...</p>" }, ...]

    ebooklib handles the unzipping and parsing.
    BeautifulSoup cleans up the HTML so it looks good in our reader.
    """
    import ebooklib
    from ebooklib import epub
    from bs4 import BeautifulSoup

    book = epub.read_epub(filepath)
    chapters = []

    # Get chapters in reading order
    spine_ids = [item_id for item_id, _ in book.spine]

    for item_id in spine_ids:
        item = book.get_item_with_id(item_id)
        if item is None:
            continue
        if item.get_type() != ebooklib.ITEM_DOCUMENT:
            continue

        # Parse the HTML content of this chapter
        soup = BeautifulSoup(item.get_content(), "html.parser")

        # Get the body text
        body = soup.find("body")
        if not body:
            continue

        # Skip chapters with almost no text (like cover pages)
        text = body.get_text(strip=True)
        if len(text) < 50:
            continue

        # Try to find a chapter title from h1/h2/h3
        heading = body.find(["h1", "h2", "h3"])
        title = heading.get_text(strip=True) if heading else f"Chapter {len(chapters) + 1}"

        # Clean the HTML: keep only safe tags
        allowed_tags = ["p", "h1", "h2", "h3", "h4", "em", "strong", "i", "b", "br", "div", "span"]
        for tag in body.find_all(True):
            if tag.name not in allowed_tags:
                tag.unwrap()  # Remove the tag but keep its text content

        # Remove all attributes except basic ones
        for tag in body.find_all(True):
            tag.attrs = {}

        chapters.append({
            "title": title,
            "html": str(body)
        })

    return chapters


@app.route("/read/<int:book_id>")
@login_required
def read_book(book_id):
    """Open the reader for a book."""
    book = database.get_book(book_id)
    if not book or not book["filename"]:
        flash("No file uploaded for this book.", "error")
        return redirect(url_for("book_detail", book_id=book_id))

    uid       = current_user_id()
    saved_pos = database.get_last_page(book_id, uid)  # encoded as chapter.scroll
    filepath  = os.path.join(app.config["UPLOAD_FOLDER"], book["filename"])
    ext       = book["filename"].rsplit(".", 1)[-1].lower()

    if ext == "epub":
        try:
            chapters = parse_epub(filepath)
        except Exception as e:
            flash(f"Could not read EPUB: {str(e)}", "error")
            return redirect(url_for("book_detail", book_id=book_id))

        if not chapters:
            flash("This EPUB appears to have no readable chapters.", "error")
            return redirect(url_for("book_detail", book_id=book_id))

        # Decode saved chapter from position
        current_chapter = min(int(saved_pos), len(chapters) - 1)

        # Pass only chapter titles to the template (content loaded via AJAX)
        chapter_list = [{"title": ch["title"]} for ch in chapters]

        return render_template("reader.html",
            book=book,
            book_id=book_id,
            chapters=chapter_list,
            current_chapter=current_chapter,
            saved_scroll=saved_pos,
            pdf_url="")

    else:
        # PDF or TXT — serve directly
        flash("For the best reading experience, please upload an EPUB file.", "info")
        return redirect(url_for("book_detail", book_id=book_id))


@app.route("/chapter/<int:book_id>/<int:chapter_index>")
@login_required
def get_chapter(book_id, chapter_index):
    """
    API endpoint: returns one chapter's HTML as JSON.
    Called by JavaScript in the reader whenever the user changes chapter.
    """
    book = database.get_book(book_id)
    if not book or not book["filename"]:
        return jsonify({"error": "Book not found"}), 404

    filepath = os.path.join(app.config["UPLOAD_FOLDER"], book["filename"])

    try:
        chapters = parse_epub(filepath)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

    if chapter_index < 0 or chapter_index >= len(chapters):
        return jsonify({"error": "Chapter not found"}), 404

    ch = chapters[chapter_index]
    return jsonify({"title": ch["title"], "html": ch["html"]})


@app.route("/save-page", methods=["POST"])
@login_required
def save_page():
    """Save reading position (chapter + scroll %)."""
    data    = request.get_json()
    book_id = data.get("book_id")
    page    = data.get("page")
    if book_id and page is not None:
        database.save_last_page(int(book_id), current_user_id(), float(page))
    return jsonify({"ok": True})


if __name__ == "__main__":
    database.init_db()
    print("✅ Database ready!")
    print("🚀 Starting app... visit http://127.0.0.1:5000")
    app.run(debug=True)
