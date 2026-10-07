from __future__ import annotations

import os
from collections import defaultdict
from datetime import datetime, timedelta
from typing import Any, Callable

from dotenv import load_dotenv
from flask import Flask, abort, redirect, render_template, request, session, url_for

load_dotenv()

from services.api_client import api_client

app = Flask(__name__)
app.config["SECRET_KEY"] = os.getenv("SECRET_KEY", "change-me")
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
app.config["SESSION_COOKIE_SECURE"] = os.getenv("FLASK_ENV", "development") == "production"

MOCK_MODE = os.getenv("MOCK_MODE", "true").lower() in {"1", "true", "yes"}
LOGIN_ATTEMPTS = defaultdict(list)


def get_client_ip() -> str:
    return request.headers.get("X-Forwarded-For", request.remote_addr or "unknown")


def generate_csrf_token() -> str:
    if "csrf_token" not in session:
        session["csrf_token"] = os.urandom(16).hex()
    return session["csrf_token"]


def validate_csrf(token: str | None) -> bool:
    return bool(token) and token == session.get("csrf_token")


def login_required(view: Callable[..., Any]) -> Callable[..., Any]:
    def wrapped(*args: Any, **kwargs: Any) -> Any:
        if "user" not in session:
            return redirect(url_for("login"))
        return view(*args, **kwargs)

    wrapped.__name__ = view.__name__
    return wrapped


@app.context_processor
def inject_context() -> dict[str, Any]:
    return {
        "current_user": session.get("user"),
        "mock_mode": MOCK_MODE,
        "csrf_token": generate_csrf_token(),
    }


@app.before_request
def ensure_csrf_for_post() -> None:
    if request.method == "POST" and request.path not in {"/login", "/logout"} and not validate_csrf(request.form.get("csrf_token")):
        abort(403)


@app.errorhandler(403)
def forbidden_error(_error: Exception) -> Any:
    return render_template("error_page.html", page_title="Forbidden", message="Your session is invalid or the form was tampered with."), 403


@app.errorhandler(500)
def internal_error(_error: Exception) -> Any:
    return render_template("error_page.html", page_title="Error", message="Something went wrong while loading the dashboard. Please try again."), 500


def clear_old_attempts() -> None:
    cutoff = datetime.utcnow() - timedelta(minutes=15)
    attempts = LOGIN_ATTEMPTS.get(get_client_ip(), [])
    LOGIN_ATTEMPTS[get_client_ip()] = [timestamp for timestamp in attempts if timestamp > cutoff]


def is_rate_limited() -> bool:
    clear_old_attempts()
    attempts = LOGIN_ATTEMPTS.get(get_client_ip(), [])
    return len(attempts) >= 5


def record_failed_login() -> None:
    LOGIN_ATTEMPTS[get_client_ip()].append(datetime.utcnow())


@app.route("/login", methods=["GET", "POST"])
def login() -> Any:
    form_error = ""
    if request.method == "POST":
        email = (request.form.get("email") or "").strip().lower()
        password = request.form.get("password") or ""
        if not email or not password or "@" not in email:
            form_error = "Invalid email or password"
            record_failed_login()
            return render_template("login.html", form_error=form_error)

        if is_rate_limited():
            form_error = "Too many failed login attempts. Please try again in 15 minutes."
            return render_template("login.html", form_error=form_error)

        try:
            response = api_client.login(email, password)
            if response.get("status") == "success":
                session.clear()
                session["user"] = response.get("user", {"email": email})
                session["token"] = response.get("token")
                session["csrf_token"] = os.urandom(16).hex()
                return redirect(url_for("overview"))
        except Exception:
            pass

        form_error = "Invalid email or password"
        record_failed_login()
        return render_template("login.html", form_error=form_error)

    if session.get("user"):
        return redirect(url_for("overview"))
    return render_template("login.html", form_error="")


@app.route("/logout", methods=["POST"])
@login_required
def logout() -> Any:
    if not validate_csrf(request.form.get("csrf_token")):
        abort(403)
    session.clear()
    return redirect(url_for("login"))


@app.route("/forgot-password")
def forgot_password() -> Any:
    return render_template("forgot_password.html")


@app.route("/")
@login_required
def overview() -> Any:
    try:
        summary = api_client.get_dashboard_summary()
    except Exception:
        summary = {
            "total_exposure": 0,
            "building_count": 0,
            "losses": {"10": 0, "25": 0, "50": 0, "100": 0, "250": 0},
            "flood_hotspots": 0,
            "hotspots_flagged": 0,
            "sample_note": "Unable to load summary data.",
            "ep_preview": []
        }
    if not summary.get("ep_preview"):
        summary["ep_preview"] = [
            {"return_period": 10, "loss": 0},
            {"return_period": 25, "loss": 0},
            {"return_period": 50, "loss": 0},
            {"return_period": 100, "loss": 0},
            {"return_period": 250, "loss": 0},
        ]
    return render_template("overview.html", summary=summary)


@app.route("/ep-curve")
@login_required
def ep_curve() -> Any:
    try:
        data = api_client.get_ep_curve()
    except Exception:
        data = {
            "loss_points": [],
            "class_breakdown": {"labels": [], "exposure": [], "loss_100": [], "loss_250": []},
            "mapping": {},
            "warning": "No curve data available.",
            "assumption_note": "ASSUMPTION: hazard tiers are mapped to return periods..."
        }
    return render_template("ep_curve.html", curve=data)


@app.route("/hotspots")
@login_required
def hotspots() -> Any:
    try:
        data = api_client.get_hotspots()
    except Exception:
        data = {"hotspots": [], "legend": {"flagged": "green", "missed": "red"}, "validation_note": "No hotspot data available."}
    return render_template("hotspots.html", hotspots=data.get("hotspots", []), validation_note=data.get("validation_note", ""), legend=data.get("legend", {"flagged": "green", "missed": "red"}))


@app.route("/drainage-reports")
@login_required
def drainage_reports() -> Any:
    try:
        data = api_client.get_drainage_reports()
    except Exception:
        data = {"items": [], "neighbourhoods": ["All"], "note": "No drainage report data available."}
    return render_template("drainage_reports.html", reports=data.get("items", []), neighbourhoods=data.get("neighbourhoods", ["All"]), note=data.get("note", ""))


@app.route("/reports/generate", methods=["GET", "POST"])
@login_required
def reports_generate() -> Any:
    generated_report = None
    previous = api_client.get_reports().get("items", [])
    if request.method == "POST":
        title = request.form.get("title") or "Untitled report"
        audience = request.form.get("audience") or "underwriter"
        return_periods = request.form.getlist("return_periods")
        sections = request.form.getlist("sections")
        report_format = request.form.get("format") or "html"
        try:
            generated_report = api_client.generate_report(title, audience, return_periods, sections, report_format)
            if generated_report.get("status") == "completed":
                previous = api_client.get_reports().get("items", [])
        except Exception:
            generated_report = {
                "report_id": "failed",
                "status": "error",
                "briefing": "The report could not be generated. Please try again.",
                "download_url": "#"
            }
    insights = api_client.get_insights().get("items", [])
    return render_template("reports_generate.html", generated_report=generated_report, previous_reports=previous, insights=insights)


@app.route("/about")
@login_required
def about() -> Any:
    return render_template("about.html")


@app.route("/health")
def health() -> str:
    return "ok"


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
