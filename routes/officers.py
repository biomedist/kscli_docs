"""역대 임원·평의원 명부: 임원 / 평의원 목록과 역대 회장단 목록."""
from flask import Blueprint, flash, redirect, render_template, request, url_for

from models import db
from menu import get_menu

bp = Blueprint("officers", __name__)

KIND_BY_TAB = {"exec": "임원", "council": "평의원"}
TAB_LABELS = {"exec": "임원", "council": "평의원", "presidents": "역대 회장단"}
POSITION_HINTS = [
    "학회장", "부학회장", "총무이사", "재무이사", "학술이사", "교육이사",
    "공보이사", "기획이사", "정무이사", "학술간사", "행정간사", "평의원",
]


def _go(tab):
    return redirect(url_for("officers.roster", tab=tab))


def _tab_from_form():
    tab = request.form.get("tab", "exec")
    return tab if tab in TAB_LABELS else "exec"


# ---------- 목록 화면 ----------
@bp.route("/audit/officers")
def roster():
    tab = request.args.get("tab", "exec")
    if tab not in TAB_LABELS:
        tab = "exec"
    with db() as conn:
        counts = {"exec": 0, "council": 0}
        for r in conn.execute("SELECT kind, COUNT(*) AS n FROM officers GROUP BY kind"):
            for key, kind in KIND_BY_TAB.items():
                if r["kind"] == kind:
                    counts[key] = r["n"]
        counts["presidents"] = conn.execute("SELECT COUNT(*) FROM presidents").fetchone()[0]

        officers, presidents, next_generation = [], [], 1
        if tab == "presidents":
            presidents = conn.execute("SELECT * FROM presidents ORDER BY generation DESC, id DESC").fetchall()
            next_generation = conn.execute(
                "SELECT COALESCE(MAX(generation), 0) + 1 FROM presidents").fetchone()[0]
        else:
            officers = conn.execute(
                "SELECT * FROM officers WHERE kind = ? ORDER BY sort_order, id",
                (KIND_BY_TAB[tab],)).fetchall()

    return render_template(
        "officers.html", page=get_menu("officers"), tab=tab, tab_labels=TAB_LABELS,
        counts=counts, officers=officers, presidents=presidents,
        next_generation=next_generation, position_hints=POSITION_HINTS,
    )


# ---------- 임원·평의원 ----------
def _officer_fields():
    f = request.form
    position = f.get("position", "").strip()
    name = f.get("name", "").strip()
    if not position or not name:
        return None
    return position, name, f.get("workplace", "").strip(), f.get("email", "").strip()


@bp.post("/audit/officers/add")
def add():
    tab = _tab_from_form()
    fields = _officer_fields()
    if tab not in KIND_BY_TAB or not fields:
        flash("직위와 성명을 입력해 주세요.", "error")
        return _go(tab)
    kind = KIND_BY_TAB[tab]
    with db() as conn:
        nxt = conn.execute(
            "SELECT COALESCE(MAX(sort_order), 0) + 1 FROM officers WHERE kind = ?", (kind,)
        ).fetchone()[0]
        conn.execute(
            "INSERT INTO officers(kind, position, name, workplace, email, sort_order) "
            "VALUES (?, ?, ?, ?, ?, ?)", (kind, *fields, nxt))
    flash(f"{fields[1]} 님을 추가했습니다.")
    return _go(tab)


@bp.post("/audit/officers/<int:officer_id>/edit")
def edit(officer_id):
    tab = _tab_from_form()
    fields = _officer_fields()
    if not fields:
        flash("직위와 성명을 입력해 주세요.", "error")
        return _go(tab)
    with db() as conn:
        conn.execute(
            "UPDATE officers SET position = ?, name = ?, workplace = ?, email = ? WHERE id = ?",
            (*fields, officer_id))
    flash(f"{fields[1]} 님의 정보를 저장했습니다.")
    return _go(tab)


@bp.post("/audit/officers/<int:officer_id>/delete")
def delete(officer_id):
    tab = _tab_from_form()
    with db() as conn:
        row = conn.execute("SELECT name FROM officers WHERE id = ?", (officer_id,)).fetchone()
        if row:
            conn.execute("DELETE FROM officers WHERE id = ?", (officer_id,))
            flash(f"{row['name']} 님을 삭제했습니다.")
    return _go(tab)


@bp.post("/audit/officers/<int:officer_id>/move")
def move(officer_id):
    """같은 구분(임원/평의원) 안에서 한 칸 위·아래로 이동합니다."""
    tab = _tab_from_form()
    step = -1 if request.form.get("dir") == "up" else 1
    with db() as conn:
        row = conn.execute("SELECT kind FROM officers WHERE id = ?", (officer_id,)).fetchone()
        if row:
            ids = [r["id"] for r in conn.execute(
                "SELECT id FROM officers WHERE kind = ? ORDER BY sort_order, id", (row["kind"],))]
            i = ids.index(officer_id)
            j = i + step
            if 0 <= j < len(ids):
                ids[i], ids[j] = ids[j], ids[i]
            for n, oid in enumerate(ids, 1):
                conn.execute("UPDATE officers SET sort_order = ? WHERE id = ?", (n, oid))
    return _go(tab)


# ---------- 역대 회장단 ----------
def _president_fields():
    f = request.form
    try:
        generation = int(f.get("generation", "").strip())
    except ValueError:
        return None
    president = f.get("president", "").strip()
    if generation < 1 or not president:
        return None
    return generation, f.get("period", "").strip(), president, f.get("vice_president", "").strip()


def _generation_taken(conn, generation, exclude_id=0):
    return conn.execute(
        "SELECT 1 FROM presidents WHERE generation = ? AND id != ?", (generation, exclude_id)
    ).fetchone() is not None


@bp.post("/audit/presidents/add")
def president_add():
    fields = _president_fields()
    if not fields:
        flash("대수(숫자)와 회장 성명을 입력해 주세요.", "error")
        return _go("presidents")
    with db() as conn:
        if _generation_taken(conn, fields[0]):
            flash(f"{fields[0]}대는 이미 등록되어 있습니다.", "error")
            return _go("presidents")
        conn.execute(
            "INSERT INTO presidents(generation, period, president, vice_president) "
            "VALUES (?, ?, ?, ?)", fields)
    flash(f"{fields[0]}대 회장단을 추가했습니다.")
    return _go("presidents")


@bp.post("/audit/presidents/<int:pid>/edit")
def president_edit(pid):
    fields = _president_fields()
    if not fields:
        flash("대수(숫자)와 회장 성명을 입력해 주세요.", "error")
        return _go("presidents")
    with db() as conn:
        if _generation_taken(conn, fields[0], pid):
            flash(f"{fields[0]}대는 이미 등록되어 있습니다.", "error")
            return _go("presidents")
        conn.execute(
            "UPDATE presidents SET generation = ?, period = ?, president = ?, vice_president = ? "
            "WHERE id = ?", (*fields, pid))
    flash(f"{fields[0]}대 회장단을 저장했습니다.")
    return _go("presidents")


@bp.post("/audit/presidents/<int:pid>/delete")
def president_delete(pid):
    with db() as conn:
        row = conn.execute("SELECT generation FROM presidents WHERE id = ?", (pid,)).fetchone()
        if row:
            conn.execute("DELETE FROM presidents WHERE id = ?", (pid,))
            flash(f"{row['generation']}대 회장단을 삭제했습니다.")
    return _go("presidents")
