"""Feature-gated player interface for cinematic scenarios."""

from flask import Blueprint, abort, g, redirect, render_template, request, url_for

from scenes import (eligible_scenes, player_scenes_enabled, resolve_choice,
                    scene_with_choices, start_scene)
from scene_combat import (begin_scene_combat, scene_combat_state,
                          take_scene_combat_turn)

bp = Blueprint("scenes", __name__, url_prefix="/scenes")


def _require_enabled():
    """Keep every player entry point dormant until the administrator enables it."""
    if not player_scenes_enabled():
        abort(404)


@bp.route("/")
def index():
    """Show the scene lobby after the feature gate is deliberately enabled."""
    _require_enabled()
    return render_template("scenes/index.html", scenes=eligible_scenes(g.player["id"]))


@bp.route("/begin", methods=["POST"])
def begin():
    """Create or resume one choice-pending scene attempt."""
    _require_enabled()
    requested = request.form.get("scene_id", type=int)
    try:
        result = start_scene(g.player["id"], requested)
    except ValueError as exc:
        return redirect(url_for("scenes.index", error=str(exc)))
    return render_template("scenes/play.html", **result)


@bp.route("/attempt/<int:attempt_id>/choose", methods=["POST"])
def choose(attempt_id: int):
    """Resolve the chosen attribute approach and show its complete result."""
    _require_enabled()
    choice_id = request.form.get("choice_id", type=int)
    if not choice_id:
        return redirect(url_for("scenes.index", error="Choose an approach first."))
    try:
        result = resolve_choice(g.player["id"], attempt_id, choice_id)
        if result["combat_pending"]:
            combat = begin_scene_combat(g.player["id"], attempt_id)
            return render_template("scenes/combat.html", combat=combat)
    except ValueError as exc:
        return redirect(url_for("scenes.index", error=str(exc)))
    return render_template("scenes/result.html", result=result)


@bp.route("/combat/<int:session_id>")
def combat(session_id: int):
    """Resume only the player's independent cinematic combat session."""
    _require_enabled()
    try:
        state = scene_combat_state(session_id, g.player["id"])
    except ValueError:
        abort(404)
    return render_template("scenes/combat.html", combat=state)


@bp.route("/combat/<int:session_id>/act", methods=["POST"])
def combat_act(session_id: int):
    """Resolve one complete player/protagonist/enemy scene round."""
    _require_enabled()
    try:
        state = take_scene_combat_turn(
            g.player["id"], session_id, request.form.get("action", ""),
            request.form.get("version", type=int),
        )
    except ValueError as exc:
        return redirect(url_for("scenes.combat", session_id=session_id,
                                error=str(exc)))
    return render_template("scenes/combat.html", combat=state)


@bp.route("/<int:scene_id>/preview")
def preview(scene_id: int):
    """Player-formatted preview, still protected by the same feature gate."""
    _require_enabled()
    scene = scene_with_choices(scene_id)
    if not scene:
        abort(404)
    return render_template("scenes/play.html", scene=scene, attempt_id=None,
                           preview_only=True, resumed=False)
