# database.py
import sqlite3
from datetime import date, timedelta

DATABASE = "reading.db"


def get_db():
    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_db()
    cursor = conn.cursor()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT NOT NULL UNIQUE,
            password TEXT NOT NULL
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS books (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            author TEXT NOT NULL,
            link TEXT,
            filename TEXT,
            added_by INTEGER NOT NULL,
            FOREIGN KEY (added_by) REFERENCES users(id)
        )
    """)

    # Migration: add 'filename' to existing databases safely
    try:
        cursor.execute("ALTER TABLE books ADD COLUMN filename TEXT")
    except Exception:
        pass

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS assignments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            book_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            total_pages INTEGER NOT NULL DEFAULT 0,
            assigned_by INTEGER NOT NULL,
            last_page INTEGER NOT NULL DEFAULT 1,
            FOREIGN KEY (book_id) REFERENCES books(id),
            FOREIGN KEY (user_id) REFERENCES users(id),
            FOREIGN KEY (assigned_by) REFERENCES users(id)
        )
    """)

    # Migration: add 'last_page' to existing assignments safely
    try:
        cursor.execute("ALTER TABLE assignments ADD COLUMN last_page INTEGER NOT NULL DEFAULT 1")
    except Exception:
        pass

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS reading_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            book_id INTEGER NOT NULL,
            pages_read INTEGER NOT NULL,
            note TEXT,
            date TEXT NOT NULL DEFAULT (date('now')),
            FOREIGN KEY (user_id) REFERENCES users(id),
            FOREIGN KEY (book_id) REFERENCES books(id)
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS reactions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            log_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            reaction TEXT NOT NULL,
            FOREIGN KEY (log_id) REFERENCES reading_logs(id),
            FOREIGN KEY (user_id) REFERENCES users(id)
        )
    """)

    cursor.execute("SELECT COUNT(*) FROM users")
    if cursor.fetchone()[0] == 0:
        cursor.execute("INSERT INTO users (username, password) VALUES (?, ?)", ("Me", "password1"))
        cursor.execute("INSERT INTO users (username, password) VALUES (?, ?)", ("Sister", "password2"))

    conn.commit()
    conn.close()


def get_user_by_username(username):
    conn = get_db()
    user = conn.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
    conn.close()
    return user


def get_all_books():
    conn = get_db()
    books = conn.execute("""
        SELECT books.*, users.username AS added_by_name
        FROM books
        JOIN users ON books.added_by = users.id
        ORDER BY books.id DESC
    """).fetchall()
    conn.close()
    return books


def get_book(book_id):
    conn = get_db()
    book = conn.execute("SELECT * FROM books WHERE id = ?", (book_id,)).fetchone()
    conn.close()
    return book


def add_book(title, author, link, filename, added_by):
    """filename = saved name of the uploaded PDF, or None if no file uploaded."""
    conn = get_db()
    conn.execute(
        "INSERT INTO books (title, author, link, filename, added_by) VALUES (?, ?, ?, ?, ?)",
        (title, author, link, filename, added_by)
    )
    conn.commit()
    conn.close()


def get_assignments_for_user(user_id):
    conn = get_db()
    assignments = conn.execute("""
        SELECT
            assignments.id AS assignment_id,
            assignments.total_pages,
            assignments.last_page,
            books.id AS book_id,
            books.title,
            books.author,
            books.filename,
            COALESCE((
                SELECT SUM(pages_read)
                FROM reading_logs
                WHERE reading_logs.book_id = books.id
                  AND reading_logs.user_id = assignments.user_id
            ), 0) AS pages_read_total
        FROM assignments
        JOIN books ON assignments.book_id = books.id
        WHERE assignments.user_id = ?
        ORDER BY assignments.id DESC
    """, (user_id,)).fetchall()
    conn.close()
    return assignments


def assign_book(book_id, user_id, total_pages, assigned_by):
    conn = get_db()
    conn.execute(
        "INSERT INTO assignments (book_id, user_id, total_pages, assigned_by) VALUES (?, ?, ?, ?)",
        (book_id, user_id, total_pages, assigned_by)
    )
    conn.commit()
    conn.close()


def save_last_page(book_id, user_id, page_number):
    """Save the page the user is on — called every time they turn a page."""
    conn = get_db()
    conn.execute("""
        UPDATE assignments SET last_page = ?
        WHERE book_id = ? AND user_id = ?
    """, (page_number, book_id, user_id))
    conn.commit()
    conn.close()


def get_last_page(book_id, user_id):
    """Get the last page this user was on. Returns 1 if not started."""
    conn = get_db()
    row = conn.execute("""
        SELECT last_page FROM assignments
        WHERE book_id = ? AND user_id = ?
    """, (book_id, user_id)).fetchone()
    conn.close()
    return row["last_page"] if row else 1


def add_reading_log(user_id, book_id, pages_read, note):
    today = str(date.today())
    conn = get_db()
    conn.execute(
        "INSERT INTO reading_logs (user_id, book_id, pages_read, note, date) VALUES (?, ?, ?, ?, ?)",
        (user_id, book_id, pages_read, note, today)
    )
    conn.commit()
    conn.close()


def get_logs_with_reactions(limit=20):
    conn = get_db()
    logs = conn.execute("""
        SELECT
            reading_logs.id,
            reading_logs.pages_read,
            reading_logs.note,
            reading_logs.date,
            books.id AS book_id,
            books.title AS book_title,
            users.username AS reader_name,
            users.id AS reader_id
        FROM reading_logs
        JOIN books ON reading_logs.book_id = books.id
        JOIN users ON reading_logs.user_id = users.id
        ORDER BY reading_logs.date DESC, reading_logs.id DESC
        LIMIT ?
    """, (limit,)).fetchall()

    result = []
    for log in logs:
        log_dict = dict(log)
        reactions = conn.execute("""
            SELECT reactions.reaction, users.username
            FROM reactions
            JOIN users ON reactions.user_id = users.id
            WHERE reactions.log_id = ?
        """, (log["id"],)).fetchall()
        log_dict["reactions"] = reactions
        result.append(log_dict)

    conn.close()
    return result


def add_reaction(log_id, user_id, reaction):
    conn = get_db()
    conn.execute("DELETE FROM reactions WHERE log_id = ? AND user_id = ?", (log_id, user_id))
    conn.execute(
        "INSERT INTO reactions (log_id, user_id, reaction) VALUES (?, ?, ?)",
        (log_id, user_id, reaction)
    )
    conn.commit()
    conn.close()


def calculate_streak(user_id):
    conn = get_db()
    dates = conn.execute("""
        SELECT DISTINCT date FROM reading_logs
        WHERE user_id = ?
        ORDER BY date DESC
    """, (user_id,)).fetchall()
    conn.close()

    if not dates:
        return 0

    streak = 0
    check_date = date.today()
    first_log_date = date.fromisoformat(dates[0]["date"])

    if (check_date - first_log_date).days > 1:
        return 0

    logged_dates = {d["date"] for d in dates}
    while str(check_date) in logged_dates:
        streak += 1
        check_date -= timedelta(days=1)

    return streak


def get_book_logs(book_id, user_id):
    conn = get_db()
    logs = conn.execute("""
        SELECT * FROM reading_logs
        WHERE book_id = ? AND user_id = ?
        ORDER BY date DESC
    """, (book_id, user_id)).fetchall()
    conn.close()
    return logs


def get_all_users():
    conn = get_db()
    users = conn.execute("SELECT * FROM users").fetchall()
    conn.close()
    return users
