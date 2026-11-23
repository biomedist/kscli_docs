from flask import Blueprint, render_template
from menu import get_menu

bp = Blueprint("plans", __name__)


@bp.route("/audit/plans")
def list_view():
    return render_template("coming_soon.html", page=get_menu("plans"))
