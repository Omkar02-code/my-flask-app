import os
import re
import json
from datetime import date, datetime, timedelta
import datetime as dt
import io
from flask import send_file
import pandas as pd
from sqlalchemy import or_, func

from flask import Flask, request, redirect, url_for, render_template, flash
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import func, and_, or_
from sqlalchemy.orm import relationship
import pandas as pd
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash
from flask_login import LoginManager, login_user, logout_user, login_required, current_user
from urllib.parse import urlencode
from sqlalchemy import cast, Date

LOGIN_MAX_ATTEMPTS = 5  # lock after 5 consecutive failures
LOGIN_WINDOW_MIN = 15  # count failures within the last 15 minutes
LOGIN_LOCK_MIN = 15  # lockout duration (minutes)

# --------------------------
# App and DB configuration
# --------------------------
db = SQLAlchemy()
login_manager = LoginManager()

# --------------------------
# Models (mirror existing schema)
# --------------------------


class ConsumerComplaints(db.Model):
    __tablename__ = "ConsumerComplaints"
    id = db.Column(db.Integer, primary_key=True)
    # storing as TEXT like before (YYYY-MM-DD)
    complaint_date = db.Column(db.String, nullable=False)
    customer_name = db.Column(db.String, nullable=False)
    consumer_mobile_number = db.Column(db.String)
    OHT_name = db.Column(db.String)
    issue = db.Column(db.Text)
    Address = db.Column(db.Text)
    longitude = db.Column(db.Float)
    latitude = db.Column(db.Float)
    complaint_details = db.Column(db.Text)
    status = db.Column(db.String)

    # works = relationship("TeamWork", back_populates="complaint", cascade="all, delete-orphan")
    works = relationship("TeamWork", back_populates="complaint")


class TeamWork(db.Model):
    __tablename__ = "TeamWork"
    id = db.Column(db.Integer, primary_key=True)
    # stored as TEXT (YYYY-MM-DD) like before
    work_date = db.Column(db.String, nullable=False)
    team_member = db.Column(db.String, nullable=False)
    OHT = db.Column(db.String)
    area = db.Column(db.String)
    work_description = db.Column(db.Text)
    complaint_id = db.Column(
        db.Integer, db.ForeignKey("ConsumerComplaints.id"))

    complaint = relationship("ConsumerComplaints", back_populates="works")
    materials = relationship(
        "Materials", back_populates="work", cascade="all, delete-orphan")


class Materials(db.Model):
    __tablename__ = "Materials"
    id = db.Column(db.Integer, primary_key=True)
    material_name = db.Column(db.String, nullable=False)
    quantity_used = db.Column(db.Float)
    work_id = db.Column(db.Integer, db.ForeignKey("TeamWork.id"))

    work = relationship("TeamWork", back_populates="materials")


class Users(UserMixin, db.Model):
    tablename = "users"
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True,
                         nullable=False, index=True)
    password_hash = db.Column(db.String(255), nullable=False)
    role = db.Column(db.String(20), nullable=False,
                     default="team")  # 'admin' or 'team'
    created_at = db.Column(db.DateTime, server_default=func.now())

    def set_password(self, password: str):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password: str) -> bool:
        return check_password_hash(self.password_hash, password)


class LoginAttempts(db.Model):
    tablename = "login_attempts"
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), index=True,
                         nullable=False)  # what the user typed
    ip = db.Column(db.String(45), index=True, nullable=False)  # supports IPv6
    attempts = db.Column(db.Integer, nullable=False, default=0)
    # last_attempt = db.Column(db.DateTime, server_default=func.now(), onupdate=func.now())
    last_attempt = db.Column(db.DateTime, nullable=True)  # set in code
    locked_until = db.Column(db.DateTime, nullable=True)

# def client_ip():
# # If behind a proxy, consider X-Forwarded-For (validate in production!)
#     return request.headers.get("X-Forwarded-For", request.remote_addr or "0.0.0.0").split(",").strip()


def client_ip():
    # Prefer X-Forwarded-For if present (first IP is the original client).
    xff_list = request.headers.getlist("X-Forwarded-For")
    if xff_list:
        # Join multiple headers if present, split by comma, take the first non-empty token.
        joined = ",".join(xff_list)
        for token in joined.split(","):
            ip = token.strip()
            if ip:
                return ip
    # Fallback to direct remote_addr
    ip = request.remote_addr or "0.0.0.0"
    return ip.strip()


def normalize_username(u: str) -> str:
    # Prevent case tricks; adjust if your usernames are case-sensitive.
    return (u or "").strip().lower()


def get_attempt_record(username, ip):
    rec = LoginAttempts.query.filter_by(username=username, ip=ip).first()
    if not rec:
        rec = LoginAttempts(username=username, ip=ip,
                            attempts=0, last_attempt=None, locked_until=None)
        db.session.add(rec)
        db.session.commit()  # commit so record exists right away
        return rec


def within_window(last: datetime | None, minutes: int) -> bool:
    if not last:
        return False
    return last >= datetime.utcnow() - timedelta(minutes=minutes)


def get_attempt_record(username, ip):
    rec = LoginAttempts.query.filter_by(username=username, ip=ip).first()
    if not rec:
        rec = LoginAttempts(username=username, ip=ip,
                            attempts=0, locked_until=None)
        db.session.add(rec)
        db.session.flush()  # ensure rec has an id without commit
    return rec


def within_window(dt, minutes):
    if not dt:
        return False
    return dt >= datetime.utcnow() - timedelta(minutes=LOGIN_WINDOW_MIN)

# --------------------------
# Helpers
# --------------------------


def like_ci(col, q):
    # case-insensitive LIKE
    return func.lower(col).like(f"%{q.lower()}%")


def ensure_initial_admin():
    if Users.query.count() == 0:
        admin = Users(username="admin", role="admin")
        admin.set_password("admin123")  # change this after first login!
        db.session.add(admin)
        db.session.commit()
        print("Created default admin: admin / admin123 (please change).")

def complaint_date_as_date():
# Cast the TEXT column to DATE for safe comparisons in Postgres
    return cast(ConsumerComplaints.complaint_date, Date)
def teamwork_date_as_date():
# Cast the TEXT column to DATE for safe comparisons in Postgres
    return cast(TeamWork.work_date, Date)



def complaints_pivot(start_date=None, end_date=None, limit_rows=50):
    allowed_statuses = ["Open", "Working"]
    qry = db.session.query(
        ConsumerComplaints.OHT_name.label("oht"),
        ConsumerComplaints.issue.label("issue"),
        func.count(ConsumerComplaints.id).label("cnt")
    ).filter(ConsumerComplaints.status.in_(allowed_statuses))
    # 2) Optional date filters so the pivot can show a window (e.g., last 30 days)
    if start_date:
        qry = qry.filter(complaint_date_as_date() >= start_date)
    if end_date:
        qry = qry.filter(complaint_date_as_date() <= end_date)

    # 3) Execute a GROUP BY query. Each row = (oht, issue, count)
    rows = (qry.group_by(ConsumerComplaints.OHT_name, ConsumerComplaints.issue)
               .all())

    # 4) Collect unique column headers (issues) and row labels (ohts)
    # Use "Unknown" if a field is NULL/empty.
    issues = sorted({(r.issue or "Unknown") for r in rows})
    ohts = sorted({(r.oht or "Unknown") for r in rows})

    # 5) Initialize a nested dict with zeros: data[oht][issue] = 0
    data = {o: {i: 0 for i in issues} for o in ohts}

    # 6) Fill in actual counts from the query results
    for r in rows:
        o = r.oht or "Unknown"
        i = r.issue or "Unknown"
        data[o][i] = int(r.cnt or 0)

    # 7) Compute totals
    row_totals = {o: sum(data[o].values()) for o in ohts}
    col_totals = {i: sum(data[o][i] for o in ohts) for i in issues}
    grand_total = sum(row_totals.values())

    # 8) Optional: limit number of row labels to keep the table readable
    if limit_rows and len(ohts) > limit_rows:
        ohts = ohts[:limit_rows]

    # 9) Return a clean package for the template
    return {
        "rows": ohts,           # list of row labels (OHTs)
        "cols": issues,         # list of column headers (Issues)
        "data": data,           # nested dict: data[row][col] -> count
        "row_totals": row_totals,
        "col_totals": col_totals,
        "grand_total": grand_total
    }


@login_manager.user_loader
def load_user(user_id):
    return Users.query.get(int(user_id))

# --------------------------
# Routes
# --------------------------


def register_routes(app: Flask):

    @app.route("/")
    @login_required
    def index():
        # Choose date window for the pivot (last 30 days)
        today = date.today()
        start = today - timedelta(days=565)
        # Build the pivot
        pivot = complaints_pivot()

    # KPIs
        total_complaints = db.session.query(
            func.count(ConsumerComplaints.id)).scalar()
        open_count = db.session.query(func.count(ConsumerComplaints.id)).filter(
            ConsumerComplaints.status == "Open").scalar()
        working_count = db.session.query(func.count(ConsumerComplaints.id)).filter(
            ConsumerComplaints.status == "Working").scalar()
        # close_count = db.session.query(func.count(ConsumerComplaints.id)).filter(ConsumerComplaints.status == "Close").scalar()
        target_close = "close"
        close_count = (
            db.session.query(func.count(ConsumerComplaints.id))
            .filter(func.lower(func.trim(ConsumerComplaints.status)) == target_close)
            .scalar())
        # Date window for charts: last 30 days
        today = date.today()
        start = today - timedelta(days=30)
        # Complaints per day
        c_rows = (db.session.query(func.date(ConsumerComplaints.complaint_date), func.count(ConsumerComplaints.id))
                #   .filter(ConsumerComplaints.complaint_date >= start)
                  .filter(complaint_date_as_date() >= start)
                  .group_by(func.date(ConsumerComplaints.complaint_date))
                  .order_by(func.date(ConsumerComplaints.complaint_date))
                  .all())
        # TeamWork per day
        t_rows = (db.session.query(func.date(TeamWork.work_date), func.count(TeamWork.id))
                # .filter(TeamWork.work_date >= start)
                  .filter(teamwork_date_as_date() >= start)
                  .group_by(func.date(TeamWork.work_date))
                  .order_by(func.date(TeamWork.work_date))
                  .all())
        # Build continuous day series for last 30 days

        def build_series(rows):
            mapping = {str(d): cnt for d, cnt in rows if d is not None}
            labels, data = [], []
            for i in range(30):
                d = start + timedelta(days=i)
                k = str(d)
                labels.append(k)
                data.append(int(mapping.get(k, 0)))
            return {"labels": labels, "data": data}

        complaints_daily = build_series(c_rows)
        teamwork_daily = build_series(t_rows)
        # Top Issues
        top_issues_rows = (db.session.query(ConsumerComplaints.issue, func.count(ConsumerComplaints.id))
                           .group_by(ConsumerComplaints.issue)
                           .order_by(func.count(ConsumerComplaints.id).desc())
                           .limit(5)
                           .all())
        top_issues = {"labels": [i or "Unknown" for i, _ in top_issues_rows],
                      "data": [int(c) for _, c in top_issues_rows]}
        # Top OHT
        top_oht_rows = (db.session.query(ConsumerComplaints.OHT_name, func.count(ConsumerComplaints.id))
                        .group_by(ConsumerComplaints.OHT_name)
                        .order_by(func.count(ConsumerComplaints.id).desc())
                        .limit(5)
                        .all())
        top_oht = {"labels": [o or "Unknown" for o, _ in top_oht_rows],
                   "data": [int(c) for _, c in top_oht_rows]}
        # Short lists
        recent_open = (ConsumerComplaints.query
                       .filter(ConsumerComplaints.status == "Open")
                       .order_by(ConsumerComplaints.complaint_date.desc(), ConsumerComplaints.id.desc())
                       .limit(5).all())
        today_work = (TeamWork.query
                    #   .filter(TeamWork.work_date >= today)
                      .filter(teamwork_date_as_date() >= today)
                      .order_by(TeamWork.id.desc())
                      .limit(10).all())
        kpi = {
            "total_complaints": int(total_complaints or 0),
            "open": int(open_count or 0),
            "working": int(working_count or 0),
            "close": int(close_count or 0),
        }
        charts = {
            "complaints_daily": complaints_daily,
            "teamwork_daily": teamwork_daily,
            "top_issues": top_issues,
            "top_oht": top_oht,
        }
        return render_template("dashboard.html",
                               kpi=kpi,
                               charts=charts,
                               pivot=pivot,
                               recent_open=recent_open,
                               today_work=today_work)
        # return render_template("index.html")

    # ---------------- Complaints: List with filters ----------------

    @app.route("/complaints")
    @login_required
    def complaints():
        # Dropdowns: distinct values
        statuses = [row[0] for row in db.session.query(ConsumerComplaints.status)
                    .filter(ConsumerComplaints.status.isnot(None))
                    .filter(ConsumerComplaints.status != "")
                    .distinct()
                    .order_by(ConsumerComplaints.status).all()]

        oht_names = [row[0] for row in db.session.query(ConsumerComplaints.OHT_name)
                     .filter(ConsumerComplaints.OHT_name.isnot(None))
                     .filter(ConsumerComplaints.OHT_name != "")
                     .distinct()
                     .order_by(ConsumerComplaints.OHT_name).all()]

        issues = [row[0] for row in db.session.query(ConsumerComplaints.issue)
                  .filter(ConsumerComplaints.issue.isnot(None))
                  .filter(ConsumerComplaints.issue != "")
                  .distinct()
                  .order_by(ConsumerComplaints.issue).all()]

        id = [row[0] for row in db.session.query(ConsumerComplaints.id)
              .filter(ConsumerComplaints.id.isnot(None))
            #   .filter(ConsumerComplaints.id != "")
              .distinct()
              .order_by(ConsumerComplaints.id).all()]

        complaint_date_from = request.args.get("date_from", "").strip()
        complaint_date_to = request.args.get("date_to", "").strip()
        sel_statuses = request.args.getlist("status")
        sel_oht_names = request.args.getlist("oht_name")
        sel_issues = request.args.getlist("issue")
        sel__ids = request.args.getlist("id")
        q = request.args.get("q", "").strip()

        qry = ConsumerComplaints.query

        if complaint_date_from:
            qry = qry.filter(ConsumerComplaints.complaint_date >=
                             complaint_date_from)
        if complaint_date_to:
            qry = qry.filter(ConsumerComplaints.complaint_date <=
                             complaint_date_to)
        if sel_statuses:
            qry = qry.filter(ConsumerComplaints.status.in_(sel_statuses))
        if sel_oht_names:
            qry = qry.filter(ConsumerComplaints.OHT_name.in_(sel_oht_names))
        if sel_issues:
            qry = qry.filter(ConsumerComplaints.issue.in_(sel_issues))
        if sel__ids:
            qry = qry.filter(ConsumerComplaints.id.in_(sel__ids))
        if q:
            qry = qry.filter(or_(
                like_ci(ConsumerComplaints.customer_name, q),
                like_ci(ConsumerComplaints.complaint_details, q),
                ConsumerComplaints.consumer_mobile_number.like(f"%{q}%")
            ))
        try:
            page = int(request.args.get("page", 1))
            if page < 1:
                page = 1
        except ValueError:
            page = 1
        try:
            per_page = int(request.args.get("per_page", 10))
            if per_page < 1 or per_page > 200:
                per_page = 10
        except ValueError:
            per_page = 10
        # 5) Count total rows for pagination
        total = qry.count()
        # 6) Apply ordering and page slice
        rows = (qry
                .order_by(ConsumerComplaints.complaint_date.desc(), ConsumerComplaints.id.desc())
                .offset((page - 1) * per_page)
                .limit(per_page)
                .all())
        # 7) Compute total pages
        total_pages = (total + per_page - 1) // per_page
        return render_template(
            "complaints.html",
            complaints=rows,
            statuses=statuses,
            oht_names=oht_names,
            issues=issues,
            id=id,
            filters={
                "date_from": complaint_date_from,
                "date_to": complaint_date_to,
                "status": sel_statuses,
                "oht_name": sel_oht_names,
                "issue": sel_issues,
                "id": sel__ids,
                "q": q
            },
            page=page,
            per_page=per_page,
            total=total,
            total_pages=total_pages
        )

    # ---------------- Complaints: Add ----------------
    @app.route("/complaints/add", methods=("GET", "POST"))
    @login_required
    def add_complaint():
        if request.method == "POST":
            rec = ConsumerComplaints(
                complaint_date=request.form["complaint_date"],
                customer_name=request.form["customer_name"],
                consumer_mobile_number=request.form.get(
                    "consumer_mobile_number") or None,
                OHT_name=request.form.get("OHT_name") or None,
                issue=request.form.get("issue") or None,
                Address=request.form.get("Address") or "",
                longitude=float(request.form["longitude"]) if request.form.get(
                    "longitude") else None,
                latitude=float(request.form["latitude"]) if request.form.get(
                    "latitude") else None,
                complaint_details=request.form.get("complaint_details") or "",
                status=request.form.get("status") or "Open"
            )
            db.session.add(rec)
            db.session.commit()
            return redirect(url_for("complaints"))

        return render_template("add_complaint.html")

    # ---------------- Complaints: Edit ----------------
    @app.route("/complaints/<int:complaint_id>/edit", methods=("GET", "POST"))
    @login_required
    def edit_complaint(complaint_id):
        c = ConsumerComplaints.query.get(complaint_id)
        if not c:
            return "Complaint not found", 404

        if request.method == "POST":
            c.complaint_date = request.form["complaint_date"]
            c.customer_name = request.form["customer_name"]
            c.consumer_mobile_number = request.form.get(
                "consumer_mobile_number") or None
            c.OHT_name = request.form.get("OHT_name") or None
            c.issue = request.form.get("issue") or None
            c.Address = request.form.get("Address") or ""
            c.longitude = float(request.form["longitude"]) if request.form.get(
                "longitude") else None
            c.latitude = float(request.form["latitude"]) if request.form.get(
                "latitude") else None
            c.complaint_details = request.form.get("complaint_details") or ""
            c.status = request.form.get("status") or None
            db.session.commit()
            return redirect(url_for("complaints"))

        return render_template("edit_complaint.html", c=c)

    @app.route("/complaints/int:complaint_id/status", methods=["POST"])
    @login_required
    def complaints_update_status(complaint_id):
        # 1) Read and normalize the new status
        new_status = (request.form.get("status")
                      or "").strip().title()  # 'open' -> 'Open'
        allowed_values = {"Open", "Working", "Close"}
        if new_status not in allowed_values:
            return "Invalid status", 400
        # 2) Load the complaint
        c = ConsumerComplaints.query.get_or_404(complaint_id)
        current = (c.status or "Open").strip().title()

        # 3) Define the policy
        def can_transition(role: str, old: str, new: str) -> bool:
            # Admins: any transition allowed
            if role == "admin":
                return True
            # Non-admins: forward-only progression
            forward_map = {
                "Open": {"Open", "Working", "Close"},
                "Working": {"Working", "Close"},
                "Close": {"Close"},
            }
            return new in forward_map.get(old, {old})

        role = getattr(current_user, "role", "team")
        if not can_transition(role, current, new_status):
            return "Forbidden: transition not allowed by policy.", 403

        # 4) No-op early exit (same status)
        if new_status == current:
            ret = request.form.get("return_to")
            dest = url_for("complaints")
            return redirect(f"{dest}?{ret}" if ret else dest)

        # 5) Update and save
        c.status = new_status
        db.session.commit()

        # 6) Redirect back to the same filtered/paginated list
        ret = request.form.get("return_to")
        dest = url_for("complaints")
        return redirect(f"{dest}?{ret}" if ret else dest)

    # ---------------- Complaints: Delete ----------------

    @app.route("/complaints/<int:complaint_id>/delete", methods=("POST",))
    @login_required
    def delete_complaint(complaint_id):
        if current_user.role != "admin":
            return "Forbidden", 403
        c = ConsumerComplaints.query.get(complaint_id)
        if c:
            db.session.delete(c)
            db.session.commit()
        return redirect(url_for("complaints"))

    @app.route("/complaints/bulk-delete", methods=["POST"])
    @login_required
    def complaints_bulk_delete():
        # Permission check
        if getattr(current_user, "role", "team") != "admin":
            return "Forbidden", 403
        # Collect IDs
        ids = request.form.getlist("ids")
        try:
            id_list = [int(x) for x in ids if str(x).strip().isdigit()]
        except Exception:
            id_list = []

        if not id_list:
            # Nothing selected; just return back
            dest = url_for("complaints")
            ret = request.form.get("return_to")
            return redirect(f"{dest}?{ret}" if ret else dest)

        # Perform delete
        ConsumerComplaints.query.filter(ConsumerComplaints.id.in_(
            id_list)).delete(synchronize_session=False)
        db.session.commit()

        # Redirect back preserving filters/pagination
        dest = url_for("complaints")
        ret = request.form.get("return_to")
        return redirect(f"{dest}?{ret}" if ret else dest)

    # ---------------- TeamWork: List with filters ----------------

    @app.route("/teamwork")
    @login_required
    def teamwork():
        # Dropdowns
        team_members = [row[0] for row in db.session.query(TeamWork.team_member)
                        .filter(TeamWork.team_member.isnot(None))
                        .filter(TeamWork.team_member != "")
                        .distinct()
                        .order_by(TeamWork.team_member).all()]
        oht_names = [row[0] for row in db.session.query(TeamWork.OHT)
                     .filter(TeamWork.OHT.isnot(None))
                     .filter(TeamWork.OHT != "")
                     .distinct()
                     .order_by(TeamWork.OHT).all()]
        areas = [row[0] for row in db.session.query(TeamWork.area)
                 .filter(TeamWork.area.isnot(None))
                 .filter(TeamWork.area != "")
                 .distinct()
                 .order_by(TeamWork.area).all()]
        work_descriptions = [row[0] for row in db.session.query(TeamWork.work_description)
                             .filter(TeamWork.work_description.isnot(None))
                             .filter(TeamWork.work_description != "")
                             .distinct()
                             .order_by(TeamWork.work_description).all()]
        complaint_ids = [row[0] for row in db.session.query(TeamWork.complaint_id)
                         .filter(TeamWork.complaint_id.isnot(None))
                         .distinct()
                         .order_by(TeamWork.complaint_id).all()]

        date_from = request.args.get("date_from", "").strip()
        date_to = request.args.get("date_to", "").strip()
        sel_team_members = request.args.getlist("team_member")
        sel_oht_names = request.args.getlist("OHT")
        sel_areas = request.args.getlist("area")
        sel_work_descriptions = request.args.getlist("work_description")
        sel_complaint_ids = request.args.getlist("complaint_id")
        q = request.args.get("q", "").strip()

        qry = db.session.query(
            TeamWork.id, TeamWork.work_date, TeamWork.team_member, TeamWork.OHT, TeamWork.area,
            TeamWork.work_description, TeamWork.complaint_id,
            ConsumerComplaints.customer_name.label("complaint_customer"),
            ConsumerComplaints.complaint_details.label("complaint_summary")
        ).outerjoin(ConsumerComplaints, TeamWork.complaint_id == ConsumerComplaints.id)

        if date_from:
            qry = qry.filter(teamwork_date_as_date() >= date_from)
        if date_to:
            qry = qry.filter(teamwork_date_as_date() <= date_to)
        if sel_team_members:
            qry = qry.filter(TeamWork.team_member.in_(sel_team_members))
        if sel_oht_names:
            qry = qry.filter(TeamWork.OHT.in_(sel_oht_names))
        if sel_areas:
            qry = qry.filter(TeamWork.area.in_(sel_areas))
        if sel_work_descriptions:
            qry = qry.filter(TeamWork.work_description.in_(
                sel_work_descriptions))
        if sel_complaint_ids:
            # complaint_ids are strings from query; cast to int where possible
            valid_ids = [int(x) for x in sel_complaint_ids if x.isdigit()]
            if valid_ids:
                qry = qry.filter(TeamWork.complaint_id.in_(valid_ids))
        if q:
            like = f"%{q.lower()}%"
            qry = qry.filter(or_(
                func.lower(TeamWork.work_description).like(like),
                func.lower(ConsumerComplaints.customer_name).like(like),
                func.lower(ConsumerComplaints.complaint_details).like(like),
            ))

        rows = qry.order_by(TeamWork.work_date.desc(),
                            TeamWork.id.desc()).all()

        return render_template(
            "teamwork.html",
            teamwork=rows,
            team_members=team_members,
            oht_names=oht_names,
            areas=areas,
            work_descriptions=work_descriptions,
            complaint_ids=complaint_ids,
            filters={
                "date_from": date_from,
                "date_to": date_to,
                "team_member": sel_team_members,
                "OHT": sel_oht_names,
                "area": sel_areas,
                "work_description": sel_work_descriptions,
                "complaint_id": sel_complaint_ids,
                "q": q
            }
        )

    # ---------------- TeamWork: Add ----------------
    @app.route("/teamwork/add", methods=("GET", "POST"))
    @login_required
    def add_teamwork():
        complaints = db.session.query(
            ConsumerComplaints.id,
            (ConsumerComplaints.customer_name + " - " +
             func.coalesce(ConsumerComplaints.complaint_details, ""))
        ).order_by(ConsumerComplaints.id.desc()).all()

        if request.method == "POST":
            complaint_id_raw = request.form.get("complaint_id", "").strip()
            complaint_id = int(complaint_id_raw) if complaint_id_raw else None

            rec = TeamWork(
                work_date=request.form["work_date"],
                team_member=request.form["team_member"],
                OHT=request.form.get("OHT") or None,
                area=request.form.get("area") or None,
                work_description=request.form.get("work_description") or None,
                complaint_id=complaint_id
            )
            db.session.add(rec)
            db.session.commit()
            return redirect(url_for("teamwork"))

        return render_template("add_teamwork.html", complaints=complaints)

    # ---------------- TeamWork: Edit ----------------
    @app.route("/teamwork/<int:work_id>/edit", methods=("GET", "POST"))
    @login_required
    def edit_teamwork(work_id):
        w = TeamWork.query.get(work_id)
        if not w:
            return "Work not found", 404

        complaints = db.session.query(
            ConsumerComplaints.id,
            (ConsumerComplaints.customer_name + " - " +
             func.coalesce(ConsumerComplaints.complaint_details, ""))
        ).order_by(ConsumerComplaints.id.desc()).all()

        if request.method == "POST":
            w.work_date = request.form["work_date"]
            w.team_member = request.form["team_member"]
            w.OHT = request.form.get("OHT") or None
            w.area = request.form.get("area") or None
            w.work_description = request.form.get("work_description") or None
            complaint_id_raw = request.form.get("complaint_id", "").strip()
            w.complaint_id = int(
                complaint_id_raw) if complaint_id_raw else None
            db.session.commit()
            return redirect(url_for("teamwork"))

        return render_template("edit_teamwork.html", w=w, complaints=complaints)

    # ---------------- TeamWork: Delete ----------------
    @app.route("/teamwork/<int:work_id>/delete", methods=("POST",))
    @login_required
    def delete_teamwork(work_id):
        if current_user.role != "admin":
            return "Forbidden", 403
        w = TeamWork.query.get(work_id)
        if w:
            db.session.delete(w)
            db.session.commit()
        return redirect(url_for("teamwork"))

    # ---------------- Materials: List with filters ----------------
    @app.route("/materials")
    @login_required
    def materials():
        material_names = [row[0] for row in db.session.query(Materials.material_name)
                          .filter(Materials.material_name.isnot(None))
                          .filter(Materials.material_name != "")
                          .distinct()
                          .order_by(Materials.material_name).all()]
        team_members = [row[0] for row in db.session.query(TeamWork.team_member)
                        .filter(TeamWork.team_member.isnot(None))
                        .filter(TeamWork.team_member != "")
                        .distinct()
                        .order_by(TeamWork.team_member).all()]
        work_ids = [row[0] for row in db.session.query(
            TeamWork.id).order_by(TeamWork.id).all()]

        date_from = request.args.get("date_from", "").strip()
        date_to = request.args.get("date_to", "").strip()
        sel_material_names = request.args.getlist("material_name")
        sel_team_members = request.args.getlist("team_member")
        sel_work_ids = request.args.getlist("work_id")
        q = request.args.get("q", "").strip()

        qry = db.session.query(
            Materials.id, Materials.material_name, Materials.quantity_used, Materials.work_id,
            TeamWork.work_date, TeamWork.team_member, TeamWork.work_description
        ).outerjoin(TeamWork, Materials.work_id == TeamWork.id)

        if date_from:
            qry = qry.filter(TeamWork.work_date >= date_from)
        if date_to:
            qry = qry.filter(TeamWork.work_date <= date_to)
        if sel_material_names:
            qry = qry.filter(Materials.material_name.in_(sel_material_names))
        if sel_team_members:
            qry = qry.filter(TeamWork.team_member.in_(sel_team_members))
        if sel_work_ids:
            valid_ids = [int(x) for x in sel_work_ids if x.isdigit()]
            if valid_ids:
                qry = qry.filter(Materials.work_id.in_(valid_ids))
        if q:
            like = f"%{q.lower()}%"
            qry = qry.filter(or_(
                func.lower(Materials.material_name).like(like),
                func.lower(TeamWork.work_description).like(like),
            ))

        rows = qry.order_by(TeamWork.work_date.desc(),
                            Materials.id.desc()).all()

        return render_template(
            "materials.html",
            materials=rows,
            material_names=material_names,
            team_members=team_members,
            work_ids=work_ids,
            filters={
                "date_from": date_from,
                "date_to": date_to,
                "material_name": sel_material_names,
                "team_member": sel_team_members,
                "work_id": sel_work_ids,
                "q": q
            }
        )

    # ---------------- Materials: Add ----------------
    @app.route("/materials/add", methods=("GET", "POST"))
    @login_required
    def add_material():
        works = db.session.query(
            TeamWork.id,
            (TeamWork.work_date + " - " + TeamWork.team_member +
             " - " + func.coalesce(TeamWork.work_description, ""))
        ).order_by(TeamWork.work_date.desc(), TeamWork.id.desc()).all()

        preselected_work_id = request.args.get("work_id", "").strip()

        if request.method == "POST":
            material_name = request.form["material_name"]
            quantity_used_raw = request.form.get("quantity_used", "").strip()
            work_id_raw = request.form.get("work_id", "").strip()

            rec = Materials(
                material_name=material_name,
                quantity_used=float(
                    quantity_used_raw) if quantity_used_raw else None,
                work_id=int(work_id_raw) if work_id_raw else None
            )
            db.session.add(rec)
            db.session.commit()

            if "save_add_another" in request.form:
                return redirect(url_for("add_material", work_id=rec.work_id))
            else:
                return redirect(url_for("materials"))

        return render_template("add_material.html", works=works, preselected_work_id=preselected_work_id)

    # ---------------- Materials: Edit ----------------
    @app.route("/materials/<int:material_id>/edit", methods=("GET", "POST"))
    @login_required
    def edit_material(material_id):
        m = Materials.query.get(material_id)
        if not m:
            return "Material not found", 404

        works = db.session.query(
            TeamWork.id,
            (TeamWork.work_date + " - " + TeamWork.team_member +
             " - " + func.coalesce(TeamWork.work_description, ""))
        ).order_by(TeamWork.work_date.desc(), TeamWork.id.desc()).all()

        if request.method == "POST":
            m.material_name = request.form["material_name"]
            quantity_used_raw = request.form.get("quantity_used", "").strip()
            work_id_raw = request.form.get("work_id", "").strip()
            m.quantity_used = float(
                quantity_used_raw) if quantity_used_raw else None
            m.work_id = int(work_id_raw) if work_id_raw else None
            db.session.commit()
            return redirect(url_for("materials"))

        return render_template("edit_material.html", m=m, works=works)

    # ---------------- Materials: Delete ----------------
    @app.route("/materials/<int:material_id>/delete", methods=("POST",))
    @login_required
    def delete_material(material_id):
        if current_user.role != "admin":
            return "Forbidden", 403
        m = Materials.query.get(material_id)
        if m:
            db.session.delete(m)
            db.session.commit()
        return redirect(url_for("materials"))

    # ---------------- Materials for a Work ----------------
    @app.route("/teamwork/<int:work_id>/materials")
    @login_required
    def materials_for_work(work_id):
        w = db.session.query(
            TeamWork.id, TeamWork.work_date, TeamWork.team_member, TeamWork.OHT, TeamWork.area, TeamWork.work_description
        ).filter(TeamWork.id == work_id).first()
        if not w:
            return "TeamWork record not found", 404

        mats = db.session.query(
            Materials.id, Materials.material_name, Materials.quantity_used
        ).filter(Materials.work_id == work_id).order_by(Materials.id).all()

        return render_template("materials_for_work.html", work=w, materials=mats)

    # ---------------- File Upload: Complaints Import ----------------
    UPLOAD_FOLDER = os.path.join(os.path.dirname(__file__), "uploads")
    os.makedirs(UPLOAD_FOLDER, exist_ok=True)
    ALLOWED_EXTENSIONS = {".xlsx", ".csv"}

    def allowed_file(filename):
        return os.path.splitext(filename)[1].lower() in ALLOWED_EXTENSIONS

    @app.route("/complaints/import", methods=("GET", "POST"))
    @login_required
    def import_complaints():
        if request.method == "GET":
            return render_template("import_complaints.html")

        file = request.files.get("file")
        if not file or file.filename == "":
            return render_template("import_complaints.html", error="Please choose a file (.xlsx or .csv).")

        if not allowed_file(file.filename):
            return render_template("import_complaints.html", error="Unsupported file type. Use .xlsx or .csv.")

        root, ext = os.path.splitext(file.filename)
        ext = ext.lower()
        tmp_path = os.path.join(UPLOAD_FOLDER, f"complaints_upload{ext}")
        file.save(tmp_path)

        try:
            if ext == ".xlsx":
                df = pd.read_excel(tmp_path)
            else:
                df = pd.read_csv(tmp_path)
        except Exception as e:
            return render_template("import_complaints.html", error=f"Could not read file: {e}")

        colmap = {
            "complaint_date": ["complaint_date", "date", "complaintdate"],
            "customer_name": ["customer_name", "name", "customer"],
            "consumer_mobile_number": ["consumer_mobile_number", "mobile", "phone", "mobile_number"],
            "OHT_name": ["OHT_name", "oht", "oht_name"],
            "issue": ["issue", "problem", "issue_description"],
            "Address": ["Address", "address", "location"],
            "longitude": ["longitude", "long", "lng"],
            "latitude": ["latitude", "lat"],
            "complaint_details": ["complaint_details", "details", "description"],
            "status": ["status", "state"]
        }

        found = {}
        lower_cols = {c.lower(): c for c in df.columns}
        for key, aliases in colmap.items():
            for a in aliases:
                if a.lower() in lower_cols:
                    found[key] = lower_cols[a.lower()]
                    break

        missing_required = [k for k in ["complaint_date",
                                        "customer_name", "complaint_details"] if k not in found]
        if missing_required:
            return render_template("import_complaints.html", error=f"Missing required columns: {', '.join(missing_required)}")

        def to_date(v):
            if pd.isna(v):
                return None
            try:
                d = pd.to_datetime(v)
                return d.strftime("%Y-%m-%d")
            except Exception:
                return None

        records = []
        errors = []
        for idx, row in df.iterrows():
            rec = {
                "complaint_date": to_date(row[found["complaint_date"]]),
                "customer_name": str(row[found["customer_name"]]).strip() if not pd.isna(row[found["customer_name"]]) else "",
                "consumer_mobile_number": str(row[found["consumer_mobile_number"]]).strip() if "consumer_mobile_number" in found and not pd.isna(row[found["consumer_mobile_number"]]) else None,
                "OHT_name": str(row[found["OHT_name"]]).strip() if "OHT_name" in found and not pd.isna(row[found["OHT_name"]]) else None,
                "issue": str(row[found["issue"]]).strip() if "issue" in found and not pd.isna(row[found["issue"]]) else None,
                "Address": str(row.get("Address", "")).strip() if "Address" in row and not pd.isna(row.get("Address")) else "",
                "longitude": float(row[found["longitude"]]) if "longitude" in found and not pd.isna(row[found["longitude"]]) else None,
                "latitude": float(row[found["latitude"]]) if "latitude" in found and not pd.isna(row[found["latitude"]]) else None,
                "complaint_details": str(row[found["complaint_details"]]).strip() if not pd.isna(row[found["complaint_details"]]) else "",
                "status": str(row[found["status"]]).strip() if "status" in found and not pd.isna(row[found["status"]]) else "Open",
            }

            row_errors = []
            if not rec["complaint_date"]:
                row_errors.append("Invalid complaint_date")
            if not rec["customer_name"]:
                row_errors.append("customer_name required")
            if not rec["complaint_details"]:
                row_errors.append("complaint_details required")
            if rec["consumer_mobile_number"] and not re.match(r'^\+?\d{10,15}$', rec["consumer_mobile_number"]):
                row_errors.append("Invalid consumer_mobile_number format")
            if rec["longitude"] is not None and not (-180 <= rec["longitude"] <= 180):
                row_errors.append("longitude out of range")
            if rec["latitude"] is not None and not (-90 <= rec["latitude"] <= 90):
                row_errors.append("latitude out of range")

            if row_errors:
                errors.append(
                    {"row_index": int(idx) + 2, "errors": row_errors})
            else:
                records.append(rec)

        json_path = os.path.join(UPLOAD_FOLDER, "complaints_upload.json")
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(records, f, ensure_ascii=False)

        summary = {"total_rows": len(df), "valid_rows": len(
            records), "invalid_rows": len(errors)}
        return render_template("import_complaints_preview.html", summary=summary, errors=errors, tmp_ext=ext)

    @app.route("/complaints/import/confirm", methods=["POST"])
    @login_required
    def import_complaints_confirm():
        json_path = os.path.join(os.path.dirname(
            __file__), "uploads", "complaints_upload.json")
        if not os.path.exists(json_path):
            return redirect(url_for("import_complaints"))

        with open(json_path, "r", encoding="utf-8") as f:
            records = json.load(f)

        if not records:
            return redirect(url_for("complaints"))

        try:
            for r in records:
                rec = ConsumerComplaints(
                    complaint_date=r["complaint_date"],
                    customer_name=r["customer_name"],
                    consumer_mobile_number=r["consumer_mobile_number"],
                    OHT_name=r["OHT_name"],
                    issue=r["issue"],
                    Address=r["Address"],
                    longitude=r["longitude"],
                    latitude=r["latitude"],
                    complaint_details=r["complaint_details"],
                    status=r["status"]
                )
                db.session.add(rec)
            db.session.commit()
        except Exception:
            db.session.rollback()
            return render_template("import_complaints.html", error="Import failed. Transaction rolled back.")

        try:
            os.remove(json_path)
        except Exception:
            pass

        return redirect(url_for("complaints"))

     # ---------------- File Dowload: Complaints Export ----------------

    @app.route("/complaints/export")
    @login_required
    def export_complaints():
        # Read filters (same names as list page)
        complaint_date_from = request.args.get("date_from", "").strip()
        complaint_date_to = request.args.get("date_to", "").strip()
        sel_statuses = request.args.getlist("status")
        sel_oht_names = request.args.getlist("oht_name")
        sel_issues = request.args.getlist("issue")
        q = request.args.get("q", "").strip()

        qry = ConsumerComplaints.query

        if complaint_date_from:
            qry = qry.filter(ConsumerComplaints.complaint_date >=
                             complaint_date_from)
        if complaint_date_to:
            qry = qry.filter(ConsumerComplaints.complaint_date <=
                             complaint_date_to)
        if sel_statuses:
            qry = qry.filter(ConsumerComplaints.status.in_(sel_statuses))
        if sel_oht_names:
            qry = qry.filter(ConsumerComplaints.OHT_name.in_(sel_oht_names))
        if sel_issues:
            qry = qry.filter(ConsumerComplaints.issue.in_(sel_issues))
        if q:
            like = f"%{q.lower()}%"
            qry = qry.filter(or_(
                func.lower(ConsumerComplaints.customer_name).like(like),
                func.lower(ConsumerComplaints.complaint_details).like(like),
                ConsumerComplaints.consumer_mobile_number.like(f"%{q}%")
            ))

        rows = qry.order_by(
            ConsumerComplaints.complaint_date.desc(),
            ConsumerComplaints.id.desc()
        ).all()

    # Convert to DataFrame
        data = []
        for c in rows:
            data.append({
                "ID": c.id,
                "Complaint Date": c.complaint_date,
                "Customer Name": c.customer_name,
                "Mobile": c.consumer_mobile_number,
                "OHT": c.OHT_name,
                "Issue": c.issue,
                "Address": c.Address,
                "Longitude": c.longitude,
                "Latitude": c.latitude,
                "Details": c.complaint_details,
                "Status": c.status
            })
        df = pd.DataFrame(data)

    # Write Excel to in-memory buffer
        output = io.BytesIO()
        with pd.ExcelWriter(output, engine="openpyxl") as writer:
            df.to_excel(writer, index=False, sheet_name="Complaints")
        output.seek(0)

        filename = f"complaints_export.xlsx"
        return send_file(
            output,
            mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            as_attachment=True,
            download_name=filename
        )

 # ---------------- File Dowload: Teamwork Export ----------------
    @app.route("/teamwork/export")
    @login_required
    def export_teamwork():
        date_from = request.args.get("date_from", "").strip()
        date_to = request.args.get("date_to", "").strip()
        sel_team_members = request.args.getlist("team_member")
        sel_oht_names = request.args.getlist("OHT")
        sel_areas = request.args.getlist("area")
        sel_work_descriptions = request.args.getlist("work_description")
        sel_complaint_ids = request.args.getlist("complaint_id")
        q = request.args.get("q", "").strip()

        qry = db.session.query(
            TeamWork.id, TeamWork.work_date, TeamWork.team_member, TeamWork.OHT, TeamWork.area,
            TeamWork.work_description, TeamWork.complaint_id,
            ConsumerComplaints.customer_name.label("complaint_customer"),
            ConsumerComplaints.complaint_details.label("complaint_summary")
        ).outerjoin(ConsumerComplaints, TeamWork.complaint_id == ConsumerComplaints.id)

        if date_from:
            qry = qry.filter(TeamWork.work_date >= date_from)
        if date_to:
            qry = qry.filter(TeamWork.work_date <= date_to)
        if sel_team_members:
            qry = qry.filter(TeamWork.team_member.in_(sel_team_members))
        if sel_oht_names:
            qry = qry.filter(TeamWork.OHT.in_(sel_oht_names))
        if sel_areas:
            qry = qry.filter(TeamWork.area.in_(sel_areas))
        if sel_work_descriptions:
            qry = qry.filter(TeamWork.work_description.in_(
                sel_work_descriptions))
        if sel_complaint_ids:
            valid_ids = [int(x) for x in sel_complaint_ids if x.isdigit()]
            if valid_ids:
                qry = qry.filter(TeamWork.complaint_id.in_(valid_ids))
        if q:
            like = f"%{q.lower()}%"
            qry = qry.filter(or_(
                func.lower(TeamWork.work_description).like(like),
                func.lower(ConsumerComplaints.customer_name).like(like),
                func.lower(ConsumerComplaints.complaint_details).like(like),
            ))

        rows = qry.order_by(TeamWork.work_date.desc(),
                            TeamWork.id.desc()).all()

        data = []
        for r in rows:
            data.append({
                "ID": r.id,
                "Work Date": r.work_date,
                "Team Member": r.team_member,
                "OHT": r.OHT,
                "Area": r.area,
                "Work Description": r.work_description,
                "Complaint ID": r.complaint_id,
                "Complaint Customer": r.complaint_customer,
                "Complaint Summary": r.complaint_summary
            })
        df = pd.DataFrame(data)

        output = io.BytesIO()
        with pd.ExcelWriter(output, engine="openpyxl") as writer:
            df.to_excel(writer, index=False, sheet_name="TeamWork")
        output.seek(0)

        filename = f"teamwork_export.xlsx"
        return send_file(
            output,
            mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            as_attachment=True,
            download_name=filename
        )
     # ---------------- File Dowload: Matrial Export ----------------

    @app.route("/materials/export")
    @login_required
    def export_materials():
        date_from = request.args.get("date_from", "").strip()
        date_to = request.args.get("date_to", "").strip()
        sel_material_names = request.args.getlist("material_name")
        sel_team_members = request.args.getlist("team_member")
        sel_work_ids = request.args.getlist("work_id")
        q = request.args.get("q", "").strip()

        qry = db.session.query(
            Materials.id, Materials.material_name, Materials.quantity_used, Materials.work_id,
            TeamWork.work_date, TeamWork.team_member, TeamWork.work_description
        ).outerjoin(TeamWork, Materials.work_id == TeamWork.id)

        if date_from:
            qry = qry.filter(TeamWork.work_date >= date_from)
        if date_to:
            qry = qry.filter(TeamWork.work_date <= date_to)
        if sel_material_names:
            qry = qry.filter(Materials.material_name.in_(sel_material_names))
        if sel_team_members:
            qry = qry.filter(TeamWork.team_member.in_(sel_team_members))
        if sel_work_ids:
            valid_ids = [int(x) for x in sel_work_ids if x.isdigit()]
            if valid_ids:
                qry = qry.filter(Materials.work_id.in_(valid_ids))
        if q:
            like = f"%{q.lower()}%"
            qry = qry.filter(or_(
                func.lower(Materials.material_name).like(like),
                func.lower(TeamWork.work_description).like(like),
            ))

        rows = qry.order_by(TeamWork.work_date.desc(),
                            Materials.id.desc()).all()

        data = []
        for r in rows:
            data.append({
                "ID": r.id,
                "Material": r.material_name,
                "Quantity": r.quantity_used,
                "Work ID": r.work_id,
                "Work Date": r.work_date,
                "Team Member": r.team_member,
                "Work Description": r.work_description
            })
        df = pd.DataFrame(data)

        output = io.BytesIO()
        with pd.ExcelWriter(output, engine="openpyxl") as writer:
            df.to_excel(writer, index=False, sheet_name="Materials")
        output.seek(0)

        filename = f"materials_export.xlsx"
        return send_file(
            output,
            mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            as_attachment=True,
            download_name=filename
        )


def register_auth_routes(app):
    @app.route("/login", methods=["GET", "POST"])
    def login():
        if request.method == "POST":
            raw_username = request.form.get("username") or ""
            password = request.form.get("password") or ""
            username = normalize_username(raw_username)
            ip = client_ip()
            now = datetime.utcnow()
            # 1) Fetch or create attempt record
            rec = get_attempt_record(username, ip)

        # 1) If locked, block
            if rec.locked_until and rec.locked_until > now:
                # Keep message generic if you prefer; below is more explicit.
                return render_template("login.html", error="Too many attempts. Try again after.")

        # 2) Check credentials
            user = Users.query.filter(db.func.lower(
                Users.username) == username).first()
            ok = bool(user and user.check_password(password))

            if ok:
                # 3) Success: reset attempts and unlock
                rec.attempts = 0
                rec.last_attempt = now
                rec.locked_until = None
                db.session.commit()

                login_user(user)
                return redirect(request.args.get("next") or url_for("index"))

            # 4) Failure: increment within window, else reset then increment
            if within_window(rec.last_attempt, LOGIN_WINDOW_MIN):
                rec.attempts = (rec.attempts or 0) + 1
            else:
                rec.attempts = 1  # reset window

            rec.last_attempt = now

            # 5) Lock if threshold reached
            if rec.attempts >= LOGIN_MAX_ATTEMPTS:
                rec.locked_until = now + timedelta(minutes=LOGIN_LOCK_MIN)
                db.session.commit()
                return render_template("login.html", error="Too many login attempts. Please try again later.")

        db.session.commit()
        return render_template("login.html", error="Invalid username or password.")

    @app.route("/logout")
    @login_required
    def logout():
        logout_user()
        return redirect(url_for("login"))
    # ADMIN-ONLY: list users

    @app.route("/users")
    @login_required
    def users_list():
        if current_user.role != "admin":
            return "Forbidden", 403
        users = Users.query.order_by(Users.id).all()
        return render_template("users.html", users=users)
    # ADMIN-ONLY: add user

    @app.route("/users/add", methods=["GET", "POST"])
    @login_required
    def users_add():
        if current_user.role != "admin":
            return "Forbidden", 403
        if request.method == "POST":
            username = request.form.get("username", "").strip()
            password = request.form.get("password", "").strip()
            role = request.form.get("role", "team")
            if not username or not password:
                return render_template("user_form.html", error="Username and password required.", mode="add")
            if Users.query.filter_by(username=username).first():
                return render_template("user_form.html", error="Username already exists.", mode="add")
            u = Users(username=username, role=role)
            u.set_password(password)
            db.session.add(u)
            db.session.commit()
            return redirect(url_for("users_list"))
        return render_template("user_form.html", mode="add")
    # ADMIN-ONLY: edit user

    @app.route("/users/<int:user_id>/edit", methods=["GET", "POST"])
    @login_required
    def users_edit(user_id):
        if current_user.role != "admin":
            return "Forbidden", 403
        u = Users.query.get_or_404(user_id)
        if request.method == "POST":
            username = request.form.get("username", "").strip()
            role = request.form.get("role", "team")
            password = request.form.get("password", "").strip()
            if username and username != u.username:
                if Users.query.filter_by(username=username).first():
                    return render_template("user_form.html", error="Username already exists.", mode="edit", user=u)
                u.username = username
            u.role = role
            if password:
                u.set_password(password)
            db.session.commit()
            return redirect(url_for("users_list"))
        return render_template("user_form.html", mode="edit", user=u)

        # ADMIN-ONLY: delete user (cannot delete yourself)
    @app.route("/users/<int:user_id>/delete", methods=["POST"])
    @login_required
    def users_delete(user_id):
        if current_user.role != "admin":
            return "Forbidden", 403
        if current_user.id == user_id:
            return "Cannot delete yourself.", 400
        u = Users.query.get_or_404(user_id)
        db.session.delete(u)
        db.session.commit()
        return redirect(url_for("users_list"))

    @app.route("/account/password", methods=["GET", "POST"])
    @login_required
    def change_password():
        if request.method == "POST":
            current = (request.form.get("current_password") or "").strip()
            new1 = (request.form.get("new_password") or "").strip()
            new2 = (request.form.get("confirm_password") or "").strip()
            # Basic validations
            errors = []
            if not current or not new1 or not new2:
                errors.append("All fields are required.")
            if new1 != new2:
                errors.append("New passwords do not match.")
            if len(new1) < 8:
                errors.append("New password must be at least 8 characters.")

            # Verify current password
            if not errors and not current_user.check_password(current):
                errors.append("Current password is incorrect.")

            if errors:
                return render_template("change_password.html", errors=errors)

            # All good: set new password
            current_user.set_password(new1)
            db.session.commit()
            return render_template("change_password.html", success="Password updated successfully.")

        # GET
        return render_template("change_password.html")


def cleanup_old_attempts(days=30):
    cutoff = datetime.utcnow() - timedelta(days=days)
    LoginAttempts.query.filter(LoginAttempts.last_attempt < cutoff).delete()
    db.session.commit()


def create_app():
    app = Flask(__name__)
    app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "dev-secret-key")

   # database_url = os.environ.get("DATABASE_URL")

    db_url = os.environ.get("DATABASE_URL") or os.environ.get("SQLALCHEMY_DATABASE_URI")
    db_url = db_url or "postgresql://neondb_owner:npg_dfpAWgDm8U0K@ep-proud-truth-adrl0p65-pooler.c-2.us-east-1.aws.neon.tech/neondb?sslmode=require&"

    # if database_url and database_url.startswith("postgres://"):
    #     database_url = database_url.replace("postgres://", "postgresql://", 1)
    # if not database_url:
    #     database_url = "sqlite:///local.db"

    app.config["SQLALCHEMY_DATABASE_URI"] = db_url
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
    engine_options = {
    "pool_pre_ping": True, # check connections before using; auto-reconnect if dead
    "pool_recycle": 900, # recycle connections every 15 minutes
    "pool_size": 5, # small pool (adjust if Railway plan allows more)
    "max_overflow": 5, # allow short bursts
    "pool_timeout": 30, # wait up to 30s for a connection from pool
    }
    if db_url.startswith("postgresql"):
        pass
    app.config["SQLALCHEMY_ENGINE_OPTIONS"] = engine_options
    print("Using DB:", app.config["SQLALCHEMY_DATABASE_URI"])

    db.init_app(app)
    login_manager.init_app(app)
    login_manager.login_view = "login"  # if not logged in, redirect here

    with app.app_context():
        db.create_all()
        ensure_initial_admin()
        cleanup_old_attempts()

    register_routes(app)
    register_auth_routes(app)
    return app


# WSGI app
app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)), debug=True)
