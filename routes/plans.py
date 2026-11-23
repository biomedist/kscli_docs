"""사업계획 및 실적: 해마다 사업실적(사업목표·사업실적·비고)과 미진사업(사업명·미진이유·비고)을 표로 정리합니다.

- 사업목표는 매년 쓰는 보수교육계획서의 내용을 옮겨 적으면 되고, 계획서 파일 자체도 그 해 칸에 첨부해 둘 수 있습니다.
- 새 해에는 [지난해 사업목표 가져오기]로 목표만 복사해 두고 실적을 채워 넣으면 됩니다.
"""
from datetime import datetime

from flask import Blueprint, flash, redirect, render_template, request, url_for

import re

import pdfdate
import storage
from menu import get_menu
from models import db

bp = Blueprint("plans", __name__)

PLAN_DOC = "plan_doc"                      # 그 해의 보수교육계획서 파일 (target_id = 연도)
KINDS = {"실적": "사업실적", "미진": "미진사업"}


WEEKDAYS = "월화수목금토일"


def _event_option(e):
    """[행사 불러오기] 목록의 한 줄: 화면에 보일 이름, 사업목표 후보, 사업실적에 채울 글"""
    try:
        d = datetime.strptime(e["held_on"], "%Y-%m-%d")
        day = f"{d.year}. {d.month}. {d.day}.({WEEKDAYS[d.weekday()]})"
    except (TypeError, ValueError):
        day = e["held_on"] or ""
    when = day + (f" {e['start_time']}~{e['end_time']}" if e["start_time"] and e["end_time"] else "")
    lines = [f"일시: {when}"]
    if e["place"]:
        lines.append(f"장소: {e['place']}")
    if e["attendees"] is not None:
        lines.append(f"참석: {e['attendees']}명")
    title = e["name"] or e["kind"]
    return {"label": f"{day} · {e['kind']}{' · ' + e['name'] if e['name'] else ''}", "name": title, "text": "\n".join(lines)}


def _back(year):
    return redirect(url_for("plans.list_view", year=year))


@bp.route("/audit/plans")
def list_view():
    with db() as conn:
        # 사업·미진 항목이 있는 해 + 보수교육계획서 파일만 올려 둔 해도 탭에 보이게 합니다
        found = {r[0] for r in conn.execute("SELECT DISTINCT year FROM plans WHERE year IS NOT NULL")}
        found |= {r[0] for r in conn.execute("SELECT DISTINCT target_id FROM files WHERE target_type = ?", (PLAN_DOC,))}
        years = sorted(found, reverse=True)
        this_year = datetime.now().year
        # 처음 열 때는 올해(자료가 있으면), 없으면 가장 최근 해를 보여 줍니다
        default = this_year if this_year in found else (years[0] if years else this_year)
        sel = request.args.get("year") or str(default)
        sel = sel if sel.isdigit() else str(datetime.now().year)
        year = int(sel)
        if year not in years:
            years = sorted(set(years) | {year}, reverse=True)
        rows = conn.execute("SELECT * FROM plans WHERE year = ? ORDER BY COALESCE(sort_order, id), id", (year,)).fetchall()
        docs = storage.files_for(conn, (PLAN_DOC,), [year]).get((PLAN_DOC, year), [])
        events_rows = conn.execute("SELECT * FROM events WHERE substr(held_on, 1, 4) = ? ORDER BY held_on, start_time, id", (sel,)).fetchall()
        prev_goals = conn.execute("SELECT COUNT(*) FROM plans WHERE year = ? AND kind = '실적'", (year - 1,)).fetchone()[0]
    events = [_event_option(e) for e in events_rows]
    results = [r for r in rows if r["kind"] == "실적"]
    lags = [r for r in rows if r["kind"] == "미진"]
    return render_template(
        "plans.html", page=get_menu("plans"), years=years, year=year, results=results, lags=lags, docs=docs,
        accept=storage.ACCEPT_ATTR, can_copy=bool(prev_goals) and not results, events=events,
        has_pdf=any(d["file_type"] == "pdf" for d in docs))


def _fields():
    f = request.form
    kind = f.get("kind", "")
    name = f.get("name", "").strip()
    year = f.get("year", "")
    if kind not in KINDS or not name or not year.isdigit():
        return None
    return {"kind": kind, "name": name[:500], "result": f.get("result", "").strip()[:2000],
            "note": f.get("note", "").strip()[:1000], "year": int(year)}


@bp.post("/audit/plans/add")
def add():
    fields = _fields()
    if not fields:
        flash("내용(사업목표 또는 사업명)을 입력해 주세요.", "error")
        return _back(request.form.get("year"))
    with db() as conn:
        cur = conn.execute("INSERT INTO plans(kind, name, result, note, year) VALUES (:kind, :name, :result, :note, :year)", fields)
        conn.execute("UPDATE plans SET sort_order = id WHERE id = ?", (cur.lastrowid,))
    flash(f"{KINDS[fields['kind']]}을(를) 추가했습니다." if fields["kind"] == "미진" else "사업실적을 추가했습니다.")
    return _back(fields["year"])


@bp.post("/audit/plans/<int:plan_id>/edit")
def edit(plan_id):
    fields = _fields()
    if not fields:
        flash("내용을 입력해 주세요.", "error")
        return _back(request.form.get("year"))
    with db() as conn:
        conn.execute("UPDATE plans SET name = :name, result = :result, note = :note WHERE id = :id", {**fields, "id": plan_id})
    flash("저장했습니다.")
    return _back(fields["year"])


@bp.post("/audit/plans/<int:plan_id>/delete")
def delete(plan_id):
    with db() as conn:
        row = conn.execute("SELECT year FROM plans WHERE id = ?", (plan_id,)).fetchone()
        conn.execute("DELETE FROM plans WHERE id = ?", (plan_id,))
    flash("삭제했습니다.")
    return _back(row["year"] if row else None)


@bp.post("/audit/plans/<int:plan_id>/move")
def move(plan_id):
    direction = request.form.get("dir")
    with db() as conn:
        row = conn.execute("SELECT * FROM plans WHERE id = ?", (plan_id,)).fetchone()
        if not row:
            return _back(None)
        mates = conn.execute("SELECT id, COALESCE(sort_order, id) AS s FROM plans WHERE year = ? AND kind = ? "
                             "ORDER BY COALESCE(sort_order, id), id", (row["year"], row["kind"])).fetchall()
        ids = [m["id"] for m in mates]
        i = ids.index(plan_id)
        j = i - 1 if direction == "up" else i + 1
        if 0 <= j < len(ids):
            ids[i], ids[j] = ids[j], ids[i]
            for n, pid in enumerate(ids, 1):      # 순서를 1부터 다시 매겨 겹치지 않게 함
                conn.execute("UPDATE plans SET sort_order = ? WHERE id = ?", (n, pid))
    return _back(row["year"])


@bp.post("/audit/plans/copy")
def copy_goals():
    year = int(request.form.get("year", "0") or 0)
    with db() as conn:
        if conn.execute("SELECT 1 FROM plans WHERE year = ? AND kind = '실적'", (year,)).fetchone():
            flash("이미 사업실적이 있어 가져오지 않았습니다.", "error")
            return _back(year)
        prev = conn.execute("SELECT name FROM plans WHERE year = ? AND kind = '실적' ORDER BY COALESCE(sort_order, id), id", (year - 1,)).fetchall()
        for r in prev:
            cur = conn.execute("INSERT INTO plans(kind, name, year) VALUES ('실적', ?, ?)", (r["name"], year))
            conn.execute("UPDATE plans SET sort_order = id WHERE id = ?", (cur.lastrowid,))
    flash(f"{year - 1}년 사업목표 {len(prev)}건을 가져왔습니다. 사업실적을 채워 주세요." if prev else "가져올 사업목표가 없습니다.",
          "message" if prev else "error")
    return _back(year)


@bp.post("/audit/plans/upload")
def upload():
    year = request.form.get("year", "")
    if not year.isdigit():
        return _back(None)
    with db() as conn:
        storage.save_request_files(conn, PLAN_DOC, int(year), "plans")
    return _back(year)


# ---------- 보수교육계획서(PDF)에서 사업목표 불러오기 ----------
_BULLET = re.compile(r"^(?:[□■▣◆◇●○◦▶▷❍ㅇ※]|\(?\d{1,2}\s*[.)]|\(?[가-하]\s*[.)]|[ⅠⅡⅢⅣⅤⅥⅦⅧ]\s*[.)]?)\s*")
_PAGE_NO = re.compile(r"^[-–—\s]*\d{1,3}\s*(?:/\s*\d{1,3})?[-–—\s]*$")


def _candidates(text, only_headings):
    """PDF 글을 줄 단위 후보로 나눕니다. 번호·기호로 시작하는 줄(□, 1., 가. 등)을 제목처럼 보고 우선 보여 줍니다."""
    lines, heads = [], []
    for raw in text.splitlines():
        line = re.sub(r"\s+", " ", raw).strip()
        if len(line) < 3 or _PAGE_NO.match(line):
            continue
        lines.append(line)
        if _BULLET.match(line):
            heads.append(_BULLET.sub("", line, count=1).strip())
    picked = heads if (only_headings and heads) else [_BULLET.sub("", l, count=1).strip() or l for l in lines]
    seen, out = set(), []
    for l in picked:
        if l and l not in seen:
            seen.add(l)
            out.append(l[:200])
    return out, bool(heads)


@bp.route("/audit/plans/import")
def import_view():
    year = request.args.get("year", "")
    if not year.isdigit():
        return _back(None)
    with db() as conn:
        files = [f for f in storage.files_for(conn, (PLAN_DOC,), [int(year)]).get((PLAN_DOC, int(year)), []) if f["file_type"] == "pdf"]
        existing = {r[0] for r in conn.execute("SELECT name FROM plans WHERE year = ? AND kind = '실적'", (int(year),))}
    if not files:
        flash(f"{year}년 보수교육계획서(PDF)가 아직 없습니다. 먼저 [+ 첨부]로 올려 주세요.", "error")
        return _back(year)
    chosen = next((f for f in files if str(f["id"]) == request.args.get("file")), None) \
        or next((f for f in files if "계획" in f["original_name"]), files[0])
    only_headings = request.args.get("all") != "1"
    text = pdfdate.full_text(storage._safe_path(chosen["stored_path"]))
    lines, has_heads = _candidates(text, only_headings)
    return render_template(
        "plans_import.html", page=get_menu("plans"), year=int(year), files=files, chosen=chosen, lines=lines,
        has_heads=has_heads, only_headings=only_headings, no_text=not text.strip(), pdf_ready=pdfdate.available(),
        existing=existing, total_chars=len(text))


@bp.post("/audit/plans/import")
def import_save():
    year = request.form.get("year", "")
    if not year.isdigit():
        return _back(None)
    wanted = [re.sub(r"\s+", " ", l).strip()[:500] for l in request.form.get("lines", "").splitlines()]
    wanted = [l for l in wanted if l][:100]
    with db() as conn:
        existing = {r[0] for r in conn.execute("SELECT name FROM plans WHERE year = ? AND kind = '실적'", (int(year),))}
        added = 0
        for name in wanted:
            if name in existing:
                continue
            existing.add(name)
            cur = conn.execute("INSERT INTO plans(kind, name, year) VALUES ('실적', ?, ?)", (name, int(year)))
            conn.execute("UPDATE plans SET sort_order = id WHERE id = ?", (cur.lastrowid,))
            added += 1
    skipped = len(wanted) - added
    flash(f"사업목표 {added}건을 등록했습니다." + (f" (이미 있는 {skipped}건은 건너뜀)" if skipped else "")
          if added else "등록할 새 사업목표가 없습니다.", "message" if added else "error")
    return _back(year)
