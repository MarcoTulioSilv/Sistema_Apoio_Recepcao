"""Página de saúde: confirma que o processo web está no ar, sem tocar no banco."""

from __future__ import annotations

from flask import Blueprint, render_template

bp = Blueprint("saude", __name__)


@bp.get("/saude")
def saude() -> str:
    return render_template("saude.html")
