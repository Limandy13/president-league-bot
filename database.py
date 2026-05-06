import sqlite3

DB_FILE = "president.db"

def init_db():
    with sqlite3.connect(DB_FILE) as conn:
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS players (
                id INTEGER PRIMARY KEY,
                username TEXT,
                display_name TEXT,
                is_playing_this_season INTEGER DEFAULT 0,
                current_season_score INTEGER DEFAULT 0
            )
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS seasons (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                is_active INTEGER DEFAULT 0,
                number_of_rounds_played INTEGER DEFAULT 0,
                special1 TEXT DEFAULT 'J',
                special2 TEXT DEFAULT 'Q'
            )
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS player_scores (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                season_id INTEGER,
                round INTEGER,
                score_change INTEGER,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(user_id) REFERENCES players(id),
                FOREIGN KEY(season_id) REFERENCES seasons(id)
            )
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS donations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                donor_id INTEGER,
                recipient_id INTEGER,
                season_id INTEGER,
                points INTEGER,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(donor_id) REFERENCES players(id),
                FOREIGN KEY(recipient_id) REFERENCES players(id),
                FOREIGN KEY(season_id) REFERENCES seasons(id)
            )
        """)
        conn.commit()

def start_new_season(name):
    with sqlite3.connect(DB_FILE) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT id FROM seasons WHERE is_active = 1")
        active_s = cursor.fetchone()
        stats = []
        if active_s:
            cursor.execute("SELECT display_name, current_season_score FROM players WHERE is_playing_this_season = 1 ORDER BY current_season_score DESC")
            stats = cursor.fetchall()

        cursor.execute("UPDATE players SET is_playing_this_season = 0, current_season_score = 0")
        cursor.execute("UPDATE seasons SET is_active = 0")
        cursor.execute("INSERT INTO seasons (name, is_active, number_of_rounds_played, special1, special2) VALUES (?, 1, 0, 'J', 'Q')", (name,))
        conn.commit()
        return stats

def register_or_join_player(user_id, username, display_name):
    with sqlite3.connect(DB_FILE) as conn:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO players (id, username, display_name, is_playing_this_season, current_season_score)
            VALUES (?, ?, ?, 1, 0)
            ON CONFLICT(id) DO UPDATE SET username = excluded.username, display_name = excluded.display_name, is_playing_this_season = 1
        """, (user_id, username, display_name))
        conn.commit()


def ensure_player_for_season(username, user_id=None, display_name=None):
    username = username.lstrip('@')
    display_name = display_name or username

    with sqlite3.connect(DB_FILE) as conn:
        cursor = conn.cursor()

        if user_id is not None:
            cursor.execute("SELECT id FROM players WHERE id = ?", (user_id,))
            row = cursor.fetchone()
            if row:
                cursor.execute(
                    """
                    UPDATE players
                    SET username = ?, display_name = ?, is_playing_this_season = 1
                    WHERE id = ?
                    """,
                    (username, display_name, user_id)
                )
                conn.commit()
                return user_id

            cursor.execute("SELECT id FROM players WHERE username = ?", (username,))
            row = cursor.fetchone()
            if row:
                uid = row[0]
                cursor.execute(
                    """
                    UPDATE players
                    SET id = ?, display_name = ?, is_playing_this_season = 1
                    WHERE id = ?
                    """,
                    (user_id, display_name, uid)
                )
                conn.commit()
                return user_id

            cursor.execute(
                """
                INSERT INTO players (id, username, display_name, is_playing_this_season, current_season_score)
                VALUES (?, ?, ?, 1, 0)
                """,
                (user_id, username, display_name)
            )
            conn.commit()
            return user_id

        cursor.execute("SELECT id FROM players WHERE username = ?", (username,))
        row = cursor.fetchone()
        if row:
            uid = row[0]
            cursor.execute(
                """
                UPDATE players
                SET display_name = ?, is_playing_this_season = 1
                WHERE id = ?
                """,
                (display_name, uid)
            )
            conn.commit()
            return uid

        cursor.execute(
            """
            INSERT INTO players (username, display_name, is_playing_this_season, current_season_score)
            VALUES (?, ?, 1, 0)
            """,
            (username, display_name)
        )
        conn.commit()
        return cursor.lastrowid


def add_round_scores(updates: dict):
    with sqlite3.connect(DB_FILE) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT id, number_of_rounds_played FROM seasons WHERE is_active = 1")
        row = cursor.fetchone()
        if not row:
            return "Aucune saison active."

        season_id, last_round = row
        new_round = last_round + 1

        players = {}
        for username in updates:
            uname = username.lstrip('@')
            cursor.execute("SELECT id FROM players WHERE username = ?", (uname,))
            user_row = cursor.fetchone()
            if not user_row:
                return f"Le joueur @{uname} n'existe pas."
            players[uname] = user_row[0]

        for username, change in updates.items():
            uid = players[username.lstrip('@')]
            cursor.execute("INSERT INTO player_scores (user_id, season_id, round, score_change) VALUES (?, ?, ?, ?)", (uid, season_id, new_round, change))
            cursor.execute("UPDATE players SET current_season_score = current_season_score + ? WHERE id = ?", (change, uid))

        cursor.execute("UPDATE seasons SET number_of_rounds_played = ? WHERE id = ?", (new_round, season_id))
        conn.commit()
        return None


def _get_active_season_id(cursor):
    cursor.execute("SELECT id FROM seasons WHERE is_active = 1")
    row = cursor.fetchone()
    return row[0] if row else None


def _get_active_player(cursor, username):
    cursor.execute(
        "SELECT id, display_name, current_season_score FROM players WHERE username = ? AND is_playing_this_season = 1",
        (username.lstrip('@'),)
    )
    return cursor.fetchone()


def donate_to_player(donor_username, recipient_username, amount):
    if amount <= 0:
        return "Le montant doit être un entier positif."

    with sqlite3.connect(DB_FILE) as conn:
        cursor = conn.cursor()
        season_id = _get_active_season_id(cursor)
        if not season_id:
            return "Aucune saison active."

        donor_row = _get_active_player(cursor, donor_username)
        if not donor_row:
            return f"Le donateur @{donor_username.lstrip('@')} n'est pas inscrit cette saison."

        donor_id, _, donor_score = donor_row
        if donor_score < amount:
            return f"Tu n'as que {donor_score} points disponibles."

        recipient_row = _get_active_player(cursor, recipient_username)
        if not recipient_row:
            return f"Le joueur @{recipient_username.lstrip('@')} n'existe pas dans cette saison."

        recipient_id = recipient_row[0]
        if donor_id == recipient_id:
            return "Tu ne peux pas te donner des points à toi-même."

        cursor.execute("UPDATE players SET current_season_score = current_season_score - ? WHERE id = ?", (amount, donor_id))
        cursor.execute("UPDATE players SET current_season_score = current_season_score + ? WHERE id = ?", (amount, recipient_id))
        cursor.execute(
            "INSERT INTO donations (donor_id, recipient_id, season_id, points) VALUES (?, ?, ?, ?)",
            (donor_id, recipient_id, season_id, amount)
        )
        conn.commit()
        return None


def donate_random(donor_username, count):
    if count <= 0:
        return "Le montant doit être un entier positif.", None

    with sqlite3.connect(DB_FILE) as conn:
        cursor = conn.cursor()
        season_id = _get_active_season_id(cursor)
        if not season_id:
            return "Aucune saison active.", None

        donor_row = _get_active_player(cursor, donor_username)
        if not donor_row:
            return f"Le donateur @{donor_username.lstrip('@')} n'est pas inscrit cette saison.", None

        donor_id, _, donor_score = donor_row
        if donor_score < count:
            return f"Tu n'as que {donor_score} points disponibles.", None

        cursor.execute(
            "SELECT id, display_name FROM players WHERE is_playing_this_season = 1 AND id != ?",
            (donor_id,)
        )
        recipients = cursor.fetchall()
        if not recipients:
            return "Aucun autre joueur actif cette saison.", None

        recipient_ids = [row[0] for row in recipients]
        from random import choices
        selected = choices(recipient_ids, k=count)
        recipient_counts = {}
        for rid in selected:
            recipient_counts[rid] = recipient_counts.get(rid, 0) + 1
            cursor.execute("UPDATE players SET current_season_score = current_season_score + 1 WHERE id = ?", (rid,))
            cursor.execute(
                "INSERT INTO donations (donor_id, recipient_id, season_id, points) VALUES (?, ?, ?, 1)",
                (donor_id, rid, season_id)
            )

        cursor.execute("UPDATE players SET current_season_score = current_season_score - ? WHERE id = ?", (count, donor_id))

        ids = list(recipient_counts.keys())
        placeholders = ",".join("?" for _ in ids)
        cursor.execute(f"SELECT id, display_name FROM players WHERE id IN ({placeholders})", ids)
        names = {row[0]: row[1] for row in cursor.fetchall()}

        summary = {names[rid]: recipient_counts[rid] for rid in ids}
        conn.commit()
        return None, summary

def apply_revolution(card):
    with sqlite3.connect(DB_FILE) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT special1 FROM seasons WHERE is_active = 1")
        row = cursor.fetchone()
        if not row:
            return False
        cursor.execute("UPDATE seasons SET special1 = ?, special2 = ? WHERE is_active = 1", (card, row[0]))
        conn.commit()
        return True

def get_current_leaderboard():
    with sqlite3.connect(DB_FILE) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT name, special1, special2 FROM seasons WHERE is_active = 1")
        info = cursor.fetchone()
        if not info:
            return [], "Inconnue", ("?", "?")
        cursor.execute("SELECT display_name, current_season_score FROM players WHERE is_playing_this_season = 1 ORDER BY current_season_score DESC")
        return cursor.fetchall(), info[0], (info[1], info[2])

def get_score_history():
    with sqlite3.connect(DB_FILE) as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT p.display_name, ps.round, ps.score_change
            FROM player_scores ps
            JOIN players p ON ps.user_id = p.id
            WHERE ps.season_id = (SELECT id FROM seasons WHERE is_active = 1)
            ORDER BY ps.round ASC
        """)
        return cursor.fetchall()

def get_player_stats(username):
    username = username.lstrip('@')
    with sqlite3.connect(DB_FILE) as conn:
        cursor = conn.cursor()

        cursor.execute("SELECT id, display_name FROM players WHERE username = ?", (username,))
        user = cursor.fetchone()
        if not user:
            return None
        uid, display_name = user

        cursor.execute("SELECT id FROM seasons WHERE is_active = 1")
        active_season_row = cursor.fetchone()
        if not active_season_row:
            return None
        sid = active_season_row[0]

        cursor.execute("SELECT COUNT(*) FROM player_scores WHERE user_id = ? AND season_id = ?", (uid, sid))
        nb_manches = cursor.fetchone()[0] or 0

        cursor.execute("SELECT AVG(score_change) FROM player_scores WHERE user_id = ? AND season_id = ?", (uid, sid))
        avg_score = cursor.fetchone()[0] or 0.0

        cursor.execute("""
            SELECT p2.display_name, COUNT(*) as common_rounds
            FROM player_scores ps1
            JOIN player_scores ps2 ON ps1.round = ps2.round AND ps1.season_id = ps2.season_id
            JOIN players p2 ON ps2.user_id = p2.id
            WHERE ps1.user_id = ? AND ps2.user_id != ? AND ps1.season_id = ?
            GROUP BY p2.id ORDER BY common_rounds DESC LIMIT 1
        """, (uid, uid, sid))
        most_played = cursor.fetchone()

        cursor.execute("""
            SELECT p2.display_name, SUM(ps2.score_change) as target_loss
            FROM player_scores ps1
            JOIN player_scores ps2 ON ps1.round = ps2.round AND ps1.season_id = ps2.season_id
            JOIN players p2 ON ps2.user_id = p2.id
            WHERE ps1.user_id = ? AND ps1.score_change > 0 AND ps2.user_id != ? AND ps1.season_id = ?
            GROUP BY p2.id ORDER BY target_loss ASC LIMIT 1
        """, (uid, uid, sid))
        victim = cursor.fetchone()

        cursor.execute("""
            SELECT p2.display_name, SUM(ps2.score_change) as target_gain
            FROM player_scores ps1
            JOIN player_scores ps2 ON ps1.round = ps2.round AND ps1.season_id = ps2.season_id
            JOIN players p2 ON ps2.user_id = p2.id
            WHERE ps1.user_id = ? AND ps1.score_change < 0 AND ps2.user_id != ? AND ps1.season_id = ?
            GROUP BY p2.id ORDER BY target_gain DESC LIMIT 1
        """, (uid, uid, sid))
        nemesis = cursor.fetchone()

        return {
            "name": display_name,
            "nb_manches": nb_manches,
            "avg_score": round(avg_score, 2),
            "most_played": most_played[0] if most_played else "N/A",
            "victim": victim[0] if victim else "N/A",
            "nemesis": nemesis[0] if nemesis else "N/A"
        }