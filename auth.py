"""금액 자료 잠금 기능 (예산·결산, 예금통장·카드, 찬조금).
- 공용 비밀번호 1개를 처음 한 번 정하고, 암호화(해시)해서 저장합니다.
- 금액 화면을 30분간 쓰지 않으면 자동으로 잠깁니다.
- 잠금은 화면만 가리는 것이 아니라 서버가 검사합니다. (주소를 직접 입력해도 열리지 않음)
"""
import os
import secrets
import time

from flask import Blueprint, abort, flash, redirect, render_template, request, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash

from models import BASE_DIR, db

bp = Blueprint("auth", __name__)

IDLE_SECONDS = 30 * 60                 # 금액 화면을 쓰지 않으면 자동 잠금
MIN_LENGTH = 6
MAX_FAILS, LOCKOUT_SECONDS = 5, 5 * 60  # 5번 틀리면 5분간 입력 불가

# 잠글 화면(주소 앞부분)과 잠글 첨부파일 종류(앞부분). 새 금액 화면은 여기에 맞춰 만듭니다.
PROTECTED_PATHS = ("/audit/budget", "/audit/accounts", "/audit/donations")
PROTECTED_FILE_PREFIXES = ("budget", "account", "card", "voucher", "donation")

_fails = {}   # 접속 주소별 {"count": 틀린 횟수, "until": 입력 가능해지는 시각}


# ---------- 비밀 키 (로그인 상태 서명용) ----------
def get_secret_key():
    """코드에 적어 두지 않고, 처음 실행할 때 무작위로 만들어 data/secret.key 에 보관합니다."""
    env = os.environ.get("KSCLI_SECRET_KEY")
    if env:
        return env
    path = os.path.join(BASE_DIR, "data", "secret.key")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    if not os.path.exists(path):
        with open(path, "w") as f:
            f.write(secrets.token_hex(32))
        try:
            os.chmod(path, 0o600)
        except OSError:
            pass
    with open(path) as f:
        return f.read().strip()


# ---------- 설정 저장소 ----------
def _get(key, default=None):
    with db() as conn:
        row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
    return row["value"] if row else default


def _set(key, value):
    with db() as conn:
        conn.execute("INSERT INTO settings(key, value) VALUES (?, ?) "
                     "ON CONFLICT(key) DO UPDATE SET value = excluded.value", (key, value))


def password_is_set():
    return _get("money_password_hash") is not None


def _change_password(new_password):
    _set("money_password_hash", generate_password_hash(new_password))
    _set("lock_epoch", str(int(_get("lock_epoch", "0")) + 1))   # 다른 브라우저의 해제 상태도 모두 잠김


# ---------- 잠금 상태 ----------
def is_unlocked():
    stamp = session.get("unlocked_at")
    if not stamp or session.get("epoch") != _get("lock_epoch", "0"):
        return False
    return time.time() - stamp < IDLE_SECONDS


def _unlock_now():
    session["unlocked_at"] = time.time()
    session["epoch"] = _get("lock_epoch", "0")


def file_is_protected(target_type):
    return bool(target_type) and target_type.startswith(PROTECTED_FILE_PREFIXES)


def require_unlocked_for_file(target_type):
    """잠긴 금액 자료의 첨부파일은 잠금이 풀린 상태에서만 열립니다."""
    if file_is_protected(target_type) and not is_unlocked():
        abort(403)


def _safe_next(value):
    if value and value.startswith("/") and not value.startswith("//"):
        return value
    return url_for("audit_home")


# ---------- 접근 막기 ----------
@bp.before_app_request
def guard():
    if not request.path.startswith(PROTECTED_PATHS):
        return None
    if is_unlocked():
        session["unlocked_at"] = time.time()    # 사용 중이면 자동 잠금 시간 연장
        return None
    if session.pop("unlocked_at", None):
        flash("일정 시간 사용하지 않아 잠겼습니다. 비밀번호를 다시 입력해 주세요.", "error")
    return redirect(url_for("auth.unlock", next=request.full_path.rstrip("?")))


@bp.app_context_processor
def inject_lock_state():
    return {"unlocked": is_unlocked(), "password_set": password_is_set()}


# ---------- 입력 화면 ----------
def _blocked_minutes(ip):
    info = _fails.get(ip)
    if info and info["until"] > time.time():
        return int((info["until"] - time.time()) // 60) + 1
    return 0


def _record_fail(ip):
    info = _fails.setdefault(ip, {"count": 0, "until": 0})
    info["count"] += 1
    if info["count"] >= MAX_FAILS:
        info.update(count=0, until=time.time() + LOCKOUT_SECONDS)


@bp.route("/unlock", methods=["GET", "POST"])
def unlock():
    nxt = _safe_next(request.values.get("next"))
    first_time = not password_is_set()
    if request.method == "POST":
        password = request.form.get("password", "")
        if first_time:
            if len(password) < MIN_LENGTH:
                flash(f"비밀번호는 {MIN_LENGTH}자 이상으로 정해 주세요.", "error")
            elif password != request.form.get("password2", ""):
                flash("비밀번호 확인이 일치하지 않습니다.", "error")
            else:
                _change_password(password)
                _unlock_now()
                flash("비밀번호를 정했습니다. 잠금이 해제되었습니다.")
                return redirect(nxt)
        else:
            ip = request.remote_addr or "?"
            wait = _blocked_minutes(ip)
            if wait:
                flash(f"비밀번호를 여러 번 틀려서 약 {wait}분 뒤에 다시 입력할 수 있습니다.", "error")
            elif check_password_hash(_get("money_password_hash"), password):
                _fails.pop(ip, None)
                _unlock_now()
                return redirect(nxt)
            else:
                _record_fail(ip)
                flash("비밀번호가 맞지 않습니다.", "error")
    return render_template("unlock.html", first_time=first_time, next=nxt, min_length=MIN_LENGTH)


@bp.post("/lock")
def lock():
    session.pop("unlocked_at", None)
    flash("잠갔습니다.")
    return redirect(url_for("audit_home"))


@bp.route("/password", methods=["GET", "POST"])
def change_password():
    if not is_unlocked():
        return redirect(url_for("auth.unlock", next=url_for("auth.change_password")))
    if request.method == "POST":
        new = request.form.get("new_password", "")
        if not check_password_hash(_get("money_password_hash"), request.form.get("current_password", "")):
            flash("현재 비밀번호가 맞지 않습니다.", "error")
        elif len(new) < MIN_LENGTH:
            flash(f"새 비밀번호는 {MIN_LENGTH}자 이상으로 정해 주세요.", "error")
        elif new != request.form.get("new_password2", ""):
            flash("새 비밀번호 확인이 일치하지 않습니다.", "error")
        else:
            _change_password(new)
            _unlock_now()
            flash("비밀번호를 바꿨습니다.")
            return redirect(url_for("audit_home"))
    return render_template("password.html")
