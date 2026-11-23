"""지출결의 (예산·결산 현황 2단계, 잠금 대상): 거래 여러 건을 묶어 결의서 한 장으로 만듭니다.

- 금액·일시·내용은 은행 거래에서 자동으로 가져오므로 따로 입력하지 않습니다. (총지출금액 = 묶인 거래의 출금 합계)
- 지출일·적요·영수자·지출방법·예산과목은 결의서에서 한 번만 지정하고, 예산과목은 묶인 모든 거래에 함께 적용됩니다.
- 결의서 이미지와 영수증은 파일을 고르거나 Ctrl+V 로 붙여넣어 증빙으로 첨부합니다. (잠금 대상 파일)
- 이 파일의 화면은 모두 /audit/budget/vouchers 로 시작하므로 비밀번호 잠금이 적용됩니다.
"""
from datetime import datetime

from flask import Blueprint, abort, flash, redirect, render_template, request, url_for

import storage
from menu import get_menu
from models import db
from .budget import _category_list, _now, _safe_next

bp = Blueprint("vouchers", __name__)

FORM_FILE = "voucher_form"        # 결의서 이미지 (잠금 대상: 'voucher' 로 시작)
RECEIPT_FILE = "voucher_receipt"  # 영수증
SLOTS = {"form": FORM_FILE, "receipt": RECEIPT_FILE}
METHODS = ["이체", "카드", "현금"]
UNBUNDLED = ("t.withdrawal > 0 AND t.is_transfer = 0 "
             "AND NOT EXISTS (SELECT 1 FROM voucher_transactions vt WHERE vt.transaction_id = t.id)")


def _date_or_none(value):
    try:
        return datetime.strptime((value or "").strip(), "%Y-%m-%d").strftime("%Y-%m-%d")
    except ValueError:
        return None


def _get(conn, voucher_id):
    v = conn.execute("SELECT * FROM vouchers WHERE id = ?", (voucher_id,)).fetchone()
    if not v:
        abort(404)
    return v


def _apply_category(conn, voucher_id, category_id):
    """결의서의 예산과목을 묶인 모든 거래에 적용합니다."""
    if category_id is None:
        return
    conn.execute(
        "UPDATE bank_transactions SET category_id = ?, category_source = 'manual' "
        "WHERE id IN (SELECT transaction_id FROM voucher_transactions WHERE voucher_id = ?)",
        (category_id, voucher_id))


def _next_no(conn, year):
    last = 0
    for r in conn.execute("SELECT voucher_no FROM vouchers WHERE voucher_no LIKE ?", (f"{year}-%",)):
        tail = (r["voucher_no"] or "").split("-")[-1]
        last = max(last, int(tail) if tail.isdigit() else 0)
    return f"{year}-{last + 1:03d}"


def _chain(categories, category_id):
    """예산과목 id → {1: 관 이름, 2: 항 이름, 3: 목 이름} (선택한 단계까지만)"""
    by_id = {c["id"]: c for c in categories}
    out, cur = {}, by_id.get(category_id)
    while cur:
        out[cur["level"]] = cur["name"]
        cur = by_id.get(cur["parent_id"])
    return out


# ---------- 목록 ----------
@bp.route("/audit/budget/vouchers")
def list_view():
    with db() as conn:
        years = [r[0] for r in conn.execute(
            "SELECT DISTINCT substr(paid_on, 1, 4) FROM vouchers WHERE paid_on IS NOT NULL ORDER BY 1 DESC")]
        year = request.args.get("year") or (years[0] if years else str(datetime.now().year))
        show_all = year == "all"
        where, args = ("1 = 1", []) if show_all else ("substr(v.paid_on, 1, 4) = ?", [year])
        rows = conn.execute(
            f"SELECT v.*, COALESCE(SUM(t.withdrawal), 0) AS total, COUNT(t.id) AS n FROM vouchers v "
            f"LEFT JOIN voucher_transactions vt ON vt.voucher_id = v.id "
            f"LEFT JOIN bank_transactions t ON t.id = vt.transaction_id WHERE {where} "
            f"GROUP BY v.id ORDER BY v.paid_on DESC, v.id DESC", args).fetchall()
        files = storage.files_for(conn, tuple(SLOTS.values()), [r["id"] for r in rows])
        paths = {c["id"]: c["path"] for c in _category_list(conn)}
        un_where, un_args = (UNBUNDLED, []) if show_all else (UNBUNDLED + " AND substr(t.occurred_at, 1, 4) = ?", [year])
        unbundled = conn.execute(
            f"SELECT COUNT(*) AS n, COALESCE(SUM(t.withdrawal), 0) AS s FROM bank_transactions t WHERE {un_where}",
            un_args).fetchone()
        if not show_all and year not in years:
            years = sorted(set(years) | {year}, reverse=True)
    return render_template(
        "vouchers.html", page=get_menu("budget"), years=years, year=year, show_all=show_all, rows=rows,
        paths=paths, files=files, unbundled=unbundled, form_type=FORM_FILE, receipt_type=RECEIPT_FILE)


# ---------- 새 결의서: 아직 안 묶인 출금 거래 고르기 ----------
@bp.route("/audit/budget/vouchers/new")
def new():
    year = request.args.get("year", str(datetime.now().year))
    q = request.args.get("q", "").strip()
    where, args = [UNBUNDLED], []
    if year != "all":
        where.append("substr(t.occurred_at, 1, 4) = ?")
        args.append(year)
    if q:
        where.append("(t.memo_own LIKE ? OR t.counterparty LIKE ? OR t.summary LIKE ?)")
        args += [f"%{q}%"] * 3
    with db() as conn:
        years = [r[0] for r in conn.execute("SELECT DISTINCT substr(occurred_at, 1, 4) FROM bank_transactions ORDER BY 1 DESC")]
        rows = conn.execute(
            f"SELECT t.*, COALESCE(f.alias, a.alias) AS fund_alias FROM bank_transactions t "
            f"JOIN accounts a ON a.id = t.account_id LEFT JOIN accounts f ON f.id = COALESCE(t.fund_account_id, t.account_id) "
            f"WHERE {' AND '.join(where)} ORDER BY t.occurred_at DESC, t.id DESC LIMIT 300", args).fetchall()
        paths = {c["id"]: c["path"] for c in _category_list(conn)}
    return render_template("voucher_new.html", page=get_menu("budget"), rows=rows, paths=paths,
                           years=years, year=year, q=q)


# ---------- 만들기 ----------
@bp.post("/audit/budget/vouchers/create")
def create():
    ids = [int(i) for i in request.form.getlist("ids") if i.isdigit()]
    back = _safe_next(request.form.get("next"))
    if not ids:
        flash("묶을 거래를 먼저 선택해 주세요.", "error")
        return redirect(back)
    marks = ",".join("?" * len(ids))
    with db() as conn:
        rows = conn.execute(
            f"SELECT t.* FROM bank_transactions t WHERE t.id IN ({marks}) AND {UNBUNDLED} "
            f"ORDER BY t.occurred_at, t.id", ids).fetchall()
        if not rows:
            flash("선택한 거래 중 결의서로 묶을 수 있는 출금 거래가 없습니다. (입금·통장 간 이체·이미 묶인 거래는 제외)", "error")
            return redirect(back)
        skipped = len(ids) - len(rows)
        first = rows[0]
        label = first["memo_own"] or first["summary"] or first["counterparty"] or "지출"
        title = label if len(rows) == 1 else f"{label} 외 {len(rows) - 1}건"
        paid_on = rows[-1]["occurred_at"][:10]
        categories = {r["category_id"] for r in rows}
        category_id = categories.pop() if len(categories) == 1 else None   # 모두 같은 과목이면 그대로 이어받음
        prev = conn.execute("SELECT receiver FROM vouchers WHERE receiver != '' ORDER BY id DESC LIMIT 1").fetchone()
        voucher_id = conn.execute(
            "INSERT INTO vouchers(voucher_no, title, issued_on, paid_on, receiver, method, category_id, created_at) "
            "VALUES (?, ?, ?, ?, ?, '이체', ?, ?)",
            (_next_no(conn, paid_on[:4]), title[:80], datetime.now().strftime("%Y-%m-%d"), paid_on,
             prev["receiver"] if prev else "", category_id, _now())).lastrowid
        conn.executemany("INSERT INTO voucher_transactions(voucher_id, transaction_id) VALUES (?, ?)",
                         [(voucher_id, r["id"]) for r in rows])
    flash(f"거래 {len(rows)}건으로 결의서를 만들었습니다." + (f" ({skipped}건은 묶을 수 없어 제외)" if skipped else "")
          + " 영수자·지출방법 등을 확인하고 저장하세요.")
    return redirect(url_for("vouchers.detail", voucher_id=voucher_id))


# ---------- 결의서 화면 ----------
@bp.route("/audit/budget/vouchers/<int:voucher_id>")
def detail(voucher_id):
    with db() as conn:
        v = _get(conn, voucher_id)
        txs = conn.execute(
            "SELECT t.*, COALESCE(f.alias, a.alias) AS fund_alias FROM voucher_transactions vt "
            "JOIN bank_transactions t ON t.id = vt.transaction_id JOIN accounts a ON a.id = t.account_id "
            "LEFT JOIN accounts f ON f.id = COALESCE(t.fund_account_id, t.account_id) "
            "WHERE vt.voucher_id = ? ORDER BY t.occurred_at, t.id", (voucher_id,)).fetchall()
        categories = _category_list(conn)
        candidates = conn.execute(
            f"SELECT t.* FROM bank_transactions t WHERE {UNBUNDLED} ORDER BY t.occurred_at DESC, t.id DESC LIMIT 80").fetchall()
        files = storage.files_for(conn, tuple(SLOTS.values()), [voucher_id])
        officers = [r["name"] for r in conn.execute("SELECT DISTINCT name FROM officers WHERE kind = '임원' ORDER BY sort_order, id")]
        mixed = len({t["category_id"] for t in txs} - {v["category_id"]}) > 0 and v["category_id"] is not None
    return render_template(
        "voucher_detail.html", page=get_menu("budget"), v=v, txs=txs, total=sum(t["withdrawal"] for t in txs),
        categories=categories, chain=_chain(categories, v["category_id"]), paths={c["id"]: c["path"] for c in categories},
        candidates=candidates, officers=officers, methods=METHODS, mixed=mixed,
        form_files=files.get((FORM_FILE, voucher_id), []), receipt_files=files.get((RECEIPT_FILE, voucher_id), []),
        accept=storage.ACCEPT_ATTR)


@bp.post("/audit/budget/vouchers/<int:voucher_id>/save")
def save(voucher_id):
    f = request.form
    title = f.get("title", "").strip()[:80]
    paid_on, issued_on = _date_or_none(f.get("paid_on")), _date_or_none(f.get("issued_on"))
    method = f.get("method") if f.get("method") in METHODS else "이체"
    raw = f.get("category_id", "")
    if not title or not paid_on:
        flash("적요와 지출일을 입력해 주세요.", "error")
        return redirect(url_for("vouchers.detail", voucher_id=voucher_id))
    with db() as conn:
        _get(conn, voucher_id)
        category_id = int(raw) if raw.isdigit() and conn.execute(
            "SELECT 1 FROM budget_categories WHERE id = ?", (int(raw),)).fetchone() else None
        conn.execute(
            "UPDATE vouchers SET title = ?, issued_on = ?, paid_on = ?, receiver = ?, method = ?, category_id = ?, note = ? WHERE id = ?",
            (title, issued_on, paid_on, f.get("receiver", "").strip()[:40], method, category_id,
             f.get("note", "").strip()[:500], voucher_id))
        _apply_category(conn, voucher_id, category_id)
    flash("결의서를 저장했습니다." + (" 묶인 거래에도 예산과목을 적용했습니다." if category_id else ""))
    return redirect(url_for("vouchers.detail", voucher_id=voucher_id))


@bp.post("/audit/budget/vouchers/<int:voucher_id>/transactions/add")
def tx_add(voucher_id):
    ids = [int(i) for i in request.form.getlist("ids") if i.isdigit()]
    with db() as conn:
        v = _get(conn, voucher_id)
        marks = ",".join("?" * len(ids)) or "NULL"
        rows = conn.execute(f"SELECT t.id FROM bank_transactions t WHERE t.id IN ({marks}) AND {UNBUNDLED}", ids).fetchall()
        conn.executemany("INSERT INTO voucher_transactions(voucher_id, transaction_id) VALUES (?, ?)",
                         [(voucher_id, r["id"]) for r in rows])
        _apply_category(conn, voucher_id, v["category_id"])
    flash(f"거래 {len(rows)}건을 결의서에 추가했습니다." if rows else "추가할 거래를 선택해 주세요.", "message" if rows else "error")
    return redirect(url_for("vouchers.detail", voucher_id=voucher_id))


@bp.post("/audit/budget/vouchers/<int:voucher_id>/transactions/<int:tx_id>/remove")
def tx_remove(voucher_id, tx_id):
    with db() as conn:
        _get(conn, voucher_id)
        conn.execute("DELETE FROM voucher_transactions WHERE voucher_id = ? AND transaction_id = ?", (voucher_id, tx_id))
    flash("거래를 결의서에서 뺐습니다. (거래 자체는 그대로 남아 있습니다)")
    return redirect(url_for("vouchers.detail", voucher_id=voucher_id))


@bp.post("/audit/budget/vouchers/<int:voucher_id>/upload")
def upload(voucher_id):
    slot = SLOTS.get(request.form.get("slot", "receipt"), RECEIPT_FILE)
    with db() as conn:
        _get(conn, voucher_id)
        storage.save_request_files(conn, slot, voucher_id, "vouchers")
    return redirect(url_for("vouchers.detail", voucher_id=voucher_id))


@bp.post("/audit/budget/vouchers/<int:voucher_id>/delete")
def delete(voucher_id):
    with db() as conn:
        v = _get(conn, voucher_id)
        storage.delete_files_for(conn, tuple(SLOTS.values()), voucher_id)
        conn.execute("DELETE FROM vouchers WHERE id = ?", (voucher_id,))   # 묶음 연결은 함께 삭제, 거래는 그대로
    flash(f"결의서 {v['voucher_no']}을(를) 삭제했습니다. 거래내역은 그대로 남아 있습니다.")
    return redirect(url_for("vouchers.list_view"))
