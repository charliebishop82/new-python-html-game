"""Public player directory plus private contracts, reputation, and War Room intelligence."""

from flask import Blueprint, render_template, g

from database import execute, execute_one
from contracts import ensure_daily_contract
from reputations import reputation_profile

bp = Blueprint("community", __name__)


@bp.route("/players")
def players():
    """Show deliberately limited public character information."""
    rows = execute(
        """SELECT p.id,p.character_name,p.level,COALESCE(ps.pvp_kills,0) pvp_wins,
          CASE WHEN p.last_login_at>=datetime('now','-5 minutes') THEN 'Active now'
               WHEN p.last_login_at>=datetime('now','-1 day') THEN 'Seen today'
               ELSE 'Away' END activity
          FROM players p LEFT JOIN player_stats ps ON ps.player_id=p.id
          WHERE p.is_banned=0 AND p.retired_at IS NULL
          ORDER BY p.level DESC,COALESCE(ps.pvp_kills,0) DESC,p.character_name COLLATE NOCASE"""
    )
    for rank, row in enumerate(rows, 1):
        row["rank"] = rank
        row["is_current_player"] = row["id"] == g.player["id"]
        row["reputation"] = reputation_profile(row["id"])["primary"]
    return render_template("community/players.html", players=rows)


@bp.route("/contracts")
def contracts():
    """Show today's objective, progress, deadline, and exact reward."""
    return render_template("community/contracts.html",
                           contract=ensure_daily_contract(g.player["id"]))


@bp.route("/war-room")
def war_room():
    """Build a private intelligence archive from discovery and combat history."""
    pid = g.player["id"]
    bosses = execute(
        """SELECT b.name,b.level,b.description,bi.kill_count,bi.discovered_at,
          CASE WHEN intel.id IS NULL THEN 0 ELSE 1 END observed,
          b.res_blade,b.res_blunt,b.res_ballistic,b.res_energy,b.res_arcane,b.res_explosive,b.res_venom,
          b.weak_blade,b.weak_blunt,b.weak_ballistic,b.weak_energy,b.weak_arcane,b.weak_explosive,b.weak_venom,
          w.name weapon,a.name armor,s.name special,
          (SELECT COUNT(*) FROM combat_sessions cs WHERE cs.boss_instance_id=bi.id AND cs.status='RESOLVED') encounters,
          (SELECT COUNT(*) FROM combat_sessions cs WHERE cs.boss_instance_id=bi.id AND cs.result IN ('1HP_WIN','SCORE_WIN')) victories
          FROM boss_instances bi JOIN bosses b ON b.id=bi.boss_id
          LEFT JOIN boss_intel intel ON intel.player_id=bi.player_id AND intel.boss_id=b.id
          LEFT JOIN master m ON m.boss_id=b.id AND m.is_active=1
          LEFT JOIN weapons w ON w.id=m.boss_weapon_id LEFT JOIN armor a ON a.id=m.boss_armor_id
          LEFT JOIN special_items s ON s.id=m.boss_special_item_id
          WHERE bi.player_id=? ORDER BY bi.discovered_at DESC""", (pid,)
    )
    minions = execute(
        """SELECT mn.name,mn.level,mn.description,mi.kill_count,mi.discovered_at,
          CASE WHEN intel.id IS NULL THEN 0 ELSE 1 END observed,
          mn.res_blade,mn.res_blunt,mn.res_ballistic,mn.res_energy,mn.res_arcane,mn.res_explosive,mn.res_venom,
          mn.weak_blade,mn.weak_blunt,mn.weak_ballistic,mn.weak_energy,mn.weak_arcane,mn.weak_explosive,mn.weak_venom,
          w.name weapon,a.name armor,s.name special,
          (SELECT COUNT(*) FROM combat_sessions cs WHERE cs.minion_instance_id=mi.id AND cs.status='RESOLVED') encounters
          FROM minion_instances mi JOIN minions mn ON mn.id=mi.minion_id
          LEFT JOIN minion_intel intel ON intel.player_id=mi.player_id AND intel.minion_id=mn.id
          LEFT JOIN master m ON m.minion_id=mn.id AND m.is_active=1
          LEFT JOIN weapons w ON w.id=m.minion_weapon_id LEFT JOIN armor a ON a.id=m.minion_armor_id
          LEFT JOIN special_items s ON s.id=m.minion_special_item_id
          WHERE mi.player_id=? ORDER BY mi.discovered_at DESC""", (pid,)
    )
    damage_types = ("blade", "blunt", "ballistic", "energy", "arcane", "explosive", "venom")
    for boss in bosses:
        boss["resistances"] = [d.title() for d in damage_types if boss.get(f"res_{d}")]
        boss["weaknesses"] = [d.title() for d in damage_types if boss.get(f"weak_{d}")]
    for minion in minions:
        minion["resistances"] = [d.title() for d in damage_types if minion.get(f"res_{d}")]
        minion["weaknesses"] = [d.title() for d in damage_types if minion.get(f"weak_{d}")]
    pvp = execute(
        """SELECT opponent,COUNT(*) encounters,SUM(won) victories,MAX(resolved_at) last_contact FROM (
          SELECT CASE WHEN cs.attacker_player_id=? THEN d.character_name ELSE a.character_name END opponent,
          CASE WHEN (cs.attacker_player_id=? AND cs.result IN ('1HP_WIN','SCORE_WIN')) THEN 1 ELSE 0 END won,
          cs.resolved_at FROM combat_sessions cs JOIN players a ON a.id=cs.attacker_player_id
          JOIN players d ON d.id=cs.defender_player_id WHERE cs.combat_type='PVP' AND cs.status='RESOLVED'
          AND (cs.attacker_player_id=? OR cs.defender_player_id=?))
          GROUP BY opponent ORDER BY last_contact DESC""", (pid,pid,pid,pid)
    )
    wealth_intel = execute(
        """SELECT p.character_name,w.wealth_band,w.learned_at
           FROM player_wealth_intel w JOIN players p ON p.id=w.target_player_id
           WHERE w.observer_player_id=? ORDER BY w.learned_at DESC""", (pid,)
    )
    return render_template("community/war_room.html", bosses=bosses,minions=minions,pvp=pvp,
                           wealth_intel=wealth_intel,reputation=reputation_profile(pid))
