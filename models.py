"""DB 테이블 정의와 초기화. SQLite 파일은 data/app.db 에 저장됩니다."""
import os
import sqlite3
from contextlib import contextmanager

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "data", "app.db")

SCHEMA = """
-- ===== 공통 기반 =====
CREATE TABLE IF NOT EXISTS files (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    original_name TEXT NOT NULL,
    stored_path   TEXT NOT NULL,
    file_type     TEXT,                 -- pdf / doc / img
    target_type   TEXT,                 -- meeting, event, document ...
    target_id     INTEGER,
    uploaded_at   TEXT DEFAULT CURRENT_TIMESTAMP,
    note          TEXT                  -- 변경 메모 (기타서류의 새 버전 등)
);
CREATE INDEX IF NOT EXISTS idx_files_target ON files(target_type, target_id);

CREATE TABLE IF NOT EXISTS file_versions (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    file_id     INTEGER NOT NULL REFERENCES files(id) ON DELETE CASCADE,
    version_no  INTEGER NOT NULL,
    stored_path TEXT NOT NULL,
    note        TEXT,
    uploaded_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS tags (
    id       INTEGER PRIMARY KEY AUTOINCREMENT,
    name     TEXT NOT NULL,             -- 같은 이름은 하나의 태그 (idx_tags_name 으로 보장)
    category TEXT NOT NULL,             -- 문서종류 / 담당자 / 연도 ... (정리·색상용 묶음)
    color    INTEGER,                   -- 이 태그만의 색(0~11). 비우면 카테고리 색
    UNIQUE(name, category)
);

CREATE TABLE IF NOT EXISTS tag_categories (    -- 카테고리별 기본 색(0~11)
    name  TEXT PRIMARY KEY,
    color INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS tag_links (
    tag_id      INTEGER NOT NULL REFERENCES tags(id) ON DELETE CASCADE,
    target_type TEXT NOT NULL,
    target_id   INTEGER NOT NULL,
    PRIMARY KEY (tag_id, target_type, target_id)
);

CREATE TABLE IF NOT EXISTS reviews (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    target_type TEXT NOT NULL,
    target_id   INTEGER NOT NULL,
    reviewed_at TEXT,
    reviewer    TEXT,
    comment     TEXT
);

CREATE TABLE IF NOT EXISTS settings (        -- 앱 설정 (잠금 비밀번호 등)
    key   TEXT PRIMARY KEY,
    value TEXT
);

-- ===== 예산·결산 =====
CREATE TABLE IF NOT EXISTS budget_categories (  -- 예산과목: 관(1) > 항(2) > 목(3)
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    parent_id  INTEGER REFERENCES budget_categories(id),
    level      INTEGER NOT NULL,                 -- 1 관 / 2 항 / 3 목
    kind       TEXT NOT NULL,                    -- 수입 / 지출
    name       TEXT NOT NULL,
    sort_order INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS bank_transactions (   -- 은행 엑셀에서 가져온 거래
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    account_id      INTEGER NOT NULL,            -- 거래가 일어난 통장
    occurred_at     TEXT NOT NULL,               -- YYYY-MM-DDTHH:MM:SS
    counterparty    TEXT,                        -- 보낸분/받는분
    memo_own        TEXT,                        -- 내 통장 표시
    memo            TEXT,
    summary         TEXT,                        -- 적요
    branch          TEXT,
    deposit         INTEGER NOT NULL DEFAULT 0,
    withdrawal      INTEGER NOT NULL DEFAULT 0,
    balance         INTEGER,
    fund_account_id INTEGER,                     -- 결산에서 속하는 회계(통장). 비우면 account_id
    category_id     INTEGER REFERENCES budget_categories(id) ON DELETE SET NULL,
    category_source TEXT,                        -- manual / rule
    is_transfer     INTEGER NOT NULL DEFAULT 0,  -- 통장 간 이체(수입·지출 합계에서 제외)
    note            TEXT,
    dedupe_key      TEXT NOT NULL,
    imported_at     TEXT
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_tx_dedupe ON bank_transactions(dedupe_key);
CREATE INDEX IF NOT EXISTS idx_tx_account_date ON bank_transactions(account_id, occurred_at);

CREATE TABLE IF NOT EXISTS bank_imports (        -- 엑셀 올린 직후 확인 화면용 임시 보관 (확정·취소하면 삭제)
    token      TEXT PRIMARY KEY,
    created_at TEXT NOT NULL,
    payload    TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS category_rules (      -- 자동 분류 규칙: 내용에 키워드가 있으면 예산과목 지정
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    field       TEXT NOT NULL,                   -- memo_own / summary / counterparty
    keyword     TEXT NOT NULL,
    category_id INTEGER NOT NULL REFERENCES budget_categories(id) ON DELETE CASCADE,
    UNIQUE(field, keyword)
);

CREATE TABLE IF NOT EXISTS vouchers (            -- 지출결의서: 거래 여러 건을 묶는 결의서 한 장
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    voucher_no  TEXT,                            -- 결의번호 (예: 2026-003)
    title       TEXT NOT NULL,                   -- 적요
    issued_on   TEXT,                            -- 발의일 YYYY-MM-DD
    paid_on     TEXT,                            -- 지출일 YYYY-MM-DD
    receiver    TEXT,                            -- 영수자
    method      TEXT NOT NULL DEFAULT '이체',    -- 지출방법: 이체 / 카드 / 현금
    category_id INTEGER REFERENCES budget_categories(id) ON DELETE SET NULL,
    note        TEXT,                            -- 참고사항
    created_at  TEXT
);
CREATE TABLE IF NOT EXISTS voucher_transactions (  -- 결의서에 묶인 거래 (거래 한 건은 결의서 하나에만)
    voucher_id     INTEGER NOT NULL REFERENCES vouchers(id) ON DELETE CASCADE,
    transaction_id INTEGER NOT NULL UNIQUE REFERENCES bank_transactions(id) ON DELETE CASCADE,
    PRIMARY KEY (voucher_id, transaction_id)
);

CREATE TABLE IF NOT EXISTS budget_amounts (      -- 결산표의 예산: 해마다·회계(통장)별·예산과목별
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    year        INTEGER NOT NULL,
    fund_account_id INTEGER NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
    category_id INTEGER NOT NULL REFERENCES budget_categories(id) ON DELETE CASCADE,
    amount      INTEGER NOT NULL DEFAULT 0,
    note        TEXT,                            -- 결산표 비고
    UNIQUE(year, fund_account_id, category_id)
);

-- ===== 메뉴별 =====
CREATE TABLE IF NOT EXISTS officers (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    kind       TEXT NOT NULL DEFAULT '임원',   -- 임원 / 평의원
    position   TEXT NOT NULL,                  -- 직위
    name       TEXT NOT NULL,                  -- 성명
    workplace  TEXT,                           -- 근무처
    email      TEXT,
    sort_order INTEGER NOT NULL DEFAULT 0      -- 목록 표시 순서
);

CREATE TABLE IF NOT EXISTS presidents (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    generation     INTEGER NOT NULL,           -- 대수 (1대, 2대 ...)
    period         TEXT,                       -- 재임기간
    president      TEXT NOT NULL,              -- 회장
    vice_president TEXT                        -- 부회장
);

CREATE TABLE IF NOT EXISTS meetings (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    year          INTEGER NOT NULL,
    held_at       TEXT,                 -- 개최일시
    place         TEXT,
    title         TEXT NOT NULL,        -- 회의명
    total_members INTEGER,              -- 총인원
    attendees     INTEGER,              -- 참석수
    agenda        TEXT                  -- 주요의결안건
);

CREATE TABLE IF NOT EXISTS meeting_attendance (
    meeting_id   INTEGER NOT NULL REFERENCES meetings(id) ON DELETE CASCADE,
    officer_id   INTEGER REFERENCES officers(id) ON DELETE SET NULL,  -- 삭제돼도 기록은 남음
    officer_name TEXT NOT NULL,        -- 회의 당시 성명
    position     TEXT,                 -- 회의 당시 직위
    kind         TEXT NOT NULL DEFAULT '임원',   -- 임원 / 평의원
    present      INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_attendance_meeting ON meeting_attendance(meeting_id);

CREATE TABLE IF NOT EXISTS events (            -- 행사 (보수교육/학술대회/워크숍)
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    kind       TEXT NOT NULL,                  -- 보수교육 / 학술대회 / 워크숍
    name       TEXT,                           -- 행사명 (선택)
    held_on    TEXT NOT NULL,                  -- 일자 YYYY-MM-DD
    start_time TEXT,
    end_time   TEXT,
    place      TEXT,
    attendees  INTEGER
);

CREATE TABLE IF NOT EXISTS event_programs (    -- 행사의 시간별 프로그램(강의)
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id    INTEGER NOT NULL REFERENCES events(id) ON DELETE CASCADE,
    start_time  TEXT,
    end_time    TEXT,
    title       TEXT NOT NULL,                 -- 강의명
    speaker     TEXT,                          -- 강연자
    affiliation TEXT                           -- 소속
);
CREATE INDEX IF NOT EXISTS idx_programs_event ON event_programs(event_id);

CREATE TABLE IF NOT EXISTS budget_periods (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    name       TEXT NOT NULL,           -- 예: 2025년 결산
    start_date TEXT,
    end_date   TEXT
);

CREATE TABLE IF NOT EXISTS budget_items (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    period_id INTEGER NOT NULL REFERENCES budget_periods(id) ON DELETE CASCADE,
    flow      TEXT NOT NULL,            -- 수입 / 비용
    subject   TEXT NOT NULL,            -- 예산과목
    budget    INTEGER DEFAULT 0,
    actual    INTEGER DEFAULT 0,        -- 지출(비용) 또는 수입 실적
    note      TEXT
);

CREATE TABLE IF NOT EXISTS accounts (          -- 통장 (경상비 / 보수교육비)
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    alias        TEXT NOT NULL DEFAULT '',     -- 별칭
    bank         TEXT,
    number       TEXT,                         -- 가려서 입력한 계좌번호 (전체 번호는 저장하지 않음)
    last4        TEXT,                         -- 끝 4자리 (엑셀 가져오기 때 통장 인식용)
    product_name TEXT,                         -- 계좌명
    purpose      TEXT,
    memo         TEXT
);

CREATE TABLE IF NOT EXISTS account_openings (  -- 통장별 전기 이월금 (회기년도별)
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    account_id INTEGER NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
    year       INTEGER NOT NULL,
    amount     INTEGER NOT NULL DEFAULT 0,
    note       TEXT,
    UNIQUE(account_id, year)
);

CREATE TABLE IF NOT EXISTS cards (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    account_id INTEGER REFERENCES accounts(id) ON DELETE SET NULL,   -- 연결된 통장
    name       TEXT NOT NULL,                  -- 카드명(카드사)
    number     TEXT,                           -- 가려서 입력한 카드번호
    holder     TEXT,                           -- 소지자
    memo       TEXT
);

CREATE TABLE IF NOT EXISTS donations (         -- 찬조금(광고비 등) 내역
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id   INTEGER,                        -- 연결된 행사 (없으면 '행사 외 찬조')
    kind       TEXT NOT NULL DEFAULT '광고비', -- 광고비 / 찬조금 / 지원금 / 기타
    donated_on TEXT,                           -- 받은 일자
    donor      TEXT,                           -- 찬조자(회사)
    amount     INTEGER,
    usage      TEXT,                           -- 사용내역
    note       TEXT                            -- 비고
);

CREATE TABLE IF NOT EXISTS plans (
    id      INTEGER PRIMARY KEY AUTOINCREMENT,
    kind    TEXT NOT NULL,              -- 실적 / 미진
    name    TEXT NOT NULL,              -- 사업목표 또는 사업명
    result  TEXT,                       -- 사업실적 또는 미진이유
    note    TEXT,
    year    INTEGER
);

CREATE TABLE IF NOT EXISTS documents (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    title       TEXT NOT NULL,
    description TEXT,
    is_active   INTEGER DEFAULT 1,
    created_at  TEXT DEFAULT CURRENT_TIMESTAMP,
    updated_at  TEXT DEFAULT CURRENT_TIMESTAMP
);
"""

DEFAULT_TAGS = {
    "문서종류": ["회의록", "규정", "학회", "워크숍", "자산", "명부"],
    "담당자": ["학회장", "부학회장", "총무이사", "학술이사", "면역전문병리사", "교육", "보수교육"],
}


DB_VERSION = 13  # 1: 최초 구성, 2: 임원 명부 개편 + 회장단 + '명부' 태그, 3: 출석 기록에 회의 당시 성명·직위 저장, 4: 행사/프로그램 2단 구조, 5: 통장·카드 구조, 6: 파일 변경 메모(files.note), 7: 같은 이름 태그 합치기 + 태그·카테고리 색, 8: 찬조금 행사 연결, 9: 예산과목·은행 거래·자동 분류 규칙, 10: 기타서류 연도 태그를 직접 단 태그로 바꿈 + 공문수신·공문발신 태그, 11: 지출결의서, 12: 결산표 예산 + 사업 순서, 13: 서류 기안일자


def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


@contextmanager
def db():
    """with db() as conn: ... 블록이 끝나면 자동 저장(commit)하고 연결을 닫습니다."""
    conn = get_db()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _migrate_officers(conn):
    """예전 officers 테이블(임기 칸 포함)을 새 구조로 바꿉니다."""
    cols = [r["name"] for r in conn.execute("PRAGMA table_info(officers)")]
    if not cols or "workplace" in cols:
        return
    if conn.execute("SELECT COUNT(*) FROM officers").fetchone()[0] == 0:
        conn.execute("DROP TABLE officers")  # 비어 있으면 새로 만듭니다
    else:  # 데이터가 있으면 칸만 추가합니다
        conn.execute("ALTER TABLE officers ADD COLUMN workplace TEXT")
        conn.execute("ALTER TABLE officers ADD COLUMN email TEXT")
        conn.execute("ALTER TABLE officers ADD COLUMN sort_order INTEGER NOT NULL DEFAULT 0")


def _seed_tags(conn):
    for category, names in DEFAULT_TAGS.items():
        conn.executemany(
            "INSERT OR IGNORE INTO tags(name, category) VALUES (?, ?)",
            [(n, category) for n in names],
        )


def _stash_old_attendance(conn):
    """예전 구조의 meeting_attendance 가 있으면 이름을 바꿔 두고 True 를 돌려줍니다."""
    cols = [r["name"] for r in conn.execute("PRAGMA table_info(meeting_attendance)")]
    if cols and "officer_name" not in cols:
        conn.execute("ALTER TABLE meeting_attendance RENAME TO meeting_attendance_old")
        return True
    return False


def _restore_old_attendance(conn):
    conn.execute(
        "INSERT INTO meeting_attendance(meeting_id, officer_id, officer_name, position, kind, present) "
        "SELECT a.meeting_id, a.officer_id, COALESCE(o.name, '(삭제됨)'), o.position, "
        "COALESCE(o.kind, '임원'), a.present "
        "FROM meeting_attendance_old a LEFT JOIN officers o ON o.id = a.officer_id")
    conn.execute("DROP TABLE meeting_attendance_old")


def _migrate_accounts(conn):
    """예전 accounts 표(칸이 달랐던 것)를 새 구조로 바꿉니다. 비어 있으면 새로 만들고, 자료가 있으면 칸만 추가합니다."""
    cols = [r["name"] for r in conn.execute("PRAGMA table_info(accounts)")]
    if not cols or "alias" in cols:
        return
    if conn.execute("SELECT COUNT(*) FROM accounts").fetchone()[0] == 0:
        conn.execute("DROP TABLE accounts")
    else:
        for col in ("alias TEXT NOT NULL DEFAULT ''", "bank TEXT", "number TEXT", "last4 TEXT", "product_name TEXT"):
            conn.execute(f"ALTER TABLE accounts ADD COLUMN {col}")


def _ensure_columns(conn):
    """이미 만들어진 DB에 새 칸이 필요하면 자료를 지우지 않고 칸만 추가합니다."""
    cols = [r["name"] for r in conn.execute("PRAGMA table_info(files)")]
    if cols and "note" not in cols:
        conn.execute("ALTER TABLE files ADD COLUMN note TEXT")
    cols = [r["name"] for r in conn.execute("PRAGMA table_info(donations)")]
    if cols and "event_id" not in cols:
        conn.execute("ALTER TABLE donations ADD COLUMN event_id INTEGER")
    if cols and "kind" not in cols:
        conn.execute("ALTER TABLE donations ADD COLUMN kind TEXT NOT NULL DEFAULT '광고비'")
    cols = [r["name"] for r in conn.execute("PRAGMA table_info(documents)")]
    if cols and "drafted_on" not in cols:
        conn.execute("ALTER TABLE documents ADD COLUMN drafted_on TEXT")      # 공문의 기안일자 (YYYY-MM-DD)
    cols = [r["name"] for r in conn.execute("PRAGMA table_info(plans)")]
    if cols and "sort_order" not in cols:
        conn.execute("ALTER TABLE plans ADD COLUMN sort_order INTEGER")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_donations_event ON donations(event_id)")   # 칸이 생긴 뒤에 만듭니다


# 처음 한 번 넣는 예산과목 (올려주신 '관항목(면역)' 시트 + 결의서에 쓰이는 운영비>회의비 + 수입 항목). 앱에서 고칠 수 있습니다.
SEED_BUDGET = [
    ("지출", "학회운영비", [("경상비", []), ("복리후생비", ["경조사비"]), ("출장비", []), ("사업운영비", []),
                      ("학술진흥정책비", []), ("운영비", ["회의비"])]),
    ("지출", "학술운영비", [("분과학술대회운영비", []), ("종합학술대회운영비", []), ("학술대회사업비", []),
                      ("분과학회협의회비", [])]),
    ("수입", "학술수익금", [("교부금", [])]),
    ("수입", "이자수익금", []),
    ("수입", "회비", []), ("수입", "보수교육 참가비", []), ("수입", "학회등록비", []),
    ("수입", "찬조금(지원금)", []), ("수입", "광고비", []), ("수입", "기타수입", []),
]
SEED_RULES = [("summary", "결산이자", "이자수익금")]


def _seed_budget(conn):
    if conn.execute("SELECT COUNT(*) FROM budget_categories").fetchone()[0]:
        return
    order = 0
    for kind, gwan, hangs in SEED_BUDGET:
        order += 1
        gid = conn.execute("INSERT INTO budget_categories(parent_id, level, kind, name, sort_order) VALUES (NULL, 1, ?, ?, ?)",
                           (kind, gwan, order)).lastrowid
        for h_order, entry in enumerate(hangs, 1):
            hang, moks = entry
            hid = conn.execute("INSERT INTO budget_categories(parent_id, level, kind, name, sort_order) VALUES (?, 2, ?, ?, ?)",
                               (gid, kind, hang, h_order)).lastrowid
            for m_order, mok in enumerate(moks, 1):
                conn.execute("INSERT INTO budget_categories(parent_id, level, kind, name, sort_order) VALUES (?, 3, ?, ?, ?)",
                             (hid, kind, mok, m_order))
    for field, keyword, name in SEED_RULES:
        row = conn.execute("SELECT id FROM budget_categories WHERE name = ?", (name,)).fetchone()
        if row:
            conn.execute("INSERT OR IGNORE INTO category_rules(field, keyword, category_id) VALUES (?, ?, ?)",
                         (field, keyword, row["id"]))


def _migrate_tags(conn):
    """같은 이름의 태그(카테고리만 다른 경우)를 하나로 합치고, 태그 색 칸을 추가합니다."""
    cols = [r["name"] for r in conn.execute("PRAGMA table_info(tags)")]
    if "color" not in cols:
        conn.execute("ALTER TABLE tags ADD COLUMN color INTEGER")
    for d in conn.execute("SELECT name FROM tags GROUP BY name HAVING COUNT(*) > 1").fetchall():
        rows = conn.execute(
            "SELECT t.id, (SELECT COUNT(*) FROM tag_links l WHERE l.tag_id = t.id) AS n "
            "FROM tags t WHERE t.name = ? ORDER BY n DESC, t.id", (d["name"],)).fetchall()
        keep = rows[0]["id"]          # 가장 많이 쓰인 태그를 남깁니다
        for r in rows[1:]:
            conn.execute("INSERT OR IGNORE INTO tag_links(tag_id, target_type, target_id) "
                         "SELECT ?, target_type, target_id FROM tag_links WHERE tag_id = ?", (keep, r["id"]))
            conn.execute("DELETE FROM tags WHERE id = ?", (r["id"],))
    conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_tags_name ON tags(name)")


def _migrate_doc_year_tags(conn):
    """예전에는 기타서류의 연도 태그가 올린 해로 자동 계산됐습니다. 지금 보이는 모습 그대로 두되
    고치고 뺄 수 있도록, 연도 태그가 없는 서류에 올린 해의 태그를 직접 붙여 줍니다. 공문 태그도 만들어 둡니다."""
    for name in ("공문수신", "공문발신"):
        conn.execute("INSERT OR IGNORE INTO tags(name, category) VALUES (?, '문서종류')", (name,))
    year_tags = {}
    for d in conn.execute("SELECT id, created_at FROM documents WHERE is_active = 1").fetchall():
        has_year = conn.execute(
            "SELECT 1 FROM tag_links l JOIN tags t ON t.id = l.tag_id "
            "WHERE l.target_type = 'document' AND l.target_id = ? AND t.name GLOB '[0-9][0-9][0-9][0-9]'",
            (d["id"],)).fetchone()
        year = (d["created_at"] or "")[:4]
        if has_year or not (len(year) == 4 and year.isdigit()):
            continue
        if year not in year_tags:
            row = conn.execute("SELECT id FROM tags WHERE name = ?", (year,)).fetchone()
            year_tags[year] = row["id"] if row else conn.execute(
                "INSERT INTO tags(name, category) VALUES (?, '연도')", (year,)).lastrowid
        conn.execute("INSERT OR IGNORE INTO tag_links(tag_id, target_type, target_id) VALUES (?, 'document', ?)",
                     (year_tags[year], d["id"]))


def _stash_old_events(conn):
    """예전(강의 한 줄 = 한 행) 구조의 events 가 있으면 이름을 바꿔 두고 그 칸 목록을 돌려줍니다."""
    cols = [r["name"] for r in conn.execute("PRAGMA table_info(events)")]
    if cols and "speaker" in cols:
        conn.execute("ALTER TABLE events RENAME TO events_old")
        return cols
    return None


def _restore_old_events(conn, cols):
    """구분·일자·장소가 같은 강의들을 한 행사로 묶고, 각 강의를 프로그램 줄로 옮깁니다.
    프로그램 id 는 예전 강의 id 를 그대로 써서, 첨부파일이 같은 줄에 계속 붙어 있게 합니다."""
    start = "held_time" if "held_time" in cols else "NULL"
    end = "end_time" if "end_time" in cols else "NULL"
    old = conn.execute(
        f"SELECT id, kind, held_on, {start} AS st, {end} AS en, place, title, speaker, attendees "
        f"FROM events_old ORDER BY held_on, COALESCE({start}, ''), id").fetchall()

    groups = {}
    for r in old:
        key = (r["kind"] or "보수교육", r["held_on"] or "", (r["place"] or "").strip())
        groups.setdefault(key, []).append(r)

    for (kind, held_on, place), rows in groups.items():
        starts = [r["st"] for r in rows if r["st"]]
        ends = [r["en"] for r in rows if r["en"]]
        attendees = [r["attendees"] for r in rows if r["attendees"] is not None]
        cur = conn.execute(
            "INSERT INTO events(kind, name, held_on, start_time, end_time, place, attendees) "
            "VALUES (?, NULL, ?, ?, ?, ?, ?)",
            (kind, held_on, min(starts) if starts else None, max(ends) if ends else None,
             place, max(attendees) if attendees else None))
        for r in rows:
            conn.execute(
                "INSERT INTO event_programs(id, event_id, start_time, end_time, title, speaker) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (r["id"], cur.lastrowid, r["st"], r["en"], r["title"], r["speaker"]))

    # 예전 첨부파일은 같은 강의 줄의 '발표자료'로 이동
    conn.execute("UPDATE files SET target_type = 'event_material' WHERE target_type = 'event_doc'")
    conn.execute("DROP TABLE events_old")


def init_db():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    with db() as conn:
        version = conn.execute("PRAGMA user_version").fetchone()[0]
        if version < DB_VERSION:
            _migrate_officers(conn)
            _migrate_accounts(conn)
        old_attendance = _stash_old_attendance(conn) if version < 3 else False
        old_events = _stash_old_events(conn) if version < 4 else None
        conn.executescript(SCHEMA)
        _ensure_columns(conn)
        _migrate_tags(conn)
        if old_attendance:
            _restore_old_attendance(conn)
        if old_events:
            _restore_old_events(conn, old_events)
        if version < 2:
            _seed_tags(conn)
        if version < 9:
            _seed_budget(conn)
        if version < 10:
            _migrate_doc_year_tags(conn)
        if version < DB_VERSION:
            conn.execute(f"PRAGMA user_version = {DB_VERSION}")
