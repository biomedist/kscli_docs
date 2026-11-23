"""임상면역검사학회 문서관리 앱 - 시작점
실행:  python app.py   →   http://서버IP:5050/
"""
import os

from flask import Flask, flash, redirect, render_template, request, url_for

import auth
from menu import MENU
from models import init_db
from routes import register_routes

APP_TITLE = "임상면역검사학회 문서관리"

app = Flask(__name__)
app.secret_key = auth.get_secret_key()   # 로그인 상태·알림 메시지 서명용 (data/secret.key)
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
app.config["MAX_CONTENT_LENGTH"] = 50 * 1024 * 1024  # 업로드 최대 50MB
register_routes(app)


@app.context_processor
def inject_globals():
    return {"app_title": APP_TITLE, "menu": MENU}


@app.errorhandler(413)
def too_large(_error):
    flash("파일이 너무 큽니다. 한 번에 올릴 수 있는 크기는 최대 50MB입니다.", "error")
    return redirect(request.referrer or url_for("home"))


@app.route("/")
def home():
    return render_template("home.html")


@app.route("/audit")
def audit_home():
    return render_template("audit_home.html")


if __name__ == "__main__":
    init_db()
    app.run(host="0.0.0.0", port=5050, debug=False)
