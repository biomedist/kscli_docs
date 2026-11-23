from flask import Blueprint, render_template
from menu import get_menu

bp = Blueprint("documents", __name__)


@bp.route("/audit/documents")
def list_view():
    return render_template("coming_soon.html", page=get_menu("documents"))
