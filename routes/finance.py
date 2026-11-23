"""금액 자료: 예금통장·카드 현황 (예산·결산, 찬조금은 다음 단계에서 구현).
이 파일의 화면은 모두 /audit/budget, /audit/accounts, /audit/donations 로 시작하는 주소라서 잠금이 적용됩니다."""
import re

from flask import Blueprint, flash, redirect, render_template, request, url_for

import storage
from menu import get_menu
from models import db

bp = Blueprint("finance", __name__)

ACCOUNT_FILE = "account_copy"   # 통장 사본 (잠금 대상: 'account' 로 시작)
CARD_FILE = "card_copy"         # 카드 사본 (잠금 대상: 'card' 로 시작)
ALIAS_HINTS = ["경상비", "보수교육비"]


@bp.app_template_filter("won")
def won(value):
    return "" if value is None else f"{int(value):,}원"


# ---------- 입력 검사 ----------
def _check_masked(value, label):
    """번호 전체를 입력하지 않도록 막습니다. (연속된 숫자가 9자리 이상이면 거절)"""
    if re.search(r"\d{9,}", re.sub(r"[\s-]", "", value or "")):
        return f"{label} 전체를 입력하지 마세요. 가려서 입력해 주세요. (예: 0484XX-XX-XX6718)"
    return None


def _last4(number):
    """마지막 숫자 덩어리의 끝 4자리. 예: '0484XX-XX-XX6718' → '6718'"""
    runs = re.findall(r"\d+", number or "")
    return runs[-1][-4:] if runs else ""


def _back():
    return redirect(url_for("finance.accounts"))


# ---------- 예금통장·카드 현황 ----------
@bp.route("/audit/accounts")
def accounts():
    with db() as conn:
        account_rows = conn.execute("SELECT * FROM accounts ORDER BY id").fetchall()
        cards = conn.execute("SELECT * FROM cards ORDER BY id").fetchall()
        openings = conn.execute("SELECT * FROM account_openings ORDER BY year DESC").fetchall()
        ids = [a["id"] for a in account_rows] + [c["id"] for c in cards]
        files = storage.files_for(conn, (ACCOUNT_FILE, CARD_FILE), ids)

    cards_by_account, unlinked = {}, []
    for c in cards:
        if c["account_id"] is None:
            unlinked.append(c)
        else:
            cards_by_account.setdefault(c["account_id"], []).append(c)
    openings_by_account = {}
    for o in openings:
        openings_by_account.setdefault(o["account_id"], []).append(o)

    return render_template(
        "accounts.html", page=get_menu("accounts"), accounts=account_rows,
        cards_by_account=cards_by_account, unlinked_cards=unlinked, openings=openings_by_account,
        files=files, accept=storage.ACCEPT_ATTR, alias_hints=ALIAS_HINTS,
    )


# --- 통장 ---
def _account_fields():
    f = request.form
    alias = f.get("alias", "").strip()
    number = f.get("number", "").strip()
    if not alias:
        return None, "별칭(예: 경상비, 보수교육비)을 입력해 주세요."
    error = _check_masked(number, "계좌번호")
    if error:
        return None, error
    return {
        "alias": alias, "bank": f.get("bank", "").strip(), "number": number, "last4": _last4(number),
        "product_name": f.get("product_name", "").strip(), "purpose": f.get("purpose", "").strip(),
        "memo": f.get("memo", "").strip(),
    }, None


@bp.post("/audit/accounts/add")
def account_add():
    fields, error = _account_fields()
    if error:
        flash(error, "error")
        return _back()
    with db() as conn:
        conn.execute(
            "INSERT INTO accounts(alias, bank, number, last4, product_name, purpose, memo) "
            "VALUES (:alias, :bank, :number, :last4, :product_name, :purpose, :memo)", fields)
    flash(f"'{fields['alias']}' 통장을 추가했습니다.")
    return _back()


@bp.post("/audit/accounts/<int:account_id>/edit")
def account_edit(account_id):
    fields, error = _account_fields()
    if error:
        flash(error, "error")
        return _back()
    with db() as conn:
        conn.execute(
            "UPDATE accounts SET alias=:alias, bank=:bank, number=:number, last4=:last4, "
            "product_name=:product_name, purpose=:purpose, memo=:memo WHERE id=:id", {**fields, "id": account_id})
    flash(f"'{fields['alias']}' 통장을 저장했습니다.")
    return _back()


@bp.post("/audit/accounts/<int:account_id>/delete")
def account_delete(account_id):
    with db() as conn:
        row = conn.execute("SELECT alias FROM accounts WHERE id = ?", (account_id,)).fetchone()
        if row and conn.execute("SELECT 1 FROM bank_transactions WHERE account_id = ? LIMIT 1", (account_id,)).fetchone():
            flash(f"'{row['alias']}' 통장에는 가져온 거래내역이 있어 삭제할 수 없습니다.", "error")
            return _back()
        if row:
            storage.delete_files_for(conn, (ACCOUNT_FILE,), account_id)
            conn.execute("DELETE FROM accounts WHERE id = ?", (account_id,))   # 이월금은 함께 삭제, 카드는 '미연결'로
            flash(f"'{row['alias']}' 통장을 삭제했습니다. 연결되어 있던 카드는 '통장 미연결'로 옮겨졌습니다.")
    return _back()


@bp.post("/audit/accounts/<int:account_id>/upload")
def account_upload(account_id):
    with db() as conn:
        if conn.execute("SELECT 1 FROM accounts WHERE id = ?", (account_id,)).fetchone():
            storage.save_request_files(conn, ACCOUNT_FILE, account_id, "accounts")
    return _back()


# --- 전기 이월금 ---
def _opening_fields():
    f = request.form
    year, amount = f.get("year", "").strip(), re.sub(r"[,\s원₩]", "", f.get("amount", ""))
    if not (year.isdigit() and 2000 <= int(year) <= 2100) or not amount.isdigit():
        return None
    return int(year), int(amount), f.get("note", "").strip()


@bp.post("/audit/accounts/<int:account_id>/openings/add")
def opening_add(account_id):
    fields = _opening_fields()
    if not fields:
        flash("연도(예: 2026)와 금액(숫자)을 확인해 주세요.", "error")
        return _back()
    with db() as conn:
        if conn.execute("SELECT 1 FROM account_openings WHERE account_id = ? AND year = ?",
                        (account_id, fields[0])).fetchone():
            flash(f"{fields[0]}년 이월금은 이미 입력되어 있습니다. [수정]으로 고쳐 주세요.", "error")
            return _back()
        conn.execute("INSERT INTO account_openings(account_id, year, amount, note) VALUES (?, ?, ?, ?)",
                     (account_id, *fields))
    flash(f"{fields[0]}년 전기 이월금을 입력했습니다.")
    return _back()


@bp.post("/audit/accounts/openings/<int:opening_id>/edit")
def opening_edit(opening_id):
    fields = _opening_fields()
    if not fields:
        flash("연도(예: 2026)와 금액(숫자)을 확인해 주세요.", "error")
        return _back()
    with db() as conn:
        row = conn.execute("SELECT account_id FROM account_openings WHERE id = ?", (opening_id,)).fetchone()
        if row:
            if conn.execute("SELECT 1 FROM account_openings WHERE account_id = ? AND year = ? AND id != ?",
                            (row["account_id"], fields[0], opening_id)).fetchone():
                flash(f"{fields[0]}년 이월금은 이미 입력되어 있습니다.", "error")
                return _back()
            conn.execute("UPDATE account_openings SET year = ?, amount = ?, note = ? WHERE id = ?",
                         (*fields, opening_id))
            flash("전기 이월금을 저장했습니다.")
    return _back()


@bp.post("/audit/accounts/openings/<int:opening_id>/delete")
def opening_delete(opening_id):
    with db() as conn:
        conn.execute("DELETE FROM account_openings WHERE id = ?", (opening_id,))
    flash("전기 이월금을 삭제했습니다.")
    return _back()


# --- 카드 ---
def _card_fields():
    f = request.form
    name = f.get("name", "").strip()
    number = f.get("number", "").strip()
    if not name:
        return None, "카드명(카드사)을 입력해 주세요."
    error = _check_masked(number, "카드번호")
    if error:
        return None, error.replace("0484XX-XX-XX6718", "1234-56XX-XXXX-3456")
    account_id = f.get("account_id", "").strip()
    return {"name": name, "number": number, "holder": f.get("holder", "").strip(),
            "memo": f.get("memo", "").strip(), "account_id": int(account_id) if account_id.isdigit() else None}, None


@bp.post("/audit/accounts/cards/add")
def card_add():
    fields, error = _card_fields()
    if error:
        flash(error, "error")
        return _back()
    with db() as conn:
        conn.execute("INSERT INTO cards(account_id, name, number, holder, memo) "
                     "VALUES (:account_id, :name, :number, :holder, :memo)", fields)
    flash(f"'{fields['name']}' 카드를 추가했습니다.")
    return _back()


@bp.post("/audit/accounts/cards/<int:card_id>/edit")
def card_edit(card_id):
    fields, error = _card_fields()
    if error:
        flash(error, "error")
        return _back()
    with db() as conn:
        conn.execute("UPDATE cards SET account_id=:account_id, name=:name, number=:number, holder=:holder, "
                     "memo=:memo WHERE id=:id", {**fields, "id": card_id})
    flash(f"'{fields['name']}' 카드를 저장했습니다.")
    return _back()


@bp.post("/audit/accounts/cards/<int:card_id>/delete")
def card_delete(card_id):
    with db() as conn:
        row = conn.execute("SELECT name FROM cards WHERE id = ?", (card_id,)).fetchone()
        if row:
            storage.delete_files_for(conn, (CARD_FILE,), card_id)
            conn.execute("DELETE FROM cards WHERE id = ?", (card_id,))
            flash(f"'{row['name']}' 카드를 삭제했습니다.")
    return _back()


@bp.post("/audit/accounts/cards/<int:card_id>/upload")
def card_upload(card_id):
    with db() as conn:
        if conn.execute("SELECT 1 FROM cards WHERE id = ?", (card_id,)).fetchone():
            storage.save_request_files(conn, CARD_FILE, card_id, "accounts")
    return _back()
