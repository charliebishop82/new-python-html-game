"""Dormant hex-board storage and axial-coordinate utilities.

The live encounter, combat, NPC, and interface paths deliberately do not import
this module yet. It provides a testable foundation without changing gameplay.
"""

from database import execute, execute_one, execute_write, exclusive_transaction


AXIAL_DIRECTIONS = ((1, 0), (1, -1), (0, -1), (-1, 0), (-1, 1), (0, 1))

# NPCs share player rows; protagonists currently live on movie rows in master.
_ENTITY_SOURCES = {
    "PLAYER": ("players", None),
    "NPC": ("players", "npc_profiles"),
    "BOSS": ("bosses", None),
    "MINION": ("minions", None),
    "WORLD_BOSS": ("world_bosses", None),
    "PROTAGONIST": ("master", None),
    "BOSS_INSTANCE": ("boss_instances", None),
    "MINION_INSTANCE": ("minion_instances", None),
}


def normalize_entity_type(entity_type: str) -> str:
    """Return a supported uppercase entity type or raise a clear error."""
    normalized = str(entity_type or "").strip().upper()
    if normalized not in _ENTITY_SOURCES:
        raise ValueError(f"Unsupported board entity type: {entity_type!r}")
    return normalized


def axial_distance(a_q: int, a_r: int, b_q: int, b_r: int) -> int:
    """Return shortest-path distance between two axial hex coordinates."""
    dq, dr = int(a_q) - int(b_q), int(a_r) - int(b_r)
    return (abs(dq) + abs(dr) + abs(dq + dr)) // 2


def axial_neighbors(q: int, r: int) -> list[tuple[int, int]]:
    """Return the six adjacent hexes in stable clockwise order."""
    q, r = int(q), int(r)
    return [(q + dq, r + dr) for dq, dr in AXIAL_DIRECTIONS]


def axial_ring(center_q: int, center_r: int, radius: int) -> list[tuple[int, int]]:
    """Return every hex exactly ``radius`` steps from the center."""
    radius = int(radius)
    if radius < 0:
        raise ValueError("Hex-ring radius cannot be negative.")
    center_q, center_r = int(center_q), int(center_r)
    if radius == 0:
        return [(center_q, center_r)]
    q = center_q + AXIAL_DIRECTIONS[4][0] * radius
    r = center_r + AXIAL_DIRECTIONS[4][1] * radius
    result = []
    for direction in AXIAL_DIRECTIONS:
        for _ in range(radius):
            result.append((q, r))
            q += direction[0]
            r += direction[1]
    return result


def create_board(name: str, radius: int | None = None, active: bool = False) -> dict:
    """Create a named board, optionally restricted to concentric rings."""
    clean_name = str(name or "").strip()
    if not clean_name:
        raise ValueError("A board name is required.")
    if radius is not None and int(radius) < 0:
        raise ValueError("Board radius cannot be negative.")
    with exclusive_transaction():
        if active:
            execute_write("UPDATE game_boards SET is_active=0")
        board_id = execute_write(
            "INSERT INTO game_boards(name,radius,is_active) VALUES(?,?,?)",
            (clean_name, None if radius is None else int(radius), int(bool(active))),
        )
    return get_board(board_id)


def get_board(board_id: int) -> dict | None:
    """Load one board definition."""
    return execute_one("SELECT * FROM game_boards WHERE id=?", (int(board_id),))


def get_active_board() -> dict | None:
    """Load the active board, if one is later activated."""
    return execute_one("SELECT * FROM game_boards WHERE is_active=1 ORDER BY id DESC LIMIT 1")


def set_active_board(board_id: int) -> dict:
    """Activate one board without exposing it to players automatically."""
    if not get_board(board_id):
        raise ValueError("Board does not exist.")
    with exclusive_transaction():
        execute_write("UPDATE game_boards SET is_active=0")
        execute_write("UPDATE game_boards SET is_active=1 WHERE id=?", (int(board_id),))
    return get_board(board_id)


def _validate_entity(entity_type: str, entity_id: int) -> str:
    entity_type = normalize_entity_type(entity_type)
    table, required_profile = _ENTITY_SOURCES[entity_type]
    entity_id = int(entity_id)
    if not execute_one(f"SELECT id FROM {table} WHERE id=?", (entity_id,)):
        raise ValueError(f"{entity_type} entity {entity_id} does not exist.")
    if required_profile and not execute_one(
            f"SELECT player_id FROM {required_profile} WHERE player_id=?", (entity_id,)):
        raise ValueError(f"Player {entity_id} is not an NPC.")
    return entity_type


def set_position(board_id: int, entity_type: str, entity_id: int,
                 q: int, r: int, layer: int = 1) -> dict:
    """Place or move an entity; shared hexes remain available for encounters."""
    board = get_board(board_id)
    if not board:
        raise ValueError("Board does not exist.")
    entity_type = _validate_entity(entity_type, entity_id)
    q, r, layer = int(q), int(r), int(layer)
    if layer < 1:
        raise ValueError("Board layers begin at 1.")
    if board["radius"] is not None and axial_distance(0, 0, q, r) > int(board["radius"]):
        raise ValueError("Coordinate lies outside this board's configured radius.")
    layer_has_tiles = execute_one(
        "SELECT COUNT(*) AS cnt FROM board_tiles WHERE board_id=? AND layer=?",
        (int(board_id), layer),
    )["cnt"]
    if layer_has_tiles and not execute_one(
            """SELECT id FROM board_tiles
               WHERE board_id=? AND layer=? AND q=? AND r=? AND is_enabled=1""",
            (int(board_id), layer, q, r)):
        raise ValueError("Coordinate is not an enabled tile on this board layer.")
    execute_write(
        """INSERT INTO board_positions(board_id,entity_type,entity_id,layer,q,r)
           VALUES(?,?,?,?,?,?)
           ON CONFLICT(board_id,entity_type,entity_id) DO UPDATE SET
             layer=excluded.layer,q=excluded.q,r=excluded.r,updated_at=datetime('now')""",
        (int(board_id), entity_type, int(entity_id), layer, q, r),
    )
    return get_position(board_id, entity_type, entity_id)


def get_position(board_id: int, entity_type: str, entity_id: int) -> dict | None:
    """Return an entity's placement, or ``None`` while it is unplaced."""
    return execute_one(
        "SELECT * FROM board_positions WHERE board_id=? AND entity_type=? AND entity_id=?",
        (int(board_id), normalize_entity_type(entity_type), int(entity_id)),
    )


def entities_at(board_id: int, q: int, r: int, layer: int = 1) -> list[dict]:
    """Return every entity occupying a particular hex."""
    return execute(
        """SELECT * FROM board_positions
           WHERE board_id=? AND layer=? AND q=? AND r=? ORDER BY id""",
        (int(board_id), int(layer), int(q), int(r)),
    )


def remove_position(board_id: int, entity_type: str, entity_id: int) -> None:
    """Make an entity unplaced without deleting the entity itself."""
    execute_write(
        "DELETE FROM board_positions WHERE board_id=? AND entity_type=? AND entity_id=?",
        (int(board_id), normalize_entity_type(entity_type), int(entity_id)),
    )


def create_standard_layer(board_id: int, layer: int, hub_name: str | None = None) -> list[dict]:
    """Create one 19-tile layer: hub + six inner + twelve outer hexes."""
    board = get_board(board_id)
    if not board:
        raise ValueError("Board does not exist.")
    layer = int(layer)
    if layer < 1:
        raise ValueError("Board layers begin at 1.")
    if execute_one(
            "SELECT id FROM board_tiles WHERE board_id=? AND layer=? LIMIT 1",
            (int(board_id), layer)):
        raise ValueError(f"Board layer {layer} already contains tiles.")
    rows = [(0, 0, 0, "HUB", hub_name or f"Layer {layer} Multiverse Hub")]
    rows.extend((q, r, 1, "MOVIE", f"Layer {layer} Inner Movie {index}")
                for index, (q, r) in enumerate(axial_ring(0, 0, 1), 1))
    rows.extend((q, r, 2, "MOVIE", f"Layer {layer} Outer Movie {index}")
                for index, (q, r) in enumerate(axial_ring(0, 0, 2), 1))
    with exclusive_transaction():
        for q, r, ring, tile_type, name in rows:
            execute_write(
                """INSERT INTO board_tiles
                   (board_id,layer,q,r,ring,tile_type,name) VALUES(?,?,?,?,?,?,?)""",
                (int(board_id), layer, q, r, ring, tile_type, name),
            )
    return get_layer_tiles(board_id, layer)


def get_layer_tiles(board_id: int, layer: int, enabled_only: bool = False) -> list[dict]:
    """Return a layer in ring and coordinate order."""
    enabled_clause = " AND is_enabled=1" if enabled_only else ""
    return execute(
        f"""SELECT * FROM board_tiles WHERE board_id=? AND layer=?{enabled_clause}
            ORDER BY ring,q,r""",
        (int(board_id), int(layer)),
    )


def assign_movie(tile_id: int, master_id: int, name: str | None = None) -> dict:
    """Associate one movie record with a non-hub tile."""
    tile = execute_one("SELECT * FROM board_tiles WHERE id=?", (int(tile_id),))
    if not tile:
        raise ValueError("Board tile does not exist.")
    if tile["tile_type"] != "MOVIE":
        raise ValueError("The central hub cannot be assigned to a movie.")
    movie = execute_one("SELECT id,movie_name FROM master WHERE id=?", (int(master_id),))
    if not movie:
        raise ValueError("Movie record does not exist.")
    execute_write(
        "UPDATE board_tiles SET master_id=?,name=? WHERE id=?",
        (int(master_id), name or movie["movie_name"], int(tile_id)),
    )
    return execute_one("SELECT * FROM board_tiles WHERE id=?", (int(tile_id),))


def connect_tiles(from_tile_id: int, to_tile_id: int,
                  connection_type: str = "VERTICAL", bidirectional: bool = True) -> dict:
    """Create a special route, typically between layers."""
    first = execute_one("SELECT * FROM board_tiles WHERE id=?", (int(from_tile_id),))
    second = execute_one("SELECT * FROM board_tiles WHERE id=?", (int(to_tile_id),))
    if not first or not second:
        raise ValueError("Both connection tiles must exist.")
    if first["board_id"] != second["board_id"]:
        raise ValueError("Connections cannot cross separate boards.")
    connection_id = execute_write(
        """INSERT INTO board_connections
           (board_id,from_tile_id,to_tile_id,connection_type,is_bidirectional)
           VALUES(?,?,?,?,?)""",
        (first["board_id"], first["id"], second["id"],
         str(connection_type or "VERTICAL").strip().upper(), int(bool(bidirectional))),
    )
    return execute_one("SELECT * FROM board_connections WHERE id=?", (connection_id,))


def connected_tiles(tile_id: int) -> list[dict]:
    """Return ordinary axial neighbors plus enabled special connections."""
    tile = execute_one("SELECT * FROM board_tiles WHERE id=? AND is_enabled=1", (int(tile_id),))
    if not tile:
        return []
    coordinates = axial_neighbors(tile["q"], tile["r"])
    placeholders = ",".join("(?,?)" for _ in coordinates)
    params = [tile["board_id"], tile["layer"]]
    for q, r in coordinates:
        params.extend((q, r))
    normal = execute(
        f"""SELECT *, 'ADJACENT' AS route_type FROM board_tiles
            WHERE board_id=? AND layer=? AND is_enabled=1
              AND (q,r) IN ({placeholders})""",
        tuple(params),
    )
    special = execute(
        """SELECT destination.*,connection.connection_type AS route_type
           FROM board_connections connection
           JOIN board_tiles destination ON destination.id = CASE
             WHEN connection.from_tile_id=? THEN connection.to_tile_id
             ELSE connection.from_tile_id END
           WHERE connection.is_enabled=1 AND destination.is_enabled=1
             AND (connection.from_tile_id=? OR
                  (connection.to_tile_id=? AND connection.is_bidirectional=1))""",
        (tile["id"], tile["id"], tile["id"]),
    )
    return normal + special


def board_snapshot(board_id: int) -> dict:
    """Build a read-only structure suitable for a future graphical client."""
    board = get_board(board_id)
    if not board:
        raise ValueError("Board does not exist.")
    return {
        "board": board,
        "tiles": execute(
            "SELECT * FROM board_tiles WHERE board_id=? ORDER BY layer,ring,q,r",
            (int(board_id),),
        ),
        "positions": execute(
            "SELECT * FROM board_positions WHERE board_id=? ORDER BY layer,q,r,id",
            (int(board_id),),
        ),
        "connections": execute(
            "SELECT * FROM board_connections WHERE board_id=? ORDER BY id",
            (int(board_id),),
        ),
    }
