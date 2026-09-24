import json
import os
import random
import threading
import time
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

try:
    import pygame
except ImportError:
    pygame = None

try:
    from mutagen import File as MutagenFile
except ImportError:
    MutagenFile = None

try:
    from PIL import Image, ImageTk
except ImportError:
    Image = ImageTk = None


APP_NAME = "MusicVault"
DATA_DIR = os.path.join(os.getenv("APPDATA") or os.path.expanduser("~"), APP_NAME)
SETTINGS_FILE = os.path.join(DATA_DIR, "settings.json")

AUDIO_EXTENSIONS = {
    ".mp3", ".wav", ".flac", ".m4a", ".aac", ".ogg", ".opus", ".wma", ".aiff", ".ape"
}


def ensure_data_dir():
    os.makedirs(DATA_DIR, exist_ok=True)


def load_settings():
    ensure_data_dir()
    defaults = {
        "music_folders": [],
        "auto_scan": True,
        "volume": 0.75,
        "theme": "dark",
    }
    try:
        with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        defaults.update(data)
    except (OSError, json.JSONDecodeError):
        pass
    return defaults


def save_settings(settings):
    ensure_data_dir()
    with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
        json.dump(settings, f, indent=2)


def clean(value, fallback="Unknown"):
    if value is None:
        return fallback
    if isinstance(value, list):
        value = value[0] if value else fallback
    value = str(value).strip()
    return value or fallback


def read_tag(tags, keys, fallback="Unknown"):
    if not tags:
        return fallback
    for key in keys:
        try:
            if key in tags:
                value = tags[key]
                if isinstance(value, (list, tuple)):
                    value = value[0] if value else fallback
                return clean(value, fallback)
        except Exception:
            continue
    return fallback


def metadata(path):
    title = os.path.splitext(os.path.basename(path))[0]
    artist = "Unknown Artist"
    album = "Unknown Album"
    year = ""
    duration = 0.0
    artwork = None

    if MutagenFile:
        try:
            audio = MutagenFile(path, easy=False)
            if audio:
                duration = float(getattr(getattr(audio, "info", None), "length", 0) or 0)
                tags = getattr(audio, "tags", None)

                if tags:
                    title = read_tag(tags, ["TIT2", "title", "\xa9nam"], title)
                    artist = read_tag(tags, ["TPE1", "artist", "\xa9ART"], artist)
                    album = read_tag(tags, ["TALB", "album", "\xa9alb"], album)
                    year = read_tag(tags, ["TDRC", "date", "\xa9day"], "")

                # Embedded artwork
                if hasattr(audio, "pictures") and audio.pictures:
                    artwork = audio.pictures[0].data
                elif tags:
                    for key in ("APIC:", "covr", "artwork"):
                        if key in tags:
                            item = tags[key]
                            if isinstance(item, list):
                                item = item[0]
                            data = getattr(item, "data", item)
                            if isinstance(data, bytes):
                                artwork = data
                            break
        except Exception:
            pass

    return {
        "path": os.path.abspath(path),
        "title": title,
        "artist": artist,
        "album": album,
        "year": year,
        "duration": duration,
        "artwork": artwork,
        "added": time.time(),
    }


class MusicVault(tk.Tk):
    def __init__(self):
        super().__init__()

        self.settings = load_settings()
        self.library = []
        self.favorites = set()
        self.playlists = {}
        self.queue = []
        self.queue_index = -1
        self.current_song = None
        self.current_art = None
        self.is_paused = False
        self.repeat_mode = "off"
        self.shuffle = False
        self.scan_running = False

        self.colors = {
            "bg": "#111315",
            "panel": "#191c20",
            "panel2": "#20242a",
            "text": "#f2f4f7",
            "muted": "#9aa3ad",
            "accent": "#8b5cf6",
            "accent2": "#a78bfa",
            "border": "#30353c",
            "hover": "#282d34",
        }

        self.title(APP_NAME)
        self.geometry("1200x760")
        self.minsize(900, 600)
        self.configure(bg=self.colors["bg"])

        self.protocol("WM_DELETE_WINDOW", self.on_close)

        self.init_audio()
        self.build_ui()
        self.load_library()
        self.refresh_library()
        self.after(500, self.update_progress)

        if self.settings.get("auto_scan", True):
            self.after(1000, self.start_scan)

    def init_audio(self):
        if pygame:
            try:
                pygame.mixer.init()
                pygame.mixer.music.set_volume(float(self.settings.get("volume", 0.75)))
            except Exception as e:
                print("Audio initialization failed:", e)

    def build_ui(self):
        self.style = ttk.Style(self)
        try:
            self.style.theme_use("clam")
        except Exception:
            pass

        self.style.configure(
            "Treeview",
            background=self.colors["panel"],
            fieldbackground=self.colors["panel"],
            foreground=self.colors["text"],
            rowheight=42,
            borderwidth=0,
            font=("Segoe UI", 10),
        )
        self.style.configure(
            "Treeview.Heading",
            background=self.colors["panel2"],
            foreground=self.colors["muted"],
            borderwidth=0,
            font=("Segoe UI Semibold", 9),
        )
        self.style.map(
            "Treeview",
            background=[("selected", self.colors["accent"])],
            foreground=[("selected", "#ffffff")],
        )

        # Header
        header = tk.Frame(self, bg=self.colors["bg"], height=68)
        header.pack(fill="x", side="top")
        header.pack_propagate(False)

        tk.Label(
            header, text="♫  MusicVault", bg=self.colors["bg"],
            fg=self.colors["text"], font=("Segoe UI Semibold", 20)
        ).pack(side="left", padx=22)

        self.search_var = tk.StringVar()
        self.search_var.trace_add("write", lambda *_: self.refresh_library())
        search = tk.Entry(
            header, textvariable=self.search_var, bg=self.colors["panel2"],
            fg=self.colors["text"], insertbackground=self.colors["text"],
            relief="flat", font=("Segoe UI", 11), width=38
        )
        search.pack(side="left", padx=20, ipady=9)
        search.insert(0, "")
        self.search_entry = search

        tk.Button(
            header, text="⚙ Settings", command=self.open_settings,
            bg=self.colors["panel2"], fg=self.colors["text"],
            activebackground=self.colors["hover"], activeforeground=self.colors["text"],
            relief="flat", padx=16, pady=8, cursor="hand2"
        ).pack(side="right", padx=20)

        # Main
        main = tk.Frame(self, bg=self.colors["bg"])
        main.pack(fill="both", expand=True)

        # Sidebar
        sidebar = tk.Frame(main, bg=self.colors["panel"], width=210)
        sidebar.pack(side="left", fill="y")
        sidebar.pack_propagate(False)

        tk.Label(
            sidebar, text="LIBRARY", bg=self.colors["panel"],
            fg=self.colors["muted"], font=("Segoe UI Semibold", 9)
        ).pack(anchor="w", padx=20, pady=(22, 8))

        self.nav_buttons = {}
        for name in ["All Songs", "Recently Added", "Favorites", "Artists", "Albums"]:
            b = tk.Button(
                sidebar, text=name, anchor="w",
                command=lambda n=name: self.set_view(n),
                bg=self.colors["panel"], fg=self.colors["text"],
                activebackground=self.colors["hover"], activeforeground=self.colors["text"],
                relief="flat", bd=0, padx=20, pady=10, font=("Segoe UI", 10),
                cursor="hand2"
            )
            b.pack(fill="x")
            self.nav_buttons[name] = b

        tk.Label(
            sidebar, text="PLAYLISTS", bg=self.colors["panel"],
            fg=self.colors["muted"], font=("Segoe UI Semibold", 9)
        ).pack(anchor="w", padx=20, pady=(28, 8))

        self.playlist_frame = tk.Frame(sidebar, bg=self.colors["panel"])
        self.playlist_frame.pack(fill="x")

        tk.Button(
            sidebar, text="+ New Playlist", anchor="w",
            command=self.new_playlist,
            bg=self.colors["panel"], fg=self.colors["accent2"],
            activebackground=self.colors["hover"], activeforeground=self.colors["accent2"],
            relief="flat", padx=20, pady=10, cursor="hand2"
        ).pack(fill="x", side="bottom", pady=15)

        # Content
        content = tk.Frame(main, bg=self.colors["bg"])
        content.pack(side="left", fill="both", expand=True, padx=18, pady=16)

        self.view_title = tk.Label(
            content, text="All Songs", bg=self.colors["bg"],
            fg=self.colors["text"], font=("Segoe UI Semibold", 22)
        )
        self.view_title.pack(anchor="w", pady=(0, 12))

        columns = ("title", "artist", "album", "duration")
        self.tree = ttk.Treeview(content, columns=columns, show="headings", selectmode="extended")
        self.tree.heading("title", text="TITLE")
        self.tree.heading("artist", text="ARTIST")
        self.tree.heading("album", text="ALBUM")
        self.tree.heading("duration", text="TIME")
        self.tree.column("title", width=350, anchor="w")
        self.tree.column("artist", width=190, anchor="w")
        self.tree.column("album", width=220, anchor="w")
        self.tree.column("duration", width=90, anchor="e")
        self.tree.pack(fill="both", expand=True)

        self.tree.bind("<Double-1>", self.play_selected)
        self.tree.bind("<Return>", self.play_selected)
        self.tree.bind("<Button-3>", self.context_menu)

        # Player
        player = tk.Frame(self, bg=self.colors["panel"], height=112)
        player.pack(fill="x", side="bottom")
        player.pack_propagate(False)

        self.art_label = tk.Label(
            player, text="♫", bg=self.colors["panel2"], fg=self.colors["muted"],
            width=7, height=4, font=("Segoe UI", 20)
        )
        self.art_label.pack(side="left", padx=16, pady=10)

        info = tk.Frame(player, bg=self.colors["panel"])
        info.pack(side="left", fill="y", pady=16)

        self.song_label = tk.Label(
            info, text="Nothing playing", bg=self.colors["panel"],
            fg=self.colors["text"], font=("Segoe UI Semibold", 11)
        )
        self.song_label.pack(anchor="w")
        self.artist_label = tk.Label(
            info, text="", bg=self.colors["panel"],
            fg=self.colors["muted"], font=("Segoe UI", 9)
        )
        self.artist_label.pack(anchor="w", pady=(3, 0))

        controls = tk.Frame(player, bg=self.colors["panel"])
        controls.pack(side="left", expand=True, fill="both")

        buttons = tk.Frame(controls, bg=self.colors["panel"])
        buttons.pack(pady=(12, 0))

        self.shuffle_btn = tk.Button(
            buttons, text="⤨", command=self.toggle_shuffle,
            bg=self.colors["panel"], fg=self.colors["muted"],
            activebackground=self.colors["panel"], activeforeground=self.colors["accent2"],
            relief="flat", font=("Segoe UI", 15), bd=0
        )
        self.shuffle_btn.pack(side="left", padx=10)

        tk.Button(
            buttons, text="◀◀", command=self.previous_song,
            bg=self.colors["panel"], fg=self.colors["text"],
            activebackground=self.colors["panel"], relief="flat",
            font=("Segoe UI", 11), bd=0
        ).pack(side="left", padx=8)

        self.play_btn = tk.Button(
            buttons, text="▶", command=self.toggle_play,
            bg=self.colors["accent"], fg="white",
            activebackground=self.colors["accent2"], activeforeground="white",
            relief="flat", font=("Segoe UI Semibold", 13), bd=0,
            width=4, height=1, cursor="hand2"
        )
        self.play_btn.pack(side="left", padx=8)

        tk.Button(
            buttons, text="▶▶", command=self.next_song,
            bg=self.colors["panel"], fg=self.colors["text"],
            activebackground=self.colors["panel"], relief="flat",
            font=("Segoe UI", 11), bd=0
        ).pack(side="left", padx=8)

        self.repeat_btn = tk.Button(
            buttons, text="↻", command=self.toggle_repeat,
            bg=self.colors["panel"], fg=self.colors["muted"],
            activebackground=self.colors["panel"], activeforeground=self.colors["accent2"],
            relief="flat", font=("Segoe UI", 15), bd=0
        )
        self.repeat_btn.pack(side="left", padx=10)

        timeline = tk.Frame(controls, bg=self.colors["panel"])
        timeline.pack(fill="x", padx=25, pady=(3, 0))

        self.time_label = tk.Label(
            timeline, text="0:00", bg=self.colors["panel"],
            fg=self.colors["muted"], font=("Segoe UI", 8)
        )
        self.time_label.pack(side="left")

        self.progress = ttk.Scale(timeline, from_=0, to=100, orient="horizontal")
        self.progress.pack(side="left", fill="x", expand=True, padx=10)
        self.progress.bind("<ButtonRelease-1>", self.seek)

        self.total_label = tk.Label(
            timeline, text="0:00", bg=self.colors["panel"],
            fg=self.colors["muted"], font=("Segoe UI", 8)
        )
        self.total_label.pack(side="right")

        volume_frame = tk.Frame(player, bg=self.colors["panel"])
        volume_frame.pack(side="right", padx=18)

        tk.Label(
            volume_frame, text="VOL", bg=self.colors["panel"],
            fg=self.colors["muted"], font=("Segoe UI Semibold", 8)
        ).pack()

        self.volume = ttk.Scale(
            volume_frame, from_=0, to=1,
            value=float(self.settings.get("volume", 0.75)),
            orient="horizontal", command=self.change_volume, length=105
        )
        self.volume.pack()

        self.status_var = tk.StringVar(value="Ready")
        tk.Label(
            self, textvariable=self.status_var, bg=self.colors["bg"],
            fg=self.colors["muted"], font=("Segoe UI", 8)
        ).place(x=225, y=48)

        self.set_view("All Songs")
        self.refresh_playlists()

    def load_library(self):
        # The app keeps its catalog in memory and rebuilds it from the selected folders.
        # This guarantees removed files do not remain as ghost entries.
        self.library = []

    def start_scan(self):
        if self.scan_running:
            return
        folders = list(self.settings.get("music_folders", []))
        if not folders:
            self.status_var.set("Add music folders in Settings")
            return

        self.scan_running = True
        self.status_var.set("Scanning music folders...")
        threading.Thread(target=self.scan_worker, args=(folders,), daemon=True).start()

    def scan_worker(self, folders):
        found = {}
        for folder in folders:
            if not os.path.isdir(folder):
                continue
            for root, dirs, files in os.walk(folder):
                # Ignore common cache/system folders
                dirs[:] = [d for d in dirs if d.lower() not in {"$recycle.bin", "system volume information"}]
                for filename in files:
                    path = os.path.abspath(os.path.join(root, filename))
                    if os.path.splitext(filename)[1].lower() in AUDIO_EXTENSIONS:
                        found[path.lower()] = path

        songs = []
        for path in found.values():
            try:
                songs.append(metadata(path))
            except Exception:
                pass

        songs.sort(key=lambda x: (x["artist"].lower(), x["album"].lower(), x["title"].lower()))
        self.after(0, lambda: self.finish_scan(songs))

    def finish_scan(self, songs):
        self.library = songs
        self.scan_running = False
        self.status_var.set(f"{len(songs)} songs in library")
        self.refresh_library()

    def format_time(self, seconds):
        seconds = max(0, int(seconds or 0))
        return f"{seconds // 60}:{seconds % 60:02d}"

    def filtered_songs(self):
        q = self.search_var.get().strip().lower()
        songs = self.library

        view = getattr(self, "current_view", "All Songs")
        if view == "Favorites":
            songs = [s for s in songs if s["path"] in self.favorites]
        elif view == "Recently Added":
            songs = sorted(songs, key=lambda x: x.get("added", 0), reverse=True)[:100]
        elif view == "Artists":
            # Artist view uses one representative row per artist.
            seen = set()
            out = []
            for s in songs:
                a = s["artist"]
                if a not in seen:
                    seen.add(a)
                    out.append(s)
            songs = out
        elif view == "Albums":
            seen = set()
            out = []
            for s in songs:
                key = (s["artist"], s["album"])
                if key not in seen:
                    seen.add(key)
                    out.append(s)
            songs = out
        elif view.startswith("Playlist:"):
            name = view.split(":", 1)[1]
            paths = set(self.playlists.get(name, []))
            songs = [s for s in songs if s["path"] in paths]

        if q:
            songs = [
                s for s in songs
                if q in s["title"].lower()
                or q in s["artist"].lower()
                or q in s["album"].lower()
            ]
        return songs

    def refresh_library(self):
        if not hasattr(self, "tree"):
            return

        for item in self.tree.get_children():
            self.tree.delete(item)

        songs = self.filtered_songs()
        for i, song in enumerate(songs):
            self.tree.insert(
                "", "end", iid=str(i),
                values=(
                    song["title"],
                    song["artist"],
                    song["album"],
                    self.format_time(song["duration"]),
                )
            )

        count = len(songs)
        self.status_var.set(f"{count} song{'s' if count != 1 else ''} shown")

    def set_view(self, view):
        self.current_view = view
        self.view_title.config(text=view.replace("Playlist:", ""))
        for name, button in self.nav_buttons.items():
            button.configure(
                bg=self.colors["hover"] if name == view else self.colors["panel"]
            )
        self.refresh_library()

    def selected_songs(self):
        indexes = self.tree.selection()
        visible = self.filtered_songs()
        result = []
        for iid in indexes:
            try:
                result.append(visible[int(iid)])
            except (ValueError, IndexError):
                pass
        return result

    def play_selected(self, event=None):
        songs = self.selected_songs()
        if not songs:
            return

        self.queue = self.filtered_songs()
        target = songs[0]
        try:
            self.queue_index = next(i for i, s in enumerate(self.queue) if s["path"] == target["path"])
        except StopIteration:
            self.queue_index = 0

        self.play_song(self.queue[self.queue_index])

    def play_song(self, song):
        if not pygame:
            messagebox.showerror(
                "Audio unavailable",
                "pygame-ce is not installed. Run: pip install pygame-ce"
            )
            return

        path = song["path"]
        if not os.path.exists(path):
            self.start_scan()
            return

        try:
            pygame.mixer.music.load(path)
            pygame.mixer.music.play()
            pygame.mixer.music.set_volume(float(self.volume.get()))
            self.current_song = song
            self.is_paused = False
            self.play_btn.config(text="Ⅱ")
            self.song_label.config(text=song["title"])
            self.artist_label.config(text=f'{song["artist"]} • {song["album"]}')
            self.total_label.config(text=self.format_time(song["duration"]))
            self.progress.configure(to=max(song["duration"], 1))
            self.progress.set(0)
            self.show_art(song)
            self.status_var.set(f'Playing: {song["title"]}')
        except Exception as e:
            messagebox.showerror("Playback error", str(e))

    def toggle_play(self):
        if not pygame:
            return
        if not self.current_song:
            if self.library:
                self.queue = self.filtered_songs()
                self.queue_index = 0
                self.play_song(self.queue[0])
            return

        if self.is_paused:
            pygame.mixer.music.unpause()
            self.is_paused = False
            self.play_btn.config(text="Ⅱ")
        elif pygame.mixer.music.get_busy():
            pygame.mixer.music.pause()
            self.is_paused = True
            self.play_btn.config(text="▶")
        else:
            self.play_song(self.current_song)

    def next_song(self):
        if not self.queue:
            self.queue = self.filtered_songs()

        if not self.queue:
            return

        if self.shuffle:
            self.queue_index = random.randrange(len(self.queue))
        else:
            self.queue_index += 1

        if self.queue_index >= len(self.queue):
            if self.repeat_mode == "all":
                self.queue_index = 0
            else:
                self.queue_index = len(self.queue) - 1
                return

        self.play_song(self.queue[self.queue_index])

    def previous_song(self):
        if not self.queue:
            self.queue = self.filtered_songs()

        if not self.queue:
            return

        if pygame and pygame.mixer.music.get_pos() > 3000:
            self.play_song(self.current_song)
            return

        self.queue_index = max(0, self.queue_index - 1)
        self.play_song(self.queue[self.queue_index])

    def toggle_shuffle(self):
        self.shuffle = not self.shuffle
        self.shuffle_btn.configure(
            fg=self.colors["accent2"] if self.shuffle else self.colors["muted"]
        )

    def toggle_repeat(self):
        self.repeat_mode = {"off": "all", "all": "one", "one": "off"}[self.repeat_mode]
        self.repeat_btn.configure(
            fg=self.colors["accent2"] if self.repeat_mode != "off" else self.colors["muted"],
            text="↻1" if self.repeat_mode == "one" else "↻"
        )

    def seek(self, event=None):
        if not pygame or not self.current_song:
            return
        try:
            pygame.mixer.music.play(start=float(self.progress.get()))
            if self.is_paused:
                pygame.mixer.music.pause()
        except Exception:
            pass

    def change_volume(self, value):
        if pygame:
            try:
                pygame.mixer.music.set_volume(float(value))
            except Exception:
                pass
        self.settings["volume"] = float(value)
        save_settings(self.settings)

    def update_progress(self):
        if pygame and self.current_song:
            try:
                pos_ms = pygame.mixer.music.get_pos()
                pos = max(0, pos_ms / 1000)
                if not self.is_paused:
                    self.progress.set(min(pos, max(self.current_song["duration"], 1)))
                    self.time_label.config(text=self.format_time(pos))

                if not pygame.mixer.music.get_busy() and not self.is_paused:
                    if self.repeat_mode == "one":
                        self.play_song(self.current_song)
                    else:
                        self.next_song()
            except Exception:
                pass
        self.after(500, self.update_progress)

    def show_art(self, song):
        if Image is None or not song.get("artwork"):
            self.art_label.config(image="", text="♫")
            self.current_art = None
            return
        try:
            import io
            image = Image.open(io.BytesIO(song["artwork"])).convert("RGB")
            image.thumbnail((64, 64))
            self.current_art = ImageTk.PhotoImage(image)
            self.art_label.config(image=self.current_art, text="")
        except Exception:
            self.art_label.config(image="", text="♫")
            self.current_art = None

    def context_menu(self, event):
        row = self.tree.identify_row(event.y)
        if not row:
            return
        self.tree.selection_set(row)

        menu = tk.Menu(self, tearoff=0, bg=self.colors["panel2"], fg=self.colors["text"])
        selected = self.selected_songs()
        if not selected:
            return

        song = selected[0]
        label = "♥ Remove Favorite" if song["path"] in self.favorites else "♡ Add Favorite"
        menu.add_command(label=label, command=lambda: self.toggle_favorite(song))
        menu.add_command(label="Play", command=self.play_selected)
        menu.add_separator()

        for playlist in self.playlists:
            menu.add_command(
                label=f"Add to {playlist}",
                command=lambda p=playlist, s=song: self.add_to_playlist(p, s)
            )
        menu.tk_popup(event.x_root, event.y_root)

    def toggle_favorite(self, song):
        path = song["path"]
        if path in self.favorites:
            self.favorites.remove(path)
        else:
            self.favorites.add(path)
        self.refresh_library()

    def refresh_playlists(self):
        for child in self.playlist_frame.winfo_children():
            child.destroy()

        for name in self.playlists:
            tk.Button(
                self.playlist_frame, text=name, anchor="w",
                command=lambda n=name: self.set_view(f"Playlist:{n}"),
                bg=self.colors["panel"], fg=self.colors["text"],
                activebackground=self.colors["hover"],
                activeforeground=self.colors["text"], relief="flat",
                padx=20, pady=7, cursor="hand2"
            ).pack(fill="x")

    def new_playlist(self):
        win = tk.Toplevel(self)
        win.title("New Playlist")
        win.geometry("360x150")
        win.configure(bg=self.colors["panel"])

        tk.Label(
            win, text="Playlist name", bg=self.colors["panel"],
            fg=self.colors["text"], font=("Segoe UI Semibold", 11)
        ).pack(pady=(20, 5))

        entry = tk.Entry(
            win, bg=self.colors["panel2"], fg=self.colors["text"],
            insertbackground=self.colors["text"], relief="flat", width=32
        )
        entry.pack(ipady=7)
        entry.focus()

        def create():
            name = entry.get().strip()
            if not name:
                return
            if name in self.playlists:
                messagebox.showwarning("Playlist", "That playlist already exists.", parent=win)
                return
            self.playlists[name] = []
            self.refresh_playlists()
            win.destroy()

        tk.Button(
            win, text="Create", command=create,
            bg=self.colors["accent"], fg="white", relief="flat",
            padx=18, pady=7
        ).pack(pady=12)

    def add_to_playlist(self, name, song):
        paths = self.playlists.setdefault(name, [])
        if song["path"] not in paths:
            paths.append(song["path"])
        self.status_var.set(f'Added "{song["title"]}" to {name}')

    def open_settings(self):
        win = tk.Toplevel(self)
        win.title("Settings")
        win.geometry("700x560")
        win.minsize(600, 480)
        win.configure(bg=self.colors["bg"])

        tk.Label(
            win, text="Settings", bg=self.colors["bg"], fg=self.colors["text"],
            font=("Segoe UI Semibold", 22)
        ).pack(anchor="w", padx=25, pady=(22, 4))

        tk.Label(
            win, text="Music folders", bg=self.colors["bg"], fg=self.colors["muted"],
            font=("Segoe UI", 10)
        ).pack(anchor="w", padx=25, pady=(0, 10))

        folder_frame = tk.Frame(win, bg=self.colors["panel"])
        folder_frame.pack(fill="both", expand=True, padx=25)

        listbox = tk.Listbox(
            folder_frame, bg=self.colors["panel"], fg=self.colors["text"],
            selectbackground=self.colors["accent"], selectforeground="white",
            relief="flat", font=("Segoe UI", 10)
        )
        listbox.pack(side="left", fill="both", expand=True, padx=12, pady=12)

        for folder in self.settings.get("music_folders", []):
            listbox.insert("end", folder)

        buttons = tk.Frame(folder_frame, bg=self.colors["panel"])
        buttons.pack(side="right", fill="y", padx=12, pady=12)

        def add_folder():
            folder = filedialog.askdirectory(parent=win, title="Choose a music folder")
            if folder:
                folder = os.path.abspath(folder)
                existing = list(listbox.get(0, "end"))
                if folder not in existing:
                    listbox.insert("end", folder)

        def remove_folder():
            selected = listbox.curselection()
            for i in reversed(selected):
                listbox.delete(i)

        def rescan():
            save()
            self.start_scan()
            win.destroy()

        tk.Button(
            buttons, text="+ Add Folder", command=add_folder,
            bg=self.colors["accent"], fg="white", relief="flat",
            padx=14, pady=8
        ).pack(fill="x", pady=(0, 8))

        tk.Button(
            buttons, text="Remove", command=remove_folder,
            bg=self.colors["panel2"], fg=self.colors["text"], relief="flat",
            padx=14, pady=8
        ).pack(fill="x")

        options = tk.Frame(win, bg=self.colors["bg"])
        options.pack(fill="x", padx=25, pady=18)

        auto_var = tk.BooleanVar(value=self.settings.get("auto_scan", True))
        tk.Checkbutton(
            options, text="Scan folders automatically when the app starts",
            variable=auto_var, bg=self.colors["bg"], fg=self.colors["text"],
            selectcolor=self.colors["panel2"], activebackground=self.colors["bg"],
            activeforeground=self.colors["text"], font=("Segoe UI", 10)
        ).pack(anchor="w")

        tk.Label(
            options,
            text="Folders are scanned recursively. Your music stays on your computer.",
            bg=self.colors["bg"], fg=self.colors["muted"], font=("Segoe UI", 9)
        ).pack(anchor="w", pady=(8, 0))

        footer = tk.Frame(win, bg=self.colors["bg"])
        footer.pack(fill="x", padx=25, pady=(0, 20))

        def save():
            self.settings["music_folders"] = list(listbox.get(0, "end"))
            self.settings["auto_scan"] = auto_var.get()
            save_settings(self.settings)
            self.status_var.set("Settings saved")

        tk.Button(
            footer, text="Save", command=save,
            bg=self.colors["accent"], fg="white", relief="flat",
            padx=22, pady=9
        ).pack(side="right", padx=(8, 0))

        tk.Button(
            footer, text="Save & Scan", command=rescan,
            bg=self.colors["panel2"], fg=self.colors["text"], relief="flat",
            padx=22, pady=9
        ).pack(side="right")

    def on_close(self):
        try:
            save_settings(self.settings)
            if pygame:
                pygame.mixer.music.stop()
                pygame.mixer.quit()
        except Exception:
            pass
        self.destroy()


if __name__ == "__main__":
    app = MusicVault()
    app.mainloop()
