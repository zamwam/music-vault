import json
import os
import sqlite3
import threading
import time


class DB:
    def __init__(self, db_file=None, data_dir=None):
        if db_file is None:
            data_dir = data_dir or os.path.join(os.getenv("APPDATA") or os.path.expanduser("~"), "MusicVault")
            os.makedirs(data_dir, exist_ok=True)
            db_file = os.path.join(data_dir, "musicvault.db")
        else:
            os.makedirs(os.path.dirname(os.path.abspath(db_file)), exist_ok=True)
        self.db_file = db_file
        self.con = sqlite3.connect(db_file, check_same_thread=False)
        self.lock = threading.RLock()
        self.setup()

    def setup(self):
        with self.lock:
            self.con.executescript("""
            CREATE TABLE IF NOT EXISTS songs(
                id INTEGER PRIMARY KEY,
                path TEXT UNIQUE NOT NULL,
                title TEXT, artist TEXT, album TEXT, genre TEXT, year TEXT,
                track INTEGER DEFAULT 0, disc INTEGER DEFAULT 0,
                duration REAL DEFAULT 0, artwork BLOB,
                added REAL, modified REAL
            );
            CREATE TABLE IF NOT EXISTS playlists(
                id INTEGER PRIMARY KEY, name TEXT UNIQUE NOT NULL, created REAL
            );
            CREATE TABLE IF NOT EXISTS playlist_songs(
                playlist_id INTEGER, song_id INTEGER, position INTEGER,
                PRIMARY KEY(playlist_id,song_id)
            );
            CREATE TABLE IF NOT EXISTS favorites(song_id INTEGER PRIMARY KEY);
            CREATE TABLE IF NOT EXISTS reactions(
                song_id INTEGER PRIMARY KEY,
                reaction INTEGER NOT NULL DEFAULT 0
            );
            CREATE TABLE IF NOT EXISTS history(
                id INTEGER PRIMARY KEY, song_id INTEGER, played_at REAL
            );
            CREATE TABLE IF NOT EXISTS positions(song_id INTEGER PRIMARY KEY, seconds REAL);
            CREATE TABLE IF NOT EXISTS ratings(
                song_id INTEGER PRIMARY KEY,
                rating INTEGER NOT NULL DEFAULT 0 CHECK(rating BETWEEN 0 AND 5)
            );
            CREATE INDEX IF NOT EXISTS idx_songs_title ON songs(title COLLATE NOCASE);
            CREATE INDEX IF NOT EXISTS idx_songs_artist ON songs(artist COLLATE NOCASE);
            CREATE INDEX IF NOT EXISTS idx_songs_album ON songs(album COLLATE NOCASE);
            CREATE INDEX IF NOT EXISTS idx_songs_genre ON songs(genre COLLATE NOCASE);
            CREATE INDEX IF NOT EXISTS idx_songs_added ON songs(added);
            CREATE INDEX IF NOT EXISTS idx_history_song_time ON history(song_id, played_at);
            """)
            self.con.commit()

    def all(self):
        with self.lock:
            rows = self.con.execute("""
            SELECT id,path,title,artist,album,genre,year,track,disc,duration,artwork,added,modified
            FROM songs
            """).fetchall()
        return [self.song(row) for row in rows]

    def song(self, row):
        keys = ["id", "path", "title", "artist", "album", "genre", "year", "track", "disc",
                "duration", "artwork", "added", "modified"]
        return dict(zip(keys, row))

    def existing_mtimes(self):
        with self.lock:
            return {path: (sid, modified) for sid, path, modified in
                    self.con.execute("SELECT id,path,modified FROM songs")}

    def upsert(self, data):
        with self.lock:
            self.con.execute("""
            INSERT INTO songs(path,title,artist,album,genre,year,track,disc,duration,artwork,added,modified)
            VALUES(?,?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(path) DO UPDATE SET
            title=excluded.title,artist=excluded.artist,album=excluded.album,
            genre=excluded.genre,year=excluded.year,track=excluded.track,disc=excluded.disc,
            duration=excluded.duration,artwork=excluded.artwork,modified=excluded.modified
            """, (data["path"], data["title"], data["artist"], data["album"], data["genre"],
                  data["year"], data["track"], data["disc"], data["duration"], data["artwork"],
                  time.time(), data["modified"]))
            self.con.commit()

    def remove_missing(self, valid):
        with self.lock:
            valid = set(valid)
            rows = self.con.execute("SELECT id,path FROM songs").fetchall()
            gone = [sid for sid, path in rows if path not in valid]
            for sid in gone:
                for table in ("playlist_songs", "favorites", "reactions", "positions", "ratings", "history"):
                    self.con.execute(f"DELETE FROM {table} WHERE song_id=?", (sid,))
                self.con.execute("DELETE FROM songs WHERE id=?", (sid,))
            self.con.commit()

    def favorites(self):
        with self.lock:
            return {row[0] for row in self.con.execute("SELECT song_id FROM favorites")}

    def toggle_favorite(self, sid):
        with self.lock:
            if self.con.execute("SELECT 1 FROM favorites WHERE song_id=?", (sid,)).fetchone():
                self.con.execute("DELETE FROM favorites WHERE song_id=?", (sid,))
            else:
                self.con.execute("INSERT OR IGNORE INTO favorites VALUES(?)", (sid,))
            self.con.commit()

    def reaction(self, sid):
        with self.lock:
            row = self.con.execute("SELECT reaction FROM reactions WHERE song_id=?", (sid,)).fetchone()
        return int(row[0]) if row else 0

    def set_reaction(self, sid, value):
        with self.lock:
            if int(value) == 0:
                self.con.execute("DELETE FROM reactions WHERE song_id=?", (sid,))
            else:
                self.con.execute("""
                    INSERT INTO reactions(song_id,reaction) VALUES(?,?)
                    ON CONFLICT(song_id) DO UPDATE SET reaction=excluded.reaction
                """, (sid, int(value)))
            self.con.commit()

    def reactions(self):
        with self.lock:
            return {sid: int(value) for sid, value in
                    self.con.execute("SELECT song_id,reaction FROM reactions")}

    def rating(self, sid):
        with self.lock:
            row = self.con.execute("SELECT rating FROM ratings WHERE song_id=?", (sid,)).fetchone()
        return int(row[0]) if row else 0

    def set_rating(self, sid, value):
        with self.lock:
            value = max(0, min(5, int(value)))
            if value == 0:
                self.con.execute("DELETE FROM ratings WHERE song_id=?", (sid,))
            else:
                self.con.execute("""
                    INSERT INTO ratings(song_id,rating) VALUES(?,?)
                    ON CONFLICT(song_id) DO UPDATE SET rating=excluded.rating
                """, (sid, value))
            self.con.commit()

    def ratings(self):
        with self.lock:
            return {sid: int(value) for sid, value in self.con.execute("SELECT song_id,rating FROM ratings")}

    def history_songs(self, limit=50, incomplete=False):
        condition = "AND COALESCE(p.seconds, 0) > 0" if incomplete else ""
        with self.lock:
            rows = self.con.execute(f"""
                SELECT s.id,s.path,s.title,s.artist,s.album,s.genre,s.year,s.track,s.disc,
                       s.duration,s.artwork,s.added,s.modified
                FROM songs s JOIN history h ON h.song_id=s.id
                LEFT JOIN positions p ON p.song_id=s.id
                WHERE 1=1 {condition}
                GROUP BY s.id ORDER BY MAX(h.played_at) DESC LIMIT ?
            """, (limit,)).fetchall()
        return [self.song(row) for row in rows]

    def recently_added(self, limit=50):
        with self.lock:
            rows = self.con.execute("""
                SELECT id,path,title,artist,album,genre,year,track,disc,duration,artwork,added,modified
                FROM songs ORDER BY added DESC LIMIT ?
            """, (limit,)).fetchall()
        return [self.song(row) for row in rows]

    def liked_songs(self, limit=50):
        with self.lock:
            rows = self.con.execute("""
                SELECT s.id,s.path,s.title,s.artist,s.album,s.genre,s.year,s.track,s.disc,
                       s.duration,s.artwork,s.added,s.modified
                FROM songs s JOIN reactions r ON r.song_id=s.id
                WHERE r.reaction=1 ORDER BY lower(s.title) LIMIT ?
            """, (limit,)).fetchall()
        return [self.song(row) for row in rows]

    def never_played(self, limit=50):
        with self.lock:
            rows = self.con.execute("""
                SELECT s.id,s.path,s.title,s.artist,s.album,s.genre,s.year,s.track,s.disc,
                       s.duration,s.artwork,s.added,s.modified
                FROM songs s LEFT JOIN history h ON h.song_id=s.id
                WHERE h.id IS NULL ORDER BY s.added DESC LIMIT ?
            """, (limit,)).fetchall()
        return [self.song(row) for row in rows]

    def song_stats(self, sid):
        with self.lock:
            row = self.con.execute("""
                SELECT COUNT(*), MIN(played_at), MAX(played_at)
                FROM history WHERE song_id=?
            """, (sid,)).fetchone()
        return {"plays": row[0] or 0, "first_played": row[1], "last_played": row[2]}

    def health_summary(self):
        with self.lock:
            rows = self.con.execute("SELECT path,title,artist,album,genre,artwork FROM songs").fetchall()
            duplicate_groups = self.con.execute("""
                SELECT lower(title), lower(artist), lower(album), CAST(duration AS INTEGER), COUNT(*)
                FROM songs
                GROUP BY lower(title), lower(artist), lower(album), CAST(duration AS INTEGER)
                HAVING COUNT(*) > 1
            """).fetchall()
        return {
            "total_songs": len(rows),
            "total_albums": len({(row[2], row[3]) for row in rows}),
            "total_artists": len({row[2] for row in rows}),
            "files_ok": sum(os.path.exists(row[0]) for row in rows),
            "missing_files": sum(not os.path.exists(row[0]) for row in rows),
            "missing_metadata": sum(any(not str(value or "").strip() or str(value).startswith("Unknown")
                                       for value in row[1:5]) for row in rows),
            "missing_artwork": sum(not row[5] for row in rows),
            "duplicate_groups": len(duplicate_groups),
        }

    def create_playlist(self, name):
        with self.lock:
            try:
                self.con.execute("INSERT INTO playlists(name,created) VALUES(?,?)", (name, time.time()))
                self.con.commit()
                return True
            except sqlite3.IntegrityError:
                return False

    def playlists(self):
        with self.lock:
            return self.con.execute("SELECT id,name FROM playlists ORDER BY lower(name)").fetchall()

    def delete_playlist(self, name):
        with self.lock:
            row = self.con.execute("SELECT id FROM playlists WHERE name=?", (name,)).fetchone()
            if row:
                self.con.execute("DELETE FROM playlist_songs WHERE playlist_id=?", (row[0],))
                self.con.execute("DELETE FROM playlists WHERE id=?", (row[0],))
                self.con.commit()

    def add_to_playlist(self, name, sid):
        with self.lock:
            row = self.con.execute("SELECT id FROM playlists WHERE name=?", (name,)).fetchone()
            if not row:
                return
            position = self.con.execute(
                "SELECT COALESCE(MAX(position),-1)+1 FROM playlist_songs WHERE playlist_id=?", (row[0],)
            ).fetchone()[0]
            self.con.execute("INSERT OR IGNORE INTO playlist_songs VALUES(?,?,?)", (row[0], sid, position))
            self.con.commit()

    def remove_from_playlist(self, name, sid):
        with self.lock:
            row = self.con.execute("SELECT id FROM playlists WHERE name=?", (name,)).fetchone()
            if row:
                self.con.execute("DELETE FROM playlist_songs WHERE playlist_id=? AND song_id=?", (row[0], sid))
                self.con.commit()

    def playlist(self, name):
        with self.lock:
            rows = self.con.execute("""
            SELECT s.id,s.path,s.title,s.artist,s.album,s.genre,s.year,s.track,s.disc,
                   s.duration,s.artwork,s.added,s.modified
            FROM songs s JOIN playlist_songs ps ON ps.song_id=s.id
            JOIN playlists p ON p.id=ps.playlist_id
            WHERE p.name=? ORDER BY ps.position
            """, (name,)).fetchall()
        return [self.song(row) for row in rows]

    def add_history(self, sid):
        with self.lock:
            self.con.execute("INSERT INTO history(song_id,played_at) VALUES(?,?)", (sid, time.time()))
            self.con.commit()

    def most_played(self, limit=200):
        with self.lock:
            rows = self.con.execute("""
            SELECT s.id,s.path,s.title,s.artist,s.album,s.genre,s.year,s.track,s.disc,
                   s.duration,s.artwork,s.added,s.modified,COUNT(h.id) AS plays
            FROM songs s LEFT JOIN history h ON h.song_id=s.id
            GROUP BY s.id ORDER BY plays DESC, lower(s.title) LIMIT ?
            """, (limit,)).fetchall()
        return [self.song(row[:13]) | {"plays": row[13]} for row in rows]

    def get_position(self, sid):
        with self.lock:
            row = self.con.execute("SELECT seconds FROM positions WHERE song_id=?", (sid,)).fetchone()
        return float(row[0]) if row else 0.0

    def set_position(self, sid, seconds):
        with self.lock:
            self.con.execute("""
            INSERT INTO positions(song_id,seconds) VALUES(?,?)
            ON CONFLICT(song_id) DO UPDATE SET seconds=excluded.seconds
            """, (sid, max(0, float(seconds))))
            self.con.commit()

    def export_data(self):
        with self.lock:
            tables = {
                "songs": self.con.execute("SELECT id,path,title,artist,album,genre,year,track,disc,duration,added,modified FROM songs").fetchall(),
                "playlists": self.con.execute("SELECT id,name,created FROM playlists").fetchall(),
                "playlist_songs": self.con.execute("SELECT playlist_id,song_id,position FROM playlist_songs").fetchall(),
                "favorites": [row[0] for row in self.con.execute("SELECT song_id FROM favorites")],
                "reactions": self.con.execute("SELECT song_id,reaction FROM reactions").fetchall(),
                "ratings": self.con.execute("SELECT song_id,rating FROM ratings").fetchall(),
                "history": self.con.execute("SELECT song_id,played_at FROM history ORDER BY played_at").fetchall(),
                "positions": self.con.execute("SELECT song_id,seconds FROM positions").fetchall(),
            }
        return {
            "version": 1, "exported_at": time.time(),
            "songs": [dict(zip(("id","path","title","artist","album","genre","year","track","disc","duration","added","modified"), row)) for row in tables["songs"]],
            "playlists": [dict(zip(("id","name","created"), row)) for row in tables["playlists"]],
            "playlist_songs": [dict(zip(("playlist_id","song_id","position"), row)) for row in tables["playlist_songs"]],
            "favorites": tables["favorites"],
            "reactions": [list(row) for row in tables["reactions"]],
            "ratings": [list(row) for row in tables["ratings"]],
            "history": [list(row) for row in tables["history"]],
            "positions": [list(row) for row in tables["positions"]],
        }

    def backup_to(self, target_path):
        with self.lock:
            with sqlite3.connect(target_path) as destination:
                self.con.backup(destination)

    def restore_from(self, source_path):
        with self.lock:
            with sqlite3.connect(source_path) as source:
                source.backup(self.con)
                self.con.commit()

    def close(self):
        with self.lock:
            self.con.close()
