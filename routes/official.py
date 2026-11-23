"""공문 수·발신 내역: 기타서류 중 '공문수신' / '공문발신' 태그가 붙은 서류를 연도별로 모아 봅니다.

- 따로 저장하는 자료는 없습니다. 기타서류의 서류를 태그로 골라서 보여 줄 뿐이라, 두 화면은 항상 같습니다.
- 여기서 올린 공문은 기타서류에 서류로 저장되고(태그: 공문수신/공문발신 + 연도), 기타서류에서 이 태그를 붙이거나 떼면 여기에도 바로 반영됩니다.
- 연도는 서류에 붙은 연도 태그(예: 2026)를 따르고, 연도 태그가 없으면 올린 해를 씁니다.
"""
from datetime import datetime

from flask import Blueprint, abort, flash, redirect, render_template, request, url_for

import pdfdate
import storage
from menu import get_menu
from models import db
from .documents import DOC_TARGET, _is_year, _now, _real_tags, _set_tags, _to_local

bp = Blueprint("official", __name__)

OCR_PER_RUN = 15          # [기안일 자동 채우기] 한 번에 OCR 로 읽을 최대 건수
DIRECTIONS = {"공문수신": "수신", "공문발신": "발신"}   # 태그 이름 → 화면에 보일 짧은 이름


def _date_or_none(value):
    try:
        return datetime.strptime((value or "").strip(), "%Y-%m-%d").strftime("%Y-%m-%d")
    except ValueError:
        return None


def _doc_year(tags, created, drafted_on=None):
    if drafted_on:                       # 기안일자를 알면 그 해로 묶습니다
        return int(drafted_on[:4])
    years = sorted((n for _, n in tags if _is_year(n)), reverse=True)
    if years:
        return int(years[0])
    local = _to_local(created)
    return local.year if local else datetime.now().year


def _collect(conn):
    real = _real_tags(conn)
    versions = {}
    for f in conn.execute("SELECT * FROM files WHERE target_type = ? ORDER BY id", (DOC_TARGET,)):
        versions.setdefault(f["target_id"], []).append(f)
    items = []
    for d in conn.execute("SELECT * FROM documents WHERE is_active = 1"):
        tags = real.get((DOC_TARGET, d["id"]), [])
        names = {n for _, n in tags}
        direction = next((t for t in DIRECTIONS if t in names), None)
        if not direction:
            continue
        files = versions.get(d["id"], [])
        items.append({
            "id": d["id"], "title": d["title"], "description": d["description"] or "",
            "direction": direction, "year": _doc_year(tags, d["created_at"], d["drafted_on"]),
            "drafted_on": d["drafted_on"],
            "date": (datetime.strptime(d["drafted_on"], "%Y-%m-%d") if d["drafted_on"] else (_to_local(d["created_at"]) or datetime.min)),
            "file": files[-1] if files else None, "versions": len(files),
            "other_tags": [n for c, n in tags if n not in DIRECTIONS and not _is_year(n)],
        })
    items.sort(key=lambda it: (it["date"], it["id"]), reverse=True)     # 기안일(없으면 등록일) 최신순
    return items


@bp.route("/audit/official")
def list_view():
    with db() as conn:
        items = _collect(conn)
    years = sorted({it["year"] for it in items}, reverse=True)
    sel = request.args.get("year")
    if sel is None:
        sel = str(years[0]) if years else str(datetime.now().year)
    show_all = sel == "all"
    if not show_all:
        sel = sel if sel.isdigit() else str(datetime.now().year)
        if int(sel) not in years:
            years = sorted(set(years) | {int(sel)}, reverse=True)
    direction = request.args.get("dir", "all")
    if direction not in DIRECTIONS:
        direction = "all"

    in_year = items if show_all else [it for it in items if it["year"] == int(sel)]
    counts = {"all": len(in_year), **{k: sum(1 for it in in_year if it["direction"] == k) for k in DIRECTIONS}}
    rows = in_year if direction == "all" else [it for it in in_year if it["direction"] == direction]

    return render_template(
        "official.html", page=get_menu("official"), years=years, selected=sel, show_all=show_all,
        rows=rows, direction=direction, counts=counts, directions=DIRECTIONS,
        pdf_ready=pdfdate.available(), missing=sum(1 for it in items if not it["drafted_on"]),
        accept=storage.ACCEPT_ATTR, default_year=int(sel) if sel.isdigit() else datetime.now().year,
        year_options=sorted(set(years) | {datetime.now().year}, reverse=True),
    )


@bp.post("/audit/official/add")
def add():
    direction = request.form.get("direction", "")
    year = request.form.get("year", "").strip()
    drafted_on = _date_or_none(request.form.get("drafted_on"))
    upload = request.files.get("file")
    back = url_for("official.list_view", year=year if year.isdigit() else None)
    if direction not in DIRECTIONS or not (year.isdigit() and len(year) == 4):
        flash("수신/발신 구분을 확인해 주세요.", "error")
        return redirect(back)
    if not upload or not upload.filename:
        flash("올릴 파일을 선택해 주세요.", "error")
        return redirect(back)
    with db() as conn:
        saved = storage.save_upload(upload, "documents")
        if saved is None:
            flash("올릴 수 없는 형식입니다. (PDF, JPG, PNG, DOC, DOCX, HWP만 가능)", "error")
            return redirect(back)
        name, rel, kind = saved
        title = request.form.get("title", "").strip() or name.rsplit(".", 1)[0]
        now = _now()
        source = "직접 입력"
        if not drafted_on:              # 입력하지 않았으면 PDF 안에서 기안일자를 읽어 옵니다
            drafted_on, source = pdfdate.drafted_date(storage._safe_path(rel))
        if drafted_on:
            year = drafted_on[:4]       # 연도 태그와 연도 탭도 기안일의 해를 따릅니다
        doc_id = conn.execute(
            "INSERT INTO documents(title, description, created_at, updated_at, drafted_on) VALUES (?, ?, ?, ?, ?)",
            (title, request.form.get("description", "").strip(), now, now, drafted_on)).lastrowid
        conn.execute(
            "INSERT INTO files(original_name, stored_path, file_type, target_type, target_id, uploaded_at, note) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)", (name, rel, kind, DOC_TARGET, doc_id, now, "최초 등록"))
        _set_tags(conn, DOC_TARGET, doc_id, [f"문서종류:{direction}", f"연도:{year}"])
    if drafted_on:
        note = "" if source == "직접 입력" else f" ({source} 기준으로 자동 입력)"
        flash(f"'{title}' 공문을 올렸습니다. 기안일 {drafted_on.replace('-', '. ')}.{note} 기타 서류에도 함께 보입니다.")
    else:
        flash(f"'{title}' 공문을 올렸습니다. 기안일자를 찾지 못했습니다 — 목록의 날짜 옆 ✎ 로 입력해 주세요.", "error")
    return redirect(url_for("official.list_view", year=year))


@bp.post("/audit/official/<int:doc_id>/edit")
def edit(doc_id):
    """제목과 기안일자 고치기 (기안일자를 비우면 다시 등록일 기준으로 돌아갑니다)"""
    raw = request.form.get("drafted_on", "").strip()
    drafted_on = _date_or_none(raw)
    with db() as conn:
        d = conn.execute("SELECT * FROM documents WHERE id = ? AND is_active = 1", (doc_id,)).fetchone()
        if not d:
            abort(404)
        if raw and not drafted_on:
            flash("기안일자 형식을 확인해 주세요.", "error")
            return redirect(url_for("official.list_view", year=request.form.get("view_year")))
        title = request.form.get("title", "").strip() or d["title"]
        conn.execute("UPDATE documents SET title = ?, drafted_on = ?, updated_at = ? WHERE id = ?",
                     (title, drafted_on, _now(), doc_id))
    flash("저장했습니다.")
    return redirect(url_for("official.list_view", year=drafted_on[:4] if drafted_on else request.form.get("view_year")))


@bp.post("/audit/official/fill")
def fill():
    """기안일자가 비어 있는 공문 PDF에서 한꺼번에 기안일자를 읽어 옵니다."""
    done = failed = guessed = 0
    budget = {"left": OCR_PER_RUN, "skipped": 0}     # OCR 은 한 건에 몇 초씩 걸려 한 번에 제한합니다
    with db() as conn:
        for it in _collect(conn):
            if it["drafted_on"]:
                continue
            f = it["file"]
            found, source = pdfdate.drafted_date(storage._safe_path(f["stored_path"]), ocr_budget=budget) if f else (None, None)
            if found:
                conn.execute("UPDATE documents SET drafted_on = ? WHERE id = ?", (found, it["id"]))
                done += 1
                guessed += 1 if source and "추정" in source else 0
            else:
                failed += 1
    flash(f"기안일자를 {done}건 채웠습니다."
          + (f" 그중 {guessed}건은 '기안일자' 칸 위치를 확정하지 못해 추정한 값이니 목록에서 한 번 확인해 주세요." if guessed else "")
          + (f" {failed}건은 찾지 못했습니다. 아래에서 이유를 확인하세요." if failed else "")
          + (f" 그림 PDF {budget['skipped']}건은 OCR 에 시간이 걸려 이번에는 건너뛰었습니다. 버튼을 한 번 더 눌러 주세요." if budget["skipped"] else ""),
          "message" if done else "error")
    if failed:
        return redirect(url_for("official.diagnose"))
    return redirect(url_for("official.list_view", year="all"))


@bp.route("/audit/official/diagnose")
def diagnose():
    """기안일자를 못 읽은 공문마다 이유와 PDF 안의 글 일부를 보여 줍니다."""
    rows = []
    budget = {"left": 8, "skipped": 0}
    with db() as conn:
        for it in _collect(conn):
            if it["drafted_on"]:
                continue
            f = it["file"]
            info = pdfdate.diagnose(storage._safe_path(f["stored_path"]) if f else None, ocr_budget=budget)
            rows.append({**it, **info})
    reasons = {}
    for r in rows:
        reasons[r["label"]] = reasons.get(r["label"], 0) + 1
    return render_template("official_diagnose.html", page=get_menu("official"), rows=rows, reasons=reasons,
                           ocr=pdfdate.ocr_status())
