from __future__ import annotations

import os
import random
import re
import sqlite3
from datetime import datetime, timedelta
from functools import wraps
from pathlib import Path
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

from flask import Flask, abort, flash, g, jsonify, redirect, render_template, request, send_from_directory, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash
from werkzeug.utils import secure_filename

BASE_DIR = Path(__file__).resolve().parent
DATABASE = BASE_DIR / "edunova.db"
UPLOAD_DIR = BASE_DIR / "uploads"
UPLOAD_DIR.mkdir(exist_ok=True)
ALLOWED_EXTENSIONS = {"pdf", "docx"}
CHAT_FILE_EXTENSIONS = {"png", "jpg", "jpeg", "gif", "webp", "pdf", "docx", "txt", "zip"}

# ==== Hằng số dùng chung (giao diện / kênh hỗ trợ / bộ câu hỏi) ====
ACCENT_COLORS = {'pink', 'blue', 'purple', 'green', 'orange', 'teal', 'red', 'yellow', 'indigo', 'cyan'}
APPEARANCE_MODES = {'light', 'dark', 'auto', 'pink', 'blue'}
OPACITY_VALUES = {str(n) for n in range(0, 41, 5)}
BACKGROUND_POSITIONS = {'center', 'top', 'bottom'}
BACKGROUND_EFFECTS = {'none', 'soft', 'blur'}
SEASONAL_PRESETS = {'spring', 'summer', 'autumn', 'winter', 'tet', 'christmas'}
BACKGROUND_IMAGE_EXTS = {"png", "jpg", "jpeg", "webp", "gif"}
FACEBOOK_HOSTS = {'facebook.com', 'www.facebook.com', 'm.facebook.com'}

_RE_PHONE = re.compile(r"[+\d() .-]{7,40}")
_RE_EMAIL = re.compile(r"[^\s@]+@[^\s@]+\.[^\s@]+")

# Regex dùng trong extract_questions — compile 1 lần thay vì mỗi lần dùng.
_RE_QUESTION_LABEL = re.compile(r"(?i)^(?:Câu(?:\s+hỏi)?|Question)\s*\d+")
_RE_ANSWER_MARK = re.compile(r"(?i)^(?:Đáp\s*án|Answer)\s*[:：-]")
_RE_OPTION_PREFIX = re.compile(r"(?i)^([A-D])\s*[.)\]:-]")
_RE_CHUNK_SPLIT = re.compile(r"(?im)(?=^(?:Câu(?:\s+hỏi)?|Question)\s*\d+\s*[:.)-]?)")
_RE_CHUNK_HEAD = re.compile(r"(?is)^\s*(?:Câu(?:\s+hỏi)?|Question)\s*\d+")
_RE_QUESTION_STRIP = re.compile(r"(?i)^(?:Câu(?:\s+hỏi)?|Question)\s*\d+\s*[:.)-]?\s*")
_RE_WHITESPACE = re.compile(r"\s+")
_RE_OPTION_FULL = re.compile(r"(?i)^([A-D])\s*[.)\]:-]\s*(.+)$")
_RE_ANSWER_LINE = re.compile(r"(?i)^(?:Đáp\s*án|Đáp\s*án\s*đúng|Answer)\s*[:：-]\s*([A-D](?:\s*[,;+&]\s*[A-D])*)(?![A-D])")
_RE_EXPLANATION = re.compile(r"(?i)^(?:Giải\s*thích|Lời\s*giải|Explanation)\s*[:：-]\s*(.*)$")
_RE_CHAPTER = re.compile(r"(?i)^Chương\s*[:：-]\s*(.+)$")
_RE_IMAGE_REF = re.compile(r"__IMAGE_(\d+)__")
_RED_RGB = {"EE0000", "FF0000", "C00000", "RED"}

app = Flask(__name__)
app.config.update(SECRET_KEY=os.environ.get("SECRET_KEY", "dev-secret-change-me"), MAX_CONTENT_LENGTH=20 * 1024 * 1024)
VIETNAM_TZ = ZoneInfo("Asia/Bangkok")


def display_datetime(value, with_time=True):
    """Đổi timestamp SQLite (UTC) sang ngày giờ Việt Nam dễ đọc."""
    if not value:
        return ""
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=ZoneInfo("UTC"))
        local = parsed.astimezone(VIETNAM_TZ)
        return local.strftime("%d/%m/%Y · %H:%M" if with_time else "%d/%m/%Y")
    except ValueError:
        return str(value)


@app.template_filter("datetime_vi")
def datetime_vi_filter(value):
    return display_datetime(value)


def study_streak(rows):
    """Tính chuỗi ngày có làm bài liên tục, tính từ ngày học gần nhất."""
    dates = set()
    for row in rows:
        try:
            parsed = datetime.fromisoformat(str(row['created_at']).replace("Z", "+00:00"))
            if parsed.tzinfo is None: parsed = parsed.replace(tzinfo=ZoneInfo("UTC"))
            dates.add(parsed.astimezone(VIETNAM_TZ).date())
        except (ValueError, TypeError):
            continue
    if not dates:
        return 0
    cursor = datetime.now(VIETNAM_TZ).date()
    if cursor not in dates:
        cursor -= timedelta(days=1)
    count = 0
    while cursor in dates:
        count += 1
        cursor -= timedelta(days=1)
    return count


def db():
    if "db" not in g:
        g.db = sqlite3.connect(DATABASE)
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON")
    return g.db


@app.teardown_appcontext
def close_db(_error=None):
    conn = g.pop("db", None)
    if conn is not None:
        conn.close()


def init_db():
    conn = sqlite3.connect(DATABASE)
    conn.executescript("""
    CREATE TABLE IF NOT EXISTS users (id INTEGER PRIMARY KEY, name TEXT NOT NULL, email TEXT UNIQUE NOT NULL, password TEXT NOT NULL, role TEXT NOT NULL DEFAULT 'student', active INTEGER NOT NULL DEFAULT 1, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
    CREATE TABLE IF NOT EXISTS subjects (id INTEGER PRIMARY KEY, name TEXT NOT NULL, level TEXT NOT NULL, icon TEXT NOT NULL DEFAULT '📘', color TEXT NOT NULL DEFAULT 'blue', description TEXT NOT NULL DEFAULT '', lessons INTEGER NOT NULL DEFAULT 0);
    CREATE TABLE IF NOT EXISTS documents (id INTEGER PRIMARY KEY, subject_id INTEGER NOT NULL REFERENCES subjects(id) ON DELETE CASCADE, title TEXT NOT NULL, filename TEXT NOT NULL, uploaded_by INTEGER REFERENCES users(id), approved INTEGER NOT NULL DEFAULT 1, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
    CREATE TABLE IF NOT EXISTS questions (id INTEGER PRIMARY KEY, subject_id INTEGER NOT NULL REFERENCES subjects(id) ON DELETE CASCADE, chapter TEXT NOT NULL, question TEXT NOT NULL, a TEXT NOT NULL, b TEXT NOT NULL, c TEXT NOT NULL, d TEXT NOT NULL, answer TEXT NOT NULL, explanation TEXT NOT NULL DEFAULT '', image_filename TEXT);
    CREATE TABLE IF NOT EXISTS attempts (id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE, subject_id INTEGER NOT NULL REFERENCES subjects(id) ON DELETE CASCADE, title TEXT NOT NULL, score REAL NOT NULL, correct INTEGER NOT NULL, total INTEGER NOT NULL, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
    CREATE TABLE IF NOT EXISTS notices (id INTEGER PRIMARY KEY, title TEXT NOT NULL, body TEXT NOT NULL, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
    CREATE TABLE IF NOT EXISTS notice_reads (user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE, notice_id INTEGER NOT NULL REFERENCES notices(id) ON DELETE CASCADE, read_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, PRIMARY KEY(user_id, notice_id));
    CREATE TABLE IF NOT EXISTS exam_settings (id INTEGER PRIMARY KEY, subject_id INTEGER NOT NULL REFERENCES subjects(id) ON DELETE CASCADE, week INTEGER NOT NULL, minutes INTEGER NOT NULL DEFAULT 0, shuffle INTEGER NOT NULL DEFAULT 0, password_hash TEXT, UNIQUE(subject_id, week));
    CREATE TABLE IF NOT EXISTS attempt_answers (id INTEGER PRIMARY KEY, attempt_id INTEGER NOT NULL REFERENCES attempts(id) ON DELETE CASCADE, question_id INTEGER NOT NULL REFERENCES questions(id) ON DELETE CASCADE, selected TEXT NOT NULL DEFAULT '', is_correct INTEGER NOT NULL DEFAULT 0);
    CREATE TABLE IF NOT EXISTS shared_resources (id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE, subject_id INTEGER NOT NULL REFERENCES subjects(id) ON DELETE CASCADE, week INTEGER NOT NULL DEFAULT 1, title TEXT NOT NULL, description TEXT NOT NULL DEFAULT '', url TEXT NOT NULL, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
    CREATE TABLE IF NOT EXISTS chat_messages (id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE, subject_id INTEGER NOT NULL REFERENCES subjects(id) ON DELETE CASCADE, week INTEGER NOT NULL DEFAULT 1, message TEXT NOT NULL, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
    CREATE TABLE IF NOT EXISTS general_chat_messages (id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE, message TEXT NOT NULL, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
    CREATE TABLE IF NOT EXISTS chat_reactions (id INTEGER PRIMARY KEY, message_id INTEGER NOT NULL REFERENCES general_chat_messages(id) ON DELETE CASCADE, user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE, emoji TEXT NOT NULL, UNIQUE(message_id,user_id,emoji));
    CREATE TABLE IF NOT EXISTS support_posts (id INTEGER PRIMARY KEY, title TEXT NOT NULL, body TEXT NOT NULL DEFAULT '', filename TEXT, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
    CREATE TABLE IF NOT EXISTS feedback (id INTEGER PRIMARY KEY, user_id INTEGER REFERENCES users(id) ON DELETE SET NULL, name TEXT NOT NULL, email TEXT NOT NULL DEFAULT '', message TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'Mới', created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
    CREATE TABLE IF NOT EXISTS site_settings (key TEXT PRIMARY KEY, value TEXT NOT NULL DEFAULT '');
    """)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.executescript("""
    CREATE INDEX IF NOT EXISTS idx_questions_subject_week ON questions(subject_id, week);
    CREATE INDEX IF NOT EXISTS idx_attempts_user ON attempts(user_id);
    CREATE INDEX IF NOT EXISTS idx_attempts_subject ON attempts(subject_id);
    CREATE INDEX IF NOT EXISTS idx_attempt_answers_attempt ON attempt_answers(attempt_id);
    CREATE INDEX IF NOT EXISTS idx_attempt_answers_question ON attempt_answers(question_id);
    CREATE INDEX IF NOT EXISTS idx_documents_subject ON documents(subject_id);
    CREATE INDEX IF NOT EXISTS idx_shared_resources_subject ON shared_resources(subject_id);
    CREATE INDEX IF NOT EXISTS idx_chat_subject_week ON chat_messages(subject_id, week);
    """)
    doc_columns = {row[1] for row in conn.execute("PRAGMA table_info(documents)")}
    if "imported_questions" not in doc_columns:
        conn.execute("ALTER TABLE documents ADD COLUMN imported_questions INTEGER NOT NULL DEFAULT 0")
    if "week" not in doc_columns:
        conn.execute("ALTER TABLE documents ADD COLUMN week INTEGER NOT NULL DEFAULT 1")
    question_columns = {row[1] for row in conn.execute("PRAGMA table_info(questions)")}
    if "multi_select" not in question_columns:
        conn.execute("ALTER TABLE questions ADD COLUMN multi_select INTEGER NOT NULL DEFAULT 0")
    if "week" not in question_columns:
        conn.execute("ALTER TABLE questions ADD COLUMN week INTEGER NOT NULL DEFAULT 1")
    if "image_filename" not in question_columns:
        conn.execute("ALTER TABLE questions ADD COLUMN image_filename TEXT")
    user_columns = {row[1] for row in conn.execute("PRAGMA table_info(users)")}
    if "avatar_filename" not in user_columns:
        conn.execute("ALTER TABLE users ADD COLUMN avatar_filename TEXT")
    chat_columns = {row[1] for row in conn.execute("PRAGMA table_info(general_chat_messages)")}
    if "attachment_filename" not in chat_columns:
        conn.execute("ALTER TABLE general_chat_messages ADD COLUMN attachment_filename TEXT")
    if "attachment_original" not in chat_columns:
        conn.execute("ALTER TABLE general_chat_messages ADD COLUMN attachment_original TEXT")
    if conn.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 0:
        conn.execute("INSERT INTO users(name,email,password,role) VALUES(?,?,?,?)", ("Quản trị viên", "admin@edunova.vn", generate_password_hash("admin123"), "admin"))
        conn.execute("INSERT INTO users(name,email,password,role) VALUES(?,?,?,?)", ("Nguyễn Minh Anh", "hocvien@edunova.vn", generate_password_hash("123456"), "student"))
        subjects = [
            ("Toán học", "Lớp 12", "∑", "violet", "Ôn tập kiến thức và chinh phục các dạng toán THPT.", 24),
            ("Vật lý", "Lớp 12", "⚡", "orange", "Nắm vững công thức, luyện bài tập từ cơ bản đến nâng cao.", 18),
            ("Tiếng Anh", "Lớp 12", "✦", "blue", "Phát triển từ vựng, ngữ pháp và kỹ năng làm đề.", 32),
            ("Hóa học", "Lớp 11", "⚗", "green", "Hệ thống hóa phản ứng và luyện tập theo chuyên đề.", 20),
        ]
        conn.executemany("INSERT INTO subjects(name,level,icon,color,description,lessons) VALUES(?,?,?,?,?,?)", subjects)
        qrows = [
            (1, "Hàm số", "Đạo hàm của hàm số f(x) = x³ − 3x là?", "3x² − 3", "x² − 3", "3x² + 3", "3x − 3", "A", "Áp dụng quy tắc đạo hàm lũy thừa: (x³)' = 3x² và (-3x)' = -3."),
            (1, "Hàm số", "Hàm số y = x² đồng biến trên khoảng nào?", "(-∞; 0)", "(0; +∞)", "ℝ", "(-1; 1)", "B", "Đạo hàm y' = 2x > 0 khi x > 0, nên hàm số đồng biến trên (0; +∞)."),
            (1, "Tích phân", "Một nguyên hàm của 2x là?", "x² + C", "2x² + C", "x + C", "x²/2 + C", "A", "Vì (x²)' = 2x nên một nguyên hàm là x² + C."),
            (2, "Dao động", "Đơn vị của tần số trong hệ SI là gì?", "m/s", "Hz", "N", "J", "B", "Tần số có đơn vị là héc (Hz)."),
            (2, "Điện học", "Định luật Ôm được viết là?", "U = I/R", "I = U.R", "U = I.R", "R = U.I", "C", "Định luật Ôm: U = I × R."),
            (3, "Ngữ pháp", "Choose the correct form: She ___ to school every day.", "go", "goes", "going", "gone", "B", "Chủ ngữ ngôi thứ ba số ít ở hiện tại đơn dùng động từ thêm -s/-es."),
            (3, "Từ vựng", "The word 'significant' is closest in meaning to:", "important", "tiny", "ordinary", "unclear", "A", "Significant có nghĩa là quan trọng, đáng kể."),
            (4, "Hóa vô cơ", "Công thức hóa học của axit sulfuric là?", "HCl", "HNO₃", "H₂SO₄", "H₃PO₄", "C", "Axit sulfuric có công thức H₂SO₄."),
        ]
        conn.executemany("INSERT INTO questions(subject_id,chapter,question,a,b,c,d,answer,explanation) VALUES(?,?,?,?,?,?,?,?,?)", qrows)
        conn.execute("INSERT INTO notices(title,body) VALUES(?,?)", ("Chào mừng đến với EduNova", "Bắt đầu hành trình học tập của bạn. Chúc bạn ôn tập hiệu quả!"))
        conn.commit()
    conn.close()


def login_required(fn):
    @wraps(fn)
    def wrapped(*args, **kwargs):
        if not session.get("user_id"):
            flash("Vui lòng đăng nhập để tiếp tục.", "warning")
            return redirect(url_for("login"))
        return fn(*args, **kwargs)
    return wrapped


def admin_required(fn):
    @wraps(fn)
    @login_required
    def wrapped(*args, **kwargs):
        if session.get("role") != "admin":
            abort(403)
        return fn(*args, **kwargs)
    return wrapped


def subjects_with_counts(conn, selected_subject=None, selected_week=None, order="s.id"):
    """Danh sách môn học kèm số câu hỏi (dùng chung cho home và admin_subjects)."""
    sql = "SELECT s.*,COUNT(q.id) question_count FROM subjects s LEFT JOIN questions q ON q.subject_id=s.id"
    filters, params = [], []
    if selected_week:
        filters.append("q.week=?")
        params.append(selected_week)
    if selected_subject:
        filters.append("s.id=?")
        params.append(selected_subject)
    if filters:
        sql += " WHERE " + " AND ".join(filters)
    sql += " GROUP BY s.id"
    if selected_week:
        sql += " HAVING COUNT(q.id)>0"
    return conn.execute(sql + f" ORDER BY {order}", params).fetchall()


def wrong_question_ids(conn, attempt_id):
    """Danh sách id câu bị sai trong một bài làm (dùng chung cho quiz GET/POST)."""
    return [r["question_id"] for r in conn.execute("SELECT question_id FROM attempt_answers WHERE attempt_id=? AND is_correct=0", (attempt_id,)).fetchall()]


def upsert_setting(conn, key, value):
    """Ghi hoặc cập nhật một dòng trong site_settings."""
    conn.execute("INSERT INTO site_settings(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, value))


def validate_support_settings(facebook, phone, email):
    """Trả về thông báo lỗi nếu kênh hỗ trợ không hợp lệ, ngược lại trả None."""
    if facebook and (urlparse(facebook).scheme != 'https' or urlparse(facebook).netloc.lower() not in FACEBOOK_HOSTS):
        return "Đường dẫn Facebook cần bắt đầu bằng https://www.facebook.com/."
    if phone and not _RE_PHONE.fullmatch(phone):
        return "Số điện thoại hỗ trợ chưa đúng định dạng."
    if email and not _RE_EMAIL.fullmatch(email):
        return "Gmail hỗ trợ chưa đúng định dạng."
    return None


def save_upload(file, prefix, allowed_extensions):
    """Lưu tệp có phần mở rộng được phép và trả về (tên_lưu, tên_gốc)."""
    original = secure_filename(file.filename or "")
    ext = original.rsplit('.', 1)[-1].lower() if '.' in original else ''
    if not original or ext not in allowed_extensions:
        return None, None
    saved = f"{prefix}_{datetime.now().strftime('%Y%m%d%H%M%S%f')}_{original}"
    file.save(UPLOAD_DIR / saved)
    return saved, original


@app.context_processor
def inject_user():
    subjects = db().execute("SELECT id,name,icon,color FROM subjects ORDER BY id").fetchall()
    theme_settings = {row['key']: row['value'] for row in db().execute("SELECT key,value FROM site_settings")}
    accent = theme_settings.get('accent', 'purple')
    if accent not in ACCENT_COLORS: accent = 'purple'
    mode = theme_settings.get('appearance_mode', 'light')
    if mode not in APPEARANCE_MODES: mode = 'light'
    opacity = theme_settings.get('background_opacity', '18')
    if not opacity.isdigit(): opacity = '18'
    position = theme_settings.get('background_position', 'center')
    if position not in BACKGROUND_POSITIONS: position = 'center'
    effect = theme_settings.get('background_effect', 'none')
    if effect not in BACKGROUND_EFFECTS: effect = 'none'
    support_posts = db().execute("SELECT * FROM support_posts ORDER BY id DESC LIMIT 3").fetchall()
    avatar = None
    if session.get('user_id'):
        row = db().execute("SELECT avatar_filename FROM users WHERE id=?", (session['user_id'],)).fetchone()
        avatar = row['avatar_filename'] if row else None
    unread_notices = 0
    if session.get('user_id') and session.get('role') != 'admin':
        unread_notices = db().execute("SELECT COUNT(*) FROM notices n LEFT JOIN notice_reads r ON r.notice_id=n.id AND r.user_id=? WHERE r.notice_id IS NULL", (session['user_id'],)).fetchone()[0]
    return {"current_user": session.get("name"), "current_role": session.get("role"), "current_avatar": avatar, "unread_notices": unread_notices, "sidebar_subjects": subjects, "support_posts": support_posts, "site_theme": theme_settings.get('theme', 'default'), "site_background": theme_settings.get('background', ''), "site_background_enabled": theme_settings.get('background_enabled', '0') == '1', "site_accent": accent, "site_appearance_mode": mode, "site_background_opacity": opacity, "site_background_position": position, "site_background_effect": effect, "support_facebook": theme_settings.get('support_facebook', ''), "support_phone": theme_settings.get('support_phone', ''), "support_email": theme_settings.get('support_email', 'hello@edunova.vn')}


@app.route("/")
def home():
    conn = db()
    selected_subject = request.args.get("subject_id", type=int)
    selected_week = request.args.get("week", type=int)
    all_subjects = conn.execute("SELECT id,name FROM subjects ORDER BY name").fetchall()
    subjects = subjects_with_counts(conn, selected_subject, selected_week)
    weeks = conn.execute("SELECT DISTINCT week FROM questions ORDER BY week").fetchall()
    attempts = conn.execute("SELECT a.*,s.name subject FROM attempts a JOIN subjects s ON s.id=a.subject_id WHERE a.user_id=? ORDER BY a.id DESC LIMIT 5", (session.get("user_id", -1),)).fetchall()
    all_attempt_dates = conn.execute("SELECT created_at FROM attempts WHERE user_id=?", (session.get("user_id", -1),)).fetchall()
    stats = {"subjects": len(all_subjects), "questions": conn.execute("SELECT COUNT(*) FROM questions").fetchone()[0], "attempts": conn.execute("SELECT COUNT(*) FROM attempts WHERE user_id=?", (session.get("user_id", -1),)).fetchone()[0]}
    today_label = datetime.now(VIETNAM_TZ).strftime("%A, %d/%m/%Y").replace("Monday", "Thứ hai").replace("Tuesday", "Thứ ba").replace("Wednesday", "Thứ tư").replace("Thursday", "Thứ năm").replace("Friday", "Thứ sáu").replace("Saturday", "Thứ bảy").replace("Sunday", "Chủ nhật")
    return render_template("home.html", subjects=subjects, all_subjects=all_subjects, weeks=weeks, selected_subject=selected_subject, selected_week=selected_week, attempts=attempts, stats=stats, streak_days=study_streak(all_attempt_dates), today_label=today_label)


@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        name, email, password = request.form.get("name", "").strip(), request.form.get("email", "").strip().lower(), request.form.get("password", "")
        if not name or not email or len(password) < 6:
            flash("Vui lòng điền đủ thông tin. Mật khẩu cần ít nhất 6 ký tự.", "error")
        else:
            try:
                db().execute("INSERT INTO users(name,email,password) VALUES(?,?,?)", (name, email, generate_password_hash(password)))
                db().commit()
                flash("Tạo tài khoản thành công. Hãy đăng nhập nhé!", "success")
                return redirect(url_for("login"))
            except sqlite3.IntegrityError:
                flash("Email này đã được đăng ký.", "error")
    return render_template("auth.html", mode="register")


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        user = db().execute("SELECT * FROM users WHERE email=?", (request.form.get("email", "").strip().lower(),)).fetchone()
        if user and user["active"] and check_password_hash(user["password"], request.form.get("password", "")):
            session.clear()
            session.update(user_id=user["id"], name=user["name"], role=user["role"])
            return redirect(url_for("admin_dashboard" if user["role"] == "admin" else "home"))
        flash("Email hoặc mật khẩu chưa chính xác, hoặc tài khoản đang bị khóa.", "error")
    return render_template("auth.html", mode="login")


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("home"))


@app.route("/profile", methods=["GET", "POST"])
@login_required
def profile():
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        current_password = request.form.get("current_password", "")
        new_password = request.form.get("new_password", "")
        confirm_password = request.form.get("confirm_password", "")
        user = db().execute("SELECT * FROM users WHERE id=?", (session["user_id"],)).fetchone()
        if new_password and (not check_password_hash(user['password'], current_password) or len(new_password) < 6 or new_password != confirm_password):
            flash("Mật khẩu hiện tại không đúng, hoặc mật khẩu mới chưa hợp lệ (ít nhất 6 ký tự).", "error")
        else:
            avatar = request.files.get('avatar')
            avatar_filename = user['avatar_filename']
            if avatar and avatar.filename:
                saved, _original = save_upload(avatar, 'avatar', {"png", "jpg", "jpeg", "gif", "webp"})
                if not saved:
                    flash("Ảnh đại diện chỉ hỗ trợ PNG, JPG, GIF hoặc WEBP.", "error")
                    return redirect(url_for('profile'))
                if avatar_filename:
                    (UPLOAD_DIR / avatar_filename).unlink(missing_ok=True)
                avatar_filename = saved
            if name:
                db().execute("UPDATE users SET name=?,avatar_filename=?,password=? WHERE id=?", (name, avatar_filename, generate_password_hash(new_password) if new_password else user['password'], session["user_id"]))
                db().commit()
                session["name"] = name
                flash("Đã cập nhật tài khoản.", "success")
    user = db().execute("SELECT * FROM users WHERE id=?", (session["user_id"],)).fetchone()
    return render_template("profile.html", user=user)


@app.route("/subjects/<int:subject_id>")
def subject_detail(subject_id):
    subject = db().execute("SELECT * FROM subjects WHERE id=?", (subject_id,)).fetchone()
    if not subject:
        abort(404)
    docs = db().execute("SELECT * FROM documents WHERE subject_id=? AND approved=1 ORDER BY id DESC", (subject_id,)).fetchall()
    questions = db().execute("SELECT chapter,COUNT(*) count FROM questions WHERE subject_id=? GROUP BY chapter", (subject_id,)).fetchall()
    weeks = db().execute("SELECT week,COUNT(*) count FROM questions WHERE subject_id=? GROUP BY week ORDER BY week", (subject_id,)).fetchall()
    resources = db().execute("SELECT COUNT(*) FROM shared_resources WHERE subject_id=?", (subject_id,)).fetchone()[0]
    return render_template("subject.html", subject=subject, docs=docs, chapters=questions, weeks=weeks, resource_count=resources, can_upload=session.get("role") == "admin")


@app.route("/uploads/<path:filename>")
@login_required
def download_document(filename):
    doc = db().execute("SELECT 1 FROM documents WHERE filename=? AND approved=1", (filename,)).fetchone()
    if not doc:
        abort(404)
    return send_from_directory(UPLOAD_DIR, filename, as_attachment=True)


@app.route("/quiz/<int:subject_id>", methods=["GET", "POST"])
@login_required
def quiz(subject_id):
    conn = db()
    subject = conn.execute("SELECT * FROM subjects WHERE id=?", (subject_id,)).fetchone()
    if not subject:
        abort(404)
    week = request.form.get("week", type=int) if request.method == "POST" else request.args.get("week", type=int)
    week = max(1, week or 1)
    review_attempt_id = request.form.get("review_attempt", type=int) if request.method == "POST" else request.args.get("review_attempt", type=int)
    settings = conn.execute("SELECT * FROM exam_settings WHERE subject_id=? AND week=?", (subject_id, week)).fetchone()
    unlock_key = f"{subject_id}:{week}:{settings['password_hash'] if settings else ''}"
    unlocks = session.get("exam_unlocks", [])
    if request.method == "POST" and request.form.get("action") == "unlock":
        if settings and settings["password_hash"] and check_password_hash(settings["password_hash"], request.form.get("password", "")):
            session["exam_unlocks"] = list(set(unlocks + [unlock_key]))
            flash("Mật khẩu đúng. Bạn có thể bắt đầu làm bài.", "success")
            return redirect(url_for("quiz", subject_id=subject_id, week=week, timed=request.form.get("timed", "0"), random=request.form.get("random", "0"), review_attempt=review_attempt_id))
        flash("Mật khẩu đề thi chưa chính xác.", "error")
    locked = bool(settings and settings["password_hash"] and unlock_key not in unlocks)
    if locked:
        return render_template("exam_password.html", subject=subject, week=week, timed=request.args.get("timed") == "1" or bool(settings and settings["minutes"]), random=request.args.get("random") == "1", review_attempt_id=review_attempt_id)
    if request.method == "POST":
        ids = [int(i) for i in request.form.getlist("question_id")]
        allowed_ids = []
        if review_attempt_id:
            source = conn.execute("SELECT * FROM attempts WHERE id=? AND user_id=?", (review_attempt_id, session["user_id"])).fetchone()
            if not source:
                abort(404)
            allowed_ids = wrong_question_ids(conn, review_attempt_id)
            ids = [qid for qid in ids if qid in allowed_ids]
        questions = conn.execute(f"SELECT * FROM questions WHERE subject_id=? AND week=? AND id IN ({','.join('?' for _ in ids)})", [subject_id, week, *ids]).fetchall() if ids else []
        if not questions:
            flash("Chưa có câu hỏi cho môn học này.", "warning")
            return redirect(url_for("subject_detail", subject_id=subject_id))
        answers = {}
        for q in questions:
            selected = sorted(set(request.form.getlist(f"answer_{q['id']}")))
            answers[q["id"]] = "".join(selected)
        correct = sum(answers[q["id"]] == "".join(sorted(set(q["answer"]))) for q in questions)
        unanswered_count = sum(not answers[q["id"]] for q in questions)
        wrong_answered_count = len(questions) - correct - unanswered_count
        incomplete_count = sum(len(answers[q["id"]]) != len(set(q["answer"])) for q in questions)
        score = round(correct * 10 / len(questions), 1)
        result_week = questions[0]["week"]
        early_exit = request.form.get("exit_early") == "1"
        incomplete_submit = request.form.get("incomplete_submit") == "1"
        title_prefix = "Ôn câu sai" if review_attempt_id else ("Nộp sớm" if early_exit or incomplete_submit else "Luyện tập")
        attempt_cursor = conn.execute("INSERT INTO attempts(user_id,subject_id,title,score,correct,total) VALUES(?,?,?,?,?,?)", (session["user_id"], subject_id, f"{title_prefix} · {subject['name']} · Tuần {result_week}", score, correct, len(questions)))
        attempt_id = attempt_cursor.lastrowid
        for q in questions:
            is_correct = answers[q["id"]] == "".join(sorted(set(q["answer"])))
            conn.execute("INSERT INTO attempt_answers(attempt_id,question_id,selected,is_correct) VALUES(?,?,?,?)", (attempt_id, q["id"], answers[q["id"]], int(is_correct)))
        conn.commit()
        rank = conn.execute("SELECT COUNT(*)+1 FROM (SELECT user_id,AVG(score) avg_score FROM attempts WHERE subject_id=? GROUP BY user_id HAVING avg_score > (SELECT AVG(score) FROM attempts WHERE user_id=? AND subject_id=?))", (subject_id, session["user_id"], subject_id)).fetchone()[0]
        leaderboard = conn.execute("SELECT u.name,ROUND(AVG(a.score),1) avg_score,COUNT(a.id) attempts FROM attempts a JOIN users u ON u.id=a.user_id WHERE a.subject_id=? GROUP BY u.id ORDER BY avg_score DESC,attempts DESC LIMIT 5", (subject_id,)).fetchall()
        if score >= 9:
            feedback = "Xuất sắc! Bạn nắm kiến thức rất vững. Hãy tiếp tục thử sức với đề khó hơn nhé!"
            feedback_type = "excellent"
        elif score >= 7:
            feedback = "Làm tốt lắm! Bạn đã hiểu phần lớn nội dung. Xem lại vài câu sai để tiến gần điểm tuyệt đối."
            feedback_type = "good"
        elif score >= 5:
            feedback = "Bạn đã đạt yêu cầu. Hãy xem lời giải, ôn lại phần còn nhầm và thử làm thêm một đề nữa."
            feedback_type = "average"
        else:
            feedback = "Đừng nản nhé — đây là cơ hội để học thêm. Xem kỹ lời giải rồi ôn lại từng chương trước khi thử lại."
            feedback_type = "encouragement"
        return render_template("result.html", subject=subject, questions=questions, answers=answers, correct=correct, score=score, total=len(questions), timed=request.form.get("timed") == "1", rank=rank, leaderboard=leaderboard, feedback=feedback, feedback_type=feedback_type, week=result_week, attempt_id=attempt_id, wrong_count=len(questions)-correct, wrong_answered_count=wrong_answered_count, unanswered_count=unanswered_count, incomplete_count=incomplete_count, early_exit=early_exit, incomplete_submit=incomplete_submit)
    chapter = request.args.get("chapter")
    sql, params = "SELECT * FROM questions WHERE subject_id=?", [subject_id]
    if week is not None:
        sql += " AND week=?"
        params.append(week)
    if chapter:
        sql += " AND chapter=?"
        params.append(chapter)
    if review_attempt_id:
        source = conn.execute("SELECT * FROM attempts WHERE id=? AND user_id=? AND subject_id=?", (review_attempt_id, session["user_id"], subject_id)).fetchone()
        if not source:
            abort(404)
        allowed_ids = wrong_question_ids(conn, review_attempt_id)
        if not allowed_ids:
            flash("Bài làm này không có câu sai cần ôn lại.", "success")
            return redirect(url_for("history"))
        sql += f" AND id IN ({','.join('?' for _ in allowed_ids)})"
        params.extend(allowed_ids)
    questions = conn.execute(sql, params).fetchall()
    if request.args.get("random") == "1":
        questions = random.sample(questions, min(10, len(questions)))
    if settings and settings["shuffle"]:
        random.shuffle(questions)
    timed = request.args.get("timed") == "1" or bool(settings and settings["minutes"])
    minutes = settings["minutes"] if settings and settings["minutes"] else max(len(questions) * 2, 5)
    return render_template("quiz.html", subject=subject, questions=questions, timed=timed, minutes=minutes, chapter=chapter, week=week, review_attempt_id=review_attempt_id)


@app.route("/attempts/<int:attempt_id>/review-mistakes")
@login_required
def review_mistakes(attempt_id):
    attempt = db().execute("SELECT subject_id,title FROM attempts WHERE id=? AND user_id=?", (attempt_id, session["user_id"])).fetchone()
    if not attempt:
        abort(404)
    week_match = re.search(r"Tuần\s+(\d+)", attempt["title"])
    week = int(week_match.group(1)) if week_match else 1
    return redirect(url_for("quiz", subject_id=attempt["subject_id"], week=week, review_attempt=attempt_id))


@app.route("/resources", methods=["GET", "POST"])
@login_required
def shared_resources():
    conn = db()
    if request.method == "POST":
        subject_id = request.form.get("subject_id", type=int)
        week = max(1, request.form.get("week", 1, type=int) or 1)
        title = request.form.get("title", "").strip()[:120]
        description = request.form.get("description", "").strip()[:500]
        url = request.form.get("url", "").strip()
        upload = request.files.get('resource_file')
        uploaded_name = None
        if upload and upload.filename:
            uploaded_name, _original = save_upload(upload, 'resource', CHAT_FILE_EXTENSIONS)
            if not uploaded_name:
                flash("Tệp không được hỗ trợ. Hãy dùng ảnh, PDF, DOCX, TXT hoặc ZIP.", "error")
                return redirect(url_for('shared_resources'))
            url = url_for('resource_media', filename=uploaded_name)
        parsed = urlparse(url)
        if not conn.execute("SELECT 1 FROM subjects WHERE id=?", (subject_id,)).fetchone():
            flash("Hãy chọn môn học hợp lệ.", "error")
        elif not title or (not uploaded_name and (parsed.scheme not in {"http", "https"} or not parsed.netloc)):
            flash("Nhập tiêu đề và chọn tệp hoặc dán liên kết hợp lệ.", "error")
        else:
            conn.execute("INSERT INTO shared_resources(user_id,subject_id,week,title,description,url) VALUES(?,?,?,?,?,?)", (session["user_id"], subject_id, week, title, description, url))
            conn.commit()
            flash("Đã chia sẻ tài liệu với cộng đồng học tập.", "success")
            return redirect(url_for("shared_resources", subject_id=subject_id, week=week))
    subject_id = request.args.get("subject_id", type=int)
    week = request.args.get("week", type=int)
    sql = "SELECT r.*,u.name,s.name subject,s.icon,s.color FROM shared_resources r JOIN users u ON u.id=r.user_id JOIN subjects s ON s.id=r.subject_id WHERE 1=1"
    params = []
    if subject_id:
        sql += " AND r.subject_id=?"
        params.append(subject_id)
    if week:
        sql += " AND r.week=?"
        params.append(week)
    sql += " ORDER BY r.id DESC LIMIT 100"
    resources = conn.execute(sql, params).fetchall()
    subjects = conn.execute("SELECT id,name FROM subjects ORDER BY name").fetchall()
    weeks = conn.execute("SELECT DISTINCT week FROM questions ORDER BY week").fetchall()
    return render_template("resources.html", resources=resources, subjects=subjects, weeks=weeks, selected_subject=subject_id, selected_week=week)


@app.route('/resource-media/<path:filename>')
@login_required
def resource_media(filename):
    filename = Path(filename).name
    row = db().execute("SELECT 1 FROM shared_resources WHERE url LIKE ?", (f'%{filename}',)).fetchone()
    if not row: abort(404)
    return send_from_directory(UPLOAD_DIR, filename)


@app.route("/chat")
@login_required
def chat_room():
    return render_template("chat.html")


@app.route("/chatbot")
@login_required
def chatbot():
    return render_template("chatbot.html")


@app.route("/api/chatbot", methods=["POST"])
@login_required
def chatbot_api():
    message = str((request.get_json(silent=True) or {}).get("message", "")).strip().lower()
    if not message or len(message) > 500:
        return jsonify(error="Hãy nhập câu hỏi từ 1 đến 500 ký tự."), 400
    if any(word in message for word in ("mật khẩu", "đăng nhập", "tài khoản")):
        answer, link, label = "Bạn có thể vào Tài khoản của bạn để đổi mật khẩu hoặc ảnh đại diện.", url_for("profile"), "Mở tài khoản"
    elif any(word in message for word in ("đề thi", "thi", "quiz", "làm bài")):
        answer, link, label = "Chọn một môn học ở trang chủ, sau đó chọn tuần và bắt đầu làm đề. Một số đề có mật khẩu hoặc giới hạn thời gian.", url_for("home"), "Chọn môn học"
    elif any(word in message for word in ("tài liệu", "file", "tệp")):
        answer, link, label = "Bạn có thể xem tài liệu cộng đồng, tải tệp hoặc chia sẻ liên kết trong khu Chia sẻ tài liệu.", url_for("shared_resources"), "Mở tài liệu"
    elif any(word in message for word in ("thông báo", "tin mới")):
        answer, link, label = "Thông báo mới nằm ở biểu tượng chuông trên thanh đầu trang. Mở trang Thông báo để xem toàn bộ nội dung.", url_for("notices"), "Xem thông báo"
    elif any(word in message for word in ("hỗ trợ", "liên hệ", "facebook", "email", "số điện thoại")):
        answer, link, label = "Bấm nút Cần trợ giúp ở đáy thanh bên để xem số điện thoại, email và Facebook của đội ngũ hỗ trợ.", None, None
    else:
        answer, link, label = "Mình có thể hỗ trợ về đề thi, tài liệu, thông báo, tài khoản và liên hệ hỗ trợ. Bạn muốn tìm hiểu phần nào?", None, None
    return jsonify(answer=answer, link=link, label=label)


@app.route("/api/chat", methods=["GET", "POST"])
@login_required
def chat_api():
    conn = db()
    if request.method == "POST":
        payload = request.get_json(silent=True) or request.form
        message = str(payload.get("message", "")).strip()
        attachment = request.files.get('attachment')
        filename = original = None
        if attachment and attachment.filename:
            filename, original = save_upload(attachment, 'chat', CHAT_FILE_EXTENSIONS)
            if not filename:
                return jsonify(error="Tệp không được hỗ trợ. Dùng ảnh, PDF, DOCX, TXT hoặc ZIP."), 400
        if (not message and not filename) or len(message) > 500:
            return jsonify(error="Hãy nhập tin nhắn hoặc đính kèm tệp; tin nhắn tối đa 500 ký tự."), 400
        cur = conn.execute("INSERT INTO general_chat_messages(user_id,message,attachment_filename,attachment_original) VALUES(?,?,?,?)", (session["user_id"], message, filename, original))
        conn.commit()
        row = chat_message_row(conn, cur.lastrowid)
        return jsonify(row), 201
    after_id = request.args.get("after", 0, type=int)
    rows = conn.execute("SELECT id FROM general_chat_messages WHERE id>? ORDER BY id ASC LIMIT 100", (after_id,)).fetchall()
    return jsonify([chat_message_row(conn, row['id']) for row in rows])


def chat_message_row(conn, message_id):
    row = conn.execute("SELECT m.id,m.user_id,m.message,m.attachment_filename,m.attachment_original,m.created_at,u.name,u.avatar_filename FROM general_chat_messages m JOIN users u ON u.id=m.user_id WHERE m.id=?", (message_id,)).fetchone()
    item = dict(row)
    reactions = conn.execute("SELECT emoji,COUNT(*) count,MAX(user_id=?) mine FROM chat_reactions WHERE message_id=? GROUP BY emoji", (session['user_id'], message_id)).fetchall()
    item['reactions'] = [dict(r) for r in reactions]
    item['attachment_url'] = url_for('chat_media', filename=item['attachment_filename']) if item['attachment_filename'] else None
    return item


@app.route('/api/chat/<int:message_id>/reaction', methods=['POST'])
@login_required
def chat_reaction(message_id):
    emoji = str((request.get_json(silent=True) or {}).get('emoji', ''))
    if emoji not in {'❤️', '👍', '😂', '🎉', '😮'}:
        return jsonify(error='Phản ứng không hợp lệ.'), 400
    conn = db()
    exists = conn.execute('SELECT 1 FROM general_chat_messages WHERE id=?', (message_id,)).fetchone()
    if not exists: abort(404)
    existing = conn.execute('SELECT id FROM chat_reactions WHERE message_id=? AND user_id=? AND emoji=?', (message_id, session['user_id'], emoji)).fetchone()
    if existing: conn.execute('DELETE FROM chat_reactions WHERE id=?', (existing['id'],))
    else: conn.execute('INSERT INTO chat_reactions(message_id,user_id,emoji) VALUES(?,?,?)', (message_id, session['user_id'], emoji))
    conn.commit()
    return jsonify(chat_message_row(conn, message_id))


@app.route('/chat-media/<path:filename>')
@login_required
def chat_media(filename):
    filename = Path(filename).name
    allowed = db().execute('SELECT 1 FROM general_chat_messages WHERE attachment_filename=? UNION SELECT 1 FROM support_posts WHERE filename=? UNION SELECT 1 FROM users WHERE avatar_filename=?', (filename, filename, filename)).fetchone()
    if not allowed: abort(404)
    return send_from_directory(UPLOAD_DIR, filename)


@app.route("/history")
@login_required
def history():
    subject_id = request.args.get('subject_id', type=int)
    conn = db()
    sql = "SELECT a.*,s.name subject,s.icon,s.color FROM attempts a JOIN subjects s ON s.id=a.subject_id WHERE a.user_id=?"
    params = [session['user_id']]
    if subject_id:
        sql += ' AND a.subject_id=?'
        params.append(subject_id)
    attempts = conn.execute(sql + " ORDER BY a.id DESC", params).fetchall()
    subjects = conn.execute("SELECT DISTINCT s.id,s.name,s.icon,s.color FROM subjects s JOIN attempts a ON a.subject_id=s.id WHERE a.user_id=? ORDER BY s.name", (session['user_id'],)).fetchall()
    return render_template("history.html", attempts=attempts, subjects=subjects, selected_subject=subject_id)


@app.route("/leaderboard")
@login_required
def leaderboard():
    subject_id = request.args.get("subject_id", type=int)
    conn = db()
    subjects = conn.execute("SELECT id,name FROM subjects ORDER BY name").fetchall()
    if subject_id is None and subjects:
        subject_id = subjects[0]["id"]
    subject = conn.execute("SELECT * FROM subjects WHERE id=?", (subject_id,)).fetchone() if subject_id else None
    leaders = conn.execute("SELECT u.id,u.name,ROUND(AVG(a.score),1) avg_score,COUNT(a.id) attempts,MAX(a.score) best_score FROM attempts a JOIN users u ON u.id=a.user_id WHERE a.subject_id=? GROUP BY u.id ORDER BY avg_score DESC,attempts DESC,best_score DESC LIMIT 50", (subject_id,)).fetchall() if subject else []
    return render_template("leaderboard.html", subjects=subjects, subject=subject, leaders=leaders)


@app.route("/admin")
@admin_required
def admin_dashboard():
    conn = db()
    stats = {"users": conn.execute("SELECT COUNT(*) FROM users WHERE role='student'").fetchone()[0], "subjects": conn.execute("SELECT COUNT(*) FROM subjects").fetchone()[0], "questions": conn.execute("SELECT COUNT(*) FROM questions").fetchone()[0], "attempts": conn.execute("SELECT COUNT(*) FROM attempts").fetchone()[0]}
    recent = conn.execute("SELECT a.*,u.name,s.name subject FROM attempts a JOIN users u ON u.id=a.user_id JOIN subjects s ON s.id=a.subject_id ORDER BY a.id DESC LIMIT 5").fetchall()
    pending = conn.execute("SELECT d.*,s.name subject FROM documents d JOIN subjects s ON s.id=d.subject_id WHERE d.approved=0").fetchall()
    return render_template("admin.html", stats=stats, recent=recent, pending=pending)


@app.route("/admin/users", methods=["GET", "POST"])
@admin_required
def admin_users():
    conn = db()
    if request.method == "POST":
        action, user_id = request.form.get("action"), request.form.get("user_id", type=int)
        if action == "role" and user_id != session["user_id"]:
            conn.execute("UPDATE users SET role=? WHERE id=?", (request.form.get("role"), user_id))
        elif action == "toggle" and user_id != session["user_id"]:
            conn.execute("UPDATE users SET active=1-active WHERE id=?", (user_id,))
        elif action == "add":
            try:
                conn.execute("INSERT INTO users(name,email,password,role) VALUES(?,?,?,?)", (request.form.get("name"), request.form.get("email", "").lower(), generate_password_hash(request.form.get("password", "123456")), request.form.get("role", "student")))
            except sqlite3.IntegrityError:
                flash("Email đã tồn tại.", "error")
        conn.commit()
    users = conn.execute("SELECT u.*,COUNT(a.id) attempt_count FROM users u LEFT JOIN attempts a ON a.user_id=u.id GROUP BY u.id ORDER BY u.id DESC").fetchall()
    return render_template("admin_users.html", users=users)


@app.route("/admin/subjects", methods=["GET", "POST"])
@admin_required
def admin_subjects():
    conn = db()
    selected_subject = request.args.get("subject_id", type=int)
    selected_week = request.args.get("week", type=int)
    if request.method == "POST":
        action = request.form.get("action")
        if action == "delete":
            conn.execute("DELETE FROM subjects WHERE id=?", (request.form.get("id", type=int),))
        else:
            data = (request.form.get("name"), request.form.get("level"), request.form.get("icon", "📘"), request.form.get("color", "blue"), request.form.get("description", ""), request.form.get("lessons", 0, type=int))
            if request.form.get("id", type=int):
                conn.execute("UPDATE subjects SET name=?,level=?,icon=?,color=?,description=?,lessons=? WHERE id=?", (*data, request.form.get("id", type=int)))
            else:
                conn.execute("INSERT INTO subjects(name,level,icon,color,description,lessons) VALUES(?,?,?,?,?,?)", data)
        conn.commit()
    if request.method == "POST":
        selected_subject = selected_subject or request.form.get("subject_filter", type=int)
        selected_week = selected_week or request.form.get("week_filter", type=int)
    all_subjects = conn.execute("SELECT id,name FROM subjects ORDER BY name").fetchall()
    weeks = conn.execute("SELECT DISTINCT week FROM questions ORDER BY week").fetchall()
    subjects = subjects_with_counts(conn, selected_subject, selected_week, order="s.name")
    return render_template("admin_subjects.html", subjects=subjects, all_subjects=all_subjects, weeks=weeks, selected_subject=selected_subject, selected_week=selected_week)


@app.route("/admin/questions", methods=["GET", "POST"])
@admin_required
def admin_questions():
    conn = db()
    selected_subject = request.args.get("subject_id", type=int)
    if request.method == "POST":
        action, qid = request.form.get("action"), request.form.get("id", type=int)
        selected_subject = selected_subject or request.form.get("subject_id", type=int)
        if action == "delete":
            conn.execute("DELETE FROM questions WHERE id=?", (qid,))
        else:
            vals = (request.form.get("subject_id", type=int), request.form.get("chapter"), request.form.get("question"), request.form.get("a"), request.form.get("b"), request.form.get("c"), request.form.get("d"), request.form.get("answer"), request.form.get("explanation", ""))
            if qid:
                conn.execute("UPDATE questions SET subject_id=?,chapter=?,question=?,a=?,b=?,c=?,d=?,answer=?,explanation=? WHERE id=?", (*vals, qid))
            else:
                conn.execute("INSERT INTO questions(subject_id,chapter,question,a,b,c,d,answer,explanation) VALUES(?,?,?,?,?,?,?,?,?)", vals)
        conn.commit()
    subjects = conn.execute("SELECT * FROM subjects ORDER BY name").fetchall()
    sql = "SELECT q.*,s.name subject FROM questions q JOIN subjects s ON s.id=q.subject_id"
    params = []
    if selected_subject:
        sql += " WHERE q.subject_id=?"
        params.append(selected_subject)
    questions = conn.execute(sql + " ORDER BY q.id DESC", params).fetchall()
    return render_template("admin_questions.html", subjects=subjects, questions=questions, selected_subject=selected_subject)


@app.route("/admin/documents", methods=["POST"])
@admin_required
def admin_document_action():
    doc_id = request.form.get("id", type=int)
    if request.form.get("action") == "approve":
        db().execute("UPDATE documents SET approved=1 WHERE id=?", (doc_id,))
    else:
        row = db().execute("SELECT filename FROM documents WHERE id=?", (doc_id,)).fetchone()
        if row:
            (UPLOAD_DIR / row["filename"]).unlink(missing_ok=True)
            db().execute("DELETE FROM documents WHERE id=?", (doc_id,))
    db().commit()
    return redirect(request.referrer or url_for("admin_documents"))


@app.route("/admin/documents", methods=["GET"])
@admin_required
def admin_documents():
    conn = db()
    docs = conn.execute("SELECT d.*,s.name subject,u.name uploader FROM documents d JOIN subjects s ON s.id=d.subject_id LEFT JOIN users u ON u.id=d.uploaded_by ORDER BY d.id DESC").fetchall()
    subjects = conn.execute("SELECT id,name FROM subjects ORDER BY name").fetchall()
    return render_template("admin_documents.html", docs=docs, subjects=subjects)


@app.route("/admin/exams", methods=["GET", "POST"])
@admin_required
def admin_exams():
    conn = db()
    if request.method == "POST":
        subject_id = request.form.get("subject_id", type=int)
        week = request.form.get("week", 1, type=int)
        minutes = request.form.get("minutes", 0, type=int)
        shuffle = int(request.form.get("shuffle") == "1")
        subject = conn.execute("SELECT id FROM subjects WHERE id=?", (subject_id,)).fetchone()
        if not subject or not week or week < 1 or minutes < 0 or minutes > 300:
            flash("Kiểm tra lại môn học, tuần và thời lượng (tối đa 300 phút).", "error")
        else:
            existing = conn.execute("SELECT password_hash FROM exam_settings WHERE subject_id=? AND week=?", (subject_id, week)).fetchone()
            password_hash = existing["password_hash"] if existing else None
            password = request.form.get("password", "").strip()
            if password and len(password) < 4:
                flash("Mật khẩu đề thi cần ít nhất 4 ký tự.", "error")
            elif request.form.get("clear_password") == "1":
                password_hash = None
            elif password:
                password_hash = generate_password_hash(password)
            if not password or len(password) >= 4:
                conn.execute("INSERT INTO exam_settings(subject_id,week,minutes,shuffle,password_hash) VALUES(?,?,?,?,?) ON CONFLICT(subject_id,week) DO UPDATE SET minutes=excluded.minutes,shuffle=excluded.shuffle,password_hash=excluded.password_hash", (subject_id, week, minutes, shuffle, password_hash))
                conn.commit()
                flash("Đã lưu cài đặt đề thi.", "success")
                return redirect(url_for("admin_exams"))
    subjects = conn.execute("SELECT * FROM subjects ORDER BY name").fetchall()
    settings = conn.execute("SELECT e.*,s.name subject,(SELECT COUNT(*) FROM questions q WHERE q.subject_id=e.subject_id AND q.week=e.week) question_count FROM exam_settings e JOIN subjects s ON s.id=e.subject_id ORDER BY s.name,e.week").fetchall()
    return render_template("admin_exams.html", subjects=subjects, settings=settings)


@app.route("/admin/exams/<int:setting_id>/delete", methods=["POST"])
@admin_required
def admin_exam_delete(setting_id):
    db().execute("DELETE FROM exam_settings WHERE id=?", (setting_id,))
    db().commit()
    flash("Đã xóa cài đặt riêng. Đề sẽ dùng cài đặt mặc định.", "success")
    return redirect(url_for("admin_exams"))


@app.route("/admin/documents/upload", methods=["POST"])
@admin_required
def admin_upload_document():
    file = request.files.get("file")
    subject_id = request.form.get("subject_id", type=int)
    subject = db().execute("SELECT id FROM subjects WHERE id=?", (subject_id,)).fetchone()
    if not subject:
        flash("Vui lòng chọn môn học hợp lệ.", "error")
        return redirect(url_for("admin_documents"))
    if not file or not file.filename or "." not in file.filename or file.filename.rsplit(".", 1)[1].lower() not in ALLOWED_EXTENSIONS:
        flash("Chỉ hỗ trợ tài liệu PDF hoặc DOCX.", "error")
        return redirect(url_for("admin_documents"))
    safe_name = secure_filename(file.filename)
    saved = f"{datetime.now().strftime('%Y%m%d%H%M%S%f')}_{safe_name}"
    file.save(UPLOAD_DIR / saved)
    conn = db()
    week = max(1, request.form.get("week", 1, type=int))
    cur = conn.execute("INSERT INTO documents(subject_id,title,filename,uploaded_by,approved,week) VALUES(?,?,?,?,1,?)", (subject_id, safe_name, saved, session["user_id"], week))
    doc_id = cur.lastrowid
    media_files = []
    try:
        extracted = extract_questions(UPLOAD_DIR / saved)
        for q_index, q in enumerate(extracted, 1):
            image_filename = None
            if q.get("image_blob"):
                image_filename = f"question_{doc_id}_{q_index}.{secure_filename(q.get('image_ext', 'png'))}"
                (UPLOAD_DIR / image_filename).write_bytes(q["image_blob"])
                media_files.append(image_filename)
            conn.execute("INSERT INTO questions(subject_id,chapter,question,a,b,c,d,answer,explanation,multi_select,week,image_filename) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)", (subject_id, f"Tuần {week}", q["question"], q["A"], q["B"], q["C"], q["D"], q["answer"], q["explanation"], len(q["answer"]) > 1, week, image_filename))
        conn.execute("UPDATE documents SET imported_questions=? WHERE id=?", (len(extracted), doc_id))
        conn.commit()
        if extracted:
            flash(f"Đã tải tài liệu và nhập {len(extracted)} câu trắc nghiệm vào ngân hàng môn học.", "success")
        else:
            flash("Tài liệu đã được lưu. Chưa tìm thấy câu hỏi theo mẫu; dùng mẫu: Câu hỏi, A./B./C./D., Đáp án: A, Giải thích: ...", "warning")
    except Exception as exc:
        conn.rollback()
        conn.execute("DELETE FROM documents WHERE id=?", (doc_id,))
        conn.commit()
        (UPLOAD_DIR / saved).unlink(missing_ok=True)
        for media_file in media_files:
            (UPLOAD_DIR / media_file).unlink(missing_ok=True)
        app.logger.exception("Không thể xử lý tài liệu trắc nghiệm")
        flash("Không đọc được tài liệu. Hãy dùng DOCX hoặc PDF có văn bản (không phải PDF scan).", "error")
    return redirect(url_for("admin_documents"))


@app.route("/question-media/<path:filename>")
@login_required
def question_media(filename):
    row = db().execute("SELECT 1 FROM questions WHERE image_filename=?", (filename,)).fetchone()
    if not row:
        abort(404)
    return send_from_directory(UPLOAD_DIR, filename)


def extract_questions(path: Path):
    """Read text based PDF/DOCX and parse the documented plain text quiz format."""
    if path.suffix.lower() == ".docx":
        from docx import Document
        source_doc = Document(path)
        image_parts = {}
        lines, marked, has_answer = [], [], False
        for paragraph in source_doc.paragraphs:
            line = paragraph.text.strip()
            if _RE_QUESTION_LABEL.match(line):
                if marked and not has_answer:
                    lines.append("Đáp án: " + ", ".join(marked))
                marked, has_answer = [], False
            if line:
                lines.append(line)
                if _RE_ANSWER_MARK.match(line):
                    has_answer = True
                option = _RE_OPTION_PREFIX.match(line)
                if option and any(run.font.color and run.font.color.type and run.font.color.rgb and str(run.font.color.rgb).upper() in _RED_RGB for run in paragraph.runs):
                    marked.append(option.group(1).upper())
            for blip in paragraph._p.xpath('.//a:blip'):
                rel_id = blip.get('{http://schemas.openxmlformats.org/officeDocument/2006/relationships}embed')
                if rel_id:
                    part = source_doc.part.related_parts[rel_id]
                    key = len(image_parts) + 1
                    ext = part.content_type.split('/')[-1].replace('jpeg', 'jpg')
                    image_parts[key] = (part.blob, ext)
                    lines.append(f"__IMAGE_{key}__")
        if marked and not has_answer:
            lines.append("Đáp án: " + ", ".join(marked))
        text = "\n".join(lines)
    else:
        import fitz
        image_parts = {}
        with fitz.open(path) as pdf:
            text = "\n".join(page.get_text() for page in pdf)
    text = text.replace("\r", "\n")
    # Split on question labels; accept Câu 1, Câu hỏi 1, Question 1.
    chunks = _RE_CHUNK_SPLIT.split(text)
    output = []
    for chunk in chunks:
        if not _RE_CHUNK_HEAD.match(chunk):
            continue
        lines = [_RE_WHITESPACE.sub(" ", line).strip() for line in chunk.splitlines() if line.strip()]
        question_line = lines[0]
        question = _RE_QUESTION_STRIP.sub("", question_line).strip()
        # If the question text follows on a separate line, join it before options.
        option_at = next((i for i, line in enumerate(lines[1:], 1) if _RE_OPTION_PREFIX.match(line)), None)
        if option_at is None:
            continue
        if not question:
            question = " ".join(lines[1:option_at])
        else:
            question = " ".join([question] + lines[1:option_at])
        options = {}
        answer = ""
        explanation = ""
        chapter = "Tài liệu"
        for line in lines[option_at:]:
            match = _RE_OPTION_FULL.match(line)
            if match:
                options[match.group(1).upper()] = match.group(2).strip()
                continue
            match = _RE_ANSWER_LINE.match(line)
            if match:
                answer = "".join(re.findall(r"[A-D]", match.group(1).upper()))
                tail = line[match.end():].strip()
                if tail:
                    explanation = tail
                continue
            match = _RE_EXPLANATION.match(line)
            if match:
                explanation = match.group(1).strip()
                continue
            match = _RE_CHAPTER.match(line)
            if match:
                chapter = match.group(1).strip()
        if question and len(options) == 4 and answer:
            image_match = _RE_IMAGE_REF.search(chunk)
            question = _RE_IMAGE_REF.sub("", question).strip()
            item = {"chapter": chapter, "question": question, **options, "answer": answer, "explanation": explanation or ""}
            if image_match and int(image_match.group(1)) in image_parts:
                item["image_blob"], item["image_ext"] = image_parts[int(image_match.group(1))]
            output.append(item)
    return output


@app.route("/admin/notices", methods=["GET", "POST"])
@admin_required
def admin_notices():
    conn = db()
    if request.method == "POST":
        if request.form.get("action") == "delete":
            conn.execute("DELETE FROM notices WHERE id=?", (request.form.get("id", type=int),))
        else:
            conn.execute("INSERT INTO notices(title,body) VALUES(?,?)", (request.form.get("title"), request.form.get("body")))
        conn.commit()
    notices = conn.execute("SELECT * FROM notices ORDER BY id DESC").fetchall()
    return render_template("admin_notices.html", notices=notices)


@app.route("/notices")
def notices():
    conn = db()
    items = conn.execute("SELECT * FROM notices ORDER BY id DESC").fetchall()
    if session.get('user_id') and session.get('role') != 'admin':
        conn.executemany("INSERT OR IGNORE INTO notice_reads(user_id,notice_id) VALUES(?,?)", [(session['user_id'], item['id']) for item in items])
        conn.commit()
    return render_template("notices.html", notices=items)


@app.route("/feedback", methods=["POST"])
def submit_feedback():
    name = (request.form.get("name") or session.get("name") or "Khách").strip()[:80]
    email = (request.form.get("email") or "").strip()[:160]
    message = (request.form.get("message") or "").strip()
    if len(message) < 5:
        flash("Vui lòng nhập góp ý từ 5 ký tự trở lên.", "warning")
    else:
        conn = db()
        conn.execute("INSERT INTO feedback(user_id,name,email,message) VALUES(?,?,?,?)", (session.get("user_id"), name, email, message[:3000]))
        conn.commit()
        flash("Cảm ơn bạn! Góp ý đã được gửi đến đội ngũ EduNova.", "success")
    return redirect(request.referrer or url_for("home"))


@app.route("/admin/feedback", methods=["GET", "POST"])
@admin_required
def admin_feedback():
    conn = db()
    if request.method == "POST":
        feedback_id = request.form.get("id", type=int)
        action = request.form.get("action")
        if action == "delete":
            conn.execute("DELETE FROM feedback WHERE id=?", (feedback_id,))
        else:
            conn.execute("UPDATE feedback SET status='Đã xem' WHERE id=?", (feedback_id,))
        conn.commit()
    items = conn.execute("SELECT * FROM feedback ORDER BY id DESC").fetchall()
    return render_template("admin_feedback.html", items=items)


@app.route("/admin/appearance", methods=["GET", "POST"])
@admin_required
def admin_appearance():
    conn = db()
    allowed_themes = {"default", "spring", "summer", "autumn", "winter", "tet", "christmas"}
    settings = {row['key']: row['value'] for row in conn.execute("SELECT key,value FROM site_settings")}
    if request.method == "POST":
        action = request.form.get("action", "save")
        if action == "restore_defaults":
            old_image = settings.get("background", "")
            if old_image and not old_image.startswith("preset:"):
                (UPLOAD_DIR / old_image).unlink(missing_ok=True)
            conn.execute("DELETE FROM site_settings WHERE key IN ('theme','background','background_enabled','accent','appearance_mode','background_opacity','background_position','background_effect')")
            conn.commit()
            flash("Đã khôi phục giao diện mặc định EduNova.", "success")
            return redirect(url_for("admin_appearance"))
        elif action == "remove_background":
            old_image = settings.get("background", "")
            if old_image:
                (UPLOAD_DIR / old_image).unlink(missing_ok=True)
            conn.execute("DELETE FROM site_settings WHERE key='background'")
            upsert_setting(conn, 'background_enabled', '0')
        else:
            upsert_setting(conn, 'background_enabled', '1' if request.form.get('background_enabled') == '1' else '0')
            appearance_options = {
                'accent': (request.form.get('accent', 'purple'), ACCENT_COLORS),
                'appearance_mode': (request.form.get('appearance_mode', 'light'), APPEARANCE_MODES),
                'background_opacity': (request.form.get('background_opacity', '18'), OPACITY_VALUES),
                'background_position': (request.form.get('background_position', 'center'), BACKGROUND_POSITIONS),
                'background_effect': (request.form.get('background_effect', 'none'), BACKGROUND_EFFECTS),
            }
            for key, (value, allowed) in appearance_options.items():
                if value not in allowed: value = next(iter(sorted(allowed)))
                upsert_setting(conn, key, value)
            facebook = request.form.get('support_facebook', '').strip()[:300]
            phone = request.form.get('support_phone', '').strip()[:40]
            email = request.form.get('support_email', '').strip()[:160]
            support_error = validate_support_settings(facebook, phone, email)
            if support_error:
                flash(support_error, "error")
                conn.rollback()
                return redirect(url_for("admin_appearance"))
            for key, value in [('support_facebook',facebook),('support_phone',phone),('support_email',email)]:
                upsert_setting(conn, key, value)
            preset = request.form.get('background_preset', '')
            if preset in SEASONAL_PRESETS:
                upsert_setting(conn, 'theme', preset)
                old_image = settings.get('background', '')
                if old_image and not old_image.startswith('preset:'):
                    (UPLOAD_DIR / old_image).unlink(missing_ok=True)
                upsert_setting(conn, 'background', f'preset:{preset}')
                upsert_setting(conn, 'background_enabled', '1')
            image = request.files.get("background_file")
            if image and image.filename:
                ext = image.filename.rsplit('.', 1)[-1].lower() if '.' in image.filename else ''
                if ext not in BACKGROUND_IMAGE_EXTS:
                    flash("Ảnh nền chỉ hỗ trợ PNG, JPG, WEBP hoặc GIF.", "error")
                    conn.rollback()
                    return redirect(url_for("admin_appearance"))
                old_image = settings.get("background", "")
                safe_image = secure_filename(image.filename)
                filename = f"background_{datetime.now().strftime('%Y%m%d%H%M%S%f')}_{safe_image}"
                image.save(UPLOAD_DIR / filename)
                upsert_setting(conn, 'background', filename)
                if old_image:
                    (UPLOAD_DIR / old_image).unlink(missing_ok=True)
                upsert_setting(conn, 'background_enabled', '1')
        conn.commit()
        flash("Đã cập nhật giao diện cho toàn bộ hệ thống.", "success")
        return redirect(url_for("admin_appearance"))
    settings = {row['key']: row['value'] for row in conn.execute("SELECT key,value FROM site_settings")}
    return render_template("admin_appearance.html", settings=settings)


@app.route("/admin/support-settings", methods=["POST"])
@admin_required
def admin_support_settings():
    facebook = request.form.get('support_facebook', '').strip()[:300]
    phone = request.form.get('support_phone', '').strip()[:40]
    email = request.form.get('support_email', '').strip()[:160]
    error = validate_support_settings(facebook, phone, email)
    if error:
        flash(error, "error")
    else:
        conn = db()
        for key, value in [('support_facebook',facebook),('support_phone',phone),('support_email',email)]:
            upsert_setting(conn, key, value)
        conn.commit()
        flash("Đã cập nhật kênh liên hệ hỗ trợ cho khách.", "success")
    return redirect(request.referrer or url_for('admin_dashboard'))


@app.route('/admin/support', methods=['GET', 'POST'])
@admin_required
def admin_support():
    conn = db()
    if request.method == 'POST':
        action = request.form.get('action')
        if action == 'delete':
            item = conn.execute('SELECT filename FROM support_posts WHERE id=?', (request.form.get('id', type=int),)).fetchone()
            if item and item['filename']: (UPLOAD_DIR / item['filename']).unlink(missing_ok=True)
            conn.execute('DELETE FROM support_posts WHERE id=?', (request.form.get('id', type=int),))
            flash('Đã gỡ nội dung hỗ trợ.', 'success')
        else:
            title = request.form.get('title', '').strip()[:140]
            body = request.form.get('body', '').strip()[:3000]
            upload = request.files.get('attachment')
            filename = None
            if upload and upload.filename:
                filename, _original = save_upload(upload, 'support', CHAT_FILE_EXTENSIONS)
                if not filename:
                    flash('Tệp hỗ trợ chưa đúng định dạng.', 'error')
                    return redirect(url_for('admin_support'))
            if not title:
                flash('Vui lòng nhập tiêu đề nội dung hỗ trợ.', 'error')
                return redirect(url_for('admin_support'))
            conn.execute('INSERT INTO support_posts(title,body,filename) VALUES(?,?,?)', (title, body, filename))
            flash('Đã đăng nội dung lên khu Cần trợ giúp của khách.', 'success')
        conn.commit()
        return redirect(url_for('admin_support'))
    posts = conn.execute('SELECT * FROM support_posts ORDER BY id DESC').fetchall()
    return render_template('admin_support.html', posts=posts)


@app.route("/appearance-background/<path:filename>")
def appearance_background(filename):
    filename = Path(filename).name
    row = db().execute("SELECT value FROM site_settings WHERE key='background' AND value=?", (filename,)).fetchone()
    if not row:
        abort(404)
    if filename.startswith('preset:'):
        preset = filename.split(':',1)[1]
        if preset not in SEASONAL_PRESETS: abort(404)
        return send_from_directory(BASE_DIR / 'static' / 'seasonal', f'{preset}.svg')
    return send_from_directory(UPLOAD_DIR, filename)


@app.errorhandler(403)
def forbidden(_):
    return render_template("message.html", title="Không có quyền truy cập", message="Trang này dành cho quản trị viên."), 403


def create_app():
    """Entry point for production servers such as Waitress."""
    init_db()
    return app


if __name__ == "__main__":
    create_app().run(debug=True)
