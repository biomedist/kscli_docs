"""국민은행 거래내역서(.xls / .xlsx) 읽기.
- 파일 맨 위 안내 줄(계좌번호, 조회기간, 출금합계, 입금합계, 총잔액)과 거래 표를 함께 읽습니다.
- 계좌번호는 끝 4자리와 별칭(예: (경상비))만 꺼내 쓰고, 전체 번호·파일 이름은 저장하지 않습니다.
- 읽은 뒤 합계 일치 여부와 잔액이 이어지는지 확인해서 빠진 거래가 없는지 검증합니다.
"""
import io
import re
from datetime import datetime

# 표 머리글(공백 제거) → 내부 이름
COLUMNS = {
    "거래일시": "when", "보낸분/받는분": "counterparty", "출금액(원)": "withdrawal", "출금액": "withdrawal",
    "입금액(원)": "deposit", "입금액": "deposit", "잔액(원)": "balance", "잔액": "balance",
    "내통장표시": "memo_own", "메모": "memo", "적요": "summary", "처리점": "branch",
}
DATE_FORMATS = ("%Y.%m.%d %H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y/%m/%d %H:%M:%S",
                "%Y.%m.%d %H:%M", "%Y-%m-%d %H:%M", "%Y.%m.%d", "%Y-%m-%d")


class ImportProblem(Exception):
    """사용자에게 그대로 보여줄 수 있는 안내 문장을 담습니다."""


def _read_rows(data, filename):
    ext = filename.lower().rsplit(".", 1)[-1] if "." in filename else ""
    if ext == "xls":
        try:
            import xlrd
        except ImportError:
            raise ImportProblem("엑셀(.xls)을 읽는 프로그램이 설치되어 있지 않습니다. "
                                "서버 PC에서 'pip install xlrd openpyxl'을 실행한 뒤 앱을 다시 시작해 주세요.")
        try:
            sheet = xlrd.open_workbook(file_contents=data).sheet_by_index(0)
        except Exception:
            raise ImportProblem("엑셀 파일을 읽지 못했습니다. 은행에서 내려받은 원본 파일인지 확인해 주세요.")
        return [[sheet.cell_value(r, c) for c in range(sheet.ncols)] for r in range(sheet.nrows)]
    if ext == "xlsx":
        try:
            from openpyxl import load_workbook
        except ImportError:
            raise ImportProblem("엑셀(.xlsx)을 읽는 프로그램이 설치되어 있지 않습니다. "
                                "서버 PC에서 'pip install xlrd openpyxl'을 실행한 뒤 앱을 다시 시작해 주세요.")
        try:
            sheet = load_workbook(io.BytesIO(data), data_only=True, read_only=True).worksheets[0]
            return [list(row) for row in sheet.iter_rows(values_only=True)]
        except Exception:
            raise ImportProblem("엑셀 파일을 읽지 못했습니다. 은행에서 내려받은 원본 파일인지 확인해 주세요.")
    raise ImportProblem("엑셀 파일(.xls, .xlsx)만 올릴 수 있습니다.")


def _to_int(value):
    if value in (None, ""):
        return 0
    if isinstance(value, (int, float)):
        return int(round(value))
    cleaned = str(value).replace(",", "").replace("원", "").strip()
    try:
        return int(float(cleaned))
    except ValueError:
        return 0


def _to_datetime(value):
    if isinstance(value, datetime):
        return value
    text = str(value or "").strip()
    for fmt in DATE_FORMATS:
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue
    return None


def _text(value):
    return "" if value is None else str(value).strip()


def _mask_numbers(text):
    """9자리 이상 숫자(계좌번호 등)는 끝 4자리만 남기고 가립니다. 예: #08117518439014 → #**********9014"""
    return re.sub(r"\d{9,}", lambda m: "*" * (len(m.group()) - 4) + m.group()[-4:], text)


def last4_and_alias(account_text):
    """'0484XX-XX-006718(경상비)' → ('6718', '경상비'). 전체 번호는 돌려주지 않습니다."""
    alias_match = re.search(r"\(([^)]*)\)\s*$", account_text or "")
    alias = alias_match.group(1).strip() if alias_match else ""
    number_part = (account_text or "").split("(")[0]
    runs = re.findall(r"\d+", number_part)
    return (runs[-1][-4:] if runs else ""), alias


def _money_header(header, key):
    value = header.get(key, "")
    digits = re.sub(r"[^\d]", "", value)
    return int(digits) if digits else None


def parse_statement(data, filename):
    """거래내역서를 읽어 {'info': 안내 줄 정보, 'rows': 거래 목록, 'checks': 검증 결과} 로 돌려줍니다."""
    rows = _read_rows(data, filename)

    # 1) 표 머리글 줄 찾기
    header_index, column_of = None, {}
    for i, row in enumerate(rows[:40]):
        names = {re.sub(r"\s+", "", _text(c)): idx for idx, c in enumerate(row)}
        if "거래일시" in names and ("출금액(원)" in names or "출금액" in names):
            header_index = i
            column_of = {COLUMNS[n]: idx for n, idx in names.items() if n in COLUMNS}
            break
    if header_index is None:
        raise ImportProblem("국민은행 거래내역서 형식이 아닙니다. ('거래일시', '출금액', '입금액' 칸을 찾지 못했습니다.)")

    # 2) 위쪽 안내 줄 ("항목 : 값")
    header = {}
    for row in rows[:header_index]:
        for cell in row:
            text = _text(cell)
            if ":" in text or "：" in text:
                key, _, value = text.replace("：", ":").partition(":")
                header.setdefault(key.strip(), value.strip())
    last4, alias = last4_and_alias(header.get("계좌번호", ""))

    # 3) 거래 읽기 (파일에 나온 순서 그대로)
    def cell(row, name):
        idx = column_of.get(name)
        return row[idx] if idx is not None and idx < len(row) else None

    parsed = []
    for row in rows[header_index + 1:]:
        when = _to_datetime(cell(row, "when"))
        if when is None:
            continue
        parsed.append({
            "occurred_at": when.strftime("%Y-%m-%dT%H:%M:%S"),
            "counterparty": _mask_numbers(_text(cell(row, "counterparty"))), "memo_own": _mask_numbers(_text(cell(row, "memo_own"))),
            "memo": _mask_numbers(_text(cell(row, "memo"))), "summary": _text(cell(row, "summary")), "branch": _text(cell(row, "branch")),
            "withdrawal": _to_int(cell(row, "withdrawal")), "deposit": _to_int(cell(row, "deposit")),
            "balance": _to_int(cell(row, "balance")) if cell(row, "balance") not in (None, "") else None,
        })
    if not parsed:
        raise ImportProblem("거래 내역을 찾지 못했습니다. 조회 기간에 거래가 없는 파일일 수 있습니다.")

    return {"info": {"last4": last4, "alias": alias, "period": header.get("조회기간", ""),
                     "header_withdrawal": _money_header(header, "출금합계"),
                     "header_deposit": _money_header(header, "입금합계"),
                     "header_balance": _money_header(header, "총잔액")},
            "rows": parsed, "checks": verify(parsed, header)}


def verify(rows, header):
    """합계·잔액 연속성 검증. 빠진 거래가 있으면 어디서 끊기는지 알려 줍니다."""
    total_withdrawal = sum(r["withdrawal"] for r in rows)
    total_deposit = sum(r["deposit"] for r in rows)
    expected_w, expected_d = _money_header(header, "출금합계"), _money_header(header, "입금합계")

    # 잔액 연속성: 파일이 최신순인지 과거순인지에 따라 다른 식으로 확인
    newest_first = rows[0]["occurred_at"] >= rows[-1]["occurred_at"]
    breaks = 0
    for a, b in zip(rows, rows[1:]):
        if a["balance"] is None or b["balance"] is None:
            continue
        if newest_first:    # 아래 줄이 더 이전 거래: 이전 잔액 = 위 잔액 + 위 출금 - 위 입금
            ok = b["balance"] == a["balance"] + a["withdrawal"] - a["deposit"]
        else:               # 아래 줄이 더 나중 거래: 아래 잔액 = 위 잔액 - 아래 출금 + 아래 입금
            ok = b["balance"] == a["balance"] - b["withdrawal"] + b["deposit"]
        if not ok:
            breaks += 1
    latest = rows[0] if newest_first else rows[-1]
    return {
        "count": len(rows), "total_withdrawal": total_withdrawal, "total_deposit": total_deposit,
        "withdrawal_ok": expected_w is None or expected_w == total_withdrawal,
        "deposit_ok": expected_d is None or expected_d == total_deposit,
        "chain_breaks": breaks,
        "balance_ok": (_money_header(header, "총잔액") is None or latest["balance"] is None
                       or latest["balance"] == _money_header(header, "총잔액")),
        "first_date": min(r["occurred_at"] for r in rows)[:10], "last_date": max(r["occurred_at"] for r in rows)[:10],
    }
