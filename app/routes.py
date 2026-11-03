import datetime
import functools

from flask import (Blueprint, abort, redirect, render_template, request,
                   session, url_for)
from flask import current_app

from . import ai_module, allocation, auth, db

bp = Blueprint("main", __name__)


def login_required(*roles):
    def deco(fn):
        @functools.wraps(fn)
        def wrapper(*a, **kw):
            user = auth.current_user()
            if not user:
                return redirect(url_for("main.login"))
            if roles and user["role"] not in roles:
                abort(403)
            return fn(user=user, *a, **kw)
        return wrapper
    return deco


def week_start_str():
    today = datetime.date.today()
    return (today - datetime.timedelta(days=today.weekday())).isoformat()


def _db():
    return current_app.config["DB_PATH"]


@bp.route("/")
def index():
    if auth.current_user():
        return redirect(url_for("main.dashboard"))
    return redirect(url_for("main.login"))


@bp.route("/login", methods=["GET", "POST"])
def login():
    error = None
    if request.method == "POST":
        if auth.authenticate(_db(), request.form["username"].strip(), request.form["password"]):
            return redirect(url_for("main.dashboard"))
        error = "Invalid username or password"
    return render_template("login.html", error=error)


@bp.route("/logout")
def logout():
    auth.logout()
    return redirect(url_for("main.login"))


@bp.route("/dashboard")
@login_required()
def dashboard(user):
    db_path = _db()
    week = week_start_str()
    with db.connect(db_path) as con:
        mine = con.execute(
            "SELECT minutes, rationale FROM allocations WHERE user_id=? AND week_start=?",
            (user["id"], week)).fetchone()
    used = db.usage_this_week(db_path, user["id"], week)
    jobs = ai_module.list_jobs(db_path, limit=8)
    materials = db.list_materials(db_path, limit=6)
    targeted = db.list_materials_for_targets(db_path, user.get("exam_targets", "") or "")
    return render_template("dashboard.html", user=user, mine=mine, used=used, week=week,
                           jobs=jobs, materials=materials, targeted=targeted,
                           ai_live=ai_module.endpoint_configured(),
                           ai_model=ai_module.DEFAULT_MODEL)


@bp.route("/usage/log", methods=["POST"])
@login_required("student")
def log_usage(user):
    minutes = int(request.form["minutes"])
    if minutes <= 0 or minutes > 24 * 60:
        abort(400)
    db.log_usage(_db(), user["id"], week_start_str(), minutes,
                 request.form.get("note", "").strip())
    return redirect(url_for("main.dashboard"))


@bp.route("/admin", methods=["GET", "POST"])
@login_required("admin", "lecturer")
def admin(user):
    db_path = _db()
    week = week_start_str()
    if request.method == "POST":
        action = request.form.get("action")
        # Allocation and student management are administrator actions.
        # Lecturers use this page for AI status and the measured panel only.
        if action in ("set_pool", "run_allocation", "add_student", "update_student") \
                and user["role"] != "admin":
            abort(403)
        if action == "set_pool":
            db.set_pool(db_path, int(request.form["total_minutes"]))
        elif action == "add_student":
            uid = auth.create_user(db_path, request.form["username"].strip(),
                                   request.form["password"], "student",
                                   request.form["full_name"].strip(),
                                   int(request.form.get("exam_urgency", 0)))
            with db.connect(db_path) as con:
                con.execute("UPDATE users SET exam_targets=? WHERE id=?",
                            (request.form.get("exam_targets", "").strip(), uid))
        elif action == "update_student":
            with db.connect(db_path) as con:
                con.execute("UPDATE users SET exam_urgency=?, need_bonus=?, exam_targets=? WHERE id=?",
                            (int(request.form["exam_urgency"]),
                             float(request.form["need_bonus"]),
                             request.form.get("exam_targets", "").strip(),
                             int(request.form["user_id"])))
        elif action == "run_allocation":
            with db.connect(db_path) as con:
                students = [dict(r) for r in con.execute(
                    "SELECT id, full_name, exam_urgency, need_bonus FROM users WHERE role='student'")]
            for a in allocation.compute_allocation(students, db.get_pool(db_path)):
                with db.connect(db_path) as con:
                    con.execute(
                        "INSERT OR REPLACE INTO allocations (user_id, week_start, minutes, rationale)"
                        " VALUES (?,?,?,?)", (a["user_id"], week, a["minutes"], a["rationale"]))
        return redirect(url_for("main.admin"))
    with db.connect(db_path) as con:
        students = [dict(r) for r in con.execute(
            "SELECT id, username, full_name, exam_urgency, need_bonus, exam_targets FROM users"
            " WHERE role='student' ORDER BY full_name")]
        allocs = [dict(r) for r in con.execute(
            "SELECT a.*, u.full_name FROM allocations a JOIN users u ON u.id=a.user_id"
            " WHERE a.week_start=? ORDER BY a.minutes DESC", (week,))]
    return render_template("admin.html", user=user, pool=db.get_pool(db_path),
                           students=students, allocs=allocs, week=week,
                           usage=db.usage_overview(db_path, week),
                           stats=ai_module.ai_stats(db_path),
                           quality=ai_module.quality_check(),
                           ai_live=ai_module.endpoint_configured(),
                           ai_model=ai_module.DEFAULT_MODEL)


@bp.route("/ai", methods=["POST"])
@login_required()
def ai_submit(user):
    kind = request.form["kind"]
    text = request.form["source_text"].strip()
    if kind not in ("summary", "quiz", "condense") or not text:
        abort(400)
    job_id, _, _ = ai_module.submit_job(_db(), kind, text)
    return redirect(url_for("main.ai_result", job_id=job_id))


@bp.route("/ai/<int:job_id>")
@login_required()
def ai_result(user, job_id):
    job = ai_module.get_job(_db(), job_id)
    if not job:
        abort(404)
    return render_template("ai_result.html", user=user, job=job)


@bp.route("/ai/<int:job_id>/publish", methods=["POST"])
@login_required("admin", "lecturer")
def ai_publish(user, job_id):
    job = ai_module.get_job(_db(), job_id)
    if not job or job["status"] != "done":
        abort(400)
    title = request.form.get("title", "").strip() or f"{job['kind'].title()} #{job_id}"
    db.add_material(_db(), title, job["kind"], job["result"], job["model"], user["id"],
                    course_tag=request.form.get("course_tag", "").strip())
    return redirect(url_for("main.materials"))


@bp.route("/materials")
@login_required()
def materials(user):
    return render_template("materials.html", user=user,
                           materials=db.list_materials(_db()))


@bp.route("/materials/<int:material_id>")
@login_required()
def material_detail(user, material_id):
    m = db.get_material(_db(), material_id)
    if not m:
        abort(404)
    db.log_material_read(_db(), material_id, user["id"])
    return render_template("material_detail.html", user=user, m=m)
