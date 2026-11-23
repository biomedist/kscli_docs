from flask import Blueprint, render_template
from menu import get_menu

bp = Blueprint("finance", __name__)


@bp.route("/audit/budget")
def budget():
    return render_template("coming_soon.html", page=get_menu("budget"))


@bp.route("/audit/accounts")
def accounts():
    return render_template("coming_soon.html", page=get_menu("accounts"))


@bp.route("/audit/donations")
def donations():
    return render_template("coming_soon.html", page=get_menu("donations"))
