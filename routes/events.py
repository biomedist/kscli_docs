"""보수교육·학술대회·워크숍: 행사 목록(1단계) → 행사별 프로그램표(2단계)."""
from datetime import datetime

from flask import Blueprint, abort, flash, redirect, render_template, request, url_for

import storage
from menu import get_menu
from models import db

bp = Blueprint("events", __name__)

KINDS = ["보수교육", "학술대회", "워크숍"]
EVENT_DOC = "event_doc"          # 행사 전체 관련문서
PROGRAM_FILE = "event_material"  # 프로그램(강의)별 발표자료


# ---------- 화면용 도우미 ----------
@bp.app_template_filter("kdate")
def kdate(value):
    """'2026-04-18' → '2026. 4. 18.'"""
    try:
        d = datetime.strptime(value, "%Y-%m-%d")
    except (TypeError, ValueError):
        return value or ""
    return f"{d.year}. {d.month}. {d.day}."


@bp.app_template_filter("krange")
def krange(row):
    """시작·종료 시간을 '10:00 ~ 10:40' 으로 보여줍니다."""
    start, end = row["start_time"], row["end_time"]
    if start and end:
        return f"{start} ~ {end}"
    return start or end or ""


def _go(year=None, kind=None):
    args = {}
    if year:
        args["year"] = year
    if kind in KINDS:
        args["kind"] = kind
    return redirect(url_for("events.list_view", **args))


def _clock(prefix):
    """시·분 선택값을 'HH:MM' 으로. 비었으면 '', 잘못되면 None."""
    h = request.form.get(prefix + "_h", "").strip()
    m = request.form.get(prefix + "_m", "").strip()
    if not h and not m:
        return ""
    if not (h.isdigit() and m.isdigit()) or int(h) > 23 or int(m) > 59:
        return None
    return f"{int(h):02d}:{int(m):02d}"


def _save_files(conn, target_type, target_id):
    """요청에 담긴 파일을 저장하고 결과 안내를 띄웁니다."""
    saved, rejected = 0, []
    for fs in request.files.getlist("files"):
        if not fs or not fs.filename:
            continue
        result = storage.save_upload(fs, "events")
        if result is None:
            rejected.append(fs.filename)
            continue
        name, rel, kind = result
        conn.execute(
            "INSERT INTO files(original_name, stored_path, file_type, target_type, target_id) "
            "VALUES (?, ?, ?, ?, ?)", (name, rel, kind, target_type, target_id))
        saved += 1
    if saved:
        flash(f"파일 {saved}개를 첨부했습니다.")
    if rejected:
        flash("올릴 수 없는 형식입니다: " + ", ".join(rejected) + " (PDF, JPG, PNG, DOC, DOCX, HWP만 가능)", "error")


def _back_to(event_id, year=None, kind=None):
    if request.form.get("back") == "detail":
        return redirect(url_for("events.detail", event_id=event_id))
    return _go(year, kind)


# ---------- 1단계: 행사 목록 ----------
@bp.route("/audit/events")
def list_view():
    kind = request.args.get("kind")
    kind = kind if kind in KINDS else None
    with db() as conn:
        years = [int(r["y"]) for r in conn.execute(
            "SELECT DISTINCT substr(held_on, 1, 4) AS y FROM events WHERE held_on != '' ORDER BY y DESC")
            if r["y"].isdigit()]
        sel = request.args.get("year")
        if sel is None:
            sel = str(years[0]) if years else str(datetime.now().year)
        show_all = sel == "all"
        sql = ("SELECT e.*, (SELECT COUNT(*) FROM event_programs p WHERE p.event_id = e.id) AS program_count "
               "FROM events e WHERE 1 = 1")
        args = []
        if not show_all:
            sel = sel if sel.isdigit() else str(datetime.now().year)
            sql += " AND substr(e.held_on, 1, 4) = ?"
            args.append(sel)
            if int(sel) not in years:
                years = sorted(set(years) | {int(sel)}, reverse=True)
        if kind:
            sql += " AND e.kind = ?"
            args.append(kind)
        sql += " ORDER BY e.held_on DESC, e.start_time, e.id"
        events = conn.execute(sql, args).fetchall()
        files = storage.files_for(conn, (EVENT_DOC,), [e["id"] for e in events])

    counts = {k: sum(1 for e in events if e["kind"] == k) for k in KINDS}
    summary = [(k, n) for k, n in counts.items() if n]
    return render_template(
        "events.html", page=get_menu("events"), years=years, selected=sel, show_all=show_all,
        kinds=KINDS, kind=kind, events=events, files=files, accept=storage.ACCEPT_ATTR, summary=summary,
    )


# ---------- 행사 저장 ----------
def _event_fields():
    f = request.form
    kind = f.get("kind", "").strip()
    held_on = f.get("held_on", "").strip()
    try:
        datetime.strptime(held_on, "%Y-%m-%d")
    except ValueError:
        return None
    start, end = _clock("start"), _clock("end")
    if kind not in KINDS or start is None or end is None:
        return None
    attendees = f.get("attendees", "").strip()
    return {
        "kind": kind, "name": f.get("name", "").strip(), "held_on": held_on,
        "start_time": start, "end_time": end, "place": f.get("place", "").strip(),
        "attendees": int(attendees) if attendees.isdigit() else None,
    }


@bp.post("/audit/events/add")
def add():
    fields = _event_fields()
    if not fields:
        flash("구분과 일자를 확인해 주세요.", "error")
        return _go()
    with db() as conn:
        cur = conn.execute(
            "INSERT INTO events(kind, name, held_on, start_time, end_time, place, attendees) "
            "VALUES (:kind, :name, :held_on, :start_time, :end_time, :place, :attendees)", fields)
    flash("행사를 추가했습니다. [+ 프로그램 추가]로 시간별 강의를 입력하세요.")
    return redirect(url_for("events.detail", event_id=cur.lastrowid))


@bp.post("/audit/events/<int:event_id>/edit")
def edit(event_id):
    fields = _event_fields()
    if not fields:
        flash("구분과 일자를 확인해 주세요.", "error")
        return _back_to(event_id)
    with db() as conn:
        conn.execute(
            "UPDATE events SET kind=:kind, name=:name, held_on=:held_on, start_time=:start_time, "
            "end_time=:end_time, place=:place, attendees=:attendees WHERE id=:id", {**fields, "id": event_id})
    flash("행사 정보를 저장했습니다.")
    return _back_to(event_id, fields["held_on"][:4])


@bp.post("/audit/events/<int:event_id>/delete")
def delete(event_id):
    year = request.form.get("year") or None
    kind = request.form.get("kind") or None
    with db() as conn:
        row = conn.execute("SELECT kind, name, held_on FROM events WHERE id = ?", (event_id,)).fetchone()
        if row and conn.execute("SELECT 1 FROM donations WHERE event_id = ?", (event_id,)).fetchone():
            flash("찬조금 내역이 연결된 행사는 삭제할 수 없습니다. 찬조금 내역을 먼저 정리해 주세요.", "error")
            return _go(year, kind)
        if row:
            for p in conn.execute("SELECT id FROM event_programs WHERE event_id = ?", (event_id,)).fetchall():
                storage.delete_files_for(conn, (PROGRAM_FILE,), p["id"])
            storage.delete_files_for(conn, (EVENT_DOC,), event_id)
            conn.execute("DELETE FROM events WHERE id = ?", (event_id,))   # 프로그램은 함께 삭제됨
            flash(f"'{row['name'] or row['kind']} ({kdate(row['held_on'])})' 행사와 프로그램·첨부파일을 삭제했습니다.")
    return _go(year, kind)


@bp.post("/audit/events/<int:event_id>/upload")
def upload(event_id):
    year = request.form.get("year") or None
    kind = request.form.get("kind") or None
    with db() as conn:
        if not conn.execute("SELECT 1 FROM events WHERE id = ?", (event_id,)).fetchone():
            flash("행사를 찾을 수 없습니다.", "error")
            return _go(year, kind)
        _save_files(conn, EVENT_DOC, event_id)
    return _back_to(event_id, year, kind)


# ---------- 2단계: 행사 프로그램표 ----------
@bp.route("/audit/events/<int:event_id>")
def detail(event_id):
    with db() as conn:
        event = conn.execute("SELECT * FROM events WHERE id = ?", (event_id,)).fetchone()
        if not event:
            abort(404)
        programs = conn.execute(
            "SELECT * FROM event_programs WHERE event_id = ? "
            "ORDER BY (start_time IS NULL OR start_time = ''), start_time, id", (event_id,)).fetchall()
        event_files = storage.files_for(conn, (EVENT_DOC,), [event_id])
        program_files = storage.files_for(conn, (PROGRAM_FILE,), [p["id"] for p in programs])
    return render_template(
        "event_detail.html", page=get_menu("events"), event=event, programs=programs, kinds=KINDS,
        event_files=event_files.get((EVENT_DOC, event_id), []), program_files=program_files,
        accept=storage.ACCEPT_ATTR,
    )


def _program_fields():
    f = request.form
    title = f.get("title", "").strip()
    start, end = _clock("start"), _clock("end")
    if not title or start is None or end is None:
        return None
    return {"title": title, "start_time": start, "end_time": end,
            "speaker": f.get("speaker", "").strip(), "affiliation": f.get("affiliation", "").strip()}


@bp.post("/audit/events/<int:event_id>/programs/add")
def program_add(event_id):
    fields = _program_fields()
    if not fields:
        flash("강의명을 입력해 주세요.", "error")
        return redirect(url_for("events.detail", event_id=event_id))
    with db() as conn:
        if not conn.execute("SELECT 1 FROM events WHERE id = ?", (event_id,)).fetchone():
            abort(404)
        conn.execute(
            "INSERT INTO event_programs(event_id, start_time, end_time, title, speaker, affiliation) "
            "VALUES (:event_id, :start_time, :end_time, :title, :speaker, :affiliation)",
            {**fields, "event_id": event_id})
    flash(f"'{fields['title']}' 프로그램을 추가했습니다.")
    return redirect(url_for("events.detail", event_id=event_id))


def _program_event_id(conn, program_id):
    row = conn.execute("SELECT event_id FROM event_programs WHERE id = ?", (program_id,)).fetchone()
    if not row:
        abort(404)
    return row["event_id"]


@bp.post("/audit/programs/<int:program_id>/edit")
def program_edit(program_id):
    fields = _program_fields()
    with db() as conn:
        event_id = _program_event_id(conn, program_id)
        if not fields:
            flash("강의명을 입력해 주세요.", "error")
        else:
            conn.execute(
                "UPDATE event_programs SET title=:title, start_time=:start_time, end_time=:end_time, "
                "speaker=:speaker, affiliation=:affiliation WHERE id=:id", {**fields, "id": program_id})
            flash(f"'{fields['title']}' 프로그램을 저장했습니다.")
    return redirect(url_for("events.detail", event_id=event_id))


@bp.post("/audit/programs/<int:program_id>/delete")
def program_delete(program_id):
    with db() as conn:
        event_id = _program_event_id(conn, program_id)
        title = conn.execute("SELECT title FROM event_programs WHERE id = ?", (program_id,)).fetchone()["title"]
        storage.delete_files_for(conn, (PROGRAM_FILE,), program_id)
        conn.execute("DELETE FROM event_programs WHERE id = ?", (program_id,))
        flash(f"'{title}' 프로그램과 발표자료를 삭제했습니다.")
    return redirect(url_for("events.detail", event_id=event_id))


@bp.post("/audit/programs/<int:program_id>/upload")
def program_upload(program_id):
    with db() as conn:
        event_id = _program_event_id(conn, program_id)
        _save_files(conn, PROGRAM_FILE, program_id)
    return redirect(url_for("events.detail", event_id=event_id))
