"""Crew membership rules, pooled earnings, scoring, logs, and NPC-facing signals."""

import math
from datetime import datetime, timedelta
from database import execute, execute_one, execute_write, exclusive_transaction


def crew_capacity() -> int:
    """Maximum members: one third of non-retired, non-banned characters, minimum three."""
    total = execute_one("SELECT COUNT(*) n FROM players WHERE is_banned=0 AND retired_at IS NULL")["n"]
    return max(3, math.floor(total / 3))


def membership(player_id: int) -> dict | None:
    return execute_one(
        """SELECT cm.*,c.name crew_name,c.tag FROM crew_memberships cm
           JOIN crews c ON c.id=cm.crew_id WHERE cm.player_id=? AND c.disbanded_at IS NULL""",
        (player_id,),
    )


def are_pvp_protected(a: int, b: int) -> bool:
    """Block current crewmates and the 24-hour former-crewmate cooling-off exploit."""
    ma, mb = membership(a), membership(b)
    if ma and mb and ma["crew_id"] == mb["crew_id"]:
        return True
    now = datetime.utcnow().isoformat()
    cooldown_a = execute_one("""SELECT crew_id FROM crew_requests WHERE player_id=? AND status='COOLDOWN'
                              AND resolved_at>? ORDER BY id DESC LIMIT 1""", (a,now))
    cooldown_b = execute_one("""SELECT crew_id FROM crew_requests WHERE player_id=? AND status='COOLDOWN'
                              AND resolved_at>? ORDER BY id DESC LIMIT 1""", (b,now))
    return bool((cooldown_a and mb and cooldown_a["crew_id"] == mb["crew_id"]) or
                (cooldown_b and ma and cooldown_b["crew_id"] == ma["crew_id"]))


def join_crew(player_id: int, crew_id: int, actor_id: int | None = None) -> None:
    """Join after server-side capacity and membership checks, then publish the event."""
    crew = execute_one("SELECT * FROM crews WHERE id=? AND disbanded_at IS NULL", (crew_id,))
    player = execute_one("SELECT character_name FROM players WHERE id=?", (player_id,))
    if not crew or not player or membership(player_id):
        raise ValueError("Crew or Free Agent status is no longer available.")
    count = execute_one("SELECT COUNT(*) n FROM crew_memberships WHERE crew_id=?", (crew_id,))["n"]
    if count >= crew_capacity():
        raise ValueError("That crew has reached the one-third population limit.")
    message = f"{player['character_name']} joined {crew['name']}."
    with exclusive_transaction():
        execute_write("INSERT INTO crew_memberships(player_id,crew_id) VALUES(?,?)", (player_id,crew_id))
        execute_write("UPDATE crew_requests SET status='ACCEPTED',resolved_at=? WHERE crew_id=? AND player_id=? AND status='PENDING'",
                      (datetime.utcnow().isoformat(),crew_id,player_id))
        _log(crew_id, player_id, "JOIN", message)
        _world(message)


def leave_crew(player_id: int) -> None:
    """Return a member to Free Agent status and retain former-crew PvP protection for 24 hours."""
    member = membership(player_id)
    if not member:
        return
    player = execute_one("SELECT character_name FROM players WHERE id=?", (player_id,))
    crew = execute_one("SELECT name FROM crews WHERE id=?", (member["crew_id"],))
    until = (datetime.utcnow() + timedelta(hours=24)).isoformat()
    message = f"{player['character_name']} left {crew['name']} and became a Free Agent."
    with exclusive_transaction():
        execute_write("DELETE FROM crew_memberships WHERE player_id=?", (player_id,))
        _log(member["crew_id"], player_id, "LEAVE", message)
        _world(message)
        # Cooldown survives departure in a lightweight sentinel request record.
        execute_write("""INSERT INTO crew_requests(crew_id,player_id,request_type,status,created_at,resolved_at)
                         VALUES(?,?,'APPLICATION','COOLDOWN',?,?)""",
                      (member["crew_id"],player_id,datetime.utcnow().isoformat(),until))
        remaining = execute_one("SELECT COUNT(*) n FROM crew_memberships WHERE crew_id=?",(member["crew_id"],))["n"]
        if not remaining:
            execute_write("UPDATE crews SET disbanded_at=? WHERE id=?",(datetime.utcnow().isoformat(),member["crew_id"]))
            _world(f"{crew['name']} has wrapped production and disbanded.")
        elif member["role"] == "DIRECTOR":
            successor = execute_one("""SELECT player_id FROM crew_memberships WHERE crew_id=?
              ORDER BY CASE role WHEN 'PRODUCER' THEN 0 ELSE 1 END,joined_at LIMIT 1""",(member["crew_id"],))
            execute_write("UPDATE crew_memberships SET role='DIRECTOR' WHERE player_id=?",(successor["player_id"],))


def record_crew_score(player_id: int, event_type: str, points: float, world_event_id=None) -> None:
    member = membership(player_id)
    if member:
        execute_write("""INSERT INTO crew_score_events(crew_id,player_id,event_type,points,world_boss_event_id)
                         VALUES(?,?,?,?,?)""", (member["crew_id"],player_id,event_type,points,world_event_id))


def contribute_earnings(player_id: int, xp: int = 0, credits: int = 0, source: str = "GAME") -> tuple[int,int]:
    """Divert five percent of a positive award and return the character's net award."""
    member = membership(player_id)
    if not member:
        return xp, credits
    xp_share = max(0, int(xp * .05)); credit_share = max(0, int(credits * .05))
    if xp_share or credit_share:
        with exclusive_transaction():
            execute_write("UPDATE crews SET pooled_xp=pooled_xp+?,pooled_credits=pooled_credits+? WHERE id=?",
                          (xp_share,credit_share,member["crew_id"]))
            execute_write("""INSERT INTO crew_contributions(crew_id,player_id,xp_amount,credit_amount,source)
                             VALUES(?,?,?,?,?)""",(member["crew_id"],player_id,xp_share,credit_share,source))
    return xp-xp_share, credits-credit_share


def divert_awarded_earnings(player_id: int, xp: int = 0, credits: int = 0, source: str = "GAME") -> None:
    """Move five percent out of an award that has already been credited to the character."""
    net_xp, net_cr = contribute_earnings(player_id, xp, credits, source)
    xp_share, cr_share = xp-net_xp, credits-net_cr
    if xp_share or cr_share:
        with exclusive_transaction():
            execute_write("UPDATE players SET xp=MAX(0,xp-?),credits=MAX(0,credits-?) WHERE id=?",
                          (xp_share,cr_share,player_id))


def distribute_pools() -> None:
    """Split each pool evenly at midnight; retain integer remainders."""
    rewarded = []
    for crew in execute("SELECT * FROM crews WHERE disbanded_at IS NULL"):
        members = execute("SELECT player_id FROM crew_memberships WHERE crew_id=?", (crew["id"],))
        if not members:
            continue
        xp_each, cr_each = crew["pooled_xp"] // len(members), crew["pooled_credits"] // len(members)
        if not xp_each and not cr_each:
            continue
        with exclusive_transaction():
            for member in members:
                execute_write("UPDATE players SET xp=xp+?,credits=credits+? WHERE id=?",
                              (xp_each,cr_each,member["player_id"]))
                rewarded.append(member["player_id"])
                execute_write("""INSERT INTO daily_feed(feed_scope,player_id,flavor_text,event_category)
                  VALUES('PERSONAL',?,?, 'CREW')""",(member["player_id"],f"Crew pool dividend: +{xp_each} XP and +{cr_each} credits."))
            execute_write("UPDATE crews SET pooled_xp=pooled_xp-?,pooled_credits=pooled_credits-? WHERE id=?",
                          (xp_each*len(members),cr_each*len(members),crew["id"]))
    from combat import engine
    for player_id in rewarded:
        player = execute_one("SELECT xp,level FROM players WHERE id=?",(player_id,))
        engine.check_level_up(player_id,player["xp"],player["level"])


def reevaluate_npc_crews() -> None:
    """Let NPCs assess invitations, apply to suitable crews, or leave a severe mismatch.

    This runs at midnight rather than every action so crew loyalty changes are
    meaningful and understandable. Motivations are matched to permanent crew
    score events; NPC identity is never exposed to ordinary players.
    """
    for npc in execute("""SELECT np.*,p.character_name FROM npc_profiles np JOIN players p ON p.id=np.player_id
                          WHERE np.enabled=1 AND np.retired=0 AND p.retired_at IS NULL"""):
        current = membership(npc["player_id"])
        invitations = execute("""SELECT r.*,c.name FROM crew_requests r JOIN crews c ON c.id=r.crew_id
          WHERE r.player_id=? AND r.request_type='INVITATION' AND r.status='PENDING'""",(npc["player_id"],))
        ranked = []
        for crew in execute("SELECT * FROM crews WHERE disbanded_at IS NULL"):
            scores = execute_one("""SELECT
              COALESCE(SUM(CASE WHEN event_type='PVP_WIN' THEN points ELSE 0 END),0) pvp,
              COALESCE(SUM(CASE WHEN event_type='BOSS_WIN' THEN points ELSE 0 END),0) boss,
              COALESCE(SUM(CASE WHEN event_type='WORLD_BOSS_DAMAGE' THEN points ELSE 0 END),0) world,
              COALESCE(SUM(CASE WHEN event_type='MINION_WIN' THEN points ELSE 0 END),0) minion
              FROM crew_score_events WHERE crew_id=? AND occurred_at>=datetime('now','-14 days')""",(crew["id"],))
            # Normalize recent activity before weighting it by the NPC's established motivations.
            fit = (min(100,scores["pvp"]*4)*npc["player_hunter"] +
                   min(100,scores["boss"]*5)*npc["boss_killer"] +
                   min(100,scores["world"])*npc["world_boss_hunter"] +
                   min(100,scores["minion"]*5)*npc["self_preservation"]) / max(1,
                   npc["player_hunter"]+npc["boss_killer"]+npc["world_boss_hunter"]+npc["self_preservation"])
            ranked.append((fit,crew))
        ranked.sort(key=lambda pair:pair[0],reverse=True)
        if current:
            fit = next((score for score,crew in ranked if crew["id"]==current["crew_id"]),50)
            if fit < 18:
                leave_crew(npc["player_id"])
            continue
        invited = [(score,crew,req) for score,crew in ranked for req in invitations if req["crew_id"]==crew["id"]]
        accepted_request_id = None
        if invited and invited[0][0] >= 30:
            try:
                join_crew(npc["player_id"], invited[0][1]["id"])
                accepted_request_id = invited[0][2]["id"]
            except ValueError:
                # Capacity or membership may have changed during evaluation;
                # the request is still resolved below instead of lingering.
                pass
        # An automated character should visibly answer every invitation at its
        # daily crew review.  Previously, invitations below the fit threshold
        # remained PENDING forever, making it appear that NPC crew behavior was
        # not running at all.
        declined = [request["id"] for request in invitations
                    if request["id"] != accepted_request_id]
        if declined:
            placeholders = ",".join("?" for _ in declined)
            execute_write(
                f"""UPDATE crew_requests SET status='DECLINED',resolved_at=datetime('now')
                    WHERE id IN ({placeholders}) AND status='PENDING'""",
                tuple(declined),
            )
        if accepted_request_id is None and ranked and ranked[0][0] >= 35:
            crew=ranked[0][1]
            execute_write("""INSERT INTO crew_requests(crew_id,player_id,request_type,created_by_player_id)
              SELECT ?,?,'APPLICATION',? WHERE NOT EXISTS(SELECT 1 FROM crew_requests WHERE crew_id=? AND player_id=? AND status='PENDING')""",
              (crew["id"],npc["player_id"],npc["player_id"],crew["id"],npc["player_id"]))


def _log(crew_id, player_id, event_type, message):
    execute_write("INSERT INTO crew_logs(crew_id,player_id,event_type,message) VALUES(?,?,?,?)",
                  (crew_id,player_id,event_type,message))


def _world(message):
    execute_write("INSERT INTO daily_feed(feed_scope,flavor_text,event_category) VALUES('GLOBAL',?,'CREW')",(message,))
