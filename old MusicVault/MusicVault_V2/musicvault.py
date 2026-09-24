import os
import json
import random
import threading
import time
import sqlite3
import io
import sys
import subprocess
import tkinter as tk
from tkinter import filedialog, messagebox, ttk, simpledialog

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
AUDIO_EXTENSIONS = {
    ".mp3", ".wav", ".flac", ".m4a", ".aac", ".ogg", ".opus",
    ".wma", ".aiff", ".aif", ".ape", ".wv", ".mka"
}

DATA_DIR = os.path.join(os.getenv("APPDATA") or os.path.expanduser("~"), APP_NAME)
DB_FILE = os.path.join(DATA_DIR, "musicvault.db")
SETTINGS_FILE = os.path.join(DATA_DIR, "settings.json")


def ensure_data():
    os.makedirs(DATA_DIR, exist_ok=True)


def load_settings():
    ensure_data()
    defaults = {
        "music_folders": [],
        "auto_scan": True,
        "volume": 0.75,
        "theme": "dark",
        "crossfade": 0,
        "gapless": True,
        "show_hidden": False,
        "last_view": "Songs",
    }
    try:
        with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
            defaults.update(json.load(f))
    except Exception:
        pass
    return defaults


def save_settings(settings):
    ensure_data()
    with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
        json.dump(settings, f, indent=2)


def clean(v, fallback="Unknown"):
    if v is None:
        return fallback
    if isinstance(v, (list, tuple)):
        v = v[0] if v else fallback
    v = str(v).strip()
    return v or fallback


def tag_value(tags, keys, fallback="Unknown"):
    if not tags:
        return fallback
    for key in keys:
        try:
            if key in tags:
                return clean(tags[key], fallback)
        except Exception:
            pass
    return fallback


def fmt_time(seconds):
    try:
        seconds = int(max(0, seconds))
    except Exception:
        seconds = 0
    return f"{seconds // 60}:{seconds % 60:02d}"


def normalize_path(path):
    return os.path.normcase(os.path.abspath(path))


def extract_metadata(path):
    base = os.path.splitext(os.path.basename(path))[0]
    data = {
        "path": normalize_path(path),
        "title": base,
        "artist": "Unknown Artist",
        "album": "Unknown Album",
        "genre": "Unknown Genre",
        "year": "",
        "track": 0,
        "disc": 0,
        "duration": 0.0,
        "artwork": None,
        "modified": os.path.getmtime(path) if os.path.exists(path) else 0,
    }

    if not MutagenFile:
        return data

    try:
        audio = MutagenFile(path, easy=False)
        if not audio:
            return data

        info = getattr(audio, "info", None)
        data["duration"] = float(getattr(info, "length", 0) or 0)

        tags = getattr(audio, "tags", None)
        if tags:
            data["title"] = tag_value(tags, ["TIT2", "title", "\xa9nam"], base)
            data["artist"] = tag_value(tags, ["TPE1", "artist", "\xa9ART"], "Unknown Artist")
            data["album"] = tag_value(tags, ["TALB", "album", "\xa9alb"], "Unknown Album")
            data["genre"] = tag_value(tags, ["TCON", "genre", "\xa9gen"], "Unknown Genre")
            data["year"] = tag_value(tags, ["TDRC", "date", "\xa9day"], "")

            track = tag_value(tags, ["TRCK", "tracknumber"], "0")
            disc = tag_value(tags, ["TPOS", "discnumber"], "0")
            try:
                data["track"] = int(str(track).split("/")[0])
            except Exception:
                data["track"] = 0
            try:
                data["disc"] = int(str(disc).split("/")[0])
            except Exception:
                data["disc"] = 0

        if hasattr(audio, "pictures") and audio.pictures:
            data["artwork"] = audio.pictures[0].data
        elif tags:
            for key in ("APIC:", "covr", "artwork"):
                try:
                    if key in tags:
                        item = tags[key]
                        if isinstance(item, list):
                            item = item[0]
                        blob = getattr(item, "data", item)
                        if isinstance(blob, bytes):
                            data["artwork"] = blob
                            break
                except Exception:
                    pass
    except Exception:
        pass

    return data


class Database:
    def __init__(self):
        ensure_data()
        self.conn = sqlite3.connect(DB_FILE, check_same_thread=False)
        self.lock = threading.Lock()
        self.setup()

    def setup(self):
        with self.lock:
            c = self.conn.cursor()
            c.executescript("""
            CREATE TABLE IF NOT EXISTS songs (
                id INTEGER PRIMARY KEY,
                path TEXT UNIQUE NOT NULL,
                title TEXT,
                artist TEXT,
                album TEXT,
                genre TEXT,
                year TEXT,
                track INTEGER DEFAULT 0,
                disc INTEGER DEFAULT 0,
                duration REAL DEFAULT 0,
                artwork BLOB,
                added REAL,
                modified REAL
            );

            CREATE TABLE IF NOT EXISTS playlists (
                id INTEGER PRIMARY KEY,
                name TEXT UNIQUE NOT NULL,
                created REAL
            );

            CREATE TABLE IF NOT EXISTS playlist_songs (
                playlist_id INTEGER,
                song_id INTEGER,
                position INTEGER,
                PRIMARY KEY (playlist_id, song_id)
            );

            CREATE TABLE IF NOT EXISTS favorites (
                song_id INTEGER PRIMARY KEY
            );

            CREATE TABLE IF NOT EXISTS play_history (
                id INTEGER PRIMARY KEY,
                song_id INTEGER,
                played_at REAL
            );
            """)
            self.conn.commit()

    def upsert_song(self, d):
        with self.lock:
            self.conn.execute("""
                INSERT INTO songs
                (path,title,artist,album,genre,year,track,disc,duration,artwork,added,modified)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(path) DO UPDATE SET
                title=excluded.title, artist=excluded.artist, album=excluded.album,
                genre=excluded.genre, year=excluded.year, track=excluded.track,
                disc=excluded.disc, duration=excluded.duration, artwork=excluded.artwork,
                modified=excluded.modified
            """, (
                d["path"], d["title"], d["artist"], d["album"], d["genre"], d["year"],
                d["track"], d["disc"], d["duration"], d["artwork"], time.time(), d["modified"]
            ))
            self.conn.commit()

    def remove_missing(self, paths):
        with self.lock:
            rows = self.conn.execute("SELECT id,path FROM songs").fetchall()
            valid = {normalize_path(p) for p in paths}
            for sid, path in rows:
                if normalize_path(path) not in valid:
                    self.conn.execute("DELETE FROM playlist_songs WHERE song_id=?", (sid,))
                    self.conn.execute("DELETE FROM favorites WHERE song_id=?", (sid,))
                    self.conn.execute("DELETE FROM songs WHERE id=?", (sid,))
            self.conn.commit()

    def songs(self):
        with self.lock:
            cur = self.conn.execute("""
                SELECT id,path,title,artist,album,genre,year,track,disc,duration,artwork,added,modified
                FROM songs
                ORDER BY lower(artist), lower(album), disc, track, lower(title)
            """)
            return [self.row(r) for r in cur.fetchall()]

    def recent(self, limit=100):
        with self.lock:
            cur = self.conn.execute("""
                SELECT id,path,title,artist,album,genre,year,track,disc,duration,artwork,added,modified
                FROM songs ORDER BY added DESC LIMIT ?
            """, (limit,))
            return [self.row(r) for r in cur.fetchall()]

    def row(self, r):
        keys = ["id","path","title","artist","album","genre","year","track","disc","duration","artwork","added","modified"]
        return dict(zip(keys, r))

    def favorites(self):
        with self.lock:
            ids = {r[0] for r in self.conn.execute("SELECT song_id FROM favorites")}
        return ids

    def toggle_favorite(self, song_id):
        with self.lock:
            if self.conn.execute("SELECT 1 FROM favorites WHERE song_id=?", (song_id,)).fetchone():
                self.conn.execute("DELETE FROM favorites WHERE song_id=?", (song_id,))
            else:
                self.conn.execute("INSERT INTO favorites(song_id) VALUES(?)", (song_id,))
            self.conn.commit()

    def create_playlist(self, name):
        with self.lock:
            try:
                self.conn.execute("INSERT INTO playlists(name,created) VALUES(?,?)", (name, time.time()))
                self.conn.commit()
                return True
            except sqlite3.IntegrityError:
                return False

    def delete_playlist(self, name):
        with self.lock:
            row = self.conn.execute("SELECT id FROM playlists WHERE name=?", (name,)).fetchone()
            if row:
                self.conn.execute("DELETE FROM playlist_songs WHERE playlist_id=?", (row[0],))
                self.conn.execute("DELETE FROM playlists WHERE id=?", (row[0],))
                self.conn.commit()

    def playlists(self):
        with self.lock:
            return self.conn.execute("SELECT id,name FROM playlists ORDER BY lower(name)").fetchall()

    def add_playlist_song(self, playlist_name, song_id):
        with self.lock:
            p = self.conn.execute("SELECT id FROM playlists WHERE name=?", (playlist_name,)).fetchone()
            if not p:
                return
            n = self.conn.execute(
                "SELECT COALESCE(MAX(position),-1)+1 FROM playlist_songs WHERE playlist_id=?",
                (p[0],)
            ).fetchone()[0]
            self.conn.execute(
                "INSERT OR IGNORE INTO playlist_songs VALUES(?,?,?)",
                (p[0], song_id, n)
            )
            self.conn.commit()

    def remove_playlist_song(self, playlist_name, song_id):
        with self.lock:
            p = self.conn.execute("SELECT id FROM playlists WHERE name=?", (playlist_name,)).fetchone()
            if p:
                self.conn.execute(
                    "DELETE FROM playlist_songs WHERE playlist_id=? AND song_id=?",
                    (p[0], song_id)
                )
                self.conn.commit()

    def playlist_songs(self, playlist_name):
        with self.lock:
            rows = self.conn.execute("""
                SELECT s.id,s.path,s.title,s.artist,s.album,s.genre,s.year,
                       s.track,s.disc,s.duration,s.artwork,s.added,s.modified
                FROM songs s
                JOIN playlist_songs ps ON ps.song_id=s.id
                JOIN playlists p ON p.id=ps.playlist_id
                WHERE p.name=?
                ORDER BY ps.position
            """, (playlist_name,)).fetchall()
            return [self.row(r) for r in rows]

    def add_history(self, song_id):
        with self.lock:
            self.conn.execute(
                "INSERT INTO play_history(song_id,played_at) VALUES(?,?)",
                (song_id, time.time())
            )
            self.conn.commit()

    def most_played(self, limit=50):
        with self.lock:
            rows = self.conn.execute("""
                SELECT s.id,s.path,s.title,s.artist,s.album,s.genre,s.year,s.track,
                       s.disc,s.duration,s.artwork,s.added,s.modified,COUNT(h.id) plays
                FROM songs s
                LEFT JOIN play_history h ON h.song_id=s.id
                GROUP BY s.id
                ORDER BY plays DESC, lower(s.title)
                LIMIT ?
            """, (limit,)).fetchall()
            return [self.row(r[:13]) | {"plays": r[13]} for r in rows]

    def close(self):
        self.conn.close()


class MusicVault(tk.Tk):
    def __init__(self):
        super().__init__()
        self.settings = load_settings()
        self.db = Database()

        self.colors = {
            "bg": "#0f1114", "panel": "#171a1f", "panel2": "#20242a",
            "hover": "#292f37", "text": "#f4f5f7", "muted": "#9aa3ad",
            "accent": "#8b5cf6", "accent2": "#a78bfa", "border": "#30363d"
        }

        self.title("MusicVault")
        self.geometry("1280x800")
        self.minsize(950, 620)
        self.configure(bg=self.colors["bg"])
        self.protocol("WM_DELETE_WINDOW", self.close_app)

        self.view = "Songs"
        self.current_playlist = None
        self.queue = []
        self.queue_index = -1
        self.current = None
        self.paused = False
        self.shuffle = False
        self.repeat = "off"
        self.art_ref = None
        self.scan_running = False
        self.search_var = tk.StringVar()
        self.search_var.trace_add("write", lambda *_: self.refresh())

        self.init_audio()
        self.build()
        self.refresh_playlists()
        self.refresh()

        if self.settings.get("auto_scan", True):
            self.after(800, self.start_scan)

        self.after(500, self.tick)

    def init_audio(self):
        if pygame:
            try:
                pygame.mixer.init()
                pygame.mixer.music.set_volume(float(self.settings.get("volume", 0.75)))
            except Exception:
                pass

    def build(self):
        # Header
        header = tk.Frame(self, bg=self.colors["bg"], height=68)
        header.pack(fill="x")
        header.pack_propagate(False)

        tk.Label(
            header, text="♫ MusicVault", bg=self.colors["bg"], fg=self.colors["text"],
            font=("Segoe UI Semibold", 20)
        ).pack(side="left", padx=22)

        search = tk.Entry(
            header, textvariable=self.search_var, bg=self.colors["panel2"],
            fg=self.colors["text"], insertbackground=self.colors["text"],
            relief="flat", font=("Segoe UI", 11), width=44
        )
        search.pack(side="left", padx=18, ipady=9)
        search.bind("<Escape>", lambda e: self.search_var.set(""))
        self.search_entry = search

        tk.Button(
            header, text="↻ Scan", command=self.start_scan, bg=self.colors["panel2"],
            fg=self.colors["text"], activebackground=self.colors["hover"],
            activeforeground=self.colors["text"], relief="flat", padx=13, pady=8
        ).pack(side="right", padx=(8, 10))

        tk.Button(
            header, text="⚙ Settings", command=self.settings_window,
            bg=self.colors["panel2"], fg=self.colors["text"],
            activebackground=self.colors["hover"], activeforeground=self.colors["text"],
            relief="flat", padx=14, pady=8
        ).pack(side="right", padx=18)

        # Main
        main = tk.Frame(self, bg=self.colors["bg"])
        main.pack(fill="both", expand=True)

        self.sidebar = tk.Frame(main, bg=self.colors["panel"], width=220)
        self.sidebar.pack(side="left", fill="y")
        self.sidebar.pack_propagate(False)

        self.add_nav("Home", "Home")
        self.add_nav("Songs", "Songs")
        self.add_nav("Albums", "Albums")
        self.add_nav("Artists", "Artists")
        self.add_nav("Genres", "Genres")
        self.add_nav("Recently Added", "Recently Added")
        self.add_nav("Most Played", "Most Played")
        self.add_nav("Favorites", "Favorites")

        tk.Label(
            self.sidebar, text="PLAYLISTS", bg=self.colors["panel"], fg=self.colors["muted"],
            font=("Segoe UI Semibold", 9)
        ).pack(anchor="w", padx=18, pady=(22, 7))

        self.playlist_frame = tk.Frame(self.sidebar, bg=self.colors["panel"])
        self.playlist_frame.pack(fill="x")

        tk.Button(
            self.sidebar, text="+ New Playlist", command=self.new_playlist,
            anchor="w", bg=self.colors["panel"], fg=self.colors["accent2"],
            activebackground=self.colors["hover"], activeforeground=self.colors["accent2"],
            relief="flat", padx=18, pady=9, cursor="hand2"
        ).pack(side="bottom", fill="x", pady=12)

        content = tk.Frame(main, bg=self.colors["bg"])
        content.pack(side="left", fill="both", expand=True, padx=18, pady=14)

        top = tk.Frame(content, bg=self.colors["bg"])
        top.pack(fill="x")

        self.view_title = tk.Label(
            top, text="Songs", bg=self.colors["bg"], fg=self.colors["text"],
            font=("Segoe UI Semibold", 23)
        )
        self.view_title.pack(side="left")

        self.count_label = tk.Label(
            top, text="", bg=self.colors["bg"], fg=self.colors["muted"],
            font=("Segoe UI", 9)
        )
        self.count_label.pack(side="left", padx=12, pady=(8, 0))

        self.album_area = tk.Frame(content, bg=self.colors["bg"])
        self.album_area.pack(fill="x", pady=(12, 8))

        # Table with vertical and horizontal scrollbars
        table_frame = tk.Frame(content, bg=self.colors["panel"])
        table_frame.pack(fill="both", expand=True)

        cols = ("title", "artist", "album", "genre", "year", "time")
        self.tree = ttk.Treeview(table_frame, columns=cols, show="headings", selectmode="extended")
        headings = {
            "title": "TITLE", "artist": "ARTIST", "album": "ALBUM",
            "genre": "GENRE", "year": "YEAR", "time": "TIME"
        }
        widths = {"title": 320, "artist": 190, "album": 230, "genre": 140, "year": 70, "time": 75}
        for c in cols:
            self.tree.heading(c, text=headings[c])
            self.tree.column(c, width=widths[c], anchor="w")

        vs = ttk.Scrollbar(table_frame, orient="vertical", command=self.tree.yview)
        hs = ttk.Scrollbar(table_frame, orient="horizontal", command=self.tree.xview)
        self.tree.configure(yscrollcommand=vs.set, xscrollcommand=hs.set)
        self.tree.grid(row=0, column=0, sticky="nsew")
        vs.grid(row=0, column=1, sticky="ns")
        hs.grid(row=1, column=0, sticky="ew")
        table_frame.rowconfigure(0, weight=1)
        table_frame.columnconfigure(0, weight=1)

        self.tree.bind("<Double-1>", self.play_selected)
        self.tree.bind("<Return>", self.play_selected)
        self.tree.bind("<Button-3>", self.context_menu)

        # Player
        self.build_player()

        self.status = tk.StringVar(value="Ready")
        tk.Label(
            self, textvariable=self.status, bg=self.colors["bg"], fg=self.colors["muted"],
            font=("Segoe UI", 8)
        ).place(x=230, y=52)

    def add_nav(self, label, view):
        b = tk.Button(
            self.sidebar, text=label, anchor="w", command=lambda: self.set_view(view),
            bg=self.colors["panel"], fg=self.colors["text"],
            activebackground=self.colors["hover"], activeforeground=self.colors["text"],
            relief="flat", padx=18, pady=9, font=("Segoe UI", 10), cursor="hand2"
        )
        b.pack(fill="x")
        setattr(self, f"nav_{view.replace(' ', '_').lower()}", b)

    def build_player(self):
        player = tk.Frame(self, bg=self.colors["panel"], height=125)
        player.pack(fill="x", side="bottom")
        player.pack_propagate(False)

        self.art_label = tk.Label(
            player, text="♫", bg=self.colors["panel2"], fg=self.colors["muted"],
            width=7, height=4, font=("Segoe UI", 20)
        )
        self.art_label.pack(side="left", padx=15, pady=10)

        info = tk.Frame(player, bg=self.colors["panel"], width=240)
        info.pack(side="left", fill="y", pady=18)
        info.pack_propagate(False)

        self.now_title = tk.Label(
            info, text="Nothing playing", bg=self.colors["panel"],
            fg=self.colors["text"], font=("Segoe UI Semibold", 11), anchor="w"
        )
        self.now_title.pack(fill="x")
        self.now_artist = tk.Label(
            info, text="", bg=self.colors["panel"], fg=self.colors["muted"],
            font=("Segoe UI", 9), anchor="w"
        )
        self.now_artist.pack(fill="x", pady=3)

        center = tk.Frame(player, bg=self.colors["panel"])
        center.pack(side="left", fill="both", expand=True)

        controls = tk.Frame(center, bg=self.colors["panel"])
        controls.pack(pady=(8, 0))

        self.shuffle_btn = self.player_button(controls, "⤨", self.toggle_shuffle)
        self.player_button(controls, "◀◀", self.previous)
        self.play_btn = tk.Button(
            controls, text="▶", command=self.toggle_play,
            bg=self.colors["accent"], fg="white", activebackground=self.colors["accent2"],
            relief="flat", width=4, font=("Segoe UI Semibold", 12), cursor="hand2"
        )
        self.play_btn.pack(side="left", padx=9)
        self.player_button(controls, "▶▶", self.next)
        self.repeat_btn = self.player_button(controls, "↻", self.toggle_repeat)

        self.progress = ttk.Scale(center, from_=0, to=100, orient="horizontal")
        self.progress.pack(fill="x", padx=22, pady=(3, 0))
        self.progress.bind("<ButtonRelease-1>", self.seek)

        times = tk.Frame(center, bg=self.colors["panel"])
        times.pack(fill="x", padx=22)
        self.elapsed = tk.Label(times, text="0:00", bg=self.colors["panel"], fg=self.colors["muted"])
        self.elapsed.pack(side="left")
        self.total = tk.Label(times, text="0:00", bg=self.colors["panel"], fg=self.colors["muted"])
        self.total.pack(side="right")

        vol = tk.Frame(player, bg=self.colors["panel"])
        vol.pack(side="right", padx=17)
        tk.Label(vol, text="VOL", bg=self.colors["panel"], fg=self.colors["muted"],
                 font=("Segoe UI Semibold", 8)).pack()
        self.volume = ttk.Scale(
            vol, from_=0, to=1, orient="horizontal",
            value=float(self.settings.get("volume", .75)),
            command=self.set_volume, length=105
        )
        self.volume.pack()

    def player_button(self, parent, text, command):
        b = tk.Button(
            parent, text=text, command=command, bg=self.colors["panel"],
            fg=self.colors["muted"], activebackground=self.colors["panel"],
            activeforeground=self.colors["accent2"], relief="flat", bd=0,
            font=("Segoe UI", 12), cursor="hand2"
        )
        b.pack(side="left", padx=8)
        return b

    def set_view(self, view):
        self.view = view
        self.current_playlist = view.split(":", 1)[1] if view.startswith("Playlist:") else None
        self.view_title.config(text=self.current_playlist if self.current_playlist else view)
        self.refresh()

    def all_songs(self):
        if self.current_playlist:
            return self.db.playlist_songs(self.current_playlist)
        if self.view == "Recently Added":
            return self.db.recent()
        if self.view == "Most Played":
            return self.db.most_played()
        return self.db.songs()

    def filtered(self):
        songs = self.all_songs()

        if self.view == "Favorites":
            ids = self.db.favorites()
            songs = [s for s in songs if s["id"] in ids]

        if self.view == "Home":
            songs = self.db.recent(25)

        if self.view == "Artists":
            seen, out = set(), []
            for s in songs:
                if s["artist"] not in seen:
                    seen.add(s["artist"])
                    out.append(s)
            songs = out

        if self.view == "Albums":
            seen, out = set(), []
            for s in songs:
                key = (s["artist"], s["album"])
                if key not in seen:
                    seen.add(key)
                    out.append(s)
            songs = out

        if self.view == "Genres":
            seen, out = set(), []
            for s in songs:
                if s["genre"] not in seen:
                    seen.add(s["genre"])
                    out.append(s)
            songs = out

        q = self.search_var.get().strip().lower()
        if q:
            songs = [
                s for s in songs if any(
                    q in str(s[k]).lower()
                    for k in ("title", "artist", "album", "genre", "year")
                )
            ]
        return songs

    def refresh(self):
        for item in self.tree.get_children():
            self.tree.delete(item)

        songs = self.filtered()
        self.visible = songs

        for i, s in enumerate(songs):
            self.tree.insert(
                "", "end", iid=str(i),
                values=(
                    s["title"], s["artist"], s["album"], s["genre"],
                    s["year"], fmt_time(s["duration"])
                )
            )

        self.count_label.config(text=f"{len(songs)} items")
        self.status.set(f"{len(songs)} item{'s' if len(songs) != 1 else ''}")
        self.refresh_album_strip(songs)

    def refresh_album_strip(self, songs):
        for child in self.album_area.winfo_children():
            child.destroy()

        if self.view not in ("Albums", "Home"):
            return

        albums = []
        seen = set()
        for s in songs:
            key = (s["artist"], s["album"])
            if key not in seen:
                seen.add(key)
                albums.append(s)

        if not albums:
            return

        canvas = tk.Canvas(self.album_area, bg=self.colors["bg"], height=135, highlightthickness=0)
        scrollbar = ttk.Scrollbar(self.album_area, orient="horizontal", command=canvas.xview)
        canvas.configure(xscrollcommand=scrollbar.set)
        inner = tk.Frame(canvas, bg=self.colors["bg"])
        canvas.create_window((0, 0), window=inner, anchor="nw")
        inner.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.pack(fill="x")
        scrollbar.pack(fill="x")

        for s in albums[:50]:
            card = tk.Frame(inner, bg=self.colors["panel"], width=105, height=122)
            card.pack(side="left", padx=(0, 9))
            card.pack_propagate(False)
            art = self.make_art(s.get("artwork"), 82)
            lab = tk.Label(card, image=art, bg=self.colors["panel"])
            lab.image = art
            lab.pack(pady=5)
            tk.Label(card, text=s["album"][:16], bg=self.colors["panel"], fg=self.colors["text"],
                     font=("Segoe UI Semibold", 8)).pack()
            tk.Label(card, text=s["artist"][:16], bg=self.colors["panel"], fg=self.colors["muted"],
                     font=("Segoe UI", 7)).pack()
            card.bind("<Double-Button-1>", lambda e, song=s: self.play_album(song))

    def make_art(self, blob, size=70):
        if Image is None:
            return None
        try:
            if blob:
                im = Image.open(io.BytesIO(blob)).convert("RGB")
                im.thumbnail((size, size))
            else:
                im = Image.new("RGB", (size, size))
                d = ImageDraw.Draw(im)
                d.rectangle((0, 0, size, size), fill="#292f37")
                d.text((size//2, size//2), "♫", fill="#a78bfa", anchor="mm")
            return ImageTk.PhotoImage(im)
        except Exception:
            return None

    def play_album(self, song):
        album_songs = [
            s for s in self.db.songs()
            if s["artist"] == song["artist"] and s["album"] == song["album"]
        ]
        album_songs.sort(key=lambda s: (s["disc"], s["track"], s["title"].lower()))
        self.queue = album_songs
        self.queue_index = 0
        self.play(self.queue[0])

    def selected(self):
        result = []
        for iid in self.tree.selection():
            try:
                result.append(self.visible[int(iid)])
            except Exception:
                pass
        return result

    def play_selected(self, event=None):
        selected = self.selected()
        if not selected:
            return
        self.queue = self.filtered()
        target = selected[0]
        self.queue_index = next(
            (i for i, s in enumerate(self.queue) if s["id"] == target["id"]), 0
        )
        self.play(self.queue[self.queue_index])

    def play(self, song):
        if not pygame:
            messagebox.showerror("Audio engine missing", "Install dependencies with run_musicvault.bat.")
            return
        if not os.path.exists(song["path"]):
            self.start_scan()
            return

        try:
            pygame.mixer.music.load(song["path"])
            pygame.mixer.music.play()
            pygame.mixer.music.set_volume(float(self.volume.get()))
            self.current = song
            self.paused = False
            self.play_btn.config(text="Ⅱ")
            self.now_title.config(text=song["title"])
            self.now_artist.config(text=f'{song["artist"]} • {song["album"]}')
            self.progress.configure(to=max(1, song["duration"]))
            self.progress.set(0)
            self.elapsed.config(text="0:00")
            self.total.config(text=fmt_time(song["duration"]))
            art = self.make_art(song.get("artwork"), 64)
            if art:
                self.art_ref = art
                self.art_label.config(image=art, text="")
            else:
                self.art_label.config(image="", text="♫")
            self.db.add_history(song["id"])
            self.status.set(f'Playing {song["title"]}')
        except Exception as e:
            messagebox.showerror("Playback error", str(e))

    def toggle_play(self):
        if not pygame:
            return
        if not self.current:
            songs = self.filtered()
            if songs:
                self.queue = songs
                self.queue_index = 0
                self.play(songs[0])
            return
        if self.paused:
            pygame.mixer.music.unpause()
            self.paused = False
            self.play_btn.config(text="Ⅱ")
        elif pygame.mixer.music.get_busy():
            pygame.mixer.music.pause()
            self.paused = True
            self.play_btn.config(text="▶")
        else:
            self.play(self.current)

    def next(self):
        if not self.queue:
            self.queue = self.filtered()
        if not self.queue:
            return
        if self.shuffle:
            self.queue_index = random.randrange(len(self.queue))
        else:
            self.queue_index += 1

        if self.queue_index >= len(self.queue):
            if self.repeat == "all":
                self.queue_index = 0
            else:
                return
        self.play(self.queue[self.queue_index])

    def previous(self):
        if not self.current:
            return
        if pygame and pygame.mixer.music.get_pos() > 3000:
            self.play(self.current)
            return
        self.queue_index = max(0, self.queue_index - 1)
        if self.queue:
            self.play(self.queue[self.queue_index])

    def toggle_shuffle(self):
        self.shuffle = not self.shuffle
        self.shuffle_btn.config(fg=self.colors["accent2"] if self.shuffle else self.colors["muted"])

    def toggle_repeat(self):
        self.repeat = {"off": "all", "all": "one", "one": "off"}[self.repeat]
        self.repeat_btn.config(
            text="↻1" if self.repeat == "one" else "↻",
            fg=self.colors["accent2"] if self.repeat != "off" else self.colors["muted"]
        )

    def seek(self, event=None):
        if not pygame or not self.current:
            return
        try:
            pygame.mixer.music.play(start=float(self.progress.get()))
        except Exception:
            pass

    def set_volume(self, value):
        try:
            value = float(value)
            if pygame:
                pygame.mixer.music.set_volume(value)
            self.settings["volume"] = value
            save_settings(self.settings)
        except Exception:
            pass

    def tick(self):
        if pygame and self.current:
            try:
                pos = max(0, pygame.mixer.music.get_pos() / 1000)
                if not self.paused:
                    self.progress.set(min(pos, max(1, self.current["duration"])))
                    self.elapsed.config(text=fmt_time(pos))
                if not pygame.mixer.music.get_busy() and not self.paused:
                    if self.repeat == "one":
                        self.play(self.current)
                    else:
                        self.next()
            except Exception:
                pass
        self.after(500, self.tick)

    def context_menu(self, event):
        row = self.tree.identify_row(event.y)
        if not row:
            return
        self.tree.selection_set(row)
        selected = self.selected()
        if not selected:
            return
        menu = tk.Menu(self, tearoff=0, bg=self.colors["panel2"], fg=self.colors["text"])
        song = selected[0]
        fav = song["id"] in self.db.favorites()
        menu.add_command(
            label="♥ Remove Favorite" if fav else "♡ Add Favorite",
            command=lambda: self.toggle_favorite(song)
        )
        menu.add_command(label="Play", command=self.play_selected)
        menu.add_command(label="Play Next", command=lambda: self.play_next(song))
        menu.add_separator()

        for _, name in self.db.playlists():
            menu.add_command(
                label=f"Add to {name}",
                command=lambda n=name, s=song: self.db.add_playlist_song(n, s["id"])
            )

        if self.current_playlist:
            menu.add_separator()
            menu.add_command(
                label="Remove from this playlist",
                command=lambda: self.remove_from_current(song)
            )

        menu.add_separator()
        menu.add_command(label="Open File Location", command=lambda: self.open_location(song["path"]))
        menu.tk_popup(event.x_root, event.y_root)

    def toggle_favorite(self, song):
        self.db.toggle_favorite(song["id"])
        self.refresh()

    def play_next(self, song):
        if not self.queue:
            self.queue = self.filtered()
        self.queue = [s for s in self.queue if s["id"] != song["id"]]
        self.queue.insert(min(self.queue_index + 1, len(self.queue)), song)

    def remove_from_current(self, song):
        if self.current_playlist:
            self.db.remove_playlist_song(self.current_playlist, song["id"])
            self.refresh()

    def open_location(self, path):
        if not os.path.exists(path):
            return
        try:
            subprocess.Popen(["explorer", "/select,", os.path.normpath(path)])
        except Exception:
            pass

    def refresh_playlists(self):
        for child in self.playlist_frame.winfo_children():
            child.destroy()

        for _, name in self.db.playlists():
            row = tk.Frame(self.playlist_frame, bg=self.colors["panel"])
            row.pack(fill="x")

            tk.Button(
                row, text=name, anchor="w",
                command=lambda n=name: self.set_view(f"Playlist:{n}"),
                bg=self.colors["panel"], fg=self.colors["text"],
                activebackground=self.colors["hover"], activeforeground=self.colors["text"],
                relief="flat", padx=18, pady=6
            ).pack(side="left", fill="x", expand=True)

            tk.Button(
                row, text="⋮", command=lambda n=name: self.playlist_menu(n),
                bg=self.colors["panel"], fg=self.colors["muted"],
                activebackground=self.colors["hover"], relief="flat", width=3
            ).pack(side="right")

    def new_playlist(self):
        name = simpledialog.askstring("New Playlist", "Playlist name:", parent=self)
        if name and name.strip():
            if not self.db.create_playlist(name.strip()):
                messagebox.showwarning("Playlist", "A playlist with that name already exists.")
            self.refresh_playlists()

    def playlist_menu(self, name):
        menu = tk.Menu(self, tearoff=0, bg=self.colors["panel2"], fg=self.colors["text"])
        menu.add_command(label="Open", command=lambda: self.set_view(f"Playlist:{name}"))
        menu.add_command(
            label="Delete Playlist",
            command=lambda: self.delete_playlist(name)
        )
        menu.tk_popup(self.winfo_pointerx(), self.winfo_pointery())

    def delete_playlist(self, name):
        if messagebox.askyesno("Delete playlist", f'Delete "{name}"?'):
            self.db.delete_playlist(name)
            if self.current_playlist == name:
                self.current_playlist = None
                self.view = "Songs"
            self.refresh_playlists()
            self.refresh()

    def settings_window(self):
        win = tk.Toplevel(self)
        win.title("MusicVault Settings")
        win.geometry("760x620")
        win.configure(bg=self.colors["bg"])
        win.transient(self)

        tk.Label(
            win, text="Settings", bg=self.colors["bg"], fg=self.colors["text"],
            font=("Segoe UI Semibold", 23)
        ).pack(anchor="w", padx=25, pady=(22, 12))

        # Folder list + scrollbars
        tk.Label(
            win, text="MUSIC FOLDERS", bg=self.colors["bg"], fg=self.colors["muted"],
            font=("Segoe UI Semibold", 9)
        ).pack(anchor="w", padx=25)

        frame = tk.Frame(win, bg=self.colors["panel"])
        frame.pack(fill="both", expand=True, padx=25, pady=8)

        lb = tk.Listbox(
            frame, bg=self.colors["panel"], fg=self.colors["text"],
            selectbackground=self.colors["accent"], relief="flat",
            font=("Segoe UI", 10)
        )
        vs = ttk.Scrollbar(frame, orient="vertical", command=lb.yview)
        lb.configure(yscrollcommand=vs.set)
        lb.grid(row=0, column=0, sticky="nsew", padx=10, pady=10)
        vs.grid(row=0, column=1, sticky="ns", pady=10)
        frame.rowconfigure(0, weight=1)
        frame.columnconfigure(0, weight=1)

        for folder in self.settings.get("music_folders", []):
            lb.insert("end", folder)

        buttons = tk.Frame(frame, bg=self.colors["panel"])
        buttons.grid(row=0, column=2, sticky="ns", padx=10, pady=10)

        tk.Button(
            buttons, text="+ Add Folder",
            command=lambda: self.add_folder(lb),
            bg=self.colors["accent"], fg="white", relief="flat", padx=15, pady=8
        ).pack(fill="x", pady=(0, 8))

        tk.Button(
            buttons, text="Remove",
            command=lambda: self.remove_folder(lb),
            bg=self.colors["panel2"], fg=self.colors["text"], relief="flat",
            padx=15, pady=8
        ).pack(fill="x")

        tk.Button(
            buttons, text="Add Drive",
            command=lambda: self.add_folder(lb, drive=True),
            bg=self.colors["panel2"], fg=self.colors["text"], relief="flat",
            padx=15, pady=8
        ).pack(fill="x", pady=(8, 0))

        opts = tk.Frame(win, bg=self.colors["bg"])
        opts.pack(fill="x", padx=25, pady=12)

        auto = tk.BooleanVar(value=self.settings.get("auto_scan", True))
        tk.Checkbutton(
            opts, text="Scan automatically at startup", variable=auto,
            bg=self.colors["bg"], fg=self.colors["text"], selectcolor=self.colors["panel2"],
            activebackground=self.colors["bg"], activeforeground=self.colors["text"]
        ).pack(anchor="w")

        tk.Label(
            opts, text="Music is never uploaded. Folders are indexed locally.",
            bg=self.colors["bg"], fg=self.colors["muted"], font=("Segoe UI", 9)
        ).pack(anchor="w", pady=(5, 0))

        footer = tk.Frame(win, bg=self.colors["bg"])
        footer.pack(fill="x", padx=25, pady=(0, 20))

        def save(and_scan=False):
            self.settings["music_folders"] = list(lb.get(0, "end"))
            self.settings["auto_scan"] = auto.get()
            save_settings(self.settings)
            win.destroy()
            if and_scan:
                self.start_scan()
            else:
                self.status.set("Settings saved")

        tk.Button(
            footer, text="Save", command=save,
            bg=self.colors["panel2"], fg=self.colors["text"], relief="flat",
            padx=20, pady=9
        ).pack(side="right", padx=7)
        tk.Button(
            footer, text="Save & Scan", command=lambda: save(True),
            bg=self.colors["accent"], fg="white", relief="flat",
            padx=20, pady=9
        ).pack(side="right")

    def add_folder(self, lb, drive=False):
        if drive:
            folder = filedialog.askdirectory(parent=self, title="Select a drive or root music folder")
        else:
            folder = filedialog.askdirectory(parent=self, title="Select music folder")
        if folder:
            folder = normalize_path(folder)
            if folder not in lb.get(0, "end"):
                lb.insert("end", folder)

    def remove_folder(self, lb):
        for i in reversed(lb.curselection()):
            lb.delete(i)

    def start_scan(self):
        if self.scan_running:
            return
        folders = [f for f in self.settings.get("music_folders", []) if os.path.isdir(f)]
        if not folders:
            self.status.set("Add music folders in Settings")
            return

        self.scan_running = True
        self.status.set("Scanning music library...")
        threading.Thread(target=self.scan_worker, args=(folders,), daemon=True).start()

    def scan_worker(self, folders):
        found = {}
        for folder in folders:
            for root, dirs, files in os.walk(folder):
                dirs[:] = [
                    d for d in dirs
                    if d.lower() not in {"$recycle.bin", "system volume information", ".git"}
                ]
                for file in files:
                    if os.path.splitext(file)[1].lower() in AUDIO_EXTENSIONS:
                        path = normalize_path(os.path.join(root, file))
                        found[path] = path

        for index, path in enumerate(found.values(), 1):
            try:
                # Skip metadata extraction only when unchanged.
                existing = None
                for s in self.db.songs():
                    if s["path"] == path and s["modified"] == os.path.getmtime(path):
                        existing = s
                        break
                if existing is None:
                    self.db.upsert_song(extract_metadata(path))
            except Exception:
                pass

        self.db.remove_missing(found.values())
        self.after(0, lambda: self.finish_scan(len(found)))

    def finish_scan(self, count):
        self.scan_running = False
        self.status.set(f"Library scan complete • {count} audio files found")
        self.refresh()

    def close_app(self):
        try:
            self.settings["last_view"] = self.view
            save_settings(self.settings)
            if pygame:
                pygame.mixer.music.stop()
                pygame.mixer.quit()
            self.db.close()
        except Exception:
            pass
        self.destroy()


if __name__ == "__main__":
    app = MusicVault()
    app.mainloop()
