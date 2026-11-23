"""각종 회의실적: 연도별 회의 목록, 임원 출석, 회의록·참석서명지 첨부."""
from datetime import datetime

from flask import Blueprint, flash, redirect, render_template, request, url_for

import storage
from menu import get_menu
from models import db

bp = Blueprint("meetings", __name__)

SLOT_TARGETS = {"minutes": "meeting_minutes", "signature": "meeting_signature"}


@bp.app_template_filter("kdt")
def kdt(value):
    """'2026-03-15T14:00' → '2026. 3. 15. 14:00'"""
    if not value:
        return ""
    try:
        d = datetime.fromisoformat(value)
    except ValueError:
        return value
    return f"{d.year}. {d.month}. {d.day}. {d:%H:%M}"


def _go(year=None):
    return redirect(url_for("meetings.list_view", year=year) if year else url_for("meetings.list_view"))


# ---------- 목록 ----------
@bp.route("/audit/meetings")
def list_view():
    with db() as conn:
        years = [r["year"] for r in conn.execute("SELECT DISTINCT year FROM meetings ORDER BY year DESC")]
        sel = request.args.get("year")
        if sel is None:
            sel = str(years[0]) if years else str(datetime.now().year)
        show_all = sel == "all"
        if show_all:
            meetings = conn.execute("SELECT * FROM meetings ORDER BY held_at DESC, id DESC").fetchall()
        else:
            sel = sel if sel.isdigit() else str(datetime.now().year)
            meetings = conn.execute(
                "SELECT * FROM meetings WHERE year = ? ORDER BY held_at DESC, id DESC", (int(sel),)).fetchall()
            if int(sel) not in years:
                years = sorted(set(years) | {int(sel)}, reverse=True)

        ids = [m["id"] for m in meetings]
        files = storage.files_for(conn, tuple(SLOT_TARGETS.values()), ids)

        attendance = {i: {"exec": [], "council": []} for i in ids}
        if ids:
            marks = ",".join("?" * len(ids))
            for r in conn.execute(
                    f"SELECT meeting_id, officer_id, kind FROM meeting_attendance "
                    f"WHERE present = 1 AND officer_id IS NOT NULL AND meeting_id IN ({marks})", ids):
                attendance[r["meeting_id"]]["exec" if r["kind"] == "임원" else "council"].append(r["officer_id"])

        exec_officers = conn.execute(
            "SELECT id, position, name FROM officers WHERE kind = '임원' ORDER BY sort_order, id").fetchall()
        council_officers = conn.execute(
            "SELECT id, position, name FROM officers WHERE kind = '평의원' ORDER BY sort_order, id").fetchall()

    return render_template(
        "meetings.html", page=get_menu("meetings"), years=years, selected=sel, show_all=show_all,
        meetings=meetings, files=files, attendance=attendance, accept=storage.ACCEPT_ATTR,
        exec_officers=exec_officers, council_officers=council_officers,
    )


# ---------- 회의 정보 저장 ----------
def _meeting_fields():
    f = request.form
    title = f.get("title", "").strip()
    try:
        held = datetime.strptime(
            f"{f.get('held_date', '').strip()} {f.get('held_h', '').strip()}:{f.get('held_m', '').strip()}",
            "%Y-%m-%d %H:%M")
    except ValueError:
        return None
    if not title:
        return None

    def number(key):
        v = f.get(key, "").strip()
        return int(v) if v.isdigit() else None

    return {
        "year": held.year, "held_at": held.strftime("%Y-%m-%dT%H:%M"),
        "place": f.get("place", "").strip(), "title": title,
        "total_members": number("total_members"), "attendees": number("attendees"),
        "agenda": f.get("agenda", "").strip(),
    }


def _save_attendance(conn, meeting_id):
    """출석 체크를 건드렸을 때만 기록합니다. (숫자만 직접 입력한 회의는 건드리지 않음)
    이미 삭제된 임원의 과거 기록(officer_id 없음)은 그대로 보존합니다."""
    if request.form.get("attendance_dirty") != "1":
        return
    exec_ids = set(request.form.getlist("exec_present", type=int))
    council_ids = set(request.form.getlist("council_present", type=int))
    conn.execute("DELETE FROM meeting_attendance WHERE meeting_id = ? AND officer_id IS NOT NULL", (meeting_id,))
    for o in conn.execute("SELECT id, kind, position, name FROM officers ORDER BY sort_order, id").fetchall():
        if o["kind"] == "임원":
            present = 1 if o["id"] in exec_ids else 0
        elif o["id"] in council_ids:
            present = 1
        else:
            continue
        conn.execute(
            "INSERT INTO meeting_attendance(meeting_id, officer_id, officer_name, position, kind, present) "
            "VALUES (?, ?, ?, ?, ?, ?)", (meeting_id, o["id"], o["name"], o["position"], o["kind"], present))


@bp.post("/audit/meetings/add")
def add():
    fields = _meeting_fields()
    if not fields:
        flash("개최일시와 회의명을 입력해 주세요.", "error")
        return _go()
    with db() as conn:
        cur = conn.execute(
            "INSERT INTO meetings(year, held_at, place, title, total_members, attendees, agenda) "
            "VALUES (:year, :held_at, :place, :title, :total_members, :attendees, :agenda)", fields)
        _save_attendance(conn, cur.lastrowid)
    flash(f"'{fields['title']}' 회의를 추가했습니다. 오른쪽 칸에서 회의록과 서명지를 첨부하세요.")
    return _go(fields["year"])


@bp.post("/audit/meetings/<int:meeting_id>/edit")
def edit(meeting_id):
    fields = _meeting_fields()
    if not fields:
        flash("개최일시와 회의명을 입력해 주세요.", "error")
        return _go()
    with db() as conn:
        conn.execute(
            "UPDATE meetings SET year=:year, held_at=:held_at, place=:place, title=:title, "
            "total_members=:total_members, attendees=:attendees, agenda=:agenda WHERE id=:id",
            {**fields, "id": meeting_id})
        _save_attendance(conn, meeting_id)
    flash(f"'{fields['title']}' 회의를 저장했습니다.")
    return _go(fields["year"])


@bp.post("/audit/meetings/<int:meeting_id>/delete")
def delete(meeting_id):
    year = request.form.get("year") or None
    with db() as conn:
        row = conn.execute("SELECT title FROM meetings WHERE id = ?", (meeting_id,)).fetchone()
        if row:
            storage.delete_files_for(conn, tuple(SLOT_TARGETS.values()), meeting_id)
            conn.execute("DELETE FROM meetings WHERE id = ?", (meeting_id,))
            flash(f"'{row['title']}' 회의와 첨부파일을 삭제했습니다.")
    return _go(year)


# ---------- 첨부파일 ----------
@bp.post("/audit/meetings/<int:meeting_id>/upload")
def upload(meeting_id):
    target = SLOT_TARGETS.get(request.form.get("slot", ""))
    year = request.form.get("year") or None
    if not target:
        return _go(year)
    saved, rejected = 0, []
    with db() as conn:
        if not conn.execute("SELECT 1 FROM meetings WHERE id = ?", (meeting_id,)).fetchone():
            flash("회의를 찾을 수 없습니다.", "error")
            return _go(year)
        for fs in request.files.getlist("files"):
            if not fs or not fs.filename:
                continue
            result = storage.save_upload(fs, "meetings")
            if result is None:
                rejected.append(fs.filename)
                continue
            name, rel, kind = result
            conn.execute(
                "INSERT INTO files(original_name, stored_path, file_type, target_type, target_id) "
                "VALUES (?, ?, ?, ?, ?)", (name, rel, kind, target, meeting_id))
            saved += 1
    if saved:
        flash(f"파일 {saved}개를 첨부했습니다.")
    if rejected:
        flash("올릴 수 없는 형식입니다: " + ", ".join(rejected) + " (PDF, JPG, PNG, DOC, DOCX, HWP만 가능)", "error")
    return _go(year)


# ---------- 임원 회의 참석 현황 ----------
@bp.route("/audit/attendance")
def attendance():
    """회의실적에서 체크한 임원 출석 기록을 임원별로 모아 보여줍니다. (따로 입력하는 값 없음)"""
    with db() as conn:
        years = [r["year"] for r in conn.execute("SELECT DISTINCT year FROM meetings ORDER BY year DESC")]
        sel = request.args.get("year")
        if sel is None:
            sel = str(years[0]) if years else str(datetime.now().year)
        show_all = sel == "all"
        if not show_all:
            sel = sel if sel.isdigit() else str(datetime.now().year)
            if int(sel) not in years:
                years = sorted(set(years) | {int(sel)}, reverse=True)
        year_sql, args = ("", ()) if show_all else (" AND m.year = ?", (int(sel),))

        rows = conn.execute(
            "SELECT a.meeting_id, a.officer_id, a.officer_name, a.position, a.present, "
            "       o.name AS cur_name, o.position AS cur_position, o.sort_order AS cur_order "
            "FROM meeting_attendance a "
            "JOIN meetings m ON m.id = a.meeting_id "
            "LEFT JOIN officers o ON o.id = a.officer_id "
            "WHERE a.kind = '임원'" + year_sql, args).fetchall()

        people, recorded_ids = {}, set()
        for r in rows:
            recorded_ids.add(r["meeting_id"])
            key = r["officer_id"] if r["officer_id"] is not None else ("former", r["officer_name"])
            person = people.setdefault(key, {
                "name": r["cur_name"] or r["officer_name"],
                "position": r["cur_position"] or r["position"] or "",
                "former": r["officer_id"] is None,
                "order": r["cur_order"] if r["cur_order"] is not None else 10 ** 6,
                "held": 0, "present": 0,
            })
            person["held"] += 1
            person["present"] += r["present"]
        table = sorted(people.values(), key=lambda p: (p["former"], p["order"], p["name"]))
        for p in table:
            p["absent"] = p["held"] - p["present"]

        meetings_in_scope = conn.execute(
            "SELECT m.id, m.held_at, m.title, m.year FROM meetings m WHERE 1 = 1" + year_sql +
            " ORDER BY m.held_at, m.id", args).fetchall()
        unrecorded = [m for m in meetings_in_scope if m["id"] not in recorded_ids]

    return render_template(
        "attendance.html", page=get_menu("attendance"), years=years, selected=sel, show_all=show_all,
        table=table, recorded_count=len(recorded_ids), total_meetings=len(meetings_in_scope),
        unrecorded=unrecorded,
    )
