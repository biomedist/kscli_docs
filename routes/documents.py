"""기타서류: 서류 업로드와 태그 검색. 다른 탭(회의·행사·통장)에 첨부된 파일도 같은 검색창에서 찾습니다.

- 직접 올린 서류: documents 표 + 파일(새 버전을 올리면 이전 버전은 보관) + 검토 기록
- 다른 탭의 첨부파일: 올린 곳에 따라 '자동 태그'(회의록, 행사 구분, 연도 …)가 계산되어 붙고, 직접 단 태그도 함께 씁니다.
- 태그는 '이름'이 같으면 같은 태그입니다. (카테고리는 정리·색상용 묶음)
- 색상은 카테고리마다 기본색이 있고, 태그마다 따로 바꿀 수 있습니다. 비슷한 태그끼리 같은 색을 쓰면 한눈에 구분됩니다.
- 금액 자료(통장 사본 등)는 비밀번호로 잠금을 푼 상태에서만 검색 결과에 나옵니다.
"""
import math
import re
from collections import Counter
from datetime import datetime, timezone

from flask import Blueprint, abort, flash, redirect, render_template, request, url_for

import auth
import pdfdate
import storage
from menu import get_menu
from models import db

bp = Blueprint("documents", __name__)

PAGE_SIZE = 24
DOC_TARGET = "document"
DEFAULT_CATEGORY = "문서종류"
DEFAULT_CATEGORIES = ["문서종류", "담당자"]
SRC_NAMES = {"doc": "기타서류", "meeting": "회의", "event": "행사", "money": "금액 자료"}

# 태그 색 12가지 (static/style.css 의 .tc0 ~ .tc11 과 같은 순서)
PALETTE_NAMES = ["주황", "파랑", "초록", "분홍", "보라", "올리브", "빨강", "청록", "노랑", "회색", "갈색", "하늘"]
DEFAULT_CATEGORY_COLORS = {"문서종류": 2, "담당자": 1, "연도": 0, "행사구분": 4}
VIRTUAL_CATEGORIES = ["연도", "행사구분"]   # 출처에서 자동으로 붙는 태그의 카테고리


# ---------- 화면용 도우미 ----------
def _now():
    return datetime.now().isoformat(timespec="seconds")


def _to_local(value):
    """DB 기본 시각(UTC)과 앱이 직접 기록한 현지 시각을 모두 현지 시각으로 맞춥니다."""
    if not value:
        return None
    try:
        d = datetime.fromisoformat(value)
    except ValueError:
        return None
    if len(value) > 10 and "T" not in value and d.tzinfo is None:   # 'YYYY-MM-DD HH:MM:SS' = DB 기본 시각(UTC)
        d = d.replace(tzinfo=timezone.utc).astimezone().replace(tzinfo=None)
    return d


@bp.app_template_filter("kdatetime")
def kdatetime(value, mode="date"):
    if isinstance(value, str):
        value = _to_local(value)
    if not value:
        return ""
    text = f"{value.year}. {value.month}. {value.day}."
    return text + (f" {value:%H:%M}" if mode == "full" else "")


def _is_year(name):
    return bool(re.fullmatch(r"\d{4}", name))


# ---------- 태그 색 ----------
def _category_colors(conn, names):
    """카테고리별 기본색. 처음 보는 카테고리는 아직 안 쓴 색을 하나 배정해 저장합니다."""
    colors = {r["name"]: r["color"] for r in conn.execute("SELECT name, color FROM tag_categories")}
    used = set(colors.values())
    for name in names:
        if name in colors:
            continue
        color = DEFAULT_CATEGORY_COLORS.get(name)
        if color is None or color in used:
            color = next((i for i in range(len(PALETTE_NAMES)) if i not in used), len(colors) % len(PALETTE_NAMES))
        conn.execute("INSERT OR IGNORE INTO tag_categories(name, color) VALUES (?, ?)", (name, color))
        colors[name] = color
        used.add(color)
    return colors


def _tag_context(conn):
    """이름으로 태그를 찾고 색을 정하기 위한 정보."""
    reg = {r["name"]: (r["category"], r["color"]) for r in conn.execute("SELECT name, category, color FROM tags")}
    names = list(dict.fromkeys(list(DEFAULT_CATEGORY_COLORS) + [c for c, _ in reg.values()]))
    return {"reg": reg, "cat": _category_colors(conn, names)}


def _resolve(tctx, name, fallback_category):
    """태그 이름 → (카테고리, 색). 만들어 둔 태그가 있으면 그 카테고리·색을 따릅니다."""
    if name in tctx["reg"]:
        category, override = tctx["reg"][name]
        return category, override if override is not None else tctx["cat"].get(category, 9)
    return fallback_category, tctx["cat"].get(fallback_category, 9)


# ---------- 태그 저장 ----------
def _clean_tags(raw_values):
    """'카테고리:이름' 문자열 목록을 정리합니다. 카테고리가 없으면 '문서종류'. 같은 이름은 하나로."""
    seen, out = set(), []
    for raw in raw_values:
        category, _, name = raw.partition(":") if ":" in raw else (DEFAULT_CATEGORY, "", raw)
        category, name = (category.strip() or DEFAULT_CATEGORY)[:20], name.strip()[:30]
        if not name or name in seen:
            continue
        seen.add(name)
        out.append((category, name))
    return out


def _set_tags(conn, target_type, target_id, raw_values):
    """대상에 붙은 태그를 주어진 목록으로 바꿉니다. 같은 이름의 태그가 있으면 그것을 쓰고, 없으면 새로 만듭니다."""
    ids = []
    for category, name in _clean_tags(raw_values):
        row = conn.execute("SELECT id FROM tags WHERE name = ?", (name,)).fetchone()
        if row is None:
            row = {"id": conn.execute("INSERT INTO tags(name, category) VALUES (?, ?)", (name, category)).lastrowid}
        ids.append(row["id"])
    conn.execute("DELETE FROM tag_links WHERE target_type = ? AND target_id = ?", (target_type, target_id))
    for tag_id in ids:
        conn.execute("INSERT OR IGNORE INTO tag_links(tag_id, target_type, target_id) VALUES (?, ?, ?)",
                     (tag_id, target_type, target_id))


def _real_tags(conn):
    """{(대상 종류, 대상 id): [(카테고리, 이름), ...]}"""
    out = {}
    for r in conn.execute(
            "SELECT tl.target_type, tl.target_id, t.category, t.name FROM tag_links tl "
            "JOIN tags t ON t.id = tl.tag_id ORDER BY t.category, t.name"):
        out.setdefault((r["target_type"], r["target_id"]), []).append((r["category"], r["name"]))
    return out


def _popular_tags(conn, tctx):
    """만들어 둔 태그를 많이 쓰는 순으로. (태그 편집 창의 '자주 쓰는 태그')"""
    rows = conn.execute(
        "SELECT t.name, COUNT(tl.tag_id) AS n FROM tags t LEFT JOIN tag_links tl ON tl.tag_id = t.id "
        "GROUP BY t.id ORDER BY n DESC, t.name").fetchall()
    out = []
    for r in rows:
        category, color = _resolve(tctx, r["name"], DEFAULT_CATEGORY)
        out.append({"name": r["name"], "category": category, "color": color, "n": r["n"]})
    return out


def _category_names(conn):
    names = [r["category"] for r in conn.execute(
        "SELECT category, COUNT(*) AS n FROM tags GROUP BY category ORDER BY n DESC")]
    return names + [c for c in DEFAULT_CATEGORIES if c not in names]


def _merge_tags(real, auto, tctx):
    """직접 단 태그 + 자동 태그를 이름 기준으로 합칩니다. (같은 이름이면 한 번만)"""
    seen, out = set(), []
    for category, name in real:
        if name in seen:
            continue
        seen.add(name)
        category, color = _resolve(tctx, name, category)
        out.append({"category": category, "name": name, "auto": False, "key": name, "color": color})
    for category, name in auto:
        if name in seen or not name:
            continue
        seen.add(name)
        category, color = _resolve(tctx, name, category)
        out.append({"category": category, "name": name, "auto": True, "key": name, "color": color})
    return out


# ---------- 다른 탭 첨부파일의 출처·자동 태그 ----------
def _load_context(conn):
    return {
        "meetings": {r["id"]: r for r in conn.execute("SELECT id, year, title, held_at FROM meetings")},
        "events": {r["id"]: r for r in conn.execute("SELECT id, kind, name, held_on FROM events")},
        "programs": {r["id"]: r for r in conn.execute("SELECT id, event_id, title FROM event_programs")},
        "accounts": {r["id"]: r for r in conn.execute("SELECT id, alias FROM accounts")},
        "cards": {r["id"]: r for r in conn.execute("SELECT id, name FROM cards")},
        "donations": {r["id"]: r for r in conn.execute("SELECT id, event_id, donor, donated_on FROM donations")},
    }


def _describe_file(f, ctx):
    """다른 탭에 첨부된 파일의 출처 정보와 자동 태그. 출처가 사라진 파일이면 None."""
    kind, tid = f["target_type"], f["target_id"]
    if kind in ("meeting_minutes", "meeting_signature"):
        m = ctx["meetings"].get(tid)
        if not m:
            return None
        auto = [("문서종류", "회의록")] + ([("문서종류", "서명지")] if kind == "meeting_signature" else []) \
            + [("연도", str(m["year"]))]
        what = "회의록" if kind == "meeting_minutes" else "참석서명지"
        return {"src": "meeting", "label": f"각종 회의실적 · {m['title']} · {what}", "auto": auto,
                "url": url_for("meetings.list_view", year=m["year"]), "locked": False}
    if kind in ("event_doc", "event_material"):
        program = ctx["programs"].get(tid) if kind == "event_material" else None
        event = ctx["events"].get(program["event_id"] if program else tid)
        if not event:
            return None
        auto = [("행사구분", event["kind"]), ("연도", (event["held_on"] or "")[:4])]
        if kind == "event_material":
            auto.insert(1, ("문서종류", "발표자료"))
        name = event["name"] or event["kind"]
        label = f"교육·학술대회·워크숍 · {name}" + (f" · {program['title']}" if program else " · 행사 관련문서")
        return {"src": "event", "label": label, "auto": [a for a in auto if a[1]],
                "url": url_for("events.detail", event_id=event["id"]), "locked": False}
    if kind == "account_copy":
        a = ctx["accounts"].get(tid)
        if not a:
            return None
        return {"src": "money", "label": f"예금통장·카드 현황 · {a['alias']} 통장 사본", "auto": [("문서종류", "통장·카드")],
                "url": url_for("finance.accounts"), "locked": True}
    if kind == "card_copy":
        c = ctx["cards"].get(tid)
        if not c:
            return None
        return {"src": "money", "label": f"예금통장·카드 현황 · {c['name']} 사본", "auto": [("문서종류", "통장·카드")],
                "url": url_for("finance.accounts"), "locked": True}
    if kind == "donation_doc":
        d = ctx["donations"].get(tid)
        if not d:
            return None
        url = (url_for("donations.event_detail", event_id=d["event_id"]) if d["event_id"]
               else url_for("donations.general_detail", year=int((d["donated_on"] or "0")[:4] or 0)))
        return {"src": "money", "label": f"찬조금 내역 · {d['donor']} 증빙", "auto": [("문서종류", "찬조금")],
                "url": url, "locked": True}
    return None


def _collect_items(conn, unlocked, tctx):
    """검색 대상 전체(직접 올린 서류 + 다른 탭 첨부파일)를 한 목록으로 만듭니다."""
    real = _real_tags(conn)
    ctx = _load_context(conn)
    items = []

    versions = {}
    for f in conn.execute("SELECT * FROM files WHERE target_type = ? ORDER BY id", (DOC_TARGET,)):
        versions.setdefault(f["target_id"], []).append(f)
    for d in conn.execute("SELECT * FROM documents WHERE is_active = 1"):
        current = versions.get(d["id"], [None])[-1]
        created = _to_local(d["created_at"])
        auto = []   # 연도 태그는 서류에 직접 붙는 태그입니다 (고치고 뺄 수 있음)
        items.append({
            "type": "document", "id": d["id"], "title": d["title"], "description": d["description"] or "",
            "src": "doc", "label": "기타서류", "date": _to_local(d["updated_at"]) or created or datetime.min,
            "file": current, "locked": False, "url": url_for("documents.document_view", doc_id=d["id"]),
            "tags": _merge_tags(real.get((DOC_TARGET, d["id"]), []), auto, tctx),
        })

    for f in conn.execute("SELECT * FROM files WHERE target_type != ? ORDER BY id", (DOC_TARGET,)):
        info = _describe_file(f, ctx)
        if not info or (info["locked"] and not unlocked):
            continue
        items.append({
            "type": "file", "id": f["id"], "title": f["original_name"], "description": "",
            "src": info["src"], "label": info["label"], "date": _to_local(f["uploaded_at"]) or datetime.min,
            "file": f, "locked": info["locked"], "source_url": info["url"],
            "url": url_for("documents.file_view", file_id=f["id"]),
            "tags": _merge_tags(real.get(("file", f["id"]), []), info["auto"], tctx),
        })
    items.sort(key=lambda it: it["date"], reverse=True)
    return items


def _haystack(item):
    parts = [item["title"], item["description"], item["label"]]
    if item["file"] is not None:
        parts.append(item["file"]["original_name"])
    parts += [t["name"] for t in item["tags"]]
    return " ".join(parts).lower()


# ---------- 목록·검색 ----------
@bp.route("/audit/documents")
def list_view():
    unlocked = auth.is_unlocked()
    q = request.args.get("q", "").strip()
    src = request.args.get("src", "all")
    mode = "any" if request.args.get("mode") == "any" else "all"
    selected = list(dict.fromkeys(t for t in request.args.getlist("tag") if t))

    with db() as conn:
        tctx = _tag_context(conn)
        items = _collect_items(conn, unlocked, tctx)
        popular = _popular_tags(conn, tctx)
        category_hints = _category_names(conn)

    # 필터 창에 보여줄 태그와 사용 횟수 (전체 자료 기준, 이름이 같으면 하나)
    counts = Counter(t["name"] for it in items for t in it["tags"])
    known = {}
    for it in items:
        for t in it["tags"]:
            known.setdefault(t["name"], (t["category"], t["color"]))
    for p in popular:                      # 아직 쓰이지 않은 태그도 선택지에 포함
        known.setdefault(p["name"], (p["category"], p["color"]))
    groups = {}
    for name, (category, color) in known.items():
        groups.setdefault(category, []).append({"key": name, "name": name, "count": counts.get(name, 0), "color": color})
    for tags in groups.values():
        tags.sort(key=lambda t: (-t["count"], t["name"]))
    tag_groups = sorted(({"name": c, "tags": tags, "total": sum(t["count"] for t in tags)}
                         for c, tags in groups.items()), key=lambda g: (-g["total"], g["name"]))
    all_tags = sorted((t for g in tag_groups for t in g["tags"]), key=lambda t: (-t["count"], t["name"]))
    by_name = {t["name"]: t for t in all_tags}

    # 걸러내기
    result = items
    if src in SRC_NAMES:
        result = [it for it in result if it["src"] == src]
    else:
        src = "all"
    if q:
        terms = q.lower().split()
        result = [it for it in result if all(term in _haystack(it) for term in terms)]
    if selected:
        pick = all if mode == "all" else any
        result = [it for it in result if pick(k in {t["name"] for t in it["tags"]} for k in selected)]

    pages = max(1, math.ceil(len(result) / PAGE_SIZE))
    raw_page = request.args.get("page", "1")
    page = min(max(1, int(raw_page) if raw_page.isdigit() else 1), pages)
    shown = result[(page - 1) * PAGE_SIZE: page * PAGE_SIZE]

    def link(**override):
        params = {"q": q, "src": src, "mode": mode, "tag": selected, "page": 1}
        params.update(override)
        if params["src"] == "all":
            params.pop("src")
        if params["mode"] == "all":
            params.pop("mode")
        params = {k: v for k, v in params.items() if v not in ("", None, [])}
        if params.get("page") == 1:
            params.pop("page")
        return url_for("documents.list_view", **params)

    def toggle(key):
        return link(tag=[k for k in selected if k != key] if key in selected else selected + [key])

    year_tags = sorted((t for t in all_tags if _is_year(t["name"])), key=lambda t: t["name"], reverse=True)
    selected_chips = [{"key": k, "color": by_name[k]["color"] if k in by_name else 9}
                      for k in selected if not _is_year(k)]
    src_counts = Counter(it["src"] for it in items)

    return render_template(
        "documents.html", page=get_menu("documents"), items=shown, total=len(result), q=q, src=src, mode=mode,
        selected=selected, selected_chips=selected_chips, tag_groups=tag_groups, all_tags=all_tags,
        year_tags=year_tags, link=link, toggle=toggle, page_no=page, pages=pages, src_names=SRC_NAMES,
        src_counts=src_counts, popular=popular, category_hints=category_hints, cat_colors=tctx["cat"],
        accept=storage.ACCEPT_ATTR, unlocked=unlocked, default_year=datetime.now().year,
    )


# ---------- 서류 추가 / 수정 / 삭제 ----------
@bp.post("/audit/documents/add")
def document_add():
    upload = request.files.get("file")
    if not upload or not upload.filename:
        flash("올릴 파일을 선택해 주세요.", "error")
        return redirect(url_for("documents.list_view"))
    with db() as conn:
        saved = storage.save_upload(upload, "documents")
        if saved is None:
            flash("올릴 수 없는 형식입니다. (PDF, JPG, PNG, DOC, DOCX, HWP만 가능)", "error")
            return redirect(url_for("documents.list_view"))
        name, rel, kind = saved
        title = request.form.get("title", "").strip() or name.rsplit(".", 1)[0]
        now = _now()
        doc_id = conn.execute(
            "INSERT INTO documents(title, description, created_at, updated_at) VALUES (?, ?, ?, ?)",
            (title, request.form.get("description", "").strip(), now, now)).lastrowid
        conn.execute(
            "INSERT INTO files(original_name, stored_path, file_type, target_type, target_id, uploaded_at, note) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)", (name, rel, kind, DOC_TARGET, doc_id, now, "최초 등록"))
        _set_tags(conn, DOC_TARGET, doc_id, request.form.getlist("tags"))
        found, _ = pdfdate.drafted_date(storage._safe_path(rel))      # 못 읽으면 비워 두고, 공문 화면에서 입력
        if found:
            conn.execute("UPDATE documents SET drafted_on = ? WHERE id = ?", (found, doc_id))
    flash(f"'{title}' 서류를 올렸습니다.")
    return redirect(url_for("documents.document_view", doc_id=doc_id))


def _get_document(conn, doc_id):
    d = conn.execute("SELECT * FROM documents WHERE id = ? AND is_active = 1", (doc_id,)).fetchone()
    if not d:
        abort(404)
    return d


@bp.post("/audit/documents/<int:doc_id>/edit")
def document_edit(doc_id):
    title = request.form.get("title", "").strip()
    with db() as conn:
        _get_document(conn, doc_id)
        if not title:
            flash("제목을 입력해 주세요.", "error")
        else:
            conn.execute("UPDATE documents SET title = ?, description = ?, updated_at = ? WHERE id = ?",
                         (title, request.form.get("description", "").strip(), _now(), doc_id))
            flash("제목과 설명을 저장했습니다.")
    return redirect(url_for("documents.document_view", doc_id=doc_id))


@bp.post("/audit/documents/<int:doc_id>/delete")
def document_delete(doc_id):
    with db() as conn:
        d = _get_document(conn, doc_id)
        storage.delete_files_for(conn, (DOC_TARGET,), doc_id)
        conn.execute("DELETE FROM tag_links WHERE target_type = ? AND target_id = ?", (DOC_TARGET, doc_id))
        conn.execute("DELETE FROM reviews WHERE target_type = ? AND target_id = ?", (DOC_TARGET, doc_id))
        conn.execute("DELETE FROM documents WHERE id = ?", (doc_id,))
    flash(f"'{d['title']}' 서류를 삭제했습니다. (이전 버전 파일도 함께 삭제됨)")
    return redirect(url_for("documents.list_view"))


@bp.post("/audit/documents/<int:doc_id>/version")
def document_version(doc_id):
    upload = request.files.get("file")
    with db() as conn:
        _get_document(conn, doc_id)
        saved = storage.save_upload(upload, "documents") if upload and upload.filename else None
        if saved is None:
            flash("새 버전 파일을 선택해 주세요. (PDF, JPG, PNG, DOC, DOCX, HWP)", "error")
        else:
            name, rel, kind = saved
            now = _now()
            conn.execute(
                "INSERT INTO files(original_name, stored_path, file_type, target_type, target_id, uploaded_at, note) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (name, rel, kind, DOC_TARGET, doc_id, now, request.form.get("note", "").strip() or "새 버전"))
            conn.execute("UPDATE documents SET updated_at = ? WHERE id = ?", (now, doc_id))
            flash("새 버전을 올렸습니다. 이전 버전은 [수정 이력]에서 볼 수 있습니다.")
    return redirect(url_for("documents.document_view", doc_id=doc_id))


# ---------- 태그 편집 ----------
@bp.post("/audit/documents/<int:doc_id>/tags")
def document_tags(doc_id):
    with db() as conn:
        _get_document(conn, doc_id)
        _set_tags(conn, DOC_TARGET, doc_id, request.form.getlist("tags"))
    flash("태그를 저장했습니다.")
    return redirect(url_for("documents.document_view", doc_id=doc_id))


@bp.post("/audit/documents/file/<int:file_id>/tags")
def file_tags(file_id):
    with db() as conn:
        row = conn.execute("SELECT target_type FROM files WHERE id = ?", (file_id,)).fetchone()
        if not row or row["target_type"] == DOC_TARGET:
            abort(404)
        auth.require_unlocked_for_file(row["target_type"])
        _set_tags(conn, "file", file_id, request.form.getlist("tags"))
    flash("태그를 저장했습니다.")
    return redirect(url_for("documents.file_view", file_id=file_id))


# ---------- 검토 기록 ----------
@bp.post("/audit/documents/<int:doc_id>/reviews/add")
def review_add(doc_id):
    reviewed_at = request.form.get("reviewed_at", "").strip()
    try:
        datetime.strptime(reviewed_at, "%Y-%m-%d")
    except ValueError:
        flash("검토일을 확인해 주세요.", "error")
        return redirect(url_for("documents.document_view", doc_id=doc_id))
    with db() as conn:
        _get_document(conn, doc_id)
        conn.execute("INSERT INTO reviews(target_type, target_id, reviewed_at, reviewer, comment) VALUES (?, ?, ?, ?, ?)",
                     (DOC_TARGET, doc_id, reviewed_at, request.form.get("reviewer", "").strip(),
                      request.form.get("comment", "").strip()))
    flash("검토 기록을 남겼습니다.")
    return redirect(url_for("documents.document_view", doc_id=doc_id))


@bp.post("/audit/documents/reviews/<int:review_id>/delete")
def review_delete(review_id):
    with db() as conn:
        row = conn.execute("SELECT target_id FROM reviews WHERE id = ? AND target_type = ?",
                           (review_id, DOC_TARGET)).fetchone()
        if not row:
            abort(404)
        conn.execute("DELETE FROM reviews WHERE id = ?", (review_id,))
    flash("검토 기록을 삭제했습니다.")
    return redirect(url_for("documents.document_view", doc_id=row["target_id"]))


# ---------- 열기 화면 ----------
def _tag_payload(tags):
    return [{"category": t["category"], "name": t["name"]} for t in tags if not t["auto"]]


@bp.route("/audit/documents/<int:doc_id>")
def document_view(doc_id):
    with db() as conn:
        d = _get_document(conn, doc_id)
        versions = conn.execute("SELECT * FROM files WHERE target_type = ? AND target_id = ? ORDER BY id",
                                (DOC_TARGET, doc_id)).fetchall()
        reviews = conn.execute(
            "SELECT * FROM reviews WHERE target_type = ? AND target_id = ? ORDER BY reviewed_at DESC, id DESC",
            (DOC_TARGET, doc_id)).fetchall()
        created = _to_local(d["created_at"])
        tctx = _tag_context(conn)
        tags = _merge_tags(_real_tags(conn).get((DOC_TARGET, doc_id), []), [], tctx)
        popular, categories = _popular_tags(conn, tctx), _category_names(conn)
    return render_template(
        "document_view.html", page=get_menu("documents"), is_document=True, doc=d, title=d["title"],
        description=d["description"] or "", versions=versions, current=versions[-1] if versions else None,
        reviews=reviews, tags=tags, tag_payload=_tag_payload(tags), updated=_to_local(d["updated_at"]),
        last_review=reviews[0]["reviewed_at"] if reviews else None, source_label=None, source_url=None,
        popular=popular, category_hints=categories, cat_colors=tctx["cat"], accept=storage.ACCEPT_ATTR,
        today=datetime.now().strftime("%Y-%m-%d"),
    )


@bp.route("/audit/documents/file/<int:file_id>")
def file_view(file_id):
    with db() as conn:
        f = conn.execute("SELECT * FROM files WHERE id = ? AND target_type != ?", (file_id, DOC_TARGET)).fetchone()
        if not f:
            abort(404)
        auth.require_unlocked_for_file(f["target_type"])
        info = _describe_file(f, _load_context(conn))
        if not info:
            abort(404)
        tctx = _tag_context(conn)
        tags = _merge_tags(_real_tags(conn).get(("file", file_id), []), info["auto"], tctx)
        popular, categories = _popular_tags(conn, tctx), _category_names(conn)
    return render_template(
        "document_view.html", page=get_menu("documents"), is_document=False, doc=None, title=f["original_name"],
        description="", versions=[], current=f, reviews=[], tags=tags, tag_payload=_tag_payload(tags),
        updated=_to_local(f["uploaded_at"]), last_review=None, source_label=info["label"], source_url=info["url"],
        popular=popular, category_hints=categories, cat_colors=tctx["cat"], accept=storage.ACCEPT_ATTR,
        today="", file_id=file_id,
    )


# ---------- 태그 관리 ----------
@bp.route("/audit/documents/tag-manage")
def tag_manage():
    with db() as conn:
        tctx = _tag_context(conn)
        rows = [dict(r) for r in conn.execute(
            "SELECT t.id, t.category, t.name, t.color, COUNT(tl.tag_id) AS n FROM tags t "
            "LEFT JOIN tag_links tl ON tl.tag_id = t.id GROUP BY t.id ORDER BY t.category, n DESC, t.name")]
        categories = _category_names(conn)
    grouped = {}
    for r in rows:
        r["effective"] = r["color"] if r["color"] is not None else tctx["cat"].get(r["category"], 9)
        grouped.setdefault(r["category"], []).append(r)
    auto_only = [c for c in VIRTUAL_CATEGORIES if c not in grouped]
    return render_template(
        "tag_manage.html", page=get_menu("documents"), grouped=grouped, category_hints=categories,
        cat_colors=tctx["cat"], palette=PALETTE_NAMES, auto_categories=auto_only,
    )


def _color_value(raw):
    raw = (raw or "").strip()
    return int(raw) if raw.isdigit() and int(raw) < len(PALETTE_NAMES) else None


@bp.post("/audit/documents/tag-manage/<int:tag_id>/edit")
def tag_edit(tag_id):
    name = request.form.get("name", "").strip()[:30]
    category = request.form.get("category", "").strip()[:20]
    color = _color_value(request.form.get("color"))
    if not name or not category:
        flash("카테고리와 태그 이름을 입력해 주세요.", "error")
        return redirect(url_for("documents.tag_manage"))
    with db() as conn:
        if not conn.execute("SELECT 1 FROM tags WHERE id = ?", (tag_id,)).fetchone():
            abort(404)
        other = conn.execute("SELECT id FROM tags WHERE name = ? AND id != ?", (name, tag_id)).fetchone()
        if other:   # 같은 이름의 태그가 이미 있으면 하나로 합칩니다
            conn.execute("INSERT OR IGNORE INTO tag_links(tag_id, target_type, target_id) "
                         "SELECT ?, target_type, target_id FROM tag_links WHERE tag_id = ?", (other["id"], tag_id))
            conn.execute("DELETE FROM tags WHERE id = ?", (tag_id,))
            flash(f"이미 있는 '{name}' 태그와 합쳤습니다.")
        else:
            conn.execute("UPDATE tags SET name = ?, category = ?, color = ? WHERE id = ?",
                         (name, category, color, tag_id))
            flash("태그를 저장했습니다.")
    return redirect(url_for("documents.tag_manage"))


@bp.post("/audit/documents/tag-manage/category-color")
def category_color():
    category = request.form.get("category", "").strip()
    color = _color_value(request.form.get("color"))
    if category and color is not None:
        with db() as conn:
            conn.execute("INSERT INTO tag_categories(name, color) VALUES (?, ?) "
                         "ON CONFLICT(name) DO UPDATE SET color = excluded.color", (category, color))
        flash(f"'{category}' 카테고리의 기본 색을 바꿨습니다. (태그별로 따로 정한 색은 그대로)")
    return redirect(url_for("documents.tag_manage"))


@bp.post("/audit/documents/tag-manage/<int:tag_id>/delete")
def tag_delete(tag_id):
    with db() as conn:
        row = conn.execute("SELECT name FROM tags WHERE id = ?", (tag_id,)).fetchone()
        if row:
            conn.execute("DELETE FROM tags WHERE id = ?", (tag_id,))   # 붙어 있던 연결도 함께 삭제
            flash(f"'{row['name']}' 태그를 삭제했습니다.")
    return redirect(url_for("documents.tag_manage"))
