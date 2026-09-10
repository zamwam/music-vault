import os
import sys
import io
import json
import time
import random
import re
import shutil
import sqlite3
import threading
import subprocess
import tkinter as tk
from tkinter import ttk, filedialog, messagebox, simpledialog

try:
    import pygame
except ImportError:
    pygame = None

try:
    from mutagen import File as MutagenFile
except ImportError:
    MutagenFile = None

try:
    from PIL import Image, ImageTk, ImageDraw
except ImportError:
    Image = ImageTk = ImageDraw = None


APP_NAME = "MusicVault"
DATA_DIR = os.path.join(os.getenv("APPDATA") or os.path.expanduser("~"), APP_NAME)
DB_FILE = os.path.join(DATA_DIR, "musicvault.db")
SETTINGS_FILE = os.path.join(DATA_DIR, "settings.json")

EXTENSIONS = {
    ".mp3", ".wav", ".flac", ".m4a", ".aac", ".ogg", ".opus",
    ".wma", ".aiff", ".aif", ".ape", ".wv", ".mka"
}


def ensure_data():
    os.makedirs(DATA_DIR, exist_ok=True)


def load_settings():
    ensure_data()
    d = {
        "music_folders": [],
        "auto_scan": True,
        "volume": 0.75,
        "accent": "blue",
        "sort": "Title",
        "sort_desc": False,
        "resume": True,
        "scan_hidden": False,
        "confirm_delete_playlist": True,
        "confirm_remove_favorite": False,
        "show_album_strip": True,
        "show_status_bar": True,
        "remember_shuffle": True,
        "remember_repeat": True,
        "smooth_ui": True,
        "reduced_motion": False,
        "density": "Comfortable",
        "library_page_size": 250,
        "startup_view": "Home",
        "player_height": "Standard",
        "home_artwork_size": "Medium",
        "home_sections": {
            "continue": True, "played": True, "added": True, "most": True,
            "favorites": True, "liked": True, "never": True,
        },
        "shuffle_mode": "Random",
        "crossfade": 0,
        "sleep_timer": 0,
    }
    try:
        with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
            d.update(json.load(f))
    except Exception:
        pass
    return d


def save_settings(d):
    ensure_data()
    with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
        json.dump(d, f, indent=2)


def normalize(path):
    return os.path.normcase(os.path.abspath(path))


def clean(value, fallback="Unknown"):
    if value is None:
        return fallback
    if isinstance(value, (list, tuple)):
        value = value[0] if value else fallback
    value = str(value).strip()
    return value or fallback


def tag(tags, keys, fallback):
    if not tags:
        return fallback
    for key in keys:
        try:
            if key in tags:
                return clean(tags[key], fallback)
        except Exception:
            pass
    return fallback


def seconds_text(v):
    try:
        v = int(max(0, v))
    except Exception:
        v = 0
    return f"{v // 60}:{v % 60:02d}"


def metadata(path):
    base = os.path.splitext(os.path.basename(path))[0]
    d = {
        "path": normalize(path),
        "title": base,
        "artist": "Unknown Artist",
        "album": "Unknown Album",
        "genre": "Unknown Genre",
        "year": "",
        "track": 0,
        "disc": 0,
        "duration": 0.0,
        "artwork": None,
        "modified": os.path.getmtime(path),
    }

    if not MutagenFile:
        return d

    try:
        audio = MutagenFile(path, easy=False)
        if not audio:
            return d

        info = getattr(audio, "info", None)
        d["duration"] = float(getattr(info, "length", 0) or 0)
        tags = getattr(audio, "tags", None)

        d["title"] = tag(tags, ["TIT2", "title", "\xa9nam"], base)
        d["artist"] = tag(tags, ["TPE1", "artist", "\xa9ART"], "Unknown Artist")
        d["album"] = tag(tags, ["TALB", "album", "\xa9alb"], "Unknown Album")
        d["genre"] = tag(tags, ["TCON", "genre", "\xa9gen"], "Unknown Genre")
        d["year"] = tag(tags, ["TDRC", "date", "\xa9day"], "")

        try:
            d["track"] = int(str(tag(tags, ["TRCK", "tracknumber"], "0")).split("/")[0])
        except Exception:
            pass
        try:
            d["disc"] = int(str(tag(tags, ["TPOS", "discnumber"], "0")).split("/")[0])
        except Exception:
            pass

        if hasattr(audio, "pictures") and audio.pictures:
            d["artwork"] = audio.pictures[0].data
        elif tags:
            for k in ("APIC:", "covr", "artwork"):
                try:
                    if k in tags:
                        x = tags[k]
                        if isinstance(x, list):
                            x = x[0]
                        blob = getattr(x, "data", x)
                        if isinstance(blob, bytes):
                            d["artwork"] = blob
                            break
                except Exception:
                    pass
    except Exception:
        pass

    return d


class DB:
    def __init__(self):
        ensure_data()
        self.con = sqlite3.connect(DB_FILE, check_same_thread=False)
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
        return [self.song(r) for r in rows]

    def song(self, r):
        keys = ["id","path","title","artist","album","genre","year","track","disc",
                "duration","artwork","added","modified"]
        return dict(zip(keys, r))

    def existing_mtimes(self):
        with self.lock:
            return {
                p: (sid, modified)
                for sid, p, modified in self.con.execute("SELECT id,path,modified FROM songs")
            }

    def upsert(self, d):
        with self.lock:
            self.con.execute("""
            INSERT INTO songs(path,title,artist,album,genre,year,track,disc,duration,artwork,added,modified)
            VALUES(?,?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(path) DO UPDATE SET
            title=excluded.title,artist=excluded.artist,album=excluded.album,
            genre=excluded.genre,year=excluded.year,track=excluded.track,disc=excluded.disc,
            duration=excluded.duration,artwork=excluded.artwork,modified=excluded.modified
            """, (
                d["path"],d["title"],d["artist"],d["album"],d["genre"],d["year"],
                d["track"],d["disc"],d["duration"],d["artwork"],time.time(),d["modified"]
            ))
            self.con.commit()

    def remove_missing(self, valid):
        valid = set(valid)
        with self.lock:
            rows = self.con.execute("SELECT id,path FROM songs").fetchall()
            gone = [sid for sid,p in rows if p not in valid]
            for sid in gone:
                self.con.execute("DELETE FROM playlist_songs WHERE song_id=?", (sid,))
                self.con.execute("DELETE FROM favorites WHERE song_id=?", (sid,))
                self.con.execute("DELETE FROM reactions WHERE song_id=?", (sid,))
                self.con.execute("DELETE FROM positions WHERE song_id=?", (sid,))
                self.con.execute("DELETE FROM ratings WHERE song_id=?", (sid,))
                self.con.execute("DELETE FROM history WHERE song_id=?", (sid,))
                self.con.execute("DELETE FROM songs WHERE id=?", (sid,))
            self.con.commit()

    def favorites(self):
        with self.lock:
            return {x[0] for x in self.con.execute("SELECT song_id FROM favorites")}

    def toggle_favorite(self, sid):
        with self.lock:
            if self.con.execute("SELECT 1 FROM favorites WHERE song_id=?", (sid,)).fetchone():
                self.con.execute("DELETE FROM favorites WHERE song_id=?", (sid,))
            else:
                self.con.execute("INSERT OR IGNORE INTO favorites VALUES(?)", (sid,))
            self.con.commit()

    def reaction(self, sid):
        with self.lock:
            r=self.con.execute("SELECT reaction FROM reactions WHERE song_id=?", (sid,)).fetchone()
        return int(r[0]) if r else 0

    def set_reaction(self, sid, value):
        value=int(value)
        with self.lock:
            if value == 0:
                self.con.execute("DELETE FROM reactions WHERE song_id=?", (sid,))
            else:
                self.con.execute(
                    "INSERT INTO reactions(song_id,reaction) VALUES(?,?) "
                    "ON CONFLICT(song_id) DO UPDATE SET reaction=excluded.reaction",
                    (sid,value)
                )
            self.con.commit()

    def reactions(self):
        with self.lock:
            return {sid:int(v) for sid,v in self.con.execute("SELECT song_id,reaction FROM reactions")}

    def rating(self, sid):
        with self.lock:
            row = self.con.execute("SELECT rating FROM ratings WHERE song_id=?", (sid,)).fetchone()
        return int(row[0]) if row else 0

    def set_rating(self, sid, value):
        value = max(0, min(5, int(value)))
        with self.lock:
            if value == 0:
                self.con.execute("DELETE FROM ratings WHERE song_id=?", (sid,))
            else:
                self.con.execute(
                    "INSERT INTO ratings(song_id,rating) VALUES(?,?) "
                    "ON CONFLICT(song_id) DO UPDATE SET rating=excluded.rating",
                    (sid, value)
                )
            self.con.commit()

    def ratings(self):
        with self.lock:
            return {sid: int(value) for sid, value in self.con.execute(
                "SELECT song_id,rating FROM ratings")}

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

    def export_data(self):
        with self.lock:
            songs = self.con.execute("SELECT id,path,title,artist,album,genre,year,track,disc,duration,added,modified FROM songs").fetchall()
            playlists = self.con.execute("SELECT id,name,created FROM playlists").fetchall()
            playlist_songs = self.con.execute("SELECT playlist_id,song_id,position FROM playlist_songs").fetchall()
            favorites = [row[0] for row in self.con.execute("SELECT song_id FROM favorites")]
            reactions = self.con.execute("SELECT song_id,reaction FROM reactions").fetchall()
            ratings = self.con.execute("SELECT song_id,rating FROM ratings").fetchall()
            history = self.con.execute("SELECT song_id,played_at FROM history ORDER BY played_at").fetchall()
            positions = self.con.execute("SELECT song_id,seconds FROM positions").fetchall()
        return {
            "version": 1, "exported_at": time.time(),
            "songs": [dict(zip(("id","path","title","artist","album","genre","year","track","disc","duration","added","modified"), row)) for row in songs],
            "playlists": [dict(zip(("id","name","created"), row)) for row in playlists],
            "playlist_songs": [dict(zip(("playlist_id","song_id","position"), row)) for row in playlist_songs],
            "favorites": favorites, "reactions": [list(row) for row in reactions],
            "ratings": [list(row) for row in ratings],
            "history": [list(row) for row in history], "positions": [list(row) for row in positions],
        }

    def create_playlist(self, name):
        with self.lock:
            try:
                self.con.execute("INSERT INTO playlists(name,created) VALUES(?,?)",
                                  (name, time.time()))
                self.con.commit()
                return True
            except sqlite3.IntegrityError:
                return False

    def playlists(self):
        with self.lock:
            return self.con.execute("SELECT id,name FROM playlists ORDER BY lower(name)").fetchall()

    def delete_playlist(self, name):
        with self.lock:
            p = self.con.execute("SELECT id FROM playlists WHERE name=?", (name,)).fetchone()
            if p:
                self.con.execute("DELETE FROM playlist_songs WHERE playlist_id=?", (p[0],))
                self.con.execute("DELETE FROM playlists WHERE id=?", (p[0],))
                self.con.commit()

    def add_to_playlist(self, name, sid):
        with self.lock:
            p = self.con.execute("SELECT id FROM playlists WHERE name=?", (name,)).fetchone()
            if not p:
                return
            pos = self.con.execute(
                "SELECT COALESCE(MAX(position),-1)+1 FROM playlist_songs WHERE playlist_id=?",
                (p[0],)
            ).fetchone()[0]
            self.con.execute(
                "INSERT OR IGNORE INTO playlist_songs VALUES(?,?,?)", (p[0],sid,pos)
            )
            self.con.commit()

    def remove_from_playlist(self, name, sid):
        with self.lock:
            p = self.con.execute("SELECT id FROM playlists WHERE name=?", (name,)).fetchone()
            if p:
                self.con.execute(
                    "DELETE FROM playlist_songs WHERE playlist_id=? AND song_id=?",
                    (p[0],sid)
                )
                self.con.commit()

    def playlist(self, name):
        with self.lock:
            rows = self.con.execute("""
            SELECT s.id,s.path,s.title,s.artist,s.album,s.genre,s.year,s.track,s.disc,
                   s.duration,s.artwork,s.added,s.modified
            FROM songs s
            JOIN playlist_songs ps ON ps.song_id=s.id
            JOIN playlists p ON p.id=ps.playlist_id
            WHERE p.name=? ORDER BY ps.position
            """, (name,)).fetchall()
        return [self.song(r) for r in rows]

    def add_history(self, sid):
        with self.lock:
            self.con.execute("INSERT INTO history(song_id,played_at) VALUES(?,?)",
                             (sid,time.time()))
            self.con.commit()

    def most_played(self, limit=200):
        with self.lock:
            rows = self.con.execute("""
            SELECT s.id,s.path,s.title,s.artist,s.album,s.genre,s.year,s.track,s.disc,
                   s.duration,s.artwork,s.added,s.modified,COUNT(h.id) AS plays
            FROM songs s LEFT JOIN history h ON h.song_id=s.id
            GROUP BY s.id ORDER BY plays DESC, lower(s.title) LIMIT ?
            """, (limit,)).fetchall()
        return [self.song(r[:13]) | {"plays": r[13]} for r in rows]

    def get_position(self, sid):
        with self.lock:
            r = self.con.execute("SELECT seconds FROM positions WHERE song_id=?", (sid,)).fetchone()
        return float(r[0]) if r else 0.0

    def set_position(self, sid, seconds):
        with self.lock:
            self.con.execute("""
            INSERT INTO positions(song_id,seconds) VALUES(?,?)
            ON CONFLICT(song_id) DO UPDATE SET seconds=excluded.seconds
            """, (sid,max(0,float(seconds))))
            self.con.commit()

    def close(self):
        self.con.close()


from database import DB
from duplicate_finder import find_duplicate_groups
from organizer import apply_plan, build_plan


class MusicVault(tk.Tk):
    def __init__(self):
        super().__init__()
        self.settings = load_settings()
        self.db = DB(DB_FILE, DATA_DIR)

        self.blue = "#3b82f6"
        self.blue2 = "#60a5fa"
        self.bg = "#080b10"
        self.panel = "#10151d"
        self.panel2 = "#171e28"
        self.hover = "#222c39"
        self.text = "#f4f7fb"
        self.muted = "#8996a6"
        self.border = "#293341"

        self.title("MusicVault")
        self.geometry("1350x850")
        self.minsize(980, 650)
        self.configure(bg=self.bg)
        self.protocol("WM_DELETE_WINDOW", self.close)

        self.view = self.settings.get("startup_view", "Home")
        self.playlist_name = None
        self.visible = []
        self.library_view_state = {}
        self.pending_library_restore = None
        self.queue = []
        self.queue_index = -1
        self.current = None
        self.paused = False
        self.shuffle = False
        self.repeat = "off"
        self.shuffle_mode = self.settings.get("shuffle_mode", "Random")
        self.dragging = False
        self.user_seeking = False
        self.scan_running = False
        self.scan_progress = None
        self.scan_result = None
        self.scan_error = None
        self.scan_cancel = threading.Event()
        self.scan_thread = None
        self.closing = False
        self.art_ref = None
        self.album_art_cache = {}
        self.library_cache = None
        self.refresh_job = None
        self.render_job = None
        self.render_generation = 0
        self.render_chunk = 120
        self.library_widgets = []
        self.now_playing_frame = None
        self.entity_frame = None
        self.entity_kind = None
        self.entity_songs = []
        self.health_frame = None
        self.queue_panel = None
        self.scroll_wheel_bound = False
        self.resize_job = None
        self.playback_offset = 0.0
        self.last_tick_time = time.monotonic()
        self.details_window = None
        self.now_window = None
        self.now_window_resize_job = None
        self.shuffle = bool(self.settings.get("shuffle", False)) if self.settings.get("remember_shuffle", True) else False
        self.repeat = self.settings.get("repeat", "off") if self.settings.get("remember_repeat", True) else "off"

        self.search = tk.StringVar()
        self.search.trace_add("write", lambda *_: self.schedule_refresh())
        self.sort_var = tk.StringVar(value=self.settings.get("sort", "Title"))

        self.init_audio()
        self.style_widgets()
        self.build()
        self.bind("<Configure>", self.window_resized, add="+")
        self.refresh_playlists()
        self.view_title.config(text=self.view)
        if self.view == "Home":
            self.show_home_view()
        else:
            self.show_library_view()

        if self.settings.get("auto_scan", True):
            self.after(600, self.start_scan)

        self.after(250, self.player_tick)
        self.after(250, self.scan_status_tick)

        self.bind_all("<space>", self.space_key)
        self.bind_all("<Control-f>", lambda e: self.focus_search())
        self.bind_all("<Control-l>", lambda e: self.start_scan())
        self.bind_all("<Control-i>", lambda e: self.open_track_details(self.current))
        self.bind_all("<Left>", lambda e: self.previous())
        self.bind_all("<Right>", lambda e: self.next())
        self.bind_all("<Control-Shift-F>", lambda e: self.toggle_favorite_current())
        self.bind_all("<Control-Shift-L>", lambda e: self.like_current())
        self.bind_all("<Control-Shift-D>", lambda e: self.dislike_current())
        self.bind_all("<KeyPress>", self.rating_key)

    def init_audio(self):
        if pygame:
            try:
                pygame.mixer.pre_init(44100, -16, 2, 512)
                pygame.mixer.init()
                pygame.mixer.music.set_volume(float(self.settings.get("volume", .75)))
            except Exception:
                pass

    def style_widgets(self):
        s = ttk.Style(self)
        try:
            s.theme_use("clam")
        except Exception:
            pass
        s.configure("Treeview", background=self.panel, fieldbackground=self.panel,
                    foreground=self.text,
                    rowheight=34 if self.settings.get("density", "Comfortable") == "Compact" else 44,
                    borderwidth=0,
                    font=("Segoe UI", 10))
        s.map("Treeview", background=[("selected", "#2458a6")],
              foreground=[("selected", "#ffffff")])
        s.configure("Treeview.Heading", background=self.panel2, foreground=self.muted,
                    font=("Segoe UI Semibold", 9), borderwidth=0)
        s.configure("Horizontal.TScale", background=self.panel)
        s.configure("Vertical.TScrollbar", troughcolor=self.panel,
                    background=self.panel2, bordercolor=self.panel)
        s.configure("Horizontal.TScrollbar", troughcolor=self.panel,
                    background=self.panel2, bordercolor=self.panel)

    def button(self, parent, text, command, **kw):
        background = kw.pop("bg", self.panel)
        hover_background = kw.pop("hover", self.blue2 if background == self.blue else self.hover)
        button = tk.Button(
            parent, text=text, command=command, bg=background,
            fg=kw.pop("fg", self.text), activebackground=kw.pop("activebackground", self.hover),
            activeforeground=kw.pop("activeforeground", self.text),
            relief="flat", bd=0, cursor="hand2", **kw
        )
        button.bind("<Enter>", lambda event: button.configure(bg=hover_background), add="+")
        button.bind("<Leave>", lambda event: button.configure(bg=background), add="+")
        return button

    def build(self):
        header = tk.Frame(self, bg=self.bg, height=72)
        header.pack(fill="x")
        header.pack_propagate(False)

        tk.Label(header, text="♫", bg=self.bg, fg=self.blue2,
                 font=("Segoe UI Semibold", 27)).pack(side="left", padx=(22,6))
        tk.Label(header, text="MusicVault", bg=self.bg, fg=self.text,
                 font=("Segoe UI Semibold", 19)).pack(side="left")

        search_wrap = tk.Frame(header, bg=self.panel2)
        search_wrap.pack(side="left", padx=28, ipady=1)
        tk.Label(search_wrap, text="⌕", bg=self.panel2, fg=self.muted,
                 font=("Segoe UI", 15)).pack(side="left", padx=(10,2))
        self.search_entry = tk.Entry(
            search_wrap, textvariable=self.search, bg=self.panel2, fg=self.text,
            insertbackground=self.text, relief="flat", width=43,
            font=("Segoe UI", 10)
        )
        self.search_entry.pack(side="left", ipady=9, padx=(0,10))

        self.button(header, "↻ Scan", self.start_scan, bg=self.panel2,
                    padx=13, pady=8).pack(side="right", padx=8)
        self.button(header, "⚙ Settings", self.settings_window, bg=self.panel2,
                    padx=13, pady=8).pack(side="right", padx=(8,18))

        main = tk.Frame(self, bg=self.bg)
        main.pack(fill="both", expand=True)

        side = tk.Frame(main, bg=self.panel, width=225)
        side.pack(side="left", fill="y")
        side.pack_propagate(False)
        tk.Label(side, text="BROWSE", bg=self.panel, fg=self.muted,
                 font=("Segoe UI Semibold", 9)).pack(anchor="w", padx=20, pady=(20,7))

        for name in ["Home","Songs","Albums","Artists","Genres","Recently Added","Most Played","Favorites","5 Star Songs","Library Health"]:
            self.nav_button(side, name)

        tk.Label(side, text="YOUR PLAYLISTS", bg=self.panel, fg=self.muted,
                 font=("Segoe UI Semibold", 9)).pack(anchor="w", padx=20, pady=(24,7))

        pf = tk.Frame(side, bg=self.panel)
        pf.pack(fill="both", expand=True)
        self.playlist_canvas = tk.Canvas(pf, bg=self.panel, highlightthickness=0)
        self.playlist_scroll = ttk.Scrollbar(pf, orient="vertical", command=self.playlist_canvas.yview)
        self.playlist_inner = tk.Frame(self.playlist_canvas, bg=self.panel)
        self.playlist_window = self.playlist_canvas.create_window((0,0), window=self.playlist_inner, anchor="nw")
        self.playlist_canvas.configure(yscrollcommand=self.playlist_scroll.set)
        self.playlist_inner.bind("<Configure>", lambda e: self.playlist_canvas.configure(
            scrollregion=self.playlist_canvas.bbox("all")))
        self.playlist_canvas.bind("<Configure>", lambda e: self.playlist_canvas.itemconfigure(
            self.playlist_window, width=e.width))
        self.bind_scroll_wheel(self.playlist_canvas, self.playlist_canvas)
        self.bind_scroll_wheel(self.playlist_inner, self.playlist_canvas)
        self.playlist_canvas.pack(side="left", fill="both", expand=True)
        self.playlist_scroll.pack(side="right", fill="y")

        self.button(side, "+ New Playlist", self.new_playlist, bg=self.panel,
                    fg=self.blue2, anchor="w", padx=20, pady=10).pack(fill="x", side="bottom")

        content = tk.Frame(main, bg=self.bg)
        self.content = content
        content.pack(side="left", fill="both", expand=True, padx=20, pady=14)

        top = tk.Frame(content, bg=self.bg)
        top.pack(fill="x")
        self.view_title = tk.Label(top, text="Home", bg=self.bg, fg=self.text,
                                   font=("Segoe UI Semibold", 26))
        self.view_title.pack(side="left")

        self.count = tk.Label(top, text="", bg=self.bg, fg=self.muted,
                              font=("Segoe UI", 9))
        self.count.pack(side="left", padx=12, pady=(9,0))

        sortbox = tk.Frame(top, bg=self.bg)
        sortbox.pack(side="right")
        tk.Label(sortbox, text="Sort", bg=self.bg, fg=self.muted).pack(side="left", padx=6)
        self.sort_combo = ttk.Combobox(
            sortbox, textvariable=self.sort_var,
            values=["Title","Artist","Album","Year","Rating","Duration","Date Added"],
            state="readonly", width=14
        )
        self.sort_combo.pack(side="left")
        self.sort_combo.bind("<<ComboboxSelected>>", lambda e: self.sort_changed())

        self.album_strip = tk.Frame(content, bg=self.bg, height=154)
        self.album_strip.pack(fill="x", pady=(12,8))
        self.album_strip.pack_propagate(False)

        actions = tk.Frame(content, bg=self.bg)
        actions.pack(fill="x", pady=(0,8))
        self.button(actions,"▶ Play",self.play_selected,bg=self.blue,fg="white",
                    padx=13,pady=6).pack(side="left",padx=(0,6))
        self.button(actions,"⤨ Shuffle",self.toggle_shuffle,bg=self.panel2,
                    padx=13,pady=6).pack(side="left",padx=6)
        self.button(actions,"♡ Favorite",self.toggle_selected_favorite,bg=self.panel2,
                    padx=13,pady=6).pack(side="left",padx=6)
        self.button(actions,"👍 Like",self.like_selected,bg=self.panel2,
                    padx=13,pady=6).pack(side="left",padx=6)
        self.button(actions,"👎 Dislike",self.dislike_selected,bg=self.panel2,
                    padx=13,pady=6).pack(side="left",padx=6)
        self.button(actions,"＋ Queue",self.queue_selected,bg=self.panel2,
                    padx=13,pady=6).pack(side="left",padx=6)

        table = tk.Frame(content, bg=self.panel)
        table.pack(fill="both", expand=True)
        cols = ("title","artist","album","genre","year","rating","time")
        self.tree = ttk.Treeview(table, columns=cols, show="headings", selectmode="extended")
        widths = {"title":300,"artist":180,"album":220,"genre":130,"year":65,"rating":90,"time":75}
        for c, heading in [("title","TITLE"),("artist","ARTIST"),("album","ALBUM"),
                   ("genre","GENRE"),("year","YEAR"),("rating","RATING"),("time","TIME")]:
            self.tree.heading(c, text=heading, command=lambda x=c: self.sort_column(x))
            self.tree.column(c, width=widths[c], anchor="w")
        vs = ttk.Scrollbar(table, orient="vertical", command=self.tree.yview)
        hs = ttk.Scrollbar(table, orient="horizontal", command=self.tree.xview)
        self.tree.configure(yscrollcommand=vs.set, xscrollcommand=hs.set)
        self.tree.grid(row=0,column=0,sticky="nsew")
        vs.grid(row=0,column=1,sticky="ns")
        hs.grid(row=1,column=0,sticky="ew")
        table.rowconfigure(0,weight=1)
        table.columnconfigure(0,weight=1)
        self.tree.bind("<Double-1>", self.play_selected)
        self.tree.bind("<Return>", self.play_selected)
        self.tree.bind("<Button-3>", self.context_menu)

        self.library_widgets = [top, self.album_strip, actions, table]
        self.build_player()
        self.build_queue_panel(main)
        self.build_now_playing_page(content)
        self.build_home_dashboard(content)

        self.status = tk.StringVar(value="Ready")
        self.status_label=tk.Label(self, textvariable=self.status, bg=self.bg, fg=self.muted,
                 font=("Segoe UI",8))
        if self.settings.get("show_status_bar",True):
            self.status_label.place(x=240,y=53)

    def nav_button(self, side, name):
        b = self.button(side, name, lambda n=name: self.set_view(n),
                        bg=self.panel, anchor="w", padx=20, pady=9)
        b.pack(fill="x")
        setattr(self, "nav_" + name.lower().replace(" ","_"), b)

    def bind_scroll_wheel(self, widget, canvas):
        if not self.scroll_wheel_bound:
            self.bind_all("<MouseWheel>", self.scroll_active_area, add="+")
            self.bind_all("<Button-4>", self.scroll_active_area, add="+")
            self.bind_all("<Button-5>", self.scroll_active_area, add="+")
            self.scroll_wheel_bound = True
        widget.unbind("<MouseWheel>")
        widget.unbind("<Button-4>")
        widget.unbind("<Button-5>")
        for child in widget.winfo_children():
            self.bind_scroll_wheel(child, canvas)

    def scroll_active_area(self, event):
        amount = -int(event.delta / 120) if getattr(event, "delta", 0) else (
            -1 if getattr(event, "num", 0) == 4 else 1)
        pointer_x = self.winfo_pointerx()
        pointer_y = self.winfo_pointery()
        for region, canvas in ((self.home_dashboard, self.home_canvas),
                               (self.playlist_canvas, self.playlist_canvas)):
            if not region.winfo_ismapped():
                continue
            left = region.winfo_rootx()
            top = region.winfo_rooty()
            right = left + region.winfo_width()
            bottom = top + region.winfo_height()
            if left <= pointer_x <= right and top <= pointer_y <= bottom:
                canvas.yview_scroll(amount or (-1 if getattr(event, "delta", 0) > 0 else 1), "units")
                return "break"

    def build_home_dashboard(self, parent):
        self.home_dashboard = tk.Frame(parent, bg=self.bg)
        self.home_canvas = tk.Canvas(self.home_dashboard, bg=self.bg, highlightthickness=0)
        self.home_scroll = ttk.Scrollbar(self.home_dashboard, orient="vertical",
                                         command=self.home_canvas.yview)
        self.home_inner = tk.Frame(self.home_canvas, bg=self.bg)
        self.home_window = self.home_canvas.create_window((0, 0), window=self.home_inner, anchor="nw")
        self.home_canvas.configure(yscrollcommand=self.home_scroll.set)
        self.home_inner.bind("<Configure>", lambda e: self.home_canvas.configure(
            scrollregion=self.home_canvas.bbox("all")))
        self.home_canvas.bind("<Configure>", lambda e: self.home_canvas.itemconfigure(
            self.home_window, width=e.width))
        self.bind_scroll_wheel(self.home_canvas, self.home_canvas)
        self.bind_scroll_wheel(self.home_inner, self.home_canvas)
        self.home_canvas.pack(side="left", fill="both", expand=True)
        self.home_scroll.pack(side="right", fill="y")

    def show_home_view(self):
        self.player_frame.pack(side="bottom", fill="x")
        if self.now_playing_frame:
            self.now_playing_frame.pack_forget()
        if self.entity_frame:
            self.entity_frame.pack_forget()
        if self.health_frame:
            self.health_frame.pack_forget()
        for widget in self.library_widgets:
            widget.pack_forget()
        self.home_dashboard.pack(fill="both", expand=True)
        self.refresh_home_dashboard()

    def refresh_home_dashboard(self):
        for child in self.home_inner.winfo_children():
            child.destroy()
        enabled = self.settings.get("home_sections", {})
        sections = [
            ("continue", "Continue Listening", self.db.history_songs(20, incomplete=True)),
            ("played", "Recently Played", self.db.history_songs(20)),
            ("added", "Recently Added", self.db.recently_added(20)),
            ("most", "Most Played", self.db.most_played(20)),
            ("favorites", "Favorite Songs", [s for s in self.get_library() if s["id"] in self.db.favorites()][:20]),
            ("liked", "Liked Songs", self.db.liked_songs(20)),
            ("never", "Never Played", self.db.never_played(20)),
        ]
        has_content = False
        reveal_delay = 0
        for key, title, songs in sections:
            if enabled.get(key, True) and songs:
                block = self.home_section(title, songs)
                if self.settings.get("smooth_ui", True) and not self.settings.get("reduced_motion", False):
                    block.pack_forget()
                    self.after(reveal_delay, lambda item=block: item.pack(fill="x", pady=(8, 18)))
                    reveal_delay += 45
                has_content = True
        if not has_content:
            tk.Label(self.home_inner, text="Your Home dashboard will fill up as you add and play music.",
                     bg=self.bg, fg=self.muted, font=("Segoe UI", 11)).pack(pady=50)

    def home_section(self, title, songs):
        block = tk.Frame(self.home_inner, bg=self.bg)
        block.pack(fill="x", pady=(8, 18))
        compact = self.settings.get("density", "Comfortable") == "Compact"
        card_width = 126 if compact else 142
        card_height = 140 if compact else 155
        artwork_sizes = {"Small": 82, "Medium": 106, "Large": 124}
        art_size = artwork_sizes.get(self.settings.get("home_artwork_size", "Medium"), 106)
        if compact:
            art_size = min(art_size, 92)
        rail_height = 155 if compact else 170
        tk.Label(block, text=title, bg=self.bg, fg=self.text,
                 font=("Segoe UI Semibold", 14)).pack(anchor="w", pady=(0, 8))
        canvas = tk.Canvas(block, height=rail_height, bg=self.bg, highlightthickness=0)
        inner = tk.Frame(canvas, bg=self.bg)
        window = canvas.create_window((0, 0), window=inner, anchor="nw")
        hbar = ttk.Scrollbar(block, orient="horizontal", command=canvas.xview)
        canvas.configure(xscrollcommand=hbar.set)
        canvas.pack(fill="x")
        hbar.pack(fill="x")
        inner.bind("<Configure>", lambda e, c=canvas: c.configure(scrollregion=c.bbox("all")))
        canvas.bind("<Configure>", lambda e, c=canvas, w=window: c.itemconfigure(w, height=rail_height - 5))
        for song in songs:
            card = tk.Frame(inner, bg=self.panel, width=card_width, height=card_height, cursor="hand2")
            card.pack(side="left", padx=(0, 10))
            card.pack_propagate(False)
            art = self.make_art(song.get("artwork"), art_size)
            image = tk.Label(card, image=art, text="♫" if art is None else "", bg=self.panel,
                             fg=self.blue2, font=("Segoe UI", 24), cursor="hand2")
            image.image = art
            image.pack(pady=(8, 4))
            tk.Label(card, text=song["title"][:22], bg=self.panel, fg=self.text,
                     font=("Segoe UI Semibold", 8), anchor="w").pack(fill="x", padx=8)
            tk.Label(card, text=song["artist"][:22], bg=self.panel, fg=self.muted,
                     font=("Segoe UI", 8), anchor="w").pack(fill="x", padx=8)
            for widget in (card, image):
                widget.bind("<Button-1>", lambda e, s=song: self.select_song_from_card(s))
                widget.bind("<Double-Button-1>", lambda e, s=song: self.play_card_song(s))
            self.bind_scroll_wheel(card, self.home_canvas)
        return block

    def select_song_from_card(self, song):
        self.queue = self.queue or self.get_library()
        self.status.set(f'Selected "{song["title"]}"')

    def play_card_song(self, song):
        if not self.queue:
            self.queue = self.get_library()
        self.queue_index = next((i for i, item in enumerate(self.queue)
                                 if item["id"] == song["id"]), 0)
        self.play(song)
        self.show_now_playing()

    def build_player(self):
        heights = {"Compact": 104, "Standard": 128, "Tall": 154}
        p = tk.Frame(self, bg=self.panel, height=heights.get(
            self.settings.get("player_height", "Standard"), 128))
        self.player_frame = p
        p.pack(side="bottom", fill="x")
        p.pack_propagate(False)

        self.art = tk.Label(p, text="♫", bg=self.panel2, fg=self.blue2,
                            width=7, height=4, font=("Segoe UI",20))
        self.art.pack(side="left", padx=15, pady=10)
        self.art.bind("<Button-1>", lambda e: self.show_now_playing())

        info = tk.Frame(p, bg=self.panel, width=250)
        info.pack(side="left", fill="y", pady=18)
        info.pack_propagate(False)
        self.now_title = tk.Label(info, text="Nothing playing", bg=self.panel,
                                  fg=self.text, font=("Segoe UI Semibold",11),
                                  anchor="w")
        self.now_title.pack(fill="x")
        self.now_title.bind("<Button-1>", lambda e: self.show_now_playing())
        self.now_artist = tk.Label(info, text="", bg=self.panel, fg=self.muted,
                                   font=("Segoe UI",9), anchor="w")
        self.now_artist.pack(fill="x", pady=3)
        self.now_artist.bind("<Button-1>", lambda e: self.show_now_playing())

        center = tk.Frame(p, bg=self.panel)
        center.pack(side="left", fill="both", expand=True)
        controls = tk.Frame(center, bg=self.panel)
        controls.pack(pady=(7,0))
        self.shuffle_btn = self.player_button(controls,"⤨",self.toggle_shuffle)
        self.player_button(controls,"◀◀",self.previous)
        self.play_btn = tk.Button(controls,text="▶",command=self.toggle_play,
                                  bg=self.blue,fg="white",activebackground=self.blue2,
                                  relief="flat",width=4,font=("Segoe UI Semibold",12),
                                  cursor="hand2")
        self.play_btn.pack(side="left",padx=9)
        self.player_button(controls,"▶▶",self.next)
        self.repeat_btn = self.player_button(controls,"↻",self.toggle_repeat)
        self.like_btn = self.player_button(controls,"♡",self.like_current)
        self.dislike_btn = self.player_button(controls,"♧",self.dislike_current)
        self.fav_btn = self.player_button(controls,"☆",self.toggle_favorite_current)
        self.player_button(controls,"☷ Queue",self.toggle_queue_panel)

        timeline = tk.Frame(center, bg=self.panel)
        timeline.pack(fill="x", padx=22)
        self.elapsed = tk.Label(timeline,text="0:00",bg=self.panel,fg=self.muted,
                                font=("Segoe UI",8))
        self.elapsed.pack(side="left")

        self.seek_var = tk.DoubleVar(value=0)
        self.seekbar = ttk.Scale(timeline,from_=0,to=100,orient="horizontal",
                                 variable=self.seek_var, command=self.seek_moving)
        self.seekbar.pack(side="left",fill="x",expand=True,padx=10)
        self.seekbar.bind("<ButtonPress-1>", self.seek_press)
        self.seekbar.bind("<ButtonRelease-1>", self.seek_release)

        self.total = tk.Label(timeline,text="0:00",bg=self.panel,fg=self.muted,
                              font=("Segoe UI",8))
        self.total.pack(side="right")

        vol = tk.Frame(p,bg=self.panel)
        vol.pack(side="right",padx=18)
        tk.Label(vol,text="VOL",bg=self.panel,fg=self.muted,
                 font=("Segoe UI Semibold",8)).pack()
        self.volume = ttk.Scale(vol,from_=0,to=1,orient="horizontal",
                                value=float(self.settings.get("volume",.75)),
                                command=self.set_volume,length=110)
        self.volume.pack()

    def player_button(self,parent,text,command):
        b=self.button(parent,text,command,bg=self.panel,fg=self.muted,
                      activebackground=self.panel,activeforeground=self.blue2,
                      font=("Segoe UI",12),padx=8,pady=4)
        b.pack(side="left",padx=6)
        return b

    def build_queue_panel(self, parent):
        self.queue_panel = tk.Frame(parent, bg=self.panel, width=290)
        self.queue_panel.pack_propagate(False)
        header = tk.Frame(self.queue_panel, bg=self.panel)
        header.pack(fill="x", padx=14, pady=(16, 8))
        tk.Label(header, text="QUEUE", bg=self.panel, fg=self.blue2,
                 font=("Segoe UI Semibold", 10)).pack(side="left")
        self.button(header, "Clear", self.clear_queue, bg=self.panel2,
                    fg=self.muted, padx=8, pady=3).pack(side="right")
        self.queue_list = tk.Listbox(self.queue_panel, bg=self.panel, fg=self.text,
                                     selectbackground="#2458a6", relief="flat",
                                     activestyle="none", font=("Segoe UI", 9))
        self.queue_list.pack(fill="both", expand=True, padx=10, pady=4)
        self.queue_list.bind("<Double-1>", self.play_queue_item)
        self.queue_list.bind("<ButtonPress-1>", self.queue_drag_start)
        self.queue_list.bind("<B1-Motion>", self.queue_drag_motion)
        footer = tk.Frame(self.queue_panel, bg=self.panel)
        footer.pack(fill="x", padx=10, pady=10)
        tools = tk.Frame(self.queue_panel, bg=self.panel)
        tools.pack(fill="x", padx=10)
        for label, command in (("Remove", self.remove_queue_item), ("Up", lambda: self.move_queue_item(-1)),
                               ("Down", lambda: self.move_queue_item(1))):
            self.button(tools, label, command, bg=self.panel2, padx=7, pady=4).pack(side="left", padx=(0, 4))
        tools2 = tk.Frame(self.queue_panel, bg=self.panel)
        tools2.pack(fill="x", padx=10, pady=(5, 0))
        for label, command in (("Shuffle", self.shuffle_queue), ("Reverse", self.reverse_queue),
                               ("Dedupe", self.deduplicate_queue), ("Clear after", self.clear_after_current)):
            self.button(tools2, label, command, bg=self.panel2, padx=5, pady=4).pack(side="left", padx=(0, 3))
        self.button(footer, "Save Queue", self.save_queue_as_playlist,
                    bg=self.blue, fg="white", padx=10, pady=6).pack(side="left")
        self.button(footer, "×", self.toggle_queue_panel, bg=self.panel2,
                    fg=self.muted, width=3, pady=6).pack(side="right")

    def toggle_queue_panel(self):
        if self.queue_panel.winfo_manager():
            self.queue_panel.pack_forget()
        else:
            self.queue_panel.pack(side="right", fill="y", before=self.content)
            self.refresh_queue_panel()

    def refresh_queue_panel(self):
        if not hasattr(self, "queue_list"):
            return
        self.queue_list.delete(0, "end")
        if self.current:
            self.queue_list.insert("end", f"NOW PLAYING  •  {self.current['title']}")
        for index, song in enumerate(self.queue):
            marker = "▶ " if index == self.queue_index else "   "
            self.queue_list.insert("end", f"{marker}{song['title']}  •  {song['artist']}")

    def clear_queue(self):
        self.queue = [self.current] if self.current else []
        self.queue_index = 0 if self.current else -1
        self.refresh_queue_panel()
        self.status.set("Queue cleared")

    def play_queue_item(self, event=None):
        selection = self.queue_list.curselection()
        if not selection:
            return
        index = selection[0] - (1 if self.current else 0)
        if 0 <= index < len(self.queue):
            self.queue_index = index
            self.play(self.queue[index])

    def queue_data_index(self):
        selection = self.queue_list.curselection()
        if not selection:
            return None
        index = selection[0] - (1 if self.current else 0)
        return index if 0 <= index < len(self.queue) else None

    def queue_drag_start(self, event):
        self.queue_drag_index = self.queue_data_index()

    def queue_drag_motion(self, event):
        source = getattr(self, "queue_drag_index", None)
        if source is None:
            return
        target_row = self.queue_list.nearest(event.y)
        target = target_row - (1 if self.current else 0)
        if target == source or not 0 <= target < len(self.queue):
            return
        if source == self.queue_index or target == self.queue_index:
            return
        item = self.queue.pop(source)
        self.queue.insert(target, item)
        self.queue_drag_index = target
        self.refresh_queue_panel()
        self.queue_list.selection_set(target + (1 if self.current else 0))

    def remove_queue_item(self):
        index = self.queue_data_index()
        if index is None or index == self.queue_index:
            return
        self.queue.pop(index)
        if index < self.queue_index:
            self.queue_index -= 1
        self.refresh_queue_panel()

    def move_queue_item(self, direction):
        index = self.queue_data_index()
        target = (index + direction) if index is not None else None
        if index is None or target is None or not 0 <= target < len(self.queue):
            return
        if index == self.queue_index or target == self.queue_index:
            return
        self.queue[index], self.queue[target] = self.queue[target], self.queue[index]
        self.refresh_queue_panel()
        self.queue_list.selection_set(target + (1 if self.current else 0))

    def shuffle_queue(self):
        current = self.queue[self.queue_index] if 0 <= self.queue_index < len(self.queue) else None
        remaining = [song for index, song in enumerate(self.queue) if index != self.queue_index]
        random.shuffle(remaining)
        self.queue = ([current] + remaining) if current else remaining
        self.queue_index = 0 if current else -1
        self.refresh_queue_panel()

    def reverse_queue(self):
        current = self.queue[self.queue_index] if 0 <= self.queue_index < len(self.queue) else None
        remaining = list(reversed([song for index, song in enumerate(self.queue) if index != self.queue_index]))
        self.queue = ([current] + remaining) if current else remaining
        self.queue_index = 0 if current else -1
        self.refresh_queue_panel()

    def deduplicate_queue(self):
        seen = set()
        current = self.queue[self.queue_index] if 0 <= self.queue_index < len(self.queue) else None
        unique = []
        for song in self.queue:
            if song["id"] not in seen:
                seen.add(song["id"])
                unique.append(song)
        self.queue = unique
        self.queue_index = next((i for i, song in enumerate(self.queue)
                                 if current and song["id"] == current["id"]), -1)
        self.refresh_queue_panel()

    def clear_after_current(self):
        if 0 <= self.queue_index < len(self.queue):
            self.queue = self.queue[:self.queue_index + 1]
            self.refresh_queue_panel()

    def save_queue_as_playlist(self):
        songs = [song for song in self.queue if song]
        if not songs:
            return
        name = simpledialog.askstring("Save Queue", "Playlist name:", parent=self)
        if not name or not name.strip() or not self.db.create_playlist(name.strip()):
            return
        for song in songs:
            self.db.add_to_playlist(name.strip(), song["id"])
        self.refresh_playlists()
        self.status.set(f'Saved queue as "{name.strip()}"')

    def build_now_playing_page(self, parent):
        self.now_playing_frame = tk.Frame(parent, bg=self.bg)
        header = tk.Frame(self.now_playing_frame, bg=self.bg)
        header.pack(fill="x", pady=(4, 14))
        self.button(header, "‹ Library", self.show_library_view, bg=self.panel2,
                    fg=self.text, padx=12, pady=6).pack(side="left")
        tk.Label(header, text="NOW PLAYING", bg=self.bg, fg=self.blue2,
                 font=("Segoe UI Semibold", 10)).pack(side="right", pady=8)

        body = tk.Frame(self.now_playing_frame, bg=self.bg)
        body.pack(fill="both", expand=True)
        self.np_art = tk.Label(body, text="♫", bg=self.panel2, fg=self.blue2,
                               font=("Segoe UI", 58))
        self.np_art.pack(pady=(18, 16))
        self.np_title = tk.Label(body, text="Nothing playing", bg=self.bg, fg=self.text,
                                 font=("Segoe UI Semibold", 25), wraplength=650)
        self.np_title.pack()
        self.np_artist = tk.Label(body, text="", bg=self.bg, fg=self.blue2,
                                  font=("Segoe UI Semibold", 12))
        self.np_artist.pack(pady=(5, 0))
        self.np_album = tk.Label(body, text="", bg=self.bg, fg=self.muted,
                                 font=("Segoe UI", 10))
        self.np_album.pack(pady=(2, 12))
        self.np_rating = tk.Label(body, text="☆☆☆☆☆", bg=self.bg, fg="#fbbf24",
                                  font=("Segoe UI", 20), cursor="hand2")
        self.np_rating.pack(pady=(0, 12))
        self.np_rating.bind("<Button-1>", lambda e: self.rate_current(0))
        self.np_stats = tk.Label(body, text="", bg=self.bg, fg=self.muted,
                                 font=("Segoe UI", 9))
        self.np_stats.pack(pady=(0, 16))
        timeline = tk.Frame(body, bg=self.bg)
        self.np_timeline = timeline
        timeline.pack(fill="x", padx=38, pady=(0, 14))
        self.np_elapsed = tk.Label(timeline, text="0:00", bg=self.bg, fg=self.muted,
                       font=("Segoe UI", 8))
        self.np_elapsed.pack(side="left")
        self.np_seekbar = ttk.Scale(timeline, from_=0, to=100, orient="horizontal",
                        variable=self.seek_var, command=self.seek_moving)
        self.np_seekbar.pack(side="left", fill="x", expand=True, padx=10)
        self.np_seekbar.bind("<ButtonPress-1>", self.seek_press)
        self.np_seekbar.bind("<ButtonRelease-1>", self.seek_release)
        self.np_total = tk.Label(timeline, text="0:00", bg=self.bg, fg=self.muted,
                     font=("Segoe UI", 8))
        self.np_total.pack(side="right")
        controls = tk.Frame(body, bg=self.bg)
        self.np_controls = controls
        controls.pack()
        self.button(controls, "⤨", self.toggle_shuffle, bg=self.panel2,
                padx=9, pady=8).pack(side="left", padx=3)
        self.button(controls, "◀◀", self.previous, bg=self.panel2, padx=13, pady=8).pack(side="left", padx=5)
        self.np_play_button = self.button(controls, "▶", self.toggle_play, bg=self.blue,
                          fg="white", width=4, padx=8, pady=8)
        self.np_play_button.pack(side="left", padx=5)
        self.button(controls, "▶▶", self.next, bg=self.panel2, padx=13, pady=8).pack(side="left", padx=5)
        self.button(controls, "↻", self.toggle_repeat, bg=self.panel2,
                padx=9, pady=8).pack(side="left", padx=3)
        self.button(controls, "♡ Favorite", self.toggle_favorite_current,
                    bg=self.panel2, padx=12, pady=8).pack(side="left", padx=5)
        self.button(controls, "👍", self.like_current, bg=self.panel2,
                padx=9, pady=8).pack(side="left", padx=3)
        self.button(controls, "👎", self.dislike_current, bg=self.panel2,
                padx=9, pady=8).pack(side="left", padx=3)

    def window_resized(self, event=None):
        if self.resize_job:
            try:
                self.after_cancel(self.resize_job)
            except Exception:
                pass
        self.resize_job = self.after_idle(self.resize_now_playing)

    def resize_now_playing(self):
        self.resize_job = None
        if not self.now_playing_frame or not self.now_playing_frame.winfo_manager():
            return
        available_height = max(300, self.winfo_height() - 245)
        available_width = max(300, self.content.winfo_width() - 40)
        size = max(150, min(330, available_height * 38 // 100, available_width - 20))
        art = self.make_art(self.current.get("artwork") if self.current else None, size)
        self.np_art.config(image=art, text="" if art else "♫", width=size, height=size)
        self.np_art.image = art
        self.np_title.config(wraplength=max(300, available_width - 20))

    def show_now_playing(self):
        self.capture_library_state()
        self.player_frame.pack(side="bottom", fill="x")
        self.np_timeline.pack_forget()
        self.np_controls.pack_forget()
        for widget in self.library_widgets:
            widget.pack_forget()
        if self.home_dashboard:
            self.home_dashboard.pack_forget()
        if self.entity_frame:
            self.entity_frame.pack_forget()
        if self.health_frame:
            self.health_frame.pack_forget()
        self.refresh_now_playing_page()
        self.now_playing_frame.pack(fill="both", expand=True)
        self.update_idletasks()
        self.resize_now_playing()

    def open_now_playing_window(self):
        if not self.current:
            return
        if self.now_window and self.now_window.winfo_exists():
            self.now_window.lift()
            self.refresh_now_window()
            return
        win = tk.Toplevel(self)
        self.now_window = win
        win.title("MusicVault • Now Playing")
        screen_width = self.winfo_screenwidth()
        screen_height = self.winfo_screenheight()
        width = min(560, max(430, screen_width - 100))
        height = min(700, max(520, screen_height - 80))
        win.geometry(f"{width}x{height}")
        win.minsize(min(430, width), min(520, height))
        win.configure(bg=self.bg)
        win.transient(self)
        win.protocol("WM_DELETE_WINDOW", win.destroy)
        tk.Label(win, text="NOW PLAYING", bg=self.bg, fg=self.blue2,
                 font=("Segoe UI Semibold", 10)).pack(anchor="w", padx=26, pady=(22, 12))
        self.window_art = tk.Label(win, bg=self.panel2, fg=self.blue2, font=("Segoe UI", 48))
        self.window_art.pack(pady=(0, 18))
        self.window_title = tk.Label(win, bg=self.bg, fg=self.text,
                                     font=("Segoe UI Semibold", 20), wraplength=width - 50)
        self.window_title.pack()
        self.window_artist = tk.Label(win, bg=self.bg, fg=self.blue2,
                                      font=("Segoe UI Semibold", 11))
        self.window_artist.pack(pady=(4, 0))
        self.window_album = tk.Label(win, bg=self.bg, fg=self.muted,
                                     font=("Segoe UI", 9))
        self.window_album.pack(pady=(2, 14))
        timeline = tk.Frame(win, bg=self.bg)
        timeline.pack(fill="x", padx=26, pady=(0, 14))
        self.window_elapsed = tk.Label(timeline, text="0:00", bg=self.bg, fg=self.muted,
                                       font=("Segoe UI", 8))
        self.window_elapsed.pack(side="left")
        self.window_seekbar = ttk.Scale(timeline, from_=0, to=100, orient="horizontal",
                                        variable=self.seek_var, command=self.seek_moving)
        self.window_seekbar.pack(side="left", fill="x", expand=True, padx=10)
        self.window_seekbar.bind("<ButtonPress-1>", self.seek_press)
        self.window_seekbar.bind("<ButtonRelease-1>", self.seek_release)
        self.window_total = tk.Label(timeline, text="0:00", bg=self.bg, fg=self.muted,
                                     font=("Segoe UI", 8))
        self.window_total.pack(side="right")
        controls = tk.Frame(win, bg=self.bg)
        controls.pack()
        self.button(controls, "◀◀", self.previous, bg=self.panel2, padx=11, pady=8).pack(side="left", padx=3)
        self.window_play_button = self.button(controls, "▶", self.toggle_play, bg=self.blue,
                              fg="white", width=4, padx=8, pady=8)
        self.window_play_button.pack(side="left", padx=4)
        self.button(controls, "▶▶", self.next, bg=self.panel2, padx=11, pady=8).pack(side="left", padx=3)
        self.button(controls, "⤨", self.toggle_shuffle, bg=self.panel2, padx=9, pady=8).pack(side="left", padx=3)
        self.button(controls, "↻", self.toggle_repeat, bg=self.panel2, padx=9, pady=8).pack(side="left", padx=3)
        self.button(controls, "♡ Favorite", self.toggle_favorite_current,
                    bg=self.panel2, padx=10, pady=8).pack(side="left", padx=4)
        win.bind("<Configure>", self.now_window_resized, add="+")
        self.refresh_now_window()

    def now_window_resized(self, event=None):
        if self.now_window_resize_job:
            try:
                self.after_cancel(self.now_window_resize_job)
            except Exception:
                pass
        self.now_window_resize_job = self.after_idle(self.refresh_now_window)

    def refresh_now_window(self):
        if (not self.now_window or not self.now_window.winfo_exists() or not self.current
                or not hasattr(self, "window_art")):
            return
        self.now_window_resize_job = None
        song = self.current
        size = max(170, min(330, self.now_window.winfo_height() - 390,
                            self.now_window.winfo_width() - 70))
        art = self.make_art(song.get("artwork"), size)
        self.window_art.config(image=art, text="" if art else "♫", width=size, height=size)
        self.window_art.image = art
        self.window_title.config(text=song["title"])
        self.window_artist.config(text=song["artist"])
        self.window_album.config(text=f'{song["album"]}  •  {song["year"] or "Year unknown"}')
        self.window_seekbar.configure(to=max(1, song["duration"]))
        self.window_elapsed.config(text=seconds_text(self.seek_var.get()))
        self.window_total.config(text=seconds_text(song["duration"]))

    def show_library_view(self):
        self.player_frame.pack(side="bottom", fill="x")
        self.pending_library_restore = self.view
        if self.now_playing_frame:
            self.now_playing_frame.pack_forget()
        if self.home_dashboard:
            self.home_dashboard.pack_forget()
        if self.entity_frame:
            self.entity_frame.pack_forget()
        if self.health_frame:
            self.health_frame.pack_forget()
        for widget in self.library_widgets:
            if widget is self.album_strip and not self.settings.get("show_album_strip", True):
                continue
            widget.pack(fill="x" if widget is not self.library_widgets[-1] else "both",
                        expand=widget is self.library_widgets[-1],
                        pady=(12, 8) if widget is self.album_strip else (0, 0))
        self.refresh()

    def refresh_now_playing_page(self):
        if not self.current:
            return
        song = self.current
        art = self.make_art(song.get("artwork"), 330)
        self.np_art.config(image=art, text="" if art else "♫")
        self.np_art.image = art
        self.np_title.config(text=song["title"])
        self.np_artist.config(text=song["artist"])
        self.np_album.config(text=f'{song["album"]}  •  {song["year"] or "Year unknown"}')
        self.np_rating.config(text="★" * self.db.rating(song["id"]) + "☆" * (5 - self.db.rating(song["id"])))
        self.np_seekbar.configure(to=max(1, song["duration"]))
        self.np_total.config(text=seconds_text(song["duration"]))
        self.np_elapsed.config(text=seconds_text(self.seek_var.get()))
        stats = self.db.song_stats(song["id"])
        self.np_stats.config(text=f'{stats["plays"]} plays  •  {seconds_text(song["duration"])}  •  {os.path.splitext(song["path"])[1].upper().lstrip(".")}')

    def set_view(self, view):
        self.capture_library_state()
        self.view = view
        self.playlist_name = view.split(":",1)[1] if view.startswith("Playlist:") else None
        self.view_title.config(text=self.playlist_name or view)
        if view == "Home":
            self.show_home_view()
        elif view == "Library Health":
            self.show_health_page()
        else:
            self.show_library_view()

    def capture_library_state(self):
        if not hasattr(self, "tree") or self.view in ("Home", "Library Health"):
            return
        selected_ids = []
        for iid in self.tree.selection():
            try:
                selected_ids.append(self.visible[int(iid)]["id"])
            except (IndexError, KeyError, ValueError):
                pass
        self.library_view_state[self.view] = {
            "scroll": self.tree.yview(),
            "selected_ids": selected_ids,
        }

    def restore_library_state(self):
        state = self.library_view_state.get(self.view)
        if not state:
            return
        selected = [str(index) for index, song in enumerate(self.visible)
                    if song["id"] in state["selected_ids"]]
        if selected:
            self.tree.selection_set(selected)
            self.tree.focus(selected[0])
        if state.get("scroll"):
            self.tree.yview_moveto(state["scroll"][0])

    def show_health_page(self):
        self.player_frame.pack(side="bottom", fill="x")
        for widget in self.library_widgets:
            widget.pack_forget()
        self.home_dashboard.pack_forget()
        if self.now_playing_frame:
            self.now_playing_frame.pack_forget()
        if self.entity_frame:
            self.entity_frame.pack_forget()
        if self.health_frame:
            self.health_frame.destroy()
        self.health_frame = tk.Frame(self.content, bg=self.bg)
        self.health_frame.pack(fill="both", expand=True)
        header = tk.Frame(self.health_frame, bg=self.bg)
        header.pack(fill="x", pady=(4, 16))
        tk.Label(header, text="LIBRARY HEALTH", bg=self.bg, fg=self.text,
                 font=("Segoe UI Semibold", 25)).pack(side="left")
        self.button(header, "Refresh", self.show_health_page, bg=self.panel2,
                    padx=12, pady=6).pack(side="right")
        summary = self.db.health_summary()
        stats = tk.Frame(self.health_frame, bg=self.bg)
        stats.pack(fill="x")
        cards = [("SONGS", summary["total_songs"]), ("ALBUMS", summary["total_albums"]),
                 ("ARTISTS", summary["total_artists"]), ("FILES OK", summary["files_ok"]),
                 ("MISSING FILES", summary["missing_files"]), ("MISSING METADATA", summary["missing_metadata"]),
                 ("MISSING ARTWORK", summary["missing_artwork"]), ("LIKELY DUPLICATES", summary["duplicate_groups"])]
        for label, value in cards:
            card = tk.Frame(stats, bg=self.panel, width=150, height=78)
            card.pack(side="left", padx=(0, 8), pady=(0, 8), fill="x", expand=True)
            card.pack_propagate(False)
            tk.Label(card, text=label, bg=self.panel, fg=self.muted,
                     font=("Segoe UI Semibold", 8)).pack(anchor="w", padx=10, pady=(10, 2))
            tk.Label(card, text=str(value), bg=self.panel, fg=self.text,
                     font=("Segoe UI Semibold", 17)).pack(anchor="w", padx=10)
        actions = tk.Frame(self.health_frame, bg=self.bg)
        actions.pack(fill="x", pady=14)
        self.button(actions, "Refresh Changed Files", self.start_scan,
                    bg=self.blue, fg="white", padx=13, pady=7).pack(side="left")
        self.button(actions, "Remove Dead Entries", self.remove_dead_entries,
                    bg=self.panel2, padx=13, pady=7).pack(side="left", padx=8)
        tk.Label(self.health_frame, text="MusicVault never deletes your music from this page.",
                 bg=self.bg, fg=self.muted, font=("Segoe UI", 10)).pack(anchor="w")

    def remove_dead_entries(self):
        if not messagebox.askyesno("Remove dead entries",
                                   "Remove database records whose files are missing?", parent=self):
            return
        self.db.remove_missing([song["path"] for song in self.get_library() if os.path.exists(song["path"])])
        self.invalidate_library()
        self.show_health_page()

    def sort_changed(self):
        self.settings["sort"] = self.sort_var.get()
        save_settings(self.settings)
        self.refresh()

    def sort_column(self, column):
        mapping = {"title":"Title","artist":"Artist","album":"Album","year":"Year",
               "rating":"Rating",
                   "time":"Duration"}
        name = mapping.get(column)
        if name:
            if self.sort_var.get() == name:
                self.settings["sort_desc"] = not self.settings.get("sort_desc",False)
            else:
                self.settings["sort"] = name
                self.settings["sort_desc"] = False
            self.sort_var.set(name)
            save_settings(self.settings)
            self.refresh()

    def base_songs(self):
        page_size = max(50, int(self.settings.get("library_page_size", 250)))
        if self.playlist_name:
            return self.db.playlist(self.playlist_name)
        if self.view == "Recently Added":
            return self.db.recently_added(page_size)
        if self.view == "Most Played":
            return self.db.most_played(page_size)
        if self.view == "5 Star Songs":
            rated = self.db.ratings()
            return [song for song in self.get_library() if rated.get(song["id"]) == 5]
        return self.get_library()

    def filtered(self):
        songs = self.base_songs()
        if self.view == "Favorites":
            fav = self.db.favorites()
            songs = [s for s in songs if s["id"] in fav]

        query = self.search.get().strip()
        operators = {}
        for match in re.finditer(r'(artist|album|genre|year|rating|format|liked|favorite|duration):("[^"]+"|\S+)', query, re.I):
            operators[match.group(1).lower()] = match.group(2).strip('"').lower()
        free_text = re.sub(r'(artist|album|genre|year|rating|format|liked|favorite|duration):("[^"]+"|\S+)', '', query, flags=re.I).strip().lower()
        ratings = self.db.ratings() if "rating" in operators else {}
        favorites = self.db.favorites() if "favorite" in operators else set()
        reactions = self.db.reactions() if "liked" in operators else {}
        if free_text:
            terms = free_text.split()
            songs = [s for s in songs if all(term in " ".join(
                str(s[k]) for k in ("title","artist","album","genre","year","path")
            ).lower() for term in terms)]
        for field in ("artist", "album", "genre", "year"):
            if field in operators:
                value = operators[field]
                songs = [s for s in songs if value in str(s[field]).lower()]
        if "rating" in operators:
            value = operators["rating"]
            songs = [s for s in songs if ratings.get(s["id"], 0) == int(value)] if value.isdigit() else songs
        if "favorite" in operators:
            songs = [s for s in songs if (s["id"] in favorites) == (operators["favorite"] in ("true", "1", "yes"))]
        if "liked" in operators:
            songs = [s for s in songs if (reactions.get(s["id"], 0) == 1) == (operators["liked"] in ("true", "1", "yes"))]
        if "format" in operators:
            songs = [s for s in songs if os.path.splitext(s["path"])[1].lstrip(".").lower() == operators["format"].lstrip(".")]
        if "duration" in operators:
            value = operators["duration"]
            match = re.match(r"([<>]=?)(\d+(?:\.\d+)?)", value)
            if match:
                operator, threshold = match.group(1), float(match.group(2))
                comparisons = {">": lambda x: x > threshold, ">=": lambda x: x >= threshold,
                               "<": lambda x: x < threshold, "<=": lambda x: x <= threshold}
                songs = [s for s in songs if comparisons[operator](s["duration"])]

        if self.view in ("Albums","Artists","Genres"):
            seen=set()
            out=[]
            key = {"Albums":lambda s:(s["artist"],s["album"]),
                   "Artists":lambda s:s["artist"],
                   "Genres":lambda s:s["genre"]}[self.view]
            for s in songs:
                k=key(s)
                if k not in seen:
                    seen.add(k); out.append(s)
            songs=out

        field = self.settings.get("sort","Title")
        key = {
            "Title":lambda s:s["title"].lower(),
            "Artist":lambda s:s["artist"].lower(),
            "Album":lambda s:s["album"].lower(),
            "Year":lambda s:str(s["year"]),
            "Rating":lambda s:self.db.rating(s["id"]),
            "Duration":lambda s:s["duration"],
            "Date Added":lambda s:s["added"],
        }.get(field,lambda s:s["title"].lower())
        try:
            songs.sort(key=key, reverse=self.settings.get("sort_desc",False))
        except Exception:
            pass
        return songs

    def schedule_refresh(self):
        if self.refresh_job:
            try: self.after_cancel(self.refresh_job)
            except Exception: pass
        self.refresh_job=self.after(140, self.refresh)

    def get_library(self):
        if self.library_cache is None:
            self.library_cache=self.db.all()
        return self.library_cache

    def invalidate_library(self):
        self.library_cache=None

    def refresh(self):
        self.refresh_job=None
        self.render_generation += 1
        generation=self.render_generation
        if self.render_job:
            try: self.after_cancel(self.render_job)
            except Exception: pass
            self.render_job=None

        self.visible=self.filtered()
        self.count.config(text=f"{len(self.visible)} items")
        if self.settings.get("show_status_bar", True):
            self.status.set(f"{len(self.visible)} items")
        self.tree.delete(*self.tree.get_children())

        def render_chunk(pos=0):
            if generation != self.render_generation:
                return
            end=min(pos+self.render_chunk,len(self.visible))
            rows=[]
            for i in range(pos,end):
                s=self.visible[i]
                rows.append((str(i),"",(
                    s["title"],s["artist"],s["album"],s["genre"],s["year"],
                    "★" * self.db.rating(s["id"]) + "☆" * (5 - self.db.rating(s["id"])),
                    seconds_text(s["duration"])
                )))
            for iid,text,values in rows:
                self.tree.insert("", "end", iid=iid, values=values)
            if end < len(self.visible):
                self.render_job=self.after(1,lambda:render_chunk(end))
            else:
                self.render_job=None
                if self.pending_library_restore == self.view:
                    self.restore_library_state()
                    self.pending_library_restore = None
                if self.settings.get("show_album_strip",True):
                    self.refresh_albums()
                if self.view == "Home":
                    self.refresh_home_dashboard()
        render_chunk()

    def toggle_selected_favorite(self):
        songs=self.selected()
        if not songs: return
        fav=self.db.favorites()
        for song in songs:
            self.db.toggle_favorite(song["id"])
        self.update_player_actions()
        self.refresh()

    def like_current(self):
        if self.current:
            self.db.set_reaction(self.current["id"],1)
            self.update_player_actions()

    def dislike_current(self):
        if self.current:
            self.db.set_reaction(self.current["id"],-1)
            self.update_player_actions()

    def like_selected(self):
        songs=self.selected()
        if not songs: return
        for song in songs: self.db.set_reaction(song["id"],1)
        self.update_player_actions()

    def dislike_selected(self):
        songs=self.selected()
        if not songs: return
        for song in songs: self.db.set_reaction(song["id"],-1)
        self.update_player_actions()

    def queue_selected(self):
        songs=self.selected()
        if not songs: return
        self.queue.extend(songs)
        self.status.set(f"Added {len(songs)} song(s) to queue")

    def refresh_albums(self):
        for c in self.album_strip.winfo_children():
            c.destroy()
        if self.view not in ("Home","Albums") or not self.visible:
            self.album_strip.pack_forget()
            return

        if not self.album_strip.winfo_manager():
            self.album_strip.pack(fill="x", pady=(12, 8), before=self.tree.master)

        albums=[]
        seen=set()
        all_songs=self.get_library()
        for s in all_songs:
            key=(s["artist"],s["album"])
            if key not in seen:
                seen.add(key); albums.append(s)
        albums=albums[:35]

        canvas=tk.Canvas(self.album_strip,bg=self.bg,height=145,highlightthickness=0)
        inner=tk.Frame(canvas,bg=self.bg)
        win=canvas.create_window((0,0),window=inner,anchor="nw")
        hbar=ttk.Scrollbar(self.album_strip,orient="horizontal",command=canvas.xview)
        canvas.configure(xscrollcommand=hbar.set)
        inner.bind("<Configure>",lambda e:canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.bind("<Configure>",lambda e:canvas.itemconfigure(win,height=145))
        canvas.pack(fill="x")
        hbar.pack(fill="x")

        for s in albums:
            card=tk.Frame(inner,bg=self.panel,width=108,height=135)
            card.pack(side="left",padx=(0,9))
            card.pack_propagate(False)
            art=self.make_art(s.get("artwork"),84)
            lab=tk.Label(card,image=art,bg=self.panel)
            lab.image=art
            lab.pack(pady=5)
            tk.Label(card,text=s["album"][:17],bg=self.panel,fg=self.text,
                     font=("Segoe UI Semibold",8)).pack()
            tk.Label(card,text=s["artist"][:17],bg=self.panel,fg=self.muted,
                     font=("Segoe UI",7)).pack()
            for w in (card,lab):
                w.bind("<Button-1>",lambda e,x=s:self.open_album_page(x))
                w.bind("<Double-Button-1>",lambda e,x=s:self.play_album(x))

    def make_art(self,blob,size):
        if Image is None:
            return None
        try:
            key=(hash(blob) if blob else 0,size)
            if key in self.album_art_cache:
                return self.album_art_cache[key]
            if blob:
                im=Image.open(io.BytesIO(blob)).convert("RGB")
                im.thumbnail((size,size))
                bg=Image.new("RGB",(size,size))
                bg.paste(im,((size-im.width)//2,(size-im.height)//2))
                im=bg
            else:
                im=Image.new("RGB",(size,size),"#1b2532")
                ImageDraw.Draw(im).text((size//2,size//2),"♫",fill="#60a5fa",
                                        anchor="mm",font=None)
            photo=ImageTk.PhotoImage(im)
            self.album_art_cache[key]=photo
            if len(self.album_art_cache)>300:
                self.album_art_cache.pop(next(iter(self.album_art_cache)))
            return photo
        except Exception:
            return None

    def play_album(self,song):
        q=[s for s in self.get_library() if s["artist"]==song["artist"] and s["album"]==song["album"]]
        if not q:
            self.status.set("That album is no longer available")
            return
        q.sort(key=lambda s:(s["disc"],s["track"],s["title"].lower()))
        self.queue=q
        self.queue_index=0
        self.play(q[0])

    def selected(self):
        out=[]
        for iid in self.tree.selection():
            try: out.append(self.visible[int(iid)])
            except Exception: pass
        return out

    def open_selected_details(self, event=None):
        row = self.tree.identify_row(event.y) if event else ""
        if row:
            self.tree.selection_set(row)
            songs = self.selected()
            if songs:
                self.open_track_details(songs[0])

    def build_entity_page(self):
        if self.entity_frame:
            self.entity_frame.destroy()
        self.entity_frame = tk.Frame(self.content, bg=self.bg)
        return self.entity_frame

    def close_entity_page(self):
        if self.entity_frame:
            self.entity_frame.pack_forget()
        self.entity_kind = None
        self.show_library_view()

    def open_album_page(self, song):
        songs = [item for item in self.get_library()
                 if item["artist"] == song["artist"] and item["album"] == song["album"]]
        if not songs:
            return
        songs.sort(key=lambda item: (item["disc"], item["track"], item["title"].lower()))
        self.entity_kind = "album"
        self.entity_songs = songs
        self.show_entity_page(song["album"], song["artist"], songs, song)

    def open_artist_page(self, song):
        songs = [item for item in self.get_library() if item["artist"] == song["artist"]]
        if not songs:
            return
        songs.sort(key=lambda item: (item["album"].lower(), item["disc"], item["track"], item["title"].lower()))
        self.entity_kind = "artist"
        self.entity_songs = songs
        self.show_entity_page(song["artist"], f'{len({item["album"] for item in songs})} albums', songs, song)

    def show_entity_page(self, title, subtitle, songs, artwork_song):
        self.player_frame.pack(side="bottom", fill="x")
        for widget in self.library_widgets:
            widget.pack_forget()
        self.home_dashboard.pack_forget()
        if self.now_playing_frame:
            self.now_playing_frame.pack_forget()
        page = self.build_entity_page()
        page.pack(fill="both", expand=True)
        header = tk.Frame(page, bg=self.bg)
        header.pack(fill="x", pady=(4, 12))
        self.button(header, "‹ Library", self.close_entity_page, bg=self.panel2,
                    padx=12, pady=6).pack(side="left")
        tk.Label(header, text="ALBUM" if self.entity_kind == "album" else "ARTIST",
                 bg=self.bg, fg=self.blue2, font=("Segoe UI Semibold", 10)).pack(side="right", pady=8)

        hero = tk.Frame(page, bg=self.panel)
        hero.pack(fill="x", pady=(0, 12))
        art = self.make_art(artwork_song.get("artwork"), 190)
        image = tk.Label(hero, image=art, text="♫" if art is None else "", bg=self.panel,
                         fg=self.blue2, font=("Segoe UI", 42))
        image.image = art
        image.pack(side="left", padx=20, pady=18)
        copy = tk.Frame(hero, bg=self.panel)
        copy.pack(side="left", fill="both", expand=True, padx=8, pady=24)
        tk.Label(copy, text=title, bg=self.panel, fg=self.text,
                 font=("Segoe UI Semibold", 25), wraplength=650, anchor="w").pack(anchor="w")
        tk.Label(copy, text=subtitle, bg=self.panel, fg=self.blue2,
                 font=("Segoe UI Semibold", 12)).pack(anchor="w", pady=(4, 0))
        total_duration = sum(item["duration"] for item in songs)
        info = f"{len(songs)} songs  •  {seconds_text(total_duration)}"
        if self.entity_kind == "album":
            info = f'{artwork_song["year"] or "Year unknown"}  •  {info}'
        tk.Label(copy, text=info, bg=self.panel, fg=self.muted,
                 font=("Segoe UI", 10)).pack(anchor="w", pady=(4, 14))
        actions = tk.Frame(copy, bg=self.panel)
        actions.pack(anchor="w")
        self.button(actions, "▶ Play", lambda: self.play_entity_songs(songs),
                    bg=self.blue, fg="white", padx=13, pady=7).pack(side="left")
        self.button(actions, "⤨ Shuffle", lambda: self.shuffle_entity_songs(songs),
                    bg=self.panel2, padx=12, pady=7).pack(side="left", padx=8)
        self.button(actions, "＋ Queue", lambda: self.add_songs_to_queue(songs),
                    bg=self.panel2, padx=12, pady=7).pack(side="left")

        if self.entity_kind == "artist":
            albums = {}
            for item in songs:
                albums.setdefault(item["album"], item)
            album_bar = tk.Frame(page, bg=self.bg)
            album_bar.pack(fill="x", pady=(0, 10))
            tk.Label(album_bar, text="ALBUMS", bg=self.bg, fg=self.muted,
                     font=("Segoe UI Semibold", 9)).pack(anchor="w", pady=(0, 6))
            for album, item in sorted(albums.items(), key=lambda pair: pair[0].lower()):
                self.button(album_bar, album, lambda selected=item: self.open_album_page(selected),
                            bg=self.panel2, anchor="w", padx=10, pady=5).pack(side="left", padx=(0, 6))

        tk.Label(page, text="TRACKS", bg=self.bg, fg=self.muted,
                 font=("Segoe UI Semibold", 9)).pack(anchor="w", pady=(3, 6))
        table = tk.Frame(page, bg=self.panel)
        table.pack(fill="both", expand=True)
        tree = ttk.Treeview(table, columns=("title", "album", "time"), show="headings")
        for column, heading, width in (("title", "TITLE", 430), ("album", "ALBUM", 260), ("time", "TIME", 80)):
            tree.heading(column, text=heading)
            tree.column(column, width=width, anchor="w")
        scroll = ttk.Scrollbar(table, orient="vertical", command=tree.yview)
        tree.configure(yscrollcommand=scroll.set)
        tree.grid(row=0, column=0, sticky="nsew")
        scroll.grid(row=0, column=1, sticky="ns")
        table.rowconfigure(0, weight=1)
        table.columnconfigure(0, weight=1)
        for index, item in enumerate(songs):
            tree.insert("", "end", iid=str(index), values=(item["title"], item["album"], seconds_text(item["duration"])))
        tree.bind("<Double-1>", lambda event: self.play_entity_selected(tree))
        self.entity_tree = tree

    def play_entity_selected(self, tree):
        selection = tree.selection()
        if not selection:
            return
        song = self.entity_songs[int(selection[0])]
        self.queue = list(self.entity_songs)
        self.queue_index = next(i for i, item in enumerate(self.queue) if item["id"] == song["id"])
        self.play(song)
        self.show_now_playing()

    def play_entity_songs(self, songs):
        self.queue = list(songs)
        self.queue_index = 0
        self.play(self.queue[0])
        self.show_now_playing()

    def shuffle_entity_songs(self, songs):
        self.queue = list(songs)
        random.shuffle(self.queue)
        self.queue_index = 0
        self.play(self.queue[0])
        self.show_now_playing()

    def add_songs_to_queue(self, songs):
        self.queue.extend(songs)
        self.refresh_queue_panel()
        self.status.set(f"Added {len(songs)} songs to queue")

    def open_track_details(self, song):
        if not song:
            return
        if self.details_window and self.details_window.winfo_exists():
            self.details_window.destroy()

        win = tk.Toplevel(self)
        self.details_window = win
        win.title(f'{song["title"]} - MusicVault')
        screen_width = self.winfo_screenwidth()
        screen_height = self.winfo_screenheight()
        window_width = min(470, max(400, screen_width - 80))
        window_height = min(610, max(460, screen_height - 70))
        art_size = max(150, min(260, window_height - 420))
        win.geometry(f"{window_width}x{window_height}")
        win.minsize(min(400, window_width), min(460, window_height))
        win.resizable(True, True)
        win.configure(bg=self.bg)
        win.transient(self)

        header = tk.Frame(win, bg=self.bg)
        header.pack(fill="x", padx=24, pady=(20, 12))
        tk.Label(header, text="TRACK DETAILS", bg=self.bg, fg=self.blue2,
                 font=("Segoe UI Semibold", 9)).pack(anchor="w")
        tk.Button(header, text="×", command=win.destroy, bg=self.bg, fg=self.muted,
                  activebackground=self.bg, activeforeground=self.text, relief="flat",
                  bd=0, font=("Segoe UI", 18), cursor="hand2").pack(side="right", anchor="ne")

        art = self.make_art(song.get("artwork"), art_size)
        art_label = tk.Label(win, image=art, text="♫" if art is None else "",
                     bg=self.panel2, fg=self.blue2, width=art_size, height=art_size,
                             font=("Segoe UI", 42))
        art_label.image = art
        art_label.pack(pady=(0, 18))

        tk.Label(win, text=song["title"], bg=self.bg, fg=self.text,
                 font=("Segoe UI Semibold", 19), wraplength=max(320, window_width - 60)).pack()
        tk.Label(win, text=song["artist"], bg=self.bg, fg=self.blue2,
                 font=("Segoe UI Semibold", 11)).pack(pady=(4, 0))
        tk.Label(win, text=f'{song["album"]}  •  {song["year"] or "Year unknown"}',
                 bg=self.bg, fg=self.muted, font=("Segoe UI", 10)).pack(pady=(2, 14))

        meta = tk.Frame(win, bg=self.panel)
        meta.pack(fill="x", padx=24, pady=(0, 14))
        details = [("GENRE", song["genre"]), ("DURATION", seconds_text(song["duration"])),
                   ("TRACK", str(song["track"] or "-")), ("FORMAT", os.path.splitext(song["path"])[1].upper().lstrip("."))]
        for label, value in details:
            cell = tk.Frame(meta, bg=self.panel)
            cell.pack(side="left", fill="both", expand=True, padx=8, pady=10)
            tk.Label(cell, text=label, bg=self.panel, fg=self.muted,
                     font=("Segoe UI Semibold", 8)).pack(anchor="w")
            tk.Label(cell, text=value, bg=self.panel, fg=self.text,
                     font=("Segoe UI", 9), wraplength=90).pack(anchor="w", pady=(3, 0))

        actions = tk.Frame(win, bg=self.bg)
        actions.pack(fill="x", padx=24)
        self.button(actions, "＋ Queue", lambda: self.add_queue(song),
                    bg=self.panel2, padx=14, pady=8).pack(side="left", padx=8)
        self.button(actions, "♡ Favorite", lambda: self.toggle_song_favorite(song),
                    bg=self.panel2, padx=14, pady=8).pack(side="left")
        self.button(actions, "Open file", lambda: self.open_location(song["path"]),
                    bg=self.panel2, padx=14, pady=8).pack(side="right")

    def play_from_details(self, song):
        if not self.queue or not any(item["id"] == song["id"] for item in self.queue):
            self.queue = self.filtered()
        if not any(item["id"] == song["id"] for item in self.queue):
            self.queue.append(song)
        self.queue_index = next((i for i, item in enumerate(self.queue)
                                 if item["id"] == song["id"]), 0)
        self.play(song)

    def play_selected(self,event=None):
        selected=self.selected()
        if not selected:return
        if self.view == "Albums":
            self.open_album_page(selected[0])
            return
        if self.view == "Artists":
            self.open_artist_page(selected[0])
            return
        if not self.queue or not any(item["id"] == selected[0]["id"] for item in self.queue):
            self.queue=self.filtered()
        if not any(item["id"] == selected[0]["id"] for item in self.queue):
            self.queue.append(selected[0])
        self.queue_index=next((i for i,s in enumerate(self.queue) if s["id"]==selected[0]["id"]),0)
        self.play(self.queue[self.queue_index])
        self.show_now_playing()

    def play(self,song,start=None):
        if not pygame:
            messagebox.showerror("Audio engine unavailable",
                                 "Install the dependencies with run_musicvault.bat.")
            return
        if not os.path.exists(song["path"]):
            self.start_scan(); return
        try:
            pygame.mixer.music.load(song["path"])
            if start is None:
                start=self.db.get_position(song["id"]) if self.settings.get("resume",True) else 0
                if start >= max(0,song["duration"]-2): start=0
            try:
                if start and start > 0.25:
                    pygame.mixer.music.play(start=float(start))
                else:
                    pygame.mixer.music.play()
            except Exception:
                # Some codecs do not support seeking from the beginning through pygame.
                pygame.mixer.music.play()
            pygame.mixer.music.set_volume(float(self.volume.get()))
            self.current=song
            self.playback_offset=float(start or 0)
            self.last_tick_time=time.monotonic()
            self.paused=False
            self.user_seeking=False
            self.set_play_symbols("Ⅱ")
            self.now_title.config(text=song["title"])
            self.now_artist.config(text=f'{song["artist"]} • {song["album"]}')
            self.seekbar.configure(to=max(1,song["duration"]))
            self.seek_var.set(max(0,float(start or 0)))
            self.elapsed.config(text=seconds_text(start or 0))
            self.total.config(text=seconds_text(song["duration"]))
            art=self.make_art(song.get("artwork"),64)
            if art:
                self.art_ref=art
                self.art.config(image=art,text="")
            else:self.art.config(image="",text="♫")
            self.db.add_history(song["id"])
            self.update_player_actions()
            self.refresh_queue_panel()
            if self.now_playing_frame and self.now_playing_frame.winfo_manager():
                self.refresh_now_playing_page()
            self.refresh_now_window()
            self.status.set(f'Playing {song["title"]}')
        except Exception as e:
            messagebox.showerror("Playback error",str(e))

    def toggle_play(self):
        if not pygame:return
        if not self.current:
            s=self.filtered()
            if s:self.queue=s;self.queue_index=0;self.play(s[0])
            return
        if self.paused:
            pygame.mixer.music.unpause()
            self.paused=False
            self.set_play_symbols("Ⅱ")
        elif pygame.mixer.music.get_busy():
            pygame.mixer.music.pause()
            self.paused=True
            self.set_play_symbols("▶")
        else:self.play(self.current)

    def set_play_symbols(self, symbol):
        self.play_btn.config(text=symbol)
        if hasattr(self, "np_play_button"):
            self.np_play_button.config(text=symbol)
        if hasattr(self, "window_play_button"):
            self.window_play_button.config(text=symbol)

    def next(self):
        if not self.queue:self.queue=self.filtered()
        if not self.queue:return
        if self.shuffle and self.shuffle_mode == "Smart":
            favorites = self.db.favorites()
            ratings = self.db.ratings()
            candidates = [song for song in self.queue if song["id"] != (self.current or {}).get("id")]
            if candidates:
                weights = [1 + ratings.get(song["id"], 0) * 3 + (4 if song["id"] in favorites else 0)
                           for song in candidates]
                chosen = random.choices(candidates, weights=weights, k=1)[0]
                self.queue_index = self.queue.index(chosen)
            else:
                self.queue_index = random.randrange(len(self.queue))
        elif self.shuffle and self.shuffle_mode in ("Artist Variety", "Album Variety"):
            current_key = ((self.current or {}).get("artist") if self.shuffle_mode == "Artist Variety"
                           else (self.current or {}).get("album"))
            candidates = [song for song in self.queue
                          if song is not self.current and (song["artist"] if self.shuffle_mode == "Artist Variety" else song["album"]) != current_key]
            chosen = random.choice(candidates or self.queue)
            self.queue_index = self.queue.index(chosen)
        elif self.shuffle:self.queue_index=random.randrange(len(self.queue))
        else:self.queue_index+=1
        if self.queue_index>=len(self.queue):
            if self.repeat=="all":self.queue_index=0
            else:return
        self.play(self.queue[self.queue_index])

    def previous(self):
        if not self.current:return
        try:
            if pygame and pygame.mixer.music.get_pos()>3000:
                self.play(self.current,start=0);return
        except Exception:pass
        self.queue_index=max(0,self.queue_index-1)
        if self.queue:self.play(self.queue[self.queue_index])

    def toggle_shuffle(self):
        self.shuffle=not self.shuffle
        self.shuffle_btn.config(fg=self.blue2 if self.shuffle else self.muted)
        if self.settings.get("remember_shuffle",True):
            self.settings["shuffle"]=self.shuffle
            save_settings(self.settings)

    def toggle_repeat(self):
        self.repeat={"off":"all","all":"one","one":"off"}[self.repeat]
        self.repeat_btn.config(text="↻1" if self.repeat=="one" else "↻",
                               fg=self.blue2 if self.repeat!="off" else self.muted)
        if self.settings.get("remember_repeat",True):
            self.settings["repeat"]=self.repeat
            save_settings(self.settings)

    # Correct seeking: stop timer updates while dragging, then perform a real seek
    # on mouse release. The release position is converted to seconds and applied.
    def seek_press(self,event=None):
        self.user_seeking=True

    def seek_moving(self,value):
        if self.user_seeking:
            try:
                self.elapsed.config(text=seconds_text(float(value)))
                if hasattr(self, "np_elapsed"):
                    self.np_elapsed.config(text=seconds_text(float(value)))
                if self.now_window and self.now_window.winfo_exists():
                    self.window_elapsed.config(text=seconds_text(float(value)))
            except Exception:pass

    def seek_release(self,event=None):
        if not self.current:
            self.user_seeking=False;return
        target=float(self.seek_var.get())
        was_paused=self.paused
        self.user_seeking=False
        try:
            pygame.mixer.music.load(self.current["path"])
            pygame.mixer.music.play(start=max(0,target))
            self.playback_offset=max(0,target)
            self.last_tick_time=time.monotonic()
            pygame.mixer.music.set_volume(float(self.volume.get()))
            if was_paused:
                pygame.mixer.music.pause()
            self.db.set_position(self.current["id"],target)
            self.elapsed.config(text=seconds_text(target))
            if hasattr(self, "np_elapsed"):
                self.np_elapsed.config(text=seconds_text(target))
            if self.now_window and self.now_window.winfo_exists():
                self.window_elapsed.config(text=seconds_text(target))
        except Exception:
            # If the codec cannot seek with SDL, keep the UI synchronized rather than
            # pretending the seek worked.
            self.status.set("This audio format does not support seeking in the current audio engine.")

    def set_volume(self,value):
        try:
            v=float(value)
            if pygame:pygame.mixer.music.set_volume(v)
            self.settings["volume"]=v
            save_settings(self.settings)
        except Exception:pass

    def player_tick(self):
        if pygame and self.current and not self.user_seeking:
            try:
                raw=pygame.mixer.music.get_pos()/1000.0
                if raw >= 0:
                    pos=self.playback_offset + raw
                else:
                    pos=self.playback_offset
                pos=min(max(0,pos),max(1,self.current["duration"]))
                self.seek_var.set(pos)
                self.elapsed.config(text=seconds_text(pos))
                if hasattr(self, "np_elapsed") and self.now_playing_frame.winfo_manager():
                    self.np_elapsed.config(text=seconds_text(pos))
                if self.now_window and self.now_window.winfo_exists():
                    self.window_elapsed.config(text=seconds_text(pos))

                now=time.monotonic()
                if now-self.last_tick_time >= 1.0:
                    self.db.set_position(self.current["id"],pos)
                    self.last_tick_time=now

                if not pygame.mixer.music.get_busy() and not self.paused:
                    self.db.set_position(self.current["id"],0)
                    if self.repeat=="one": self.play(self.current,start=0)
                    else: self.next()
            except Exception:
                pass
        self.after(400,self.player_tick)

    def toggle_favorite_current(self):
        if self.current:
            self.db.toggle_favorite(self.current["id"])
            self.update_player_actions()
            self.refresh()

    def rate_current(self, value):
        if self.current:
            current = self.db.rating(self.current["id"])
            self.db.set_rating(self.current["id"], value if value else (0 if current == 5 else current + 1))
            self.refresh_now_playing_page()
            self.refresh()

    def rate_selected(self, value):
        songs = self.selected()
        for song in songs:
            self.db.set_rating(song["id"], value)
        if songs and self.current and self.current["id"] in {song["id"] for song in songs}:
            self.refresh_now_playing_page()
        self.refresh()

    def rating_key(self, event):
        if isinstance(event.widget, (tk.Entry, ttk.Combobox, tk.Text)):
            return
        if event.char in "12345":
            self.rate_current(int(event.char))

    def update_player_actions(self):
        if not self.current:
            return
        fav=self.current["id"] in self.db.favorites()
        reaction=self.db.reaction(self.current["id"])
        self.fav_btn.config(text="★" if fav else "☆",
                            fg=self.blue2 if fav else self.muted)
        self.like_btn.config(text="👍✓" if reaction==1 else "👍",
                             fg=self.blue2 if reaction==1 else self.muted)
        self.dislike_btn.config(text="👎✓" if reaction==-1 else "👎",
                                fg="#f87171" if reaction==-1 else self.muted)

    def space_key(self,event):
        if isinstance(event.widget,(tk.Entry,ttk.Combobox,tk.Text)):
            return
        self.toggle_play()
        return "break"

    def focus_search(self):
        self.search_entry.focus_set()
        self.search_entry.select_range(0,"end")

    def context_menu(self,event):
        row=self.tree.identify_row(event.y)
        if not row:return
        self.tree.selection_set(row)
        songs=self.selected()
        if not songs:return
        s=songs[0]
        m=tk.Menu(self,tearoff=0,bg=self.panel2,fg=self.text)
        fav=s["id"] in self.db.favorites()
        m.add_command(label="♥ Remove Favorite" if fav else "♡ Add Favorite",
                      command=lambda:self.toggle_song_favorite(s))
        m.add_command(label="👍 Like",command=lambda:self.set_song_reaction(s,1))
        m.add_command(label="👎 Dislike",command=lambda:self.set_song_reaction(s,-1))
        m.add_command(label="Clear Like/Dislike",command=lambda:self.set_song_reaction(s,0))
        m.add_separator()
        for value in range(1, 6):
            m.add_command(label=f"{'★' * value} Rate {value}", command=lambda v=value:self.rate_selected(v))
        m.add_command(label="Clear rating", command=lambda:self.rate_selected(0))
        m.add_command(label="Play",command=self.play_selected)
        m.add_command(label="Play Next",command=lambda:self.play_next_song(s))
        m.add_command(label="Add to Queue",command=lambda:self.add_queue(s))
        m.add_command(label="Queue Album",command=lambda:self.add_songs_to_queue(
            [item for item in self.get_library() if item["artist"] == s["artist"] and item["album"] == s["album"]]))
        m.add_command(label="Queue Artist",command=lambda:self.add_songs_to_queue(
            [item for item in self.get_library() if item["artist"] == s["artist"]]))
        m.add_command(label="View Details",command=lambda:self.open_track_details(s))
        m.add_command(label="Open Album",command=lambda:self.open_album_page(s))
        m.add_command(label="Open Artist",command=lambda:self.open_artist_page(s))
        m.add_command(label="Edit Metadata",command=lambda:self.edit_metadata(s))
        m.add_command(label="Find Duplicates",command=lambda:self.find_duplicates_for_song(s))
        m.add_separator()
        for _,name in self.db.playlists():
            m.add_command(label=f"Add to {name}",
                          command=lambda n=name:self.db.add_to_playlist(n,s["id"]))
        if self.playlist_name:
            m.add_separator()
            m.add_command(label="Remove from playlist",
                          command=lambda:self.remove_from_playlist(s))
        m.add_separator()
        m.add_command(label="Open File Location",command=lambda:self.open_location(s["path"]))
        m.tk_popup(event.x_root,event.y_root)

    def edit_metadata(self, song):
        if not MutagenFile or not os.path.exists(song["path"]):
            messagebox.showerror("Metadata editor", "This file cannot be edited because it is missing or Mutagen is unavailable.", parent=self)
            return
        win = tk.Toplevel(self)
        win.title(f'Edit Metadata • {song["title"]}')
        win.geometry("520x470")
        win.configure(bg=self.bg)
        win.transient(self)
        fields = [("Title", "title"), ("Artist", "artist"), ("Album", "album"),
                  ("Genre", "genre"), ("Year", "year"), ("Track", "track"), ("Disc", "disc")]
        entries = {}
        form = tk.Frame(win, bg=self.bg)
        form.pack(fill="both", expand=True, padx=24, pady=20)
        for row, (label, key) in enumerate(fields):
            tk.Label(form, text=label, bg=self.bg, fg=self.muted,
                     font=("Segoe UI Semibold", 9)).grid(row=row, column=0, sticky="w", pady=5)
            entry = tk.Entry(form, bg=self.panel2, fg=self.text, insertbackground=self.text,
                             relief="flat", width=42)
            entry.insert(0, str(song[key] or ""))
            entry.grid(row=row, column=1, sticky="ew", padx=(16, 0), ipady=5)
            entries[key] = entry
        form.columnconfigure(1, weight=1)
        tk.Label(form, text="A backup is created beside the file before saving.",
                 bg=self.bg, fg=self.muted, font=("Segoe UI", 9)).grid(row=len(fields), column=0,
                 columnspan=2, sticky="w", pady=(16, 4))
        footer = tk.Frame(win, bg=self.bg)
        footer.pack(fill="x", padx=24, pady=(0, 20))

        def save_metadata():
            backup = song["path"] + ".musicvault.bak"
            try:
                shutil.copy2(song["path"], backup)
                audio = MutagenFile(song["path"], easy=True)
                if not audio:
                    raise ValueError("This audio format does not expose editable tags.")
                if audio.tags is None:
                    audio.add_tags()
                values = {key: entries[key].get().strip() for _, key in fields}
                for key in ("title", "artist", "album", "genre", "date"):
                    if key in values:
                        audio[key if key != "date" else "date"] = [values[key]] if values[key] else []
                if values["year"]:
                    audio["date"] = [values["year"]]
                for key in ("tracknumber", "discnumber"):
                    source = "track" if key == "tracknumber" else "disc"
                    audio[key] = [values[source]] if values[source] else []
                audio.save()
                updated = metadata(song["path"])
                self.db.upsert(updated)
                self.invalidate_library()
                self.refresh()
                win.destroy()
                self.status.set(f'Updated metadata for "{updated["title"]}"')
            except Exception as exc:
                messagebox.showerror("Metadata save failed", str(exc), parent=win)

        self.button(footer, "Cancel", win.destroy, bg=self.panel2,
                    padx=14, pady=7).pack(side="right")
        self.button(footer, "Save Metadata", save_metadata, bg=self.blue,
                    fg="white", padx=14, pady=7).pack(side="right", padx=8)

    def find_duplicates_for_song(self, song):
        candidates = [item for item in self.get_library()
                      if item["artist"] == song["artist"] and item["title"] == song["title"]]
        groups = find_duplicate_groups(candidates)
        matches = groups["exact"] or groups["likely"]
        if not matches:
            messagebox.showinfo("Duplicate finder", "No exact or likely duplicates were found.", parent=self)
            return
        win = tk.Toplevel(self)
        win.title(f'Duplicates • {song["title"]}')
        win.geometry("720x360")
        win.configure(bg=self.bg)
        tk.Label(win, text="DUPLICATE CANDIDATES", bg=self.bg, fg=self.blue2,
                 font=("Segoe UI Semibold", 10)).pack(anchor="w", padx=22, pady=(18, 8))
        tk.Label(win, text="No files are deleted automatically.", bg=self.bg, fg=self.muted,
                 font=("Segoe UI", 9)).pack(anchor="w", padx=22, pady=(0, 8))
        listing = tk.Listbox(win, bg=self.panel, fg=self.text, relief="flat",
                             selectbackground="#2458a6", font=("Segoe UI", 9))
        listing.pack(fill="both", expand=True, padx=22, pady=8)
        for group in matches:
            for item in group:
                listing.insert("end", f'{item["artist"]} - {item["title"]}  •  {item["path"]}')
        self.button(win, "Close", win.destroy, bg=self.panel2, padx=14, pady=7).pack(
            anchor="e", padx=22, pady=(0, 18))

    def toggle_song_favorite(self,s):
        removing = s["id"] in self.db.favorites()
        if removing and self.settings.get("confirm_remove_favorite", False):
            if not messagebox.askyesno("Remove favorite", f'Remove "{s["title"]}" from favorites?', parent=self):
                return
        self.db.toggle_favorite(s["id"])
        self.update_player_actions()
        self.refresh()

    def set_song_reaction(self,s,value):
        self.db.set_reaction(s["id"],value)
        self.update_player_actions()

    def add_queue(self,s):
        self.queue.append(s)
        self.refresh_queue_panel()
        self.status.set(f'Added "{s["title"]}" to queue')

    def play_next_song(self,s):
        if not self.queue:self.queue=self.filtered()
        self.queue.insert(min(self.queue_index+1,len(self.queue)),s)

    def remove_from_playlist(self,s):
        if self.playlist_name:
            self.db.remove_from_playlist(self.playlist_name,s["id"]);self.refresh()

    def open_location(self,path):
        try:
            subprocess.Popen(["explorer","/select,",os.path.normpath(path)])
        except Exception:pass

    def refresh_playlists(self):
        for c in self.playlist_inner.winfo_children():c.destroy()
        for _,name in self.db.playlists():
            row=tk.Frame(self.playlist_inner,bg=self.panel)
            row.pack(fill="x")
            self.button(row,name,lambda n=name:self.set_view("Playlist:"+n),
                        bg=self.panel,anchor="w",padx=18,pady=6).pack(side="left",fill="x",expand=True)
            self.button(row,"⋮",lambda n=name:self.playlist_options(n),
                        bg=self.panel,fg=self.muted,width=3).pack(side="right")
            self.bind_scroll_wheel(row, self.playlist_canvas)

    def new_playlist(self):
        name=simpledialog.askstring("New Playlist","Playlist name:",parent=self)
        if name and name.strip():
            if not self.db.create_playlist(name.strip()):
                messagebox.showwarning("Playlist","That playlist already exists.",parent=self)
            self.refresh_playlists()

    def playlist_options(self,name):
        menu=tk.Menu(self,tearoff=0,bg=self.panel2,fg=self.text)
        menu.add_command(label="Open",command=lambda:self.set_view("Playlist:"+name))
        menu.add_command(label="Delete",command=lambda:self.delete_playlist(name))
        menu.tk_popup(self.winfo_pointerx(),self.winfo_pointery())

    def delete_playlist(self,name):
        if self.settings.get("confirm_delete_playlist",True):
            if not messagebox.askyesno("Delete playlist",f'Delete "{name}"?',parent=self):return
        self.db.delete_playlist(name)
        if self.playlist_name==name:self.set_view("Songs")
        self.refresh_playlists();self.refresh()

    def settings_window(self):
        win=tk.Toplevel(self)
        win.title("MusicVault Settings")
        win.geometry("800x670")
        win.configure(bg=self.bg)
        win.transient(self)

        tk.Label(win,text="Settings",bg=self.bg,fg=self.text,
                 font=("Segoe UI Semibold",24)).pack(anchor="w",padx=25,pady=(22,14))

        tk.Label(win,text="MUSIC FOLDERS",bg=self.bg,fg=self.muted,
                 font=("Segoe UI Semibold",9)).pack(anchor="w",padx=25)

        frame=tk.Frame(win,bg=self.panel)
        frame.pack(fill="both",expand=True,padx=25,pady=8)
        lb=tk.Listbox(frame,bg=self.panel,fg=self.text,
                      selectbackground="#2458a6",relief="flat",font=("Segoe UI",10))
        vs=ttk.Scrollbar(frame,orient="vertical",command=lb.yview)
        lb.configure(yscrollcommand=vs.set)
        lb.grid(row=0,column=0,sticky="nsew",padx=10,pady=10)
        vs.grid(row=0,column=1,sticky="ns",pady=10)
        frame.rowconfigure(0,weight=1);frame.columnconfigure(0,weight=1)
        for f in self.settings.get("music_folders",[]):lb.insert("end",f)

        tools=tk.Frame(frame,bg=self.panel)
        tools.grid(row=0,column=2,sticky="ns",padx=10,pady=10)
        self.button(tools,"+ Add Folder",lambda:self.add_setting_folder(lb),
                    bg=self.blue,fg="white",padx=14,pady=8).pack(fill="x")
        self.button(tools,"Remove",lambda:self.remove_setting_folder(lb),
                    bg=self.panel2,padx=14,pady=8).pack(fill="x",pady=8)
        self.button(tools,"Add Drive",lambda:self.add_setting_folder(lb),
                    bg=self.panel2,padx=14,pady=8).pack(fill="x")

        opts_host = tk.Frame(win, bg=self.bg, height=230)
        opts_host.pack(fill="x", padx=25, pady=12)
        opts_host.pack_propagate(False)
        opts_canvas = tk.Canvas(opts_host, bg=self.bg, highlightthickness=0)
        opts_scroll = ttk.Scrollbar(opts_host, orient="vertical", command=opts_canvas.yview)
        opts = tk.Frame(opts_canvas, bg=self.bg)
        opts_window = opts_canvas.create_window((0, 0), window=opts, anchor="nw")
        opts_canvas.configure(yscrollcommand=opts_scroll.set)
        opts.bind("<Configure>", lambda event: opts_canvas.configure(
            scrollregion=opts_canvas.bbox("all")))
        opts_canvas.bind("<Configure>", lambda event: opts_canvas.itemconfigure(
            opts_window, width=event.width))
        opts_canvas.bind("<MouseWheel>", lambda event: opts_canvas.yview_scroll(
            -int(event.delta / 120) or (-1 if event.delta > 0 else 1), "units"))
        opts_canvas.pack(side="left", fill="both", expand=True)
        opts_scroll.pack(side="right", fill="y")
        auto=tk.BooleanVar(value=self.settings.get("auto_scan",True))
        resume=tk.BooleanVar(value=self.settings.get("resume",True))
        confirm=tk.BooleanVar(value=self.settings.get("confirm_delete_playlist",True))
        albumstrip=tk.BooleanVar(value=self.settings.get("show_album_strip",True))
        statusbar=tk.BooleanVar(value=self.settings.get("show_status_bar",True))
        remember_shuffle=tk.BooleanVar(value=self.settings.get("remember_shuffle",True))
        remember_repeat=tk.BooleanVar(value=self.settings.get("remember_repeat",True))
        scan_hidden=tk.BooleanVar(value=self.settings.get("scan_hidden",False))
        confirm_remove_favorite=tk.BooleanVar(value=self.settings.get("confirm_remove_favorite",False))
        smooth_ui=tk.BooleanVar(value=self.settings.get("smooth_ui",True))
        reduced_motion=tk.BooleanVar(value=self.settings.get("reduced_motion",False))
        density=tk.StringVar(value=self.settings.get("density", "Comfortable"))
        startup_view=tk.StringVar(value=self.settings.get("startup_view", "Home"))
        player_height=tk.StringVar(value=self.settings.get("player_height", "Standard"))
        home_artwork_size=tk.StringVar(value=self.settings.get("home_artwork_size", "Medium"))
        library_page_size=tk.StringVar(value=str(self.settings.get("library_page_size", 250)))
        saved_home_sections = self.settings.get("home_sections", {})
        if not isinstance(saved_home_sections, dict):
            saved_home_sections = {}
        home_section_vars = {key: tk.BooleanVar(value=saved_home_sections.get(key, True))
                             for key in ("continue", "played", "added", "most", "favorites", "liked", "never")}
        shuffle_mode=tk.StringVar(value=self.settings.get("shuffle_mode", "Random"))
        for text,var in [("Scan automatically at startup",auto),
                         ("Resume songs where you left off",resume),
                         ("Confirm before deleting playlists",confirm),
                 ("Confirm before removing favorites",confirm_remove_favorite),
                 ("Scan hidden files and folders",scan_hidden),
                         ("Show album carousel",albumstrip),
                         ("Show status bar",statusbar),
                         ("Use smooth UI transitions",smooth_ui),
                         ("Reduce motion and animations",reduced_motion),
                         ("Remember shuffle state",remember_shuffle),
                         ("Remember repeat mode",remember_repeat)]:
            tk.Checkbutton(opts,text=text,variable=var,bg=self.bg,fg=self.text,
                           selectcolor=self.panel2,activebackground=self.bg,
                           activeforeground=self.text).pack(anchor="w")

        tk.Label(opts,text="Blue theme • local playback • no music uploads",
                 bg=self.bg,fg=self.muted,font=("Segoe UI",9)).pack(anchor="w",pady=(7,0))
        density_row=tk.Frame(opts,bg=self.bg)
        density_row.pack(fill="x", pady=(8, 0))
        tk.Label(density_row,text="Interface density",bg=self.bg,fg=self.text,
                 font=("Segoe UI Semibold",9)).pack(side="left")
        ttk.Combobox(density_row, textvariable=density,
                     values=["Comfortable", "Compact"], state="readonly",
                     width=18).pack(side="left", padx=12)
        shuffle_row = tk.Frame(opts, bg=self.bg)
        shuffle_row.pack(fill="x", pady=(8, 0))
        tk.Label(shuffle_row, text="Shuffle strategy", bg=self.bg, fg=self.text,
             font=("Segoe UI Semibold", 9)).pack(side="left")
        ttk.Combobox(shuffle_row, textvariable=shuffle_mode,
                 values=["Random", "Smart", "Artist Variety", "Album Variety"],
                 state="readonly", width=18).pack(side="left", padx=12)
        display_row=tk.Frame(opts,bg=self.bg)
        display_row.pack(fill="x", pady=(8, 0))
        for label, variable, values in (
            ("Startup view", startup_view, ["Home", "Songs", "Albums", "Artists", "Favorites", "Recently Added", "Most Played"]),
            ("Player height", player_height, ["Compact", "Standard", "Tall"]),
            ("Home artwork", home_artwork_size, ["Small", "Medium", "Large"]),
            ("Library result limit", library_page_size, ["100", "250", "500", "1000"]),
        ):
            row=tk.Frame(opts,bg=self.bg)
            row.pack(fill="x", pady=(5, 0))
            tk.Label(row,text=label,bg=self.bg,fg=self.text,
                     font=("Segoe UI Semibold",9),width=20,anchor="w").pack(side="left")
            ttk.Combobox(row,textvariable=variable,values=values,
                         state="readonly",width=20).pack(side="left",padx=12)
        tk.Label(opts,text="HOME SECTIONS",bg=self.bg,fg=self.muted,
                 font=("Segoe UI Semibold",9)).pack(anchor="w",pady=(12,4))
        for label, key in (("Continue Listening", "continue"), ("Recently Played", "played"),
                           ("Recently Added", "added"), ("Most Played", "most"),
                           ("Favorite Songs", "favorites"), ("Liked Songs", "liked"),
                           ("Never Played", "never")):
            tk.Checkbutton(opts,text=label,variable=home_section_vars[key],bg=self.bg,fg=self.text,
                           selectcolor=self.panel2,activebackground=self.bg,
                           activeforeground=self.text).pack(anchor="w")

        foot=tk.Frame(win,bg=self.bg);foot.pack(fill="x",padx=25,pady=(0,20))
        def save(and_scan=False):
            self.settings["music_folders"]=list(lb.get(0,"end"))
            self.settings["auto_scan"]=auto.get()
            self.settings["resume"]=resume.get()
            self.settings["confirm_delete_playlist"]=confirm.get()
            self.settings["show_album_strip"]=albumstrip.get()
            self.settings["show_status_bar"]=statusbar.get()
            self.settings["smooth_ui"]=smooth_ui.get()
            self.settings["reduced_motion"]=reduced_motion.get()
            self.settings["density"]=density.get()
            self.settings["startup_view"]=startup_view.get()
            self.settings["player_height"]=player_height.get()
            self.settings["home_artwork_size"]=home_artwork_size.get()
            self.settings["library_page_size"]=int(library_page_size.get())
            self.settings["home_sections"]={key: variable.get() for key, variable in home_section_vars.items()}
            self.settings["remember_shuffle"]=remember_shuffle.get()
            self.settings["remember_repeat"]=remember_repeat.get()
            self.settings["scan_hidden"]=scan_hidden.get()
            self.settings["confirm_remove_favorite"]=confirm_remove_favorite.get()
            self.settings["shuffle_mode"]=shuffle_mode.get()
            self.shuffle_mode=shuffle_mode.get()
            self.style_widgets()
            self.player_frame.config(height={"Compact": 104, "Standard": 128, "Tall": 154}.get(
                player_height.get(), 128))
            save_settings(self.settings);win.destroy()
            if statusbar.get():
                self.status_label.place(x=240, y=53)
            else:
                self.status_label.place_forget()
            self.album_strip.pack_forget() if not albumstrip.get() else None
            if albumstrip.get() and self.album_strip.winfo_manager()=="":
                self.album_strip.pack(fill="x", pady=(12,8), before=self.tree.master)
            if and_scan:self.start_scan()
            else:
                if self.view == "Home":
                    self.refresh_home_dashboard()
                else:
                    self.refresh()
                self.status.set("Settings saved")
        self.button(foot,"Save",save,bg=self.panel2,padx=20,pady=9).pack(side="right",padx=7)
        self.button(foot,"Save & Scan",lambda:save(True),
                    bg=self.blue,fg="white",padx=20,pady=9).pack(side="right")
        self.button(foot,"Export JSON",self.export_library_json,
                    bg=self.panel2,padx=14,pady=9).pack(side="left")
        self.button(foot,"Backup DB",self.backup_database,
                    bg=self.panel2,padx=14,pady=9).pack(side="left", padx=7)
        self.button(foot,"Restore DB",self.restore_database,
                bg=self.panel2,padx=14,pady=9).pack(side="left")
        self.button(foot,"Export M3U",self.export_m3u,
                bg=self.panel2,padx=14,pady=9).pack(side="left", padx=7)
        self.button(foot,"Organize Library",self.organizer_window,
            bg=self.panel2,padx=14,pady=9).pack(side="left")

    def backup_database(self):
        target = filedialog.asksaveasfilename(parent=self, title="Backup MusicVault database",
                                               defaultextension=".db",
                                               filetypes=[("SQLite database", "*.db"), ("All files", "*.*")])
        if not target:
            return
        try:
            self.db.backup_to(target)
            self.status.set("Database backup created")
        except (OSError, sqlite3.Error) as exc:
            messagebox.showerror("Backup failed", str(exc), parent=self)

    def export_library_json(self):
        target = filedialog.asksaveasfilename(parent=self, title="Export MusicVault data",
                                               defaultextension=".json",
                                               filetypes=[("JSON", "*.json"), ("All files", "*.*")])
        if not target:
            return
        try:
            payload = self.db.export_data()
            payload["settings"] = self.settings
            with open(target, "w", encoding="utf-8") as stream:
                json.dump(payload, stream, indent=2)
            self.status.set("MusicVault data exported")
        except (OSError, TypeError) as exc:
            messagebox.showerror("Export failed", str(exc), parent=self)

    def restore_database(self):
        source_path = filedialog.askopenfilename(parent=self, title="Restore MusicVault database",
                                                 filetypes=[("SQLite database", "*.db"), ("All files", "*.*")])
        if not source_path or os.path.abspath(source_path) == os.path.abspath(DB_FILE):
            return
        if not messagebox.askyesno("Restore database",
                                   "The current database will be backed up before restore. Continue?",
                                   parent=self):
            return
        try:
            automatic_backup = os.path.join(DATA_DIR, f"musicvault-before-restore-{int(time.time())}.db")
            self.db.backup_to(automatic_backup)
            self.db.restore_from(source_path)
            self.invalidate_library()
            self.refresh_playlists()
            self.refresh()
            self.status.set("Database restored; previous database backed up")
        except (OSError, sqlite3.Error) as exc:
            messagebox.showerror("Restore failed", str(exc), parent=self)

    def export_m3u(self):
        songs = self.base_songs()
        if not songs:
            self.status.set("No songs to export")
            return
        target = filedialog.asksaveasfilename(parent=self, title="Export playlist",
                                               defaultextension=".m3u8",
                                               filetypes=[("M3U8 playlist", "*.m3u8"), ("M3U playlist", "*.m3u")])
        if not target:
            return
        try:
            with open(target, "w", encoding="utf-8") as stream:
                stream.write("#EXTM3U\n")
                for song in songs:
                    stream.write(f"#EXTINF:{int(song['duration'])},{song['artist']} - {song['title']}\n")
                    stream.write(song["path"] + "\n")
            self.status.set("Playlist exported")
        except OSError as exc:
            messagebox.showerror("Playlist export failed", str(exc), parent=self)

    def organizer_window(self):
        songs = self.get_library()
        if not songs:
            self.status.set("There are no songs to organize")
            return
        root = filedialog.askdirectory(parent=self, title="Choose organization root")
        if not root:
            return
        template = simpledialog.askstring(
            "Organization template",
            "Use {Artist}, {Album}, {Year}, {Track}, {Title}, and {ext}.",
            initialvalue="{Artist}/{Year} - {Album}/{Track} - {Title}.{ext}",
            parent=self,
        )
        if not template:
            return
        try:
            plan = build_plan(songs, root, template)
        except (KeyError, ValueError) as exc:
            messagebox.showerror("Organizer", f"Invalid template: {exc}", parent=self)
            return
        win = tk.Toplevel(self)
        win.title("MusicVault Organizer Preview")
        win.geometry("850x500")
        win.configure(bg=self.bg)
        tk.Label(win, text="ORGANIZATION PREVIEW", bg=self.bg, fg=self.blue2,
                 font=("Segoe UI Semibold", 10)).pack(anchor="w", padx=22, pady=(18, 4))
        tk.Label(win, text="Nothing moves until you confirm Apply.", bg=self.bg, fg=self.muted,
                 font=("Segoe UI", 9)).pack(anchor="w", padx=22, pady=(0, 8))
        listing = tk.Listbox(win, bg=self.panel, fg=self.text, relief="flat",
                             font=("Segoe UI", 9))
        listing.pack(fill="both", expand=True, padx=22, pady=8)
        for item in plan:
            listing.insert("end", f'{item["source"]}  ->  {item["destination"]}')
        footer = tk.Frame(win, bg=self.bg)
        footer.pack(fill="x", padx=22, pady=(0, 18))

        def apply_changes():
            if not messagebox.askyesno("Confirm organization", "Move these files now?", parent=win):
                return
            try:
                moved = apply_plan(plan)
                win.destroy()
                self.invalidate_library()
                self.start_scan()
                self.status.set(f"Moved {len(moved)} files; rescanning library")
            except (OSError, ValueError) as exc:
                messagebox.showerror("Organization failed", str(exc), parent=win)

        self.button(footer, "Cancel", win.destroy, bg=self.panel2,
                    padx=14, pady=7).pack(side="right")
        self.button(footer, "Apply Moves", apply_changes, bg=self.blue,
                    fg="white", padx=14, pady=7).pack(side="right", padx=8)

    def add_setting_folder(self,lb):
        f=filedialog.askdirectory(parent=self,title="Select music folder")
        if f:
            f=normalize(f)
            if f not in lb.get(0,"end"):lb.insert("end",f)

    def remove_setting_folder(self,lb):
        for i in reversed(lb.curselection()):lb.delete(i)

    def start_scan(self):
        if self.scan_running:return
        folders=[normalize(f) for f in self.settings.get("music_folders",[]) if os.path.isdir(f)]
        if not folders:
            self.status.set("Add music folders in Settings")
            return
        self.scan_running=True
        self.scan_cancel.clear()
        self.scan_progress = (0, 0)
        self.scan_result = None
        self.scan_error = None
        self.status.set("Scanning library...")
        self.scan_thread = threading.Thread(target=self.scan_worker, args=(folders,), daemon=True)
        self.scan_thread.start()

    def scan_status_tick(self):
        if self.scan_progress and self.scan_running:
            changed, total = self.scan_progress
            self.status.set(f"Scanning... {changed} changed • {total} files found")
        if self.scan_result:
            total, changed, error, cancelled = self.scan_result
            self.scan_result = None
            self.scan_progress = None
            if error:
                self.scan_running = False
                self.status.set(f"Scan failed: {error}")
            elif cancelled:
                self.scan_running = False
                self.status.set("Scan cancelled")
            else:
                self.scan_finished(total, changed)
        self.after(250, self.scan_status_tick)

    def scan_worker(self,folders):
        found = {}
        total = changed = 0
        error = None
        try:
            for folder in folders:
                if self.scan_cancel.is_set():
                    break
                for root, dirs, files in os.walk(folder):
                    if self.scan_cancel.is_set():
                        break
                    dirs[:] = [d for d in dirs if d.lower() not in {
                        "$recycle.bin", "system volume information", ".git", ".venv", "node_modules"
                    }]
                    if not self.settings.get("scan_hidden", False):
                        dirs[:] = [d for d in dirs if not d.startswith(".")]
                    for file in files:
                        if not self.settings.get("scan_hidden", False) and file.startswith("."):
                            continue
                        if os.path.splitext(file)[1].lower() in EXTENSIONS:
                            p = normalize(os.path.join(root, file))
                            found[p] = p

            old = self.db.existing_mtimes()
            paths = list(found.values())
            total = len(paths)
            for path in paths:
                if self.scan_cancel.is_set():
                    break
                try:
                    modified = os.path.getmtime(path)
                    item = old.get(path)
                    if item is None or abs(float(item[1]) - modified) > 0.001:
                        self.db.upsert(metadata(path))
                        changed += 1
                    if changed % 25 == 0:
                        self.scan_progress = (changed, total)
                except (OSError, PermissionError):
                    pass
            if not self.scan_cancel.is_set():
                self.db.remove_missing(paths)
        except Exception as exc:
            error = str(exc)
        self.scan_progress = (changed, total)
        self.scan_result = (total, changed, error, self.scan_cancel.is_set())

    def scan_finished(self,total,changed):
        self.scan_running=False
        self.invalidate_library()
        self.status.set(f"Library ready • {total} files • {changed} updated")
        self.refresh()
        self.refresh_playlists()

    def close(self):
        self.closing = True
        self.scan_cancel.set()
        if self.scan_thread and self.scan_thread.is_alive():
            self.scan_thread.join(timeout=5)
        try:
            if self.current and pygame and not self.paused:
                pos=max(0,self.playback_offset + pygame.mixer.music.get_pos()/1000)
                self.db.set_position(self.current["id"],pos)
            save_settings(self.settings)
            if pygame:
                pygame.mixer.music.stop();pygame.mixer.quit()
            if not self.scan_thread or not self.scan_thread.is_alive():
                self.db.close()
        except Exception:pass
        self.destroy()


if __name__ == "__main__":
    MusicVault().mainloop()
