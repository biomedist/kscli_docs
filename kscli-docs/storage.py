"""첨부파일 저장·삭제·열기 공통 기능. 다른 메뉴(예결산, 행사 등)에서도 그대로 재사용합니다."""
import os
import uuid

from flask import Blueprint, abort, flash, redirect, request, send_file

from models import BASE_DIR, db

UPLOAD_ROOT = os.path.join(BASE_DIR, "uploads")

# 확장자 → 종류
ALLOWED = {
    "pdf": "pdf",
    "jpg": "image", "jpeg": "image", "png": "image",
    "docx": "docx", "doc": "doc",
    "hwp": "hwp", "hwpx": "hwp",
}
MIME = {
    "pdf": "application/pdf",
    "jpg": "image/jpeg", "jpeg": "image/jpeg", "png": "image/png",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
}
INLINE_KINDS = {"pdf", "image", "docx"}   # 브라우저 화면에서 바로 열 수 있는 종류
ACCEPT_ATTR = ",".join("." + e for e in ALLOWED)

bp = Blueprint("files", __name__)


def _safe_path(rel):
    full = os.path.normpath(os.path.join(UPLOAD_ROOT, rel))
    return full if full.startswith(UPLOAD_ROOT + os.sep) else None


def save_upload(file_storage, subdir):
    """허용된 형식이면 저장하고 (원본이름, 상대경로, 종류)를 돌려줍니다. 아니면 None."""
    name = os.path.basename(file_storage.filename.replace("\\", "/"))
    name = "".join(ch for ch in name if ch.isprintable()).strip()
    ext = name.rsplit(".", 1)[-1].lower() if "." in name else ""
    if not name or ext not in ALLOWED:
        return None
    folder = os.path.join(UPLOAD_ROOT, subdir)
    os.makedirs(folder, exist_ok=True)
    stored = f"{uuid.uuid4().hex}.{ext}"
    file_storage.save(os.path.join(folder, stored))
    return name, f"{subdir}/{stored}", ALLOWED[ext]


def files_for(conn, target_types, target_ids):
    """{(target_type, target_id): [파일 행, ...]} 형태로 돌려줍니다."""
    out = {}
    if not target_ids:
        return out
    t_marks = ",".join("?" * len(target_types))
    i_marks = ",".join("?" * len(target_ids))
    rows = conn.execute(
        f"SELECT * FROM files WHERE target_type IN ({t_marks}) AND target_id IN ({i_marks}) ORDER BY id",
        (*target_types, *target_ids))
    for r in rows:
        out.setdefault((r["target_type"], r["target_id"]), []).append(r)
    return out


def _remove_from_disk(rel):
    path = _safe_path(rel)
    if path and os.path.isfile(path):
        os.remove(path)


def delete_files_for(conn, target_types, target_id):
    """대상(예: 회의)에 붙은 파일을 디스크와 DB에서 모두 지웁니다."""
    marks = ",".join("?" * len(target_types))
    for r in conn.execute(
            f"SELECT id, stored_path FROM files WHERE target_type IN ({marks}) AND target_id = ?",
            (*target_types, target_id)).fetchall():
        _remove_from_disk(r["stored_path"])
        conn.execute("DELETE FROM files WHERE id = ?", (r["id"],))


def _send(file_id, inline):
    with db() as conn:
        row = conn.execute("SELECT * FROM files WHERE id = ?", (file_id,)).fetchone()
    if not row:
        abort(404)
    path = _safe_path(row["stored_path"])
    if not path or not os.path.isfile(path):
        abort(404)
    ext = row["stored_path"].rsplit(".", 1)[-1].lower()
    inline = inline and row["file_type"] in INLINE_KINDS
    resp = send_file(path, mimetype=MIME.get(ext, "application/octet-stream"),
                     as_attachment=not inline, download_name=row["original_name"])
    resp.headers["X-Content-Type-Options"] = "nosniff"
    return resp


@bp.get("/files/<int:file_id>")
def view(file_id):
    return _send(file_id, inline=True)


@bp.get("/files/<int:file_id>/download")
def download(file_id):
    return _send(file_id, inline=False)


@bp.post("/files/<int:file_id>/delete")
def delete(file_id):
    nxt = request.form.get("next", "/")
    if not nxt.startswith("/") or nxt.startswith("//"):
        nxt = "/"
    with db() as conn:
        row = conn.execute("SELECT original_name, stored_path FROM files WHERE id = ?", (file_id,)).fetchone()
        if row:
            _remove_from_disk(row["stored_path"])
            conn.execute("DELETE FROM files WHERE id = ?", (file_id,))
            flash(f"'{row['original_name']}' 파일을 삭제했습니다.")
    return redirect(nxt)
