import csv
import io
from datetime import datetime, date
from flask import make_response


def money(value, symbol=None):
    try:
        value = float(value or 0)
    except (TypeError, ValueError):
        value = 0
    sym = symbol
    if sym is None:
        try:
            import db as _db
            row = _db.query("SELECT currency_symbol FROM company_settings WHERE id=1", one=True)
            sym = (row["currency_symbol"] if row else "$") + " "
        except Exception:
            sym = "$ "
    return f"{sym}{value:,.2f}"


def today_iso():
    return date.today().isoformat()


def now_iso():
    return datetime.utcnow().isoformat(timespec="seconds")


def fmt_date(value):
    if not value:
        return "-"
    try:
        return datetime.fromisoformat(str(value)[:19]).strftime("%d %b %Y")
    except ValueError:
        return str(value)[:10]


def fmt_datetime(value):
    if not value:
        return "-"
    try:
        return datetime.fromisoformat(str(value)[:19]).strftime("%d %b %Y %I:%M %p")
    except ValueError:
        return str(value)


def fmt_time(value):
    if not value:
        return "-"
    s = str(value)
    try:
        if len(s) <= 5:
            return datetime.strptime(s, "%H:%M").strftime("%I:%M %p")
        return datetime.fromisoformat(s[:19]).strftime("%I:%M %p")
    except ValueError:
        return s


def days_until(value):
    if not value:
        return None
    try:
        d = datetime.fromisoformat(str(value)[:10]).date()
        return (d - date.today()).days
    except ValueError:
        return None


def age_years(value):
    if not value:
        return None
    try:
        d = datetime.fromisoformat(str(value)[:10]).date()
        today = date.today()
        return today.year - d.year - ((today.month, today.day) < (d.month, d.day))
    except ValueError:
        return None


def initials(name):
    if not name:
        return "?"
    parts = str(name).strip().split()
    if not parts:
        return "?"
    if len(parts) == 1:
        return parts[0][:2].upper()
    return (parts[0][0] + parts[-1][0]).upper()


def paginate_args(request, default_per_page=15):
    try:
        page = max(1, int(request.args.get("page", 1)))
    except ValueError:
        page = 1
    try:
        per_page = min(200, max(5, int(request.args.get("per_page", default_per_page))))
    except ValueError:
        per_page = default_per_page
    return page, per_page


def csv_response(filename, header, rows):
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(header)
    for r in rows:
        writer.writerow(r)
    resp = make_response(buf.getvalue())
    resp.headers["Content-Type"] = "text/csv"
    resp.headers["Content-Disposition"] = f"attachment; filename={filename}"
    return resp


def status_badge_class(status):
    mapping = {
        "draft": "gray", "new": "blue", "open": "blue", "pending": "amber",
        "sent": "blue", "planning": "gray", "planned": "blue", "scheduled": "blue",
        "in progress": "amber", "goal setting": "blue", "self review": "amber",
        "manager review": "amber", "completed": "green", "closed": "green",
        "active": "green", "inactive": "gray", "on hold": "amber",
        "cancelled": "red", "rejected": "red", "declined": "red", "withdrawn": "gray",
        "approved": "green", "confirmed": "green", "accepted": "green", "won": "green",
        "lost": "red", "paid": "green", "unpaid": "red", "processed": "green",
        "applied": "blue", "screening": "amber", "shortlisted": "indigo",
        "interview": "indigo", "technical interview": "indigo", "hr interview": "indigo",
        "selected": "green", "offer": "indigo", "joined": "green",
        "manager approved": "amber", "finance verified": "amber",
        "present": "green", "absent": "red", "half day": "amber", "on leave": "indigo",
        "holiday": "gray", "week off": "gray", "not started": "gray",
        "enrolled": "blue", "attended": "green", "contacted": "blue",
        "qualified": "indigo", "proposal": "amber", "negotiation": "amber",
        "expert": "green", "advanced": "indigo", "intermediate": "amber", "beginner": "gray",
        "full-time": "blue", "part-time": "indigo", "contract": "amber", "intern": "gray",
        "resigned": "red", "terminated": "red", "suspended": "red",
    }
    return mapping.get(str(status).lower(), "gray")
