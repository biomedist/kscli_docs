from flask import Blueprint, render_template
from menu import get_menu

bp = Blueprint("events", __name__)


@bp.route("/audit/events")
def list_view():
    return render_template("coming_soon.html", page=get_menu("events"))
