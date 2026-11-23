"""결산표 (예산·결산 현황 3번째 탭, 잠금 대상): 기간과 회계를 고르면 관·항·목 소계가 쌓이는 표가 나옵니다.

- 실적은 거래내역에서 자동 집계합니다. (통장 간 이체로 표시한 거래는 빠지고, 찬조금도 거래내역에 있으므로 따로 더하지 않습니다)
- 예산은 회계(통장)·연도별로 목(가장 아래 단계)마다 입력하면 항·관 예산은 자동으로 합쳐집니다.
- 예산과목이 없는 거래는 '미분류' 줄로 따로 잡아 합계가 통장과 어긋나지 않게 하고, 알림으로 알려 줍니다.
- 잔액 검증: 전기이월금 + 거래 합계가 통장에 찍힌 마지막 잔액과 같은지 확인합니다. (빠진 거래를 찾는 용도)
- 주소가 /audit/budget 으로 시작하므로 비밀번호 잠금이 적용됩니다.
"""
import io
from datetime import date, datetime, timedelta

from flask import Blueprint, flash, redirect, render_template, request, send_file, url_for

from menu import get_menu
from models import db
from .budget import _category_list

bp = Blueprint("settlement", __name__)

KINDS = ("수입", "지출")


@bp.app_template_filter("comma")
def comma(value):
    return "" if value is None else f"{int(value):,}"


# ---------- 조회 조건 ----------
def _d(text, default):
    try:
        return datetime.strptime((text or "").strip(), "%Y-%m-%d").date()
    except ValueError:
        return default


def _params(source):
    today = date.today()
    start = _d(source.get("start"), date(today.year, 1, 1))
    end = _d(source.get("end"), today)
    if start > end:
        start, end = end, start
    fund = source.get("fund", "all")
    return start, end, (fund if fund.isdigit() else "all")


def _presets():
    t = date.today()
    return [
        ("올해 누계", date(t.year, 1, 1), t),
        ("올해 상반기", date(t.year, 1, 1), date(t.year, 6, 30)),
        ("올해 하반기", date(t.year, 7, 1), date(t.year, 12, 31)),
        (f"{t.year - 1}년 전체", date(t.year - 1, 1, 1), date(t.year - 1, 12, 31)),
    ]


# ---------- 계산 ----------
def _fund_expr():
    return "COALESCE(t.fund_account_id, t.account_id)"


def compute(conn, start, end, fund):
    accounts = conn.execute("SELECT id, alias FROM accounts ORDER BY id").fetchall()
    name = {a["id"]: (a["alias"] or f"통장 {a['id']}") for a in accounts}
    funds = [a["id"] for a in accounts] if fund == "all" else [int(fund)]
    funds = [f for f in funds if f in name]
    marks = ",".join("?" * len(funds)) or "NULL"
    s, e = start.isoformat(), end.isoformat()
    year = end.year      # 예산은 기간이 끝나는 해 기준
    cats = _category_list(conn)

    # 실적: 예산과목별 입금·출금 (통장 간 이체 제외)
    flow = {r["category_id"]: r for r in conn.execute(
        f"SELECT t.category_id, SUM(t.deposit) AS d, SUM(t.withdrawal) AS w, COUNT(*) AS n FROM bank_transactions t "
        f"WHERE t.is_transfer = 0 AND substr(t.occurred_at, 1, 10) BETWEEN ? AND ? AND {_fund_expr()} IN ({marks}) "
        f"GROUP BY t.category_id", [s, e, *funds])}

    # 예산
    budget, notes = {}, {}
    for r in conn.execute(
            f"SELECT fund_account_id, category_id, amount, note FROM budget_amounts WHERE year = ? AND fund_account_id IN ({marks})",
            [year, *funds]):
        budget[r["category_id"]] = budget.get(r["category_id"], 0) + (r["amount"] or 0)
        if r["note"]:
            notes.setdefault(r["category_id"], []).append((name[r["fund_account_id"]], r["note"]))

    children = {}
    for c in cats:
        children.setdefault(c["parent_id"], []).append(c["id"])
    by_id = {c["id"]: c for c in cats}
    memo = {}

    def total(cid):
        if cid in memo:
            return memo[cid]
        c = by_id[cid]
        f = flow.get(cid)
        own = 0
        if f:
            own = (f["w"] - f["d"]) if c["kind"] == "지출" else (f["d"] - f["w"])
        b, a = budget.get(cid, 0), own
        for ch in children.get(cid, []):
            cb, ca = total(ch)
            b, a = b + cb, a + ca
        memo[cid] = (b, a)
        return memo[cid]

    def note_text(cid):
        items = notes.get(cid, [])
        if len(funds) == 1:
            return " / ".join(t for _, t in items)
        return " · ".join(f"{n}: {t}" for n, t in items)

    sections = {}
    for kind in KINDS:
        rows = []
        for c in cats:
            if c["kind"] != kind:
                continue
            b, a = total(c["id"])
            rows.append({"id": c["id"], "name": c["name"], "level": c["level"], "depth": c["depth"],
                         "leaf": c["id"] not in children, "budget": b, "actual": a,
                         "own_budget": budget.get(c["id"], 0), "note": note_text(c["id"]),
                         "note_raw": notes.get(c["id"], [("", "")])[0][1] if len(funds) == 1 and notes.get(c["id"]) else ""})
        un = flow.get(None)
        un_amt = (un["w"] if kind == "지출" else un["d"]) if un else 0
        top = [r for r in rows if r["level"] == 1]
        sections[kind] = {
            "rows": rows, "unclassified": un_amt,
            "budget": sum(r["budget"] for r in top), "actual": sum(r["actual"] for r in top) + un_amt,
        }
    un = flow.get(None)
    unclassified = {"n": un["n"] if un else 0, "d": un["d"] if un else 0, "w": un["w"] if un else 0}

    # 잔액 검증 (회계=통장 별)
    y0 = start.year
    jan1 = date(y0, 1, 1).isoformat()
    day_before = (start - timedelta(days=1)).isoformat()
    opening = {r["account_id"]: r["amount"] for r in conn.execute(
        "SELECT account_id, amount FROM account_openings WHERE year = ?", (y0,))}

    def net(where, args):
        r = conn.execute(f"SELECT COALESCE(SUM(t.deposit - t.withdrawal), 0) AS n FROM bank_transactions t WHERE {where}", args).fetchone()
        return r["n"]

    check = []
    for fid in funds:
        carry = opening.get(fid, 0) + net(f"{_fund_expr()} = ? AND substr(t.occurred_at, 1, 10) BETWEEN ? AND ?", [fid, jan1, day_before])
        pr = conn.execute(
            f"SELECT COALESCE(SUM(CASE WHEN t.is_transfer = 0 THEN t.deposit END), 0) AS d, "
            f"COALESCE(SUM(CASE WHEN t.is_transfer = 0 THEN t.withdrawal END), 0) AS w, "
            f"COALESCE(SUM(CASE WHEN t.is_transfer = 1 THEN t.deposit - t.withdrawal END), 0) AS tr "
            f"FROM bank_transactions t WHERE {_fund_expr()} = ? AND substr(t.occurred_at, 1, 10) BETWEEN ? AND ?",
            [fid, s, e]).fetchone()
        closing = carry + pr["d"] - pr["w"] + pr["tr"]
        # 통장에 찍힌 잔액과 비교
        expected = opening.get(fid, 0) + net("t.account_id = ? AND substr(t.occurred_at, 1, 10) BETWEEN ? AND ?", [fid, jan1, e])
        last = conn.execute(
            "SELECT occurred_at FROM bank_transactions WHERE account_id = ? AND substr(occurred_at, 1, 10) <= ? AND balance IS NOT NULL "
            "ORDER BY occurred_at DESC, id DESC LIMIT 1", (fid, e)).fetchone()
        bank = None
        if last:
            balances = [r["balance"] for r in conn.execute(
                "SELECT balance FROM bank_transactions WHERE account_id = ? AND occurred_at = ? AND balance IS NOT NULL ORDER BY id DESC",
                (fid, last["occurred_at"]))]
            bank = expected if expected in balances else balances[0]   # 같은 시각 거래가 여럿이면 맞는 쪽을 기준으로
        adj = net(f"{_fund_expr()} = ? AND t.account_id != ? AND substr(t.occurred_at, 1, 10) BETWEEN ? AND ?", [fid, fid, jan1, e]) \
            - net("t.account_id = ? AND COALESCE(t.fund_account_id, t.account_id) != ? AND substr(t.occurred_at, 1, 10) BETWEEN ? AND ?", [fid, fid, jan1, e])
        if bank is None:
            status = "none"
        elif bank == expected:
            status = "ok"      # 전기이월금을 따로 넣지 않았어도 0원으로 맞으면 통과
        elif fid not in opening:
            status = "no_opening"
        else:
            status = "diff"
        check.append({"id": fid, "name": name[fid], "carry": carry, "d": pr["d"], "w": pr["w"], "tr": pr["tr"],
                      "closing": closing, "bank": bank, "expected": expected, "diff": (bank - expected) if bank is not None else None,
                      "status": status, "adj": adj})
    return {"name": name, "funds": funds, "sections": sections, "unclassified": unclassified, "check": check,
            "year": year, "has_budget": bool(budget), "cats": cats,
            "closing": sum(c["closing"] for c in check), "carry": sum(c["carry"] for c in check),
            "all_ok": all(c["status"] == "ok" for c in check) if check else False}


def _pct(budget, actual):
    return round(actual / budget * 100, 1) if budget else None


@bp.route("/audit/budget/settlement")
def view():
    start, end, fund = _params(request.args)
    edit = request.args.get("edit") == "1" and fund != "all"
    show_empty = request.args.get("empty") == "1" or edit
    with db() as conn:
        data = compute(conn, start, end, fund)
        accounts = conn.execute("SELECT id, alias FROM accounts ORDER BY id").fetchall()
    for sec in data["sections"].values():
        for r in sec["rows"]:
            r["pct"] = _pct(r["budget"], r["actual"])
        sec["pct"] = _pct(sec["budget"], sec["actual"])
        if not show_empty:
            sec["rows"] = [r for r in sec["rows"] if r["budget"] or r["actual"] or r["note"]]
    inc, exp = data["sections"]["수입"], data["sections"]["지출"]
    spans = start.year != end.year
    return render_template(
        "settlement.html", page=get_menu("budget"), start=start, end=end, fund=fund, accounts=accounts, data=data,
        inc=inc, exp=exp, edit=edit, show_empty=show_empty, presets=_presets(), spans=spans,
        today=date.today(), balance_diff=(inc["actual"] - exp["actual"]))


@bp.post("/audit/budget/settlement/save")
def save():
    start, end, fund = _params(request.form)
    back = url_for("settlement.view", start=start, end=end, fund=fund)
    if fund == "all":
        flash("예산은 회계를 하나 골라서 입력해 주세요.", "error")
        return redirect(back)
    fid, year = int(fund), end.year
    with db() as conn:
        cats = _category_list(conn)
        has_child = {c["parent_id"] for c in cats if c["parent_id"]}
        saved = 0
        for c in cats:
            note = request.form.get(f"note_{c['id']}", "").strip()[:200]
            amount = None
            if c["id"] not in has_child:
                raw = request.form.get(f"amt_{c['id']}", "").replace(",", "").replace("원", "").strip()
                amount = int(raw) if raw.lstrip("-").isdigit() else 0
            if amount or note:
                conn.execute(
                    "INSERT INTO budget_amounts(year, fund_account_id, category_id, amount, note) VALUES (?, ?, ?, ?, ?) "
                    "ON CONFLICT(year, fund_account_id, category_id) DO UPDATE SET amount = excluded.amount, note = excluded.note",
                    (year, fid, c["id"], amount or 0, note))
                saved += 1
            else:
                conn.execute("DELETE FROM budget_amounts WHERE year = ? AND fund_account_id = ? AND category_id = ?",
                             (year, fid, c["id"]))
    flash(f"{year}년 예산을 저장했습니다.")
    return redirect(back)


@bp.route("/audit/budget/settlement.xlsx")
def export():
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill
    start, end, fund = _params(request.args)
    with db() as conn:
        data = compute(conn, start, end, fund)
    label = "합계" if fund == "all" else data["name"].get(int(fund), "")
    wb = Workbook()
    ws = wb.active
    ws.title = "결산표"
    ws.append([f"결산표 ({label})"])
    ws["A1"].font = Font(bold=True, size=14)
    ws.append([f"기간: {start:%Y.%m.%d} ~ {end:%Y.%m.%d}"])
    for kind in KINDS:
        sec = data["sections"][kind]
        ws.append([])
        ws.append([f"{kind} 부", "예산", "실적", "비율(%)", "비고"])
        for cell in ws[ws.max_row]:
            cell.font, cell.fill = Font(bold=True), PatternFill("solid", fgColor="EFE6D8")
        for r in sec["rows"]:
            if not (r["budget"] or r["actual"] or r["note"]):
                continue
            ws.append(["　" * r["depth"] + r["name"], r["budget"], r["actual"], _pct(r["budget"], r["actual"]), r["note"]])
            if r["level"] == 1:
                for cell in ws[ws.max_row]:
                    cell.font = Font(bold=True)
        if sec["unclassified"]:
            ws.append(["미분류", None, sec["unclassified"], None, "예산과목이 없는 거래"])
        ws.append([f"{kind} 합계", sec["budget"], sec["actual"], _pct(sec["budget"], sec["actual"]), ""])
        for cell in ws[ws.max_row]:
            cell.font = Font(bold=True)
    ws.append([])
    ws.append(["차인 (수입 − 지출)", data["sections"]["수입"]["budget"] - data["sections"]["지출"]["budget"],
               data["sections"]["수입"]["actual"] - data["sections"]["지출"]["actual"]])
    ws.column_dimensions["A"].width = 30
    for col in "BC":
        ws.column_dimensions[col].width = 16
    ws.column_dimensions["E"].width = 40
    for row in ws.iter_rows(min_row=4, min_col=2, max_col=3):
        for cell in row:
            cell.number_format = "#,##0"
            cell.alignment = Alignment(horizontal="right")
    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return send_file(buf, as_attachment=True, download_name=f"결산표_{label}_{start:%Y%m%d}-{end:%Y%m%d}.xlsx",
                     mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
