import os
import sys
import io
import json
import time
import random
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
            CREATE TABLE IF NOT EXISTS history(
                id INTEGER PRIMARY KEY, song_id INTEGER, played_at REAL
            );
            CREATE TABLE IF NOT EXISTS positions(song_id INTEGER PRIMARY KEY, seconds REAL);
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
                self.con.execute("DELETE FROM positions WHERE song_id=?", (sid,))
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

    def most_played(self):
        with self.lock:
            rows = self.con.execute("""
            SELECT s.id,s.path,s.title,s.artist,s.album,s.genre,s.year,s.track,s.disc,
                   s.duration,s.artwork,s.added,s.modified,COUNT(h.id) AS plays
            FROM songs s LEFT JOIN history h ON h.song_id=s.id
            GROUP BY s.id ORDER BY plays DESC, lower(s.title)
            """).fetchall()
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


class MusicVault(tk.Tk):
    def __init__(self):
        super().__init__()
        self.settings = load_settings()
        self.db = DB()

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

        self.view = "Home"
        self.playlist_name = None
        self.visible = []
        self.queue = []
        self.queue_index = -1
        self.current = None
        self.paused = False
        self.shuffle = False
        self.repeat = "off"
        self.dragging = False
        self.user_seeking = False
        self.scan_running = False
        self.art_ref = None
        self.album_art_cache = {}

        self.search = tk.StringVar()
        self.search.trace_add("write", lambda *_: self.refresh())
        self.sort_var = tk.StringVar(value=self.settings.get("sort", "Title"))

        self.init_audio()
        self.style_widgets()
        self.build()
        self.refresh_playlists()
        self.refresh()

        if self.settings.get("auto_scan", True):
            self.after(600, self.start_scan)

        self.after(250, self.player_tick)

        self.bind_all("<space>", self.space_key)
        self.bind_all("<Control-f>", lambda e: self.focus_search())
        self.bind_all("<Control-l>", lambda e: self.start_scan())
        self.bind_all("<Left>", lambda e: self.previous())
        self.bind_all("<Right>", lambda e: self.next())
        self.bind_all("<Control-Shift-F>", lambda e: self.toggle_favorite_current())

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
                    foreground=self.text, rowheight=44, borderwidth=0,
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
        return tk.Button(
            parent, text=text, command=command, bg=kw.pop("bg", self.panel),
            fg=kw.pop("fg", self.text), activebackground=kw.pop("activebackground", self.hover),
            activeforeground=kw.pop("activeforeground", self.text),
            relief="flat", bd=0, cursor="hand2", **kw
        )

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

        for name in ["Home","Songs","Albums","Artists","Genres","Recently Added","Most Played","Favorites"]:
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
        self.playlist_canvas.pack(side="left", fill="both", expand=True)
        self.playlist_scroll.pack(side="right", fill="y")

        self.button(side, "+ New Playlist", self.new_playlist, bg=self.panel,
                    fg=self.blue2, anchor="w", padx=20, pady=10).pack(fill="x", side="bottom")

        content = tk.Frame(main, bg=self.bg)
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
            values=["Title","Artist","Album","Year","Duration","Date Added"],
            state="readonly", width=14
        )
        self.sort_combo.pack(side="left")
        self.sort_combo.bind("<<ComboboxSelected>>", lambda e: self.sort_changed())

        self.album_strip = tk.Frame(content, bg=self.bg, height=154)
        self.album_strip.pack(fill="x", pady=(12,8))
        self.album_strip.pack_propagate(False)

        table = tk.Frame(content, bg=self.panel)
        table.pack(fill="both", expand=True)
        cols = ("title","artist","album","genre","year","time")
        self.tree = ttk.Treeview(table, columns=cols, show="headings", selectmode="extended")
        widths = {"title":340,"artist":190,"album":235,"genre":140,"year":70,"time":75}
        for c, heading in [("title","TITLE"),("artist","ARTIST"),("album","ALBUM"),
                           ("genre","GENRE"),("year","YEAR"),("time","TIME")]:
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

        self.build_player()

        self.status = tk.StringVar(value="Ready")
        tk.Label(self, textvariable=self.status, bg=self.bg, fg=self.muted,
                 font=("Segoe UI",8)).place(x=240,y=53)

    def nav_button(self, side, name):
        b = self.button(side, name, lambda n=name: self.set_view(n),
                        bg=self.panel, anchor="w", padx=20, pady=9)
        b.pack(fill="x")
        setattr(self, "nav_" + name.lower().replace(" ","_"), b)

    def build_player(self):
        p = tk.Frame(self, bg=self.panel, height=128)
        p.pack(side="bottom", fill="x")
        p.pack_propagate(False)

        self.art = tk.Label(p, text="♫", bg=self.panel2, fg=self.blue2,
                            width=7, height=4, font=("Segoe UI",20))
        self.art.pack(side="left", padx=15, pady=10)

        info = tk.Frame(p, bg=self.panel, width=250)
        info.pack(side="left", fill="y", pady=18)
        info.pack_propagate(False)
        self.now_title = tk.Label(info, text="Nothing playing", bg=self.panel,
                                  fg=self.text, font=("Segoe UI Semibold",11),
                                  anchor="w")
        self.now_title.pack(fill="x")
        self.now_artist = tk.Label(info, text="", bg=self.panel, fg=self.muted,
                                   font=("Segoe UI",9), anchor="w")
        self.now_artist.pack(fill="x", pady=3)

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

    def set_view(self, view):
        self.view = view
        self.playlist_name = view.split(":",1)[1] if view.startswith("Playlist:") else None
        self.view_title.config(text=self.playlist_name or view)
        self.refresh()

    def sort_changed(self):
        self.settings["sort"] = self.sort_var.get()
        save_settings(self.settings)
        self.refresh()

    def sort_column(self, column):
        mapping = {"title":"Title","artist":"Artist","album":"Album","year":"Year",
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
        if self.playlist_name:
            return self.db.playlist(self.playlist_name)
        if self.view == "Recently Added":
            return sorted(self.db.all(), key=lambda x:x["added"], reverse=True)[:200]
        if self.view == "Most Played":
            return self.db.most_played()
        return self.db.all()

    def filtered(self):
        songs = self.base_songs()
        if self.view == "Favorites":
            fav = self.db.favorites()
            songs = [s for s in songs if s["id"] in fav]

        q = self.search.get().strip().lower()
        if q:
            songs = [s for s in songs if q in " ".join(
                str(s[k]) for k in ("title","artist","album","genre","year")
            ).lower()]

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
            "Duration":lambda s:s["duration"],
            "Date Added":lambda s:s["added"],
        }.get(field,lambda s:s["title"].lower())
        try:
            songs.sort(key=key, reverse=self.settings.get("sort_desc",False))
        except Exception:
            pass
        return songs

    def refresh(self):
        for item in self.tree.get_children():
            self.tree.delete(item)
        self.visible=self.filtered()
        for i,s in enumerate(self.visible):
            self.tree.insert("", "end", iid=str(i), values=(
                s["title"],s["artist"],s["album"],s["genre"],s["year"],
                seconds_text(s["duration"])
            ))
        self.count.config(text=f"{len(self.visible)} items")
        self.status.set(f"{len(self.visible)} items")
        self.refresh_albums()

    def refresh_albums(self):
        for c in self.album_strip.winfo_children():
            c.destroy()
        if self.view not in ("Home","Albums") or not self.visible:
            return

        albums=[]
        seen=set()
        all_songs=self.db.all()
        for s in all_songs:
            key=(s["artist"],s["album"])
            if key not in seen:
                seen.add(key); albums.append(s)
        albums=albums[:60]

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
                w.bind("<Double-Button-1>",lambda e,x=s:self.play_album(x))

    def make_art(self,blob,size):
        if Image is None:
            return None
        try:
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
            return ImageTk.PhotoImage(im)
        except Exception:
            return None

    def play_album(self,song):
        q=[s for s in self.db.all() if s["artist"]==song["artist"] and s["album"]==song["album"]]
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

    def play_selected(self,event=None):
        selected=self.selected()
        if not selected:return
        self.queue=self.filtered()
        self.queue_index=next((i for i,s in enumerate(self.queue) if s["id"]==selected[0]["id"]),0)
        self.play(self.queue[self.queue_index])

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
            self.paused=False
            self.user_seeking=False
            self.play_btn.config(text="Ⅱ")
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
            self.play_btn.config(text="Ⅱ")
        elif pygame.mixer.music.get_busy():
            pygame.mixer.music.pause()
            self.paused=True
            self.play_btn.config(text="▶")
        else:self.play(self.current)

    def next(self):
        if not self.queue:self.queue=self.filtered()
        if not self.queue:return
        if self.shuffle:self.queue_index=random.randrange(len(self.queue))
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

    def toggle_repeat(self):
        self.repeat={"off":"all","all":"one","one":"off"}[self.repeat]
        self.repeat_btn.config(text="↻1" if self.repeat=="one" else "↻",
                               fg=self.blue2 if self.repeat!="off" else self.muted)

    # Correct seeking: stop timer updates while dragging, then perform a real seek
    # on mouse release. The release position is converted to seconds and applied.
    def seek_press(self,event=None):
        self.user_seeking=True

    def seek_moving(self,value):
        if self.user_seeking:
            try:self.elapsed.config(text=seconds_text(float(value)))
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
            pygame.mixer.music.set_volume(float(self.volume.get()))
            if was_paused:
                pygame.mixer.music.pause()
            self.db.set_position(self.current["id"],target)
            self.elapsed.config(text=seconds_text(target))
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
                pos=max(0,pygame.mixer.music.get_pos()/1000)
                # get_pos resets after a seek, so stored position is used as the
                # authoritative value when necessary.
                self.seek_var.set(min(pos,max(1,self.current["duration"])))
                self.elapsed.config(text=seconds_text(pos))
                if not pygame.mixer.music.get_busy() and not self.paused:
                    self.db.set_position(self.current["id"],0)
                    if self.repeat=="one":self.play(self.current,start=0)
                    else:self.next()
                elif self.current and pos > 0:
                    self.db.set_position(self.current["id"],pos)
            except Exception:pass
        self.after(250,self.player_tick)

    def toggle_favorite_current(self):
        if self.current:
            self.db.toggle_favorite(self.current["id"])
            self.refresh()

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
        m.add_command(label="Play",command=self.play_selected)
        m.add_command(label="Play Next",command=lambda:self.play_next_song(s))
        m.add_command(label="Add to Queue",command=lambda:self.add_queue(s))
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

    def toggle_song_favorite(self,s):
        self.db.toggle_favorite(s["id"]);self.refresh()

    def add_queue(self,s):
        self.queue.append(s)
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

        opts=tk.Frame(win,bg=self.bg)
        opts.pack(fill="x",padx=25,pady=12)
        auto=tk.BooleanVar(value=self.settings.get("auto_scan",True))
        resume=tk.BooleanVar(value=self.settings.get("resume",True))
        confirm=tk.BooleanVar(value=self.settings.get("confirm_delete_playlist",True))
        for text,var in [("Scan automatically at startup",auto),
                         ("Resume songs where you left off",resume),
                         ("Confirm before deleting playlists",confirm)]:
            tk.Checkbutton(opts,text=text,variable=var,bg=self.bg,fg=self.text,
                           selectcolor=self.panel2,activebackground=self.bg,
                           activeforeground=self.text).pack(anchor="w")

        tk.Label(opts,text="Blue theme • local playback • no music uploads",
                 bg=self.bg,fg=self.muted,font=("Segoe UI",9)).pack(anchor="w",pady=(7,0))

        foot=tk.Frame(win,bg=self.bg);foot.pack(fill="x",padx=25,pady=(0,20))
        def save(and_scan=False):
            self.settings["music_folders"]=list(lb.get(0,"end"))
            self.settings["auto_scan"]=auto.get()
            self.settings["resume"]=resume.get()
            self.settings["confirm_delete_playlist"]=confirm.get()
            save_settings(self.settings);win.destroy()
            if and_scan:self.start_scan()
            else:self.status.set("Settings saved")
        self.button(foot,"Save",save,bg=self.panel2,padx=20,pady=9).pack(side="right",padx=7)
        self.button(foot,"Save & Scan",lambda:save(True),
                    bg=self.blue,fg="white",padx=20,pady=9).pack(side="right")

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
        self.status.set("Scanning library...")
        threading.Thread(target=self.scan_worker,args=(folders,),daemon=True).start()

    def scan_worker(self,folders):
        found={}
        for folder in folders:
            for root,dirs,files in os.walk(folder):
                dirs[:]=[d for d in dirs if d.lower() not in {
                    "$recycle.bin","system volume information",".git",".venv","node_modules"
                }]
                for file in files:
                    if os.path.splitext(file)[1].lower() in EXTENSIONS:
                        p=normalize(os.path.join(root,file))
                        found[p]=p

        old=self.db.existing_mtimes()
        paths=list(found.values())
        total=len(paths)
        changed=0

        for p in paths:
            try:
                mt=os.path.getmtime(p)
                item=old.get(p)
                if item is None or abs(float(item[1])-mt)>0.001:
                    self.db.upsert(metadata(p))
                    changed+=1
                if changed % 25 == 0:
                    self.after(0,lambda n=changed,t=total:self.status.set(
                        f"Scanning... {n} changed • {t} files found"))
            except (OSError,PermissionError):
                pass

        self.db.remove_missing(paths)
        self.after(0,lambda:self.scan_finished(total,changed))

    def scan_finished(self,total,changed):
        self.scan_running=False
        self.status.set(f"Library ready • {total} files • {changed} updated")
        self.refresh()
        self.refresh_playlists()

    def close(self):
        try:
            if self.current and pygame and not self.paused:
                pos=max(0,pygame.mixer.music.get_pos()/1000)
                self.db.set_position(self.current["id"],pos)
            save_settings(self.settings)
            if pygame:
                pygame.mixer.music.stop();pygame.mixer.quit()
            self.db.close()
        except Exception:pass
        self.destroy()


if __name__ == "__main__":
    MusicVault().mainloop()
