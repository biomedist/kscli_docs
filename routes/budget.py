"""예산·결산 현황 (잠금 대상).  1단계: 예산과목 관리 + 은행 엑셀 가져오기 + 거래내역 정리.
- 국민은행 거래내역서(.xls/.xlsx)를 올리면 통장을 자동 인식하고, 합계·잔액을 검증한 뒤 확인 화면을 거쳐 저장합니다.
- 거래마다 예산과목(관·항·목)과 소속 회계(경상비/보수교육비)를 지정하고, 통장 간 이체는 합계에서 제외합니다.
- 이 파일의 화면은 모두 /audit/budget 으로 시작하므로 비밀번호 잠금이 적용됩니다."""
import json
import re
import secrets
from datetime import datetime, timedelta

from flask import Blueprint, abort, flash, redirect, render_template, request, url_for

import bankimport
from menu import get_menu
from models import db

bp = Blueprint("budget", __name__)

PER_PAGE = 50
RULE_FIELDS = {"memo_own": "내 통장 표시", "summary": "적요", "counterparty": "상대방"}


# ---------- 화면용 도우미 ----------
@bp.app_template_filter("ktx")
def ktx(value):
    """'2026-10-12T09:41:23' → '2026.10.12 09:41'"""
    try:
        d = datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return value or ""
    return f"{d.year}.{d.month:02d}.{d.day:02d} {d:%H:%M}"


def _safe_next(value):
    if value and value.startswith("/audit/budget") and not value.startswith("//"):
        return value
    return url_for("budget.transactions")


def _now():
    return datetime.now().isoformat(timespec="seconds")


@bp.route("/audit/budget")
def index():
    return redirect(url_for("budget.transactions"))


# ---------- 예산과목 목록 ----------
def _category_list(conn):
    """트리 순서(관 > 항 > 목)로 펼친 목록. 각 항목에 path(전체 이름)와 depth 가 들어 있습니다."""
    rows = conn.execute("SELECT * FROM budget_categories ORDER BY sort_order, id").fetchall()
    children = {}
    for r in rows:
        children.setdefault(r["parent_id"], []).append(r)
    out = []

    def walk(parent_id, trail):
        for r in children.get(parent_id, []):
            path = trail + [r["name"]]
            out.append({"id": r["id"], "name": r["name"], "level": r["level"], "kind": r["kind"],
                        "parent_id": r["parent_id"], "path": " > ".join(path), "depth": r["level"] - 1,
                        "has_children": r["id"] in children})
            walk(r["id"], path)
    walk(None, [])
    return out


# ---------- 자동 분류 ----------
def _load_rules(conn):
    rows = conn.execute("SELECT field, keyword, category_id FROM category_rules").fetchall()
    return sorted(((r["field"], r["keyword"], r["category_id"]) for r in rows), key=lambda x: -len(x[1]))


def _apply_rules(rules, row):
    for field, keyword, category_id in rules:
        if keyword and keyword in (row.get(field) or ""):
            return category_id
    return None


def _keyword(memo_own):
    """'운영회의 0930' → '운영회의', '휴가보전수당_홍길동' → '휴가보전수당' (날짜·이름 부분은 뺍니다)"""
    text = (memo_own or "").split("_")[0]
    text = re.sub(r"^[\d\s./~\-]+", "", text)
    text = re.sub(r"[\d\s./~\-]+$", "", text)
    return text.strip()


def _remember_rules(conn, ids, category_id):
    """선택한 거래의 '내 통장 표시'를 규칙으로 기억하고, 아직 분류 안 된 같은 내용의 거래에도 적용합니다."""
    marks = ",".join("?" * len(ids))
    keywords = {_keyword(r["memo_own"]) for r in conn.execute(
        f"SELECT memo_own FROM bank_transactions WHERE id IN ({marks})", ids)}
    applied = 0
    for keyword in sorted(k for k in keywords if len(k) >= 2):
        conn.execute("INSERT INTO category_rules(field, keyword, category_id) VALUES ('memo_own', ?, ?) "
                     "ON CONFLICT(field, keyword) DO UPDATE SET category_id = excluded.category_id", (keyword, category_id))
        applied += conn.execute(
            "UPDATE bank_transactions SET category_id = ?, category_source = 'rule' "
            "WHERE category_id IS NULL AND is_transfer = 0 AND instr(memo_own, ?) > 0", (category_id, keyword)).rowcount
    return len(keywords), applied


# ---------- 거래내역 ----------
def _date_arg(text):
    """'2026-01-31' 형식만 받아 그대로 돌려주고, 아니면 None"""
    try:
        return datetime.strptime((text or "").strip(), "%Y-%m-%d").strftime("%Y-%m-%d")
    except ValueError:
        return None


def _range_presets():
    """기간 빠른 선택: 이번 달 / 지난 달 / 올해 상반기 / 올해 하반기"""
    t = datetime.now().date()
    first = t.replace(day=1)
    last_prev = first - timedelta(days=1)
    return [("이번 달", first, t), ("지난 달", last_prev.replace(day=1), last_prev),
            ("올해 상반기", t.replace(month=1, day=1), t.replace(month=6, day=30)),
            ("올해 하반기", t.replace(month=7, day=1), t.replace(month=12, day=31))]


@bp.route("/audit/budget/transactions")
def transactions():
    now_year = datetime.now().year
    account = request.args.get("account", "all")
    status = request.args.get("status", "all")
    q = request.args.get("q", "").strip()
    start, end = _date_arg(request.args.get("start")), _date_arg(request.args.get("end"))
    if start and end and start > end:
        start, end = end, start
    with db() as conn:
        accounts = conn.execute("SELECT id, alias, last4 FROM accounts ORDER BY id").fetchall()
        years = [int(r["y"]) for r in conn.execute(
            "SELECT DISTINCT substr(occurred_at, 1, 4) AS y FROM bank_transactions ORDER BY y DESC")]
        year = request.args.get("year")
        if year is None:
            year = str(years[0]) if years else str(now_year)
        elif year != "all" and not year.isdigit():
            year = str(now_year)

        where, args = ["1 = 1"], []
        if account.isdigit():
            where.append("t.account_id = ?"); args.append(int(account))
        else:
            account = "all"
        if start or end:            # 기간을 정하면 연도 선택보다 우선합니다
            year = "all"
            if start:
                where.append("substr(t.occurred_at, 1, 10) >= ?"); args.append(start)
            if end:
                where.append("substr(t.occurred_at, 1, 10) <= ?"); args.append(end)
        elif year != "all":
            where.append("substr(t.occurred_at, 1, 4) = ?"); args.append(year)
        base_where, base_args = " AND ".join(where), list(args)      # 상태·검색 조건을 빼고 센 값(미분류 건수용)

        if status == "unclassified":
            where.append("t.category_id IS NULL AND t.is_transfer = 0")
        elif status == "auto":
            where.append("t.category_source = 'rule'")
        elif status == "transfer":
            where.append("t.is_transfer = 1")
        elif status == "moved":
            where.append("t.fund_account_id IS NOT NULL AND t.fund_account_id != t.account_id")
        else:
            status = "all"
        if q:
            where.append("(t.memo_own LIKE ? OR t.counterparty LIKE ? OR t.summary LIKE ? OR t.memo LIKE ?)")
            args += [f"%{q}%"] * 4
        clause = " AND ".join(where)

        total_count = conn.execute(f"SELECT COUNT(*) FROM bank_transactions t WHERE {clause}", args).fetchone()[0]
        sums = conn.execute(
            f"SELECT COALESCE(SUM(deposit), 0) AS d, COALESCE(SUM(withdrawal), 0) AS w FROM bank_transactions t "
            f"WHERE {clause} AND t.is_transfer = 0", args).fetchone()
        unclassified = conn.execute(
            f"SELECT COUNT(*) FROM bank_transactions t WHERE {base_where} AND t.category_id IS NULL AND t.is_transfer = 0",
            base_args).fetchone()[0]
        pages = max(1, -(-total_count // PER_PAGE))
        page = request.args.get("page", "1")
        page = min(max(1, int(page) if page.isdigit() else 1), pages)
        rows = conn.execute(
            f"SELECT t.*, a.alias AS account_alias, f.alias AS fund_alias, vt.voucher_id, v.voucher_no FROM bank_transactions t "
            f"JOIN accounts a ON a.id = t.account_id "
            f"LEFT JOIN accounts f ON f.id = COALESCE(t.fund_account_id, t.account_id) "
            f"LEFT JOIN voucher_transactions vt ON vt.transaction_id = t.id "
            f"LEFT JOIN vouchers v ON v.id = vt.voucher_id "
            f"WHERE {clause} ORDER BY t.occurred_at DESC, t.id DESC LIMIT ? OFFSET ?",
            args + [PER_PAGE, (page - 1) * PER_PAGE]).fetchall()
        categories = _category_list(conn)
        paths = {c["id"]: c["path"] for c in categories}

    def link(**override):
        params = {"account": account, "year": None if (start or end) else year, "status": status, "q": q,
                  "start": start, "end": end, "page": 1}
        params.update(override)
        params = {k: v for k, v in params.items() if v not in ("", None) and not (k in ("account", "status") and v == "all")}
        if params.get("page") == 1:
            params.pop("page", None)
        return url_for("budget.transactions", **params)

    return render_template(
        "budget_transactions.html", page=get_menu("budget"), accounts=accounts, account=account, years=years,
        year=year, status=status, q=q, rows=rows, paths=paths, categories=categories, total_count=total_count,
        deposit_sum=sums["d"], withdrawal_sum=sums["w"], unclassified=unclassified, page_no=page, pages=pages,
        link=link, next_url=link(page=page) if page > 1 else link(),
        start=start or "", end=end or "", presets=_range_presets(),
    )


@bp.post("/audit/budget/transactions/<int:tx_id>/category")
def tx_category(tx_id):
    """거래 한 건의 예산과목을 바로 지정·변경·해제합니다. (거래내역의 예산과목 칸에서 호출)"""
    nxt = _safe_next(request.form.get("next"))
    raw = request.form.get("category_id", "")
    with db() as conn:
        if not conn.execute("SELECT 1 FROM bank_transactions WHERE id = ?", (tx_id,)).fetchone():
            abort(404)
        if raw.isdigit():
            category = conn.execute("SELECT name FROM budget_categories WHERE id = ?", (int(raw),)).fetchone()
            if not category:
                flash("예산과목을 선택해 주세요.", "error")
                return redirect(nxt)
            conn.execute("UPDATE bank_transactions SET category_id = ?, category_source = 'manual' WHERE id = ?",
                         (int(raw), tx_id))
            message = f"'{category['name']}'(으)로 분류했습니다."
            if request.form.get("remember"):
                n_rules, applied = _remember_rules(conn, [tx_id], int(raw))
                if n_rules:
                    message += f" 같은 내용은 다음에도 자동 분류되도록 기억했고, 이미 있던 {applied}건에도 적용했습니다."
            flash(message)
        else:
            conn.execute("UPDATE bank_transactions SET category_id = NULL, category_source = NULL WHERE id = ?", (tx_id,))
            flash("분류를 해제했습니다.")
    return redirect(nxt)


@bp.post("/audit/budget/transactions/bulk")
def bulk():
    nxt = _safe_next(request.form.get("next"))
    ids = [int(i) for i in request.form.getlist("ids") if i.isdigit()]
    action, _, extra = request.form.get("action", "").partition(":")
    if not ids:
        flash("거래를 먼저 선택해 주세요.", "error")
        return redirect(nxt)
    marks = ",".join("?" * len(ids))
    with db() as conn:
        if action == "category":
            raw = request.form.get("category_id", "")
            category = conn.execute("SELECT name FROM budget_categories WHERE id = ?", (int(raw),)).fetchone() if raw.isdigit() else None
            if not category:
                flash("예산과목을 선택해 주세요.", "error")
                return redirect(nxt)
            conn.execute(f"UPDATE bank_transactions SET category_id = ?, category_source = 'manual' WHERE id IN ({marks})",
                         [int(raw)] + ids)
            message = f"{len(ids)}건을 '{category['name']}'(으)로 분류했습니다."
            if request.form.get("remember"):
                n_rules, applied = _remember_rules(conn, ids, int(raw))
                message += f" 같은 내용은 다음에도 자동 분류되도록 기억했고, 이미 있던 {applied}건에도 적용했습니다." if n_rules else ""
            flash(message)
        elif action == "clear_category":
            conn.execute(f"UPDATE bank_transactions SET category_id = NULL, category_source = NULL WHERE id IN ({marks})", ids)
            flash(f"{len(ids)}건의 분류를 해제했습니다.")
        elif action == "fund" and extra.isdigit():
            target = conn.execute("SELECT alias FROM accounts WHERE id = ?", (int(extra),)).fetchone()
            if not target:
                abort(404)
            conn.execute(f"UPDATE bank_transactions SET fund_account_id = CASE WHEN account_id = ? THEN NULL ELSE ? END "
                         f"WHERE id IN ({marks})", [int(extra), int(extra)] + ids)
            flash(f"{len(ids)}건의 소속 회계를 '{target['alias']}'(으)로 옮겼습니다.")
        elif action in ("transfer_on", "transfer_off"):
            conn.execute(f"UPDATE bank_transactions SET is_transfer = ? WHERE id IN ({marks})",
                         [1 if action == "transfer_on" else 0] + ids)
            flash(f"{len(ids)}건을 {'이체로 표시했습니다. 수입·지출 합계에서 제외됩니다.' if action == 'transfer_on' else '이체 표시를 해제했습니다.'}")
        else:
            flash("알 수 없는 작업입니다.", "error")
    return redirect(nxt)


# ---------- 엑셀 가져오기 ----------
def _existing_keys(conn, account_id, rows):
    low, high = min(r["occurred_at"] for r in rows), max(r["occurred_at"] for r in rows)
    return {r["dedupe_key"] for r in conn.execute(
        "SELECT dedupe_key FROM bank_transactions WHERE account_id = ? AND occurred_at BETWEEN ? AND ?",
        (account_id, low, high))}


def _dedupe_key(account_id, r):
    return f"{account_id}|{r['occurred_at']}|{r['withdrawal']}|{r['deposit']}|{r['balance']}"


@bp.post("/audit/budget/import")
def import_upload():
    upload = request.files.get("file")
    if not upload or not upload.filename:
        flash("올릴 엑셀 파일을 선택해 주세요.", "error")
        return redirect(url_for("budget.transactions"))
    try:
        parsed = bankimport.parse_statement(upload.read(), upload.filename)   # 파일 이름·원본은 저장하지 않습니다
    except bankimport.ImportProblem as problem:
        flash(str(problem), "error")
        return redirect(url_for("budget.transactions"))
    token = secrets.token_urlsafe(12)
    with db() as conn:
        conn.execute("DELETE FROM bank_imports WHERE created_at < ?", ((datetime.now() - timedelta(days=1)).isoformat(timespec="seconds"),))
        conn.execute("INSERT INTO bank_imports(token, created_at, payload) VALUES (?, ?, ?)",
                     (token, _now(), json.dumps(parsed, ensure_ascii=False)))
    return redirect(url_for("budget.import_preview", token=token))


def _load_import(conn, token):
    row = conn.execute("SELECT payload FROM bank_imports WHERE token = ?", (token,)).fetchone()
    if not row:
        flash("확인 시간이 지났거나 이미 처리된 파일입니다. 엑셀을 다시 올려 주세요.", "error")
        return None
    return json.loads(row["payload"])


@bp.route("/audit/budget/import/<token>")
def import_preview(token):
    with db() as conn:
        parsed = _load_import(conn, token)
        if parsed is None:
            return redirect(url_for("budget.transactions"))
        accounts = conn.execute("SELECT id, alias, last4 FROM accounts ORDER BY id").fetchall()
        info, rows = parsed["info"], parsed["rows"]
        chosen = request.args.get("account", "")
        match = next((a for a in accounts if info["last4"] and a["last4"] == info["last4"]), None) \
            or next((a for a in accounts if info["alias"] and a["alias"] == info["alias"]), None)
        account_id = int(chosen) if chosen.isdigit() else (match["id"] if match else None)
        rules = _load_rules(conn)
        paths = {c["id"]: c["path"] for c in _category_list(conn)}
        existing = _existing_keys(conn, account_id, rows) if account_id else set()

    fresh = [r for r in rows if _dedupe_key(account_id, r) not in existing] if account_id else rows
    suggestions = [(r, _apply_rules(rules, r)) for r in fresh]
    auto_count = sum(1 for _, c in suggestions if c)
    preview = [{"row": r, "category": paths.get(c)} for r, c in suggestions[:40]]
    return render_template(
        "budget_import.html", page=get_menu("budget"), token=token, info=info, checks=parsed["checks"], accounts=accounts,
        account_id=account_id, matched=bool(match) and not chosen, new_count=len(fresh), dup_count=len(rows) - len(fresh) if account_id else 0,
        auto_count=auto_count, preview=preview, preview_more=max(0, len(fresh) - 40),
    )


@bp.post("/audit/budget/import/<token>/confirm")
def import_confirm(token):
    raw = request.form.get("account_id", "")
    with db() as conn:
        parsed = _load_import(conn, token)
        if parsed is None:
            return redirect(url_for("budget.transactions"))
        if not raw.isdigit() or not conn.execute("SELECT 1 FROM accounts WHERE id = ?", (int(raw),)).fetchone():
            flash("거래를 넣을 통장을 선택해 주세요.", "error")
            return redirect(url_for("budget.import_preview", token=token))
        account_id = int(raw)
        rules = _load_rules(conn)
        added = auto = 0
        for r in parsed["rows"]:
            category_id = _apply_rules(rules, r)
            cur = conn.execute(
                "INSERT OR IGNORE INTO bank_transactions(account_id, occurred_at, counterparty, memo_own, memo, summary, branch, "
                "deposit, withdrawal, balance, category_id, category_source, dedupe_key, imported_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (account_id, r["occurred_at"], r["counterparty"], r["memo_own"], r["memo"], r["summary"], r["branch"],
                 r["deposit"], r["withdrawal"], r["balance"], category_id, "rule" if category_id else None,
                 _dedupe_key(account_id, r), _now()))
            if cur.rowcount:
                added += 1
                auto += 1 if category_id else 0
        skipped = len(parsed["rows"]) - added
        conn.execute("DELETE FROM bank_imports WHERE token = ?", (token,))
    flash(f"새 거래 {added}건을 가져왔습니다. (이미 있던 {skipped}건 제외 · 자동 분류 {auto}건 · 직접 분류할 거래 {added - auto}건)")
    return redirect(url_for("budget.transactions", account=account_id, status="unclassified" if added - auto else None))


@bp.post("/audit/budget/import/<token>/cancel")
def import_cancel(token):
    with db() as conn:
        conn.execute("DELETE FROM bank_imports WHERE token = ?", (token,))
    flash("가져오기를 취소했습니다. 아무것도 저장되지 않았습니다.")
    return redirect(url_for("budget.transactions"))


# ---------- 통장 간 이체 후보 ----------
def _transfer_pairs(conn):
    """금액이 같고 3일 이내인 '한 통장 출금 ↔ 다른 통장 입금' 쌍을 찾습니다."""
    rows = conn.execute(
        "SELECT t.id, t.account_id, t.occurred_at, t.deposit, t.withdrawal, t.memo_own, t.summary, a.alias "
        "FROM bank_transactions t JOIN accounts a ON a.id = t.account_id WHERE t.is_transfer = 0").fetchall()
    deposits = {}
    for r in rows:
        if r["deposit"] > 0:
            deposits.setdefault(r["deposit"], []).append(r)
    used, pairs = set(), []
    for w in sorted((r for r in rows if r["withdrawal"] > 0), key=lambda r: r["occurred_at"], reverse=True):
        w_time = datetime.fromisoformat(w["occurred_at"])
        best = None
        for d in deposits.get(w["withdrawal"], []):
            if d["id"] in used or d["account_id"] == w["account_id"]:
                continue
            gap = abs((datetime.fromisoformat(d["occurred_at"]) - w_time).total_seconds())
            if gap <= 3 * 86400 and (best is None or gap < best[0]):
                best = (gap, d)
        if best:
            used.add(best[1]["id"])
            pairs.append({"withdrawal": w, "deposit": best[1]})
    return pairs[:200]


@bp.route("/audit/budget/transfers")
def transfers():
    with db() as conn:
        pairs = _transfer_pairs(conn)
    return render_template("budget_transfers.html", page=get_menu("budget"), pairs=pairs)


@bp.post("/audit/budget/transfers/mark")
def transfers_mark():
    marked = 0
    with db() as conn:
        for pair in request.form.getlist("pair"):
            w_id, _, d_id = pair.partition(":")
            if not (w_id.isdigit() and d_id.isdigit()):
                continue
            w = conn.execute("SELECT account_id, withdrawal FROM bank_transactions WHERE id = ?", (int(w_id),)).fetchone()
            d = conn.execute("SELECT account_id, deposit FROM bank_transactions WHERE id = ?", (int(d_id),)).fetchone()
            if w and d and w["account_id"] != d["account_id"] and w["withdrawal"] == d["deposit"]:
                conn.execute("UPDATE bank_transactions SET is_transfer = 1 WHERE id IN (?, ?)", (int(w_id), int(d_id)))
                marked += 1
    flash(f"{marked}쌍을 통장 간 이체로 표시했습니다. 수입·지출 합계에서 제외됩니다." if marked else "선택한 쌍이 없습니다.",
          "message" if marked else "error")
    return redirect(url_for("budget.transfers"))


# ---------- 예산과목 관리 ----------
@bp.route("/audit/budget/categories")
def categories():
    with db() as conn:
        tree = _category_list(conn)
        used = {r["category_id"]: r["n"] for r in conn.execute(
            "SELECT category_id, COUNT(*) AS n FROM bank_transactions WHERE category_id IS NOT NULL GROUP BY category_id")}
        rules = conn.execute(
            "SELECT r.id, r.field, r.keyword, c.name FROM category_rules r JOIN budget_categories c ON c.id = r.category_id "
            "ORDER BY c.name, r.keyword").fetchall()
    for node in tree:
        node["used"] = used.get(node["id"], 0)
    return render_template(
        "budget_categories.html", page=get_menu("budget"), expense=[n for n in tree if n["kind"] == "지출"],
        income=[n for n in tree if n["kind"] == "수입"], rules=rules, rule_fields=RULE_FIELDS,
    )


def _siblings(conn, parent_id, kind=None):
    if parent_id is None:
        return conn.execute("SELECT id FROM budget_categories WHERE parent_id IS NULL AND kind = ? ORDER BY sort_order, id", (kind,)).fetchall()
    return conn.execute("SELECT id FROM budget_categories WHERE parent_id = ? ORDER BY sort_order, id", (parent_id,)).fetchall()


@bp.post("/audit/budget/categories/add")
def category_add():
    name = request.form.get("name", "").strip()[:40]
    parent_raw = request.form.get("parent_id", "").strip()
    kind = request.form.get("kind", "").strip()
    if not name:
        flash("예산과목 이름을 입력해 주세요.", "error")
        return redirect(url_for("budget.categories"))
    with db() as conn:
        if parent_raw.isdigit():
            parent = conn.execute("SELECT * FROM budget_categories WHERE id = ?", (int(parent_raw),)).fetchone()
            if not parent:
                abort(404)
            if parent["level"] >= 3:
                flash("목 아래에는 더 만들 수 없습니다. (관 > 항 > 목까지)", "error")
                return redirect(url_for("budget.categories"))
            level, kind, parent_id = parent["level"] + 1, parent["kind"], parent["id"]
        else:
            if kind not in ("수입", "지출"):
                flash("수입 또는 지출을 선택해 주세요.", "error")
                return redirect(url_for("budget.categories"))
            level, parent_id = 1, None
        if conn.execute("SELECT 1 FROM budget_categories WHERE name = ? AND parent_id IS ? AND kind = ?", (name, parent_id, kind)).fetchone():
            flash(f"같은 위치에 '{name}'이(가) 이미 있습니다.", "error")
            return redirect(url_for("budget.categories"))
        order = len(_siblings(conn, parent_id, kind)) + 1
        conn.execute("INSERT INTO budget_categories(parent_id, level, kind, name, sort_order) VALUES (?, ?, ?, ?, ?)",
                     (parent_id, level, kind, name, order))
    flash(f"'{name}'을(를) 추가했습니다.")
    return redirect(url_for("budget.categories"))


@bp.post("/audit/budget/categories/<int:category_id>/edit")
def category_edit(category_id):
    name = request.form.get("name", "").strip()[:40]
    if not name:
        flash("예산과목 이름을 입력해 주세요.", "error")
        return redirect(url_for("budget.categories"))
    with db() as conn:
        row = conn.execute("SELECT * FROM budget_categories WHERE id = ?", (category_id,)).fetchone()
        if not row:
            abort(404)
        if conn.execute("SELECT 1 FROM budget_categories WHERE name = ? AND parent_id IS ? AND kind = ? AND id != ?",
                        (name, row["parent_id"], row["kind"], category_id)).fetchone():
            flash(f"같은 위치에 '{name}'이(가) 이미 있습니다.", "error")
        else:
            conn.execute("UPDATE budget_categories SET name = ? WHERE id = ?", (name, category_id))
            flash("이름을 바꿨습니다. 이미 분류된 거래에도 그대로 반영됩니다.")
    return redirect(url_for("budget.categories"))


@bp.post("/audit/budget/categories/<int:category_id>/delete")
def category_delete(category_id):
    with db() as conn:
        row = conn.execute("SELECT name FROM budget_categories WHERE id = ?", (category_id,)).fetchone()
        if not row:
            abort(404)
        if conn.execute("SELECT 1 FROM budget_categories WHERE parent_id = ?", (category_id,)).fetchone():
            flash(f"'{row['name']}' 아래에 하위 과목이 있어 삭제할 수 없습니다. 하위 과목을 먼저 지워 주세요.", "error")
        elif conn.execute("SELECT 1 FROM bank_transactions WHERE category_id = ? LIMIT 1", (category_id,)).fetchone():
            flash(f"'{row['name']}'(으)로 분류된 거래가 있어 삭제할 수 없습니다. 거래를 다른 과목으로 옮긴 뒤 지워 주세요.", "error")
        else:
            conn.execute("DELETE FROM budget_categories WHERE id = ?", (category_id,))
            flash(f"'{row['name']}'을(를) 삭제했습니다.")
    return redirect(url_for("budget.categories"))


@bp.post("/audit/budget/categories/<int:category_id>/move")
def category_move(category_id):
    step = -1 if request.form.get("dir") == "up" else 1
    with db() as conn:
        row = conn.execute("SELECT parent_id, kind FROM budget_categories WHERE id = ?", (category_id,)).fetchone()
        if not row:
            abort(404)
        ids = [r["id"] for r in _siblings(conn, row["parent_id"], row["kind"])]
        i = ids.index(category_id)
        j = i + step
        if 0 <= j < len(ids):
            ids[i], ids[j] = ids[j], ids[i]
        for n, cid in enumerate(ids, 1):
            conn.execute("UPDATE budget_categories SET sort_order = ? WHERE id = ?", (n, cid))
    return redirect(url_for("budget.categories"))


@bp.post("/audit/budget/rules/<int:rule_id>/delete")
def rule_delete(rule_id):
    with db() as conn:
        conn.execute("DELETE FROM category_rules WHERE id = ?", (rule_id,))
    flash("자동 분류 규칙을 삭제했습니다. 이미 분류된 거래는 그대로입니다.")
    return redirect(url_for("budget.categories"))
