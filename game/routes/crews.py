"""Crew directory, creation, applications, invitations, headquarters, and departure."""

import re
from flask import Blueprint, render_template, request, redirect, url_for, g
from database import execute, execute_one, execute_write, exclusive_transaction
from crews import crew_capacity, membership, join_crew, leave_crew

bp = Blueprint("crews", __name__)


@bp.route("/crews")
def index():
    member = membership(g.player["id"])
    crews = execute("""SELECT c.*,
      (SELECT COUNT(*) FROM crew_memberships WHERE crew_id=c.id) members,
      COALESCE((SELECT SUM(points) FROM crew_score_events WHERE crew_id=c.id AND event_type='PVP_WIN'),0) pvp_score,
      COALESCE((SELECT SUM(points) FROM crew_score_events WHERE crew_id=c.id AND event_type='BOSS_WIN'),0) boss_score,
      COALESCE((SELECT SUM(points) FROM crew_score_events WHERE crew_id=c.id AND event_type='WORLD_BOSS_DAMAGE'),0) world_damage
      FROM crews c WHERE c.disbanded_at IS NULL ORDER BY world_damage DESC,c.name""")
    invitations = execute("""SELECT r.id,c.name,c.tag FROM crew_requests r JOIN crews c ON c.id=r.crew_id
      WHERE r.player_id=? AND r.request_type='INVITATION' AND r.status='PENDING'""",(g.player["id"],))
    for crew in crews:
        values = {"Raiders": crew["world_damage"] / 25, "Enforcers": crew["pvp_score"],
                  "Boss Hunters": crew["boss_score"]}
        crew["reputation"] = max(values,key=values.get) if max(values.values()) > 0 else "New Production"
    return render_template("crews/index.html",crews=crews,member=member,capacity=crew_capacity(),invitations=invitations)


@bp.route("/crews/create",methods=["POST"])
def create():
    if execute_one("SELECT 1 FROM npc_profiles WHERE player_id=?",(g.player["id"],)):
        return redirect(url_for("crews.index",error="NPCs cannot create crews."))
    if membership(g.player["id"]):
        return redirect(url_for("crews.index",error="Leave your current crew first."))
    name=request.form.get("name","").strip(); tag=request.form.get("tag","").strip().upper()
    if len(name)<3 or not re.fullmatch(r"[A-Z0-9]{2,6}",tag):
        return redirect(url_for("crews.index",error="Use a name of 3+ characters and a 2–6 letter/number tag."))
    try:
        with exclusive_transaction():
            cid=execute_write("INSERT INTO crews(name,tag,description,motto,founder_player_id) VALUES(?,?,?,?,?)",
              (name,tag,request.form.get("description","").strip(),request.form.get("motto","").strip(),g.player["id"]))
            execute_write("INSERT INTO crew_memberships(player_id,crew_id,role) VALUES(?,?,'DIRECTOR')",(g.player["id"],cid))
            execute_write("INSERT INTO crew_logs(crew_id,player_id,event_type,message) VALUES(?,?,'CREATED',?)",
                          (cid,g.player["id"],f"{g.player['character_name']} founded {name}."))
            execute_write("INSERT INTO daily_feed(feed_scope,flavor_text,event_category) VALUES('GLOBAL',?,'CREW')",(f"{name} [{tag}] has entered the Movie Multiverse.",))
    except Exception:
        return redirect(url_for("crews.index",error="That crew name or tag is already in use."))
    return redirect(url_for("crews.headquarters",crew_id=cid))


@bp.route("/crews/<int:crew_id>")
def headquarters(crew_id):
    crew=execute_one("SELECT * FROM crews WHERE id=? AND disbanded_at IS NULL",(crew_id,))
    if not crew: return redirect(url_for("crews.index"))
    mine=membership(g.player["id"]); is_member=bool(mine and mine["crew_id"]==crew_id)
    members=execute("""SELECT p.id player_id,p.character_name,p.level,cm.role,cm.joined_at,
      COALESCE(SUM(se.points),0) score FROM crew_memberships cm JOIN players p ON p.id=cm.player_id
      LEFT JOIN crew_score_events se ON se.player_id=p.id AND se.crew_id=cm.crew_id
      WHERE cm.crew_id=? GROUP BY p.id ORDER BY CASE cm.role WHEN 'DIRECTOR' THEN 0 WHEN 'PRODUCER' THEN 1 ELSE 2 END,p.level DESC""",(crew_id,))
    logs=execute("SELECT * FROM crew_logs WHERE crew_id=? ORDER BY id DESC LIMIT 40",(crew_id,)) if is_member else []
    requests=execute("""SELECT r.*,p.character_name,p.level FROM crew_requests r JOIN players p ON p.id=r.player_id
      WHERE r.crew_id=? AND r.status='PENDING' ORDER BY r.id DESC""",(crew_id,)) if is_member and mine["role"] in ('DIRECTOR','PRODUCER') else []
    free_agents=execute("""SELECT p.id,p.character_name,p.level FROM players p LEFT JOIN crew_memberships cm ON cm.player_id=p.id
      WHERE cm.player_id IS NULL AND p.is_banned=0 AND p.retired_at IS NULL ORDER BY p.level DESC""") if is_member and mine["role"] in ('DIRECTOR','PRODUCER') else []
    return render_template("crews/headquarters.html",crew=crew,members=members,logs=logs,requests=requests,
                           free_agents=free_agents,mine=mine,is_member=is_member,capacity=crew_capacity())


@bp.route("/crews/<int:crew_id>/apply",methods=["POST"])
def apply(crew_id):
    if membership(g.player["id"]): return redirect(url_for("crews.index"))
    with exclusive_transaction(): execute_write("""INSERT INTO crew_requests(crew_id,player_id,request_type,created_by_player_id)
      SELECT ?,?,'APPLICATION',? WHERE NOT EXISTS(SELECT 1 FROM crew_requests WHERE crew_id=? AND player_id=? AND status='PENDING')""",
      (crew_id,g.player["id"],g.player["id"],crew_id,g.player["id"]))
    return redirect(url_for("crews.headquarters",crew_id=crew_id))


@bp.route("/crews/<int:crew_id>/invite",methods=["POST"])
def invite(crew_id):
    mine=membership(g.player["id"]); target=request.form.get("player_id",type=int)
    if not mine or mine["crew_id"]!=crew_id or mine["role"] not in ('DIRECTOR','PRODUCER'):
        return redirect(url_for("crews.index"))
    with exclusive_transaction(): execute_write("""INSERT INTO crew_requests(crew_id,player_id,request_type,created_by_player_id)
      SELECT ?,?,'INVITATION',? WHERE NOT EXISTS(SELECT 1 FROM crew_requests WHERE crew_id=? AND player_id=? AND status='PENDING')""",
      (crew_id,target,g.player["id"],crew_id,target))
    return redirect(url_for("crews.headquarters",crew_id=crew_id))


@bp.route("/crews/request/<int:request_id>/<decision>",methods=["POST"])
def resolve(request_id,decision):
    row=execute_one("SELECT * FROM crew_requests WHERE id=? AND status='PENDING'",(request_id,))
    if not row: return redirect(url_for("crews.index"))
    mine=membership(g.player["id"])
    allowed=(row["request_type"]=='INVITATION' and row["player_id"]==g.player["id"]) or (row["request_type"]=='APPLICATION' and mine and mine["crew_id"]==row["crew_id"] and mine["role"] in ('DIRECTOR','PRODUCER'))
    if allowed and decision=='accept': join_crew(row["player_id"],row["crew_id"],g.player["id"])
    elif allowed:
        with exclusive_transaction(): execute_write("UPDATE crew_requests SET status='DECLINED',resolved_at=datetime('now') WHERE id=?",(request_id,))
    return redirect(url_for("crews.index"))


@bp.route("/crews/leave",methods=["POST"])
def leave():
    leave_crew(g.player["id"]); return redirect(url_for("crews.index"))


@bp.route("/crews/<int:crew_id>/member/<int:player_id>/<action>",methods=["POST"])
def manage_member(crew_id,player_id,action):
    """Allow leadership to promote, demote, or remove ordinary members."""
    mine=membership(g.player["id"]); target=membership(player_id)
    if not mine or not target or mine["crew_id"]!=crew_id or target["crew_id"]!=crew_id:
        return redirect(url_for("crews.index"))
    if mine["role"]=='DIRECTOR' and player_id!=g.player["id"] and action in ('promote','demote'):
        with exclusive_transaction(): execute_write("UPDATE crew_memberships SET role=? WHERE player_id=?",
          ('PRODUCER' if action=='promote' else 'MEMBER',player_id))
    elif mine["role"] in ('DIRECTOR','PRODUCER') and target["role"]=='MEMBER' and action=='remove':
        leave_crew(player_id)
    return redirect(url_for("crews.headquarters",crew_id=crew_id))
