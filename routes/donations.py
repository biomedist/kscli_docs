"""찬조금 내역 (잠금 대상): 행사별로 찬조금(주로 광고비)을 기록하고, 첫 화면에서 연간 합계를 보여줍니다.
- 연도는 '행사 일자'의 연도 기준입니다. (행사와 무관한 찬조금은 받은 일자 기준)
- 이 파일의 화면은 모두 /audit/donations 로 시작하므로 비밀번호 잠금이 적용됩니다."""
import re
from datetime import datetime

from flask import Blueprint, abort, flash, redirect, render_template, request, url_for

import storage
from menu import get_menu
from models import db

bp = Blueprint("donations", __name__)

DONATION_FILE = "donation_doc"       # 증빙 첨부 (잠금 대상: 'donation' 으로 시작)
KINDS = ["광고비", "찬조금", "지원금", "기타"]


def _won_to_int(raw):
    cleaned = re.sub(r"[,\s원₩]", "", raw or "")
    return int(cleaned) if cleaned.isdigit() else None


def _year_filters(year):
    """선택한 연도에 속하는 찬조금: 행사에 연결된 것은 행사 일자 기준, 행사 외는 받은 일자 기준."""
    return ("((d.event_id IS NOT NULL AND substr(e.held_on, 1, 4) = ?) "
            "OR (d.event_id IS NULL AND substr(d.donated_on, 1, 4) = ?))", (str(year), str(year)))


# ---------- 첫 화면: 연간 합계 + 행사별 목록 ----------
@bp.route("/audit/donations")
def list_view():
    now_year = datetime.now().year
    with db() as conn:
        years = {int(r["y"]) for r in conn.execute(
            "SELECT DISTINCT substr(held_on, 1, 4) AS y FROM events WHERE held_on != ''") if r["y"].isdigit()}
        years |= {int(r["y"]) for r in conn.execute(
            "SELECT DISTINCT substr(donated_on, 1, 4) AS y FROM donations WHERE event_id IS NULL AND donated_on != ''")
            if r["y"] and r["y"].isdigit()}
        with_donations = {int(r["y"]) for r in conn.execute(
            "SELECT DISTINCT substr(e.held_on, 1, 4) AS y FROM donations d JOIN events e ON e.id = d.event_id")
            if r["y"].isdigit()}
        raw = request.args.get("year")
        if raw and raw.isdigit():
            year = int(raw)
        else:
            year = max(with_donations | {y for y in years if y == now_year} or years or {now_year})
        years.add(year)

        events = conn.execute(
            "SELECT e.*, COUNT(d.id) AS n, COALESCE(SUM(d.amount), 0) AS total FROM events e "
            "LEFT JOIN donations d ON d.event_id = e.id WHERE substr(e.held_on, 1, 4) = ? "
            "GROUP BY e.id ORDER BY e.held_on, e.id", (str(year),)).fetchall()
        general = conn.execute(
            "SELECT COUNT(*) AS n, COALESCE(SUM(amount), 0) AS total FROM donations "
            "WHERE event_id IS NULL AND substr(donated_on, 1, 4) = ?", (str(year),)).fetchone()
        clause, args = _year_filters(year)
        by_kind = conn.execute(
            "SELECT d.kind, COUNT(*) AS n, COALESCE(SUM(d.amount), 0) AS total FROM donations d "
            "LEFT JOIN events e ON e.id = d.event_id WHERE " + clause + " GROUP BY d.kind", args).fetchall()

    total = sum(e["total"] for e in events) + general["total"]
    count = sum(e["n"] for e in events) + general["n"]
    kind_rows = sorted(by_kind, key=lambda r: -r["total"])
    return render_template(
        "donations.html", page=get_menu("donations"), years=sorted(years, reverse=True), year=year,
        events=events, general=general, total=total, count=count, kind_rows=kind_rows,
    )


# ---------- 세부 화면 ----------
def _detail(scope, event, year, rows, files):
    total = sum((r["amount"] or 0) for r in rows)
    return render_template(
        "donations_detail.html", page=get_menu("donations"), scope=scope, event=event, year=year, rows=rows,
        files=files, total=total, kinds=KINDS, accept=storage.ACCEPT_ATTR,
        add_event_id=event["id"] if event else "",
    )


@bp.route("/audit/donations/event/<int:event_id>")
def event_detail(event_id):
    with db() as conn:
        event = conn.execute("SELECT * FROM events WHERE id = ?", (event_id,)).fetchone()
        if not event:
            abort(404)
        rows = conn.execute("SELECT * FROM donations WHERE event_id = ? ORDER BY donated_on, id", (event_id,)).fetchall()
        files = storage.files_for(conn, (DONATION_FILE,), [r["id"] for r in rows])
    return _detail("event", event, event["held_on"][:4], rows, files)


@bp.route("/audit/donations/general/<int:year>")
def general_detail(year):
    with db() as conn:
        rows = conn.execute(
            "SELECT * FROM donations WHERE event_id IS NULL AND substr(donated_on, 1, 4) = ? ORDER BY donated_on, id",
            (str(year),)).fetchall()
        files = storage.files_for(conn, (DONATION_FILE,), [r["id"] for r in rows])
    return _detail("general", None, str(year), rows, files)


def _detail_url(event_id, donated_on):
    if event_id:
        return url_for("donations.event_detail", event_id=event_id)
    return url_for("donations.general_detail", year=int((donated_on or str(datetime.now().year))[:4]))


# ---------- 저장 ----------
def _fields():
    f = request.form
    donated_on = f.get("donated_on", "").strip()
    try:
        datetime.strptime(donated_on, "%Y-%m-%d")
    except ValueError:
        return None
    kind = f.get("kind", "").strip()
    donor = f.get("donor", "").strip()
    amount = _won_to_int(f.get("amount"))
    if kind not in KINDS or not donor or amount is None:
        return None
    return {"donated_on": donated_on, "kind": kind, "donor": donor, "amount": amount,
            "usage": f.get("usage", "").strip(), "note": f.get("note", "").strip()}


def _event_id_from_form(conn):
    raw = request.form.get("event_id", "").strip()
    if not raw.isdigit():
        return None
    return int(raw) if conn.execute("SELECT 1 FROM events WHERE id = ?", (int(raw),)).fetchone() else None


@bp.post("/audit/donations/add")
def add():
    fields = _fields()
    with db() as conn:
        event_id = _event_id_from_form(conn)
        if not fields:
            flash("일자, 구분, 찬조자(회사), 금액(숫자)을 확인해 주세요.", "error")
            return redirect(url_for("donations.event_detail", event_id=event_id) if event_id
                            else url_for("donations.list_view"))
        conn.execute(
            "INSERT INTO donations(event_id, kind, donated_on, donor, amount, usage, note) "
            "VALUES (:event_id, :kind, :donated_on, :donor, :amount, :usage, :note)", {**fields, "event_id": event_id})
    flash(f"'{fields['donor']}' 찬조금을 추가했습니다.")
    return redirect(_detail_url(event_id, fields["donated_on"]))


def _get(conn, donation_id):
    row = conn.execute("SELECT * FROM donations WHERE id = ?", (donation_id,)).fetchone()
    if not row:
        abort(404)
    return row


@bp.post("/audit/donations/<int:donation_id>/edit")
def edit(donation_id):
    fields = _fields()
    with db() as conn:
        row = _get(conn, donation_id)
        if not fields:
            flash("일자, 구분, 찬조자(회사), 금액(숫자)을 확인해 주세요.", "error")
            return redirect(_detail_url(row["event_id"], row["donated_on"]))
        conn.execute(
            "UPDATE donations SET donated_on=:donated_on, kind=:kind, donor=:donor, amount=:amount, usage=:usage, "
            "note=:note WHERE id=:id", {**fields, "id": donation_id})
    flash(f"'{fields['donor']}' 찬조금을 저장했습니다.")
    return redirect(_detail_url(row["event_id"], fields["donated_on"]))


@bp.post("/audit/donations/<int:donation_id>/delete")
def delete(donation_id):
    with db() as conn:
        row = _get(conn, donation_id)
        storage.delete_files_for(conn, (DONATION_FILE,), donation_id)
        conn.execute("DELETE FROM donations WHERE id = ?", (donation_id,))
    flash(f"'{row['donor']}' 찬조금과 증빙 파일을 삭제했습니다.")
    return redirect(_detail_url(row["event_id"], row["donated_on"]))


@bp.post("/audit/donations/<int:donation_id>/upload")
def upload(donation_id):
    with db() as conn:
        row = _get(conn, donation_id)
        storage.save_request_files(conn, DONATION_FILE, donation_id, "donations")
    return redirect(_detail_url(row["event_id"], row["donated_on"]))
