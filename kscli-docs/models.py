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
    uploaded_at   TEXT DEFAULT CURRENT_TIMESTAMP
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
    name     TEXT NOT NULL,
    category TEXT NOT NULL,             -- 문서종류 / 담당자 / 연도
    UNIQUE(name, category)
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

CREATE TABLE IF NOT EXISTS events (
    id       INTEGER PRIMARY KEY AUTOINCREMENT,
    kind     TEXT,                      -- 보수교육 / 학술대회 / 워크숍
    held_on  TEXT,
    held_time TEXT,
    place    TEXT,
    title    TEXT NOT NULL,             -- 강의명
    speaker  TEXT,
    attendees INTEGER
);

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

CREATE TABLE IF NOT EXISTS accounts (
    id     INTEGER PRIMARY KEY AUTOINCREMENT,
    kind   TEXT,                        -- 통장 / 카드
    issuer TEXT,                        -- 은행·카드사
    purpose TEXT,
    memo   TEXT
);

CREATE TABLE IF NOT EXISTS donations (
    id       INTEGER PRIMARY KEY AUTOINCREMENT,
    donated_on TEXT,
    donor    TEXT,                      -- 찬조자(회사)
    amount   INTEGER,
    usage    TEXT,                      -- 사용내역
    note     TEXT
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


DB_VERSION = 3  # 1: 최초 구성, 2: 임원 명부 개편 + 회장단 + '명부' 태그, 3: 출석 기록에 회의 당시 성명·직위 저장


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


def init_db():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    with db() as conn:
        version = conn.execute("PRAGMA user_version").fetchone()[0]
        if version < DB_VERSION:
            _migrate_officers(conn)
        old_attendance = _stash_old_attendance(conn) if version < 3 else False
        conn.executescript(SCHEMA)
        if old_attendance:
            _restore_old_attendance(conn)
        if version < DB_VERSION:
            _seed_tags(conn)
            conn.execute(f"PRAGMA user_version = {DB_VERSION}")
