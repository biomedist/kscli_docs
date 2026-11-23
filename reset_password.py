"""금액 자료 잠금 비밀번호 초기화 (서버 PC에서 실행)
사용법:  python reset_password.py
실행하면 비밀번호가 지워지고, 다음에 금액 화면을 열 때 새 비밀번호를 정하게 됩니다.
"""
from models import db, init_db

init_db()
with db() as conn:
    conn.execute("DELETE FROM settings WHERE key = 'money_password_hash'")
    row = conn.execute("SELECT value FROM settings WHERE key = 'lock_epoch'").fetchone()
    conn.execute("INSERT INTO settings(key, value) VALUES ('lock_epoch', ?) "
                 "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                 (str(int(row['value']) + 1 if row else 1),))
print("비밀번호를 초기화했습니다. 다음에 금액 화면(예산·결산, 통장·카드, 찬조금)을 열 때 새 비밀번호를 정하세요.")
