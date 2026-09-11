# MusicVault 🎵

**A powerful Spotify-style local music player and library manager for Windows.**

MusicVault is a desktop music player built for people who want complete control over their own music library. It scans your local music folders, reads embedded metadata and album artwork, organizes your collection into a searchable library, and gives you modern playback features without requiring a streaming service.

Your music stays on your computer.

---

## ✨ Features

### 🎧 Playback

* Play local music files directly from your library
* Play / pause
* Previous / next track
* Seek through tracks
* Volume control
* Shuffle
* Repeat
* Resume playback
* Persistent playback position
* Queue management
* Embedded Now Playing interface
* Optional separate Now Playing window
* Configurable player height
* Smooth UI transitions
* Reduced-motion option

### 🔀 Smart Shuffle

MusicVault includes multiple shuffle strategies:

* **Random** - completely random playback
* **Smart** - smarter randomization based on your library
* **Artist Variety** - reduces consecutive tracks from the same artist
* **Album Variety** - keeps albums more evenly represented

Shuffle and repeat preferences can be remembered between sessions.

---

## 🏠 Home Dashboard

The Home screen gives you a Spotify-style overview of your personal library.

Available sections include:

* Continue Listening
* Recently Played
* Recently Added
* Most Played
* Favorite Songs
* Liked Songs
* Never Played

Home sections can be individually enabled or disabled, and artwork size can be customized.

---

## 📚 Music Library

MusicVault organizes your collection into dedicated views for:

* Songs
* Albums
* Artists
* Genres
* Favorites
* Recently Added
* Most Played
* 5-Star Songs
* Playlists

Album and artist pages include their associated tracks and playback actions.

The library is designed to remain responsive even with large collections, using cached library data and incremental rendering.

---

## 🔎 Powerful Search

Search your entire library using normal text or advanced search operators.

Examples:

```text
artist:"Juice WRLD"
```

```text
rating:5
```

```text
format:flac
```

```text
favorite:true
```

Operators can also be combined:

```text
artist:"Juice WRLD" rating:5 format:flac favorite:true
```

Search results can be sorted by different library attributes including title, artist, album, year, rating, duration, and date added.

---

## ⭐ Ratings, Favorites & Reactions

MusicVault gives you several ways to personalize your library.

### Ratings

Rate songs from **1 to 5 stars**.

Keyboard shortcuts:

```text
1 - 5
```

Ratings can also be used for sorting and filtering.

### Favorites

Mark songs as favorites and access them from the dedicated Favorites view.

### Reactions

Songs can also have:

* 👍 Like
* 👎 Dislike
* No reaction

Reactions can be changed from the player, action bar, or song context menu.

---

## 🎵 Playlists

Create and manage playlists directly inside MusicVault.

Playlist functionality includes:

* Create playlists
* Add songs
* Remove songs
* Manage playlist order
* Play playlists
* Queue playlist tracks

Queues can also be saved directly as playlists.

---

## 📋 Queue Management

The queue is more than just a list of upcoming songs.

You can:

* Add songs
* Remove songs
* Reorder tracks
* Shuffle the queue
* Reverse the queue
* Deduplicate the queue
* Clear everything after the current track
* Clear the queue
* Save the queue as a playlist

A dedicated queue drawer keeps upcoming music accessible while browsing the library.

---

## 🖼️ Album Artwork & Metadata

MusicVault reads metadata directly from your music files using **Mutagen**.

Supported metadata includes:

* Title
* Artist
* Album
* Genre
* Year
* Track number
* Disc number
* Duration
* Embedded album artwork

Embedded artwork is cached to improve performance when browsing large libraries.

If artwork or metadata is missing, MusicVault can identify those issues through **Library Health**.

---

## 🩺 Library Health

The Library Health section provides an overview of your collection.

It can help identify:

* Missing metadata
* Missing artwork
* Library statistics
* Dead library entries
* Duplicate music

MusicVault also provides safe cleanup tools for entries that no longer point to existing files.

---

## 🔍 Duplicate Detection

MusicVault includes dedicated duplicate detection.

It can identify:

### Exact duplicates

Files are compared using:

* File size
* SHA-256 file hashes

This allows MusicVault to identify files that are byte-for-byte identical.

### Likely duplicates

MusicVault can also find songs that appear to represent the same recording using:

* Normalized title
* Normalized artist
* Normalized album
* Track duration

This helps identify duplicate versions that may have different filenames or locations.

---

## 🗂️ Music Organizer

MusicVault includes a library organizer for planning and safely moving music into a consistent folder structure.

Organization templates can use metadata such as:

```text
{Artist}
{Album}
{Year}
{Track}
{Title}
{ext}
```

For example:

```text
Artist/
    Album/
        01 - Song.ext
```

MusicVault builds a destination plan before applying moves and avoids overwriting an existing destination file.

---

## ✏️ Metadata Management

Track metadata can be inspected and edited from MusicVault.

Metadata editing supports common fields such as:

* Title
* Artist
* Album
* Genre
* Year
* Track number
* Disc number

File backups are supported when modifying metadata.

---

## 💾 Database & Backup

MusicVault uses a local **SQLite database** to store library information and user preferences.

The database keeps track of:

* Songs
* Playlists
* Playlist membership
* Favorites
* Reactions
* Ratings
* Playback history
* Playback positions
* Library metadata
* Album artwork

The database is stored in the MusicVault application data directory.

### Export & Backup

MusicVault supports:

* SQLite database backup
* Database restore
* Automatic pre-restore backup
* JSON library export
* M3U playlist export

---

## ⚙️ Customization

MusicVault includes settings for customizing the experience.

Available options include:

* Startup view
* Player height
* Home artwork size
* Library result limits
* Home section visibility
* Album carousel
* Status bar
* Playback preferences
* Shuffle preferences
* Repeat preferences
* Hidden-file scanning
* Favorite-removal confirmation
* UI density
* Smooth transitions
* Reduced motion

---

## 🖥️ Performance

MusicVault is designed to remain usable with large local music collections.

Performance improvements include:

* Debounced search
* Incremental table rendering
* Cached album artwork
* Cached library data
* SQLite indexes
* Background library scanning
* Efficient metadata updates
* Persistent database storage

The database indexes commonly searched fields such as title, artist, album, genre, and date added.

---

## 🎼 Supported Music Metadata

MusicVault uses [Mutagen](https://mutagen.readthedocs.io/) to read and work with audio metadata.

The application is designed around common local music formats and metadata containers supported by Mutagen.

Actual playback support depends on the audio engine and the codecs available on the system.

---

## 🛠️ Technology

MusicVault is built with:

* **Python**
* **Tkinter**
* **Pygame CE**
* **Mutagen**
* **Pillow**
* **PyStray**
* **SQLite**

### Architecture

The project is split into several major components:

```text
music-player/
├── musicvault.py
├── database.py
├── duplicate_finder.py
├── organizer.py
├── requirements.txt
├── run_musicvault.bat
└── README.md
```

### Core components

**`musicvault.py`**

The main MusicVault application and user interface.

**`database.py`**

SQLite database layer responsible for library data, playlists, favorites, reactions, ratings, history, and playback positions.

**`duplicate_finder.py`**

Handles exact-hash and likely-duplicate detection.

**`organizer.py`**

Handles music organization planning and safe file moves.

**`requirements.txt`**

Contains the Python dependencies required by the application.

---

## 🚀 Installation

### Requirements

MusicVault is currently designed for **Windows**.

You will need:

* Windows
* Python 3
* A local music library

The included launcher can install the required Python packages automatically.

### Quick Start

1. Download or clone the repository.

```bash
git clone https://github.com/zamwam/music-player.git
```

2. Open the project folder.

3. Run:

```text
run_musicvault.bat
```

4. Open **Settings**.

5. Add one or more folders containing your music.

6. Click **Save & Scan**.

MusicVault will scan the selected folders and build your local library.

---

## 📁 Library Scanning

MusicVault supports scanning multiple music folders.

During scanning, MusicVault reads each supported audio file and extracts its metadata, artwork, duration, and filesystem information.

The database tracks file modification times so existing library entries can be updated when files change.

Missing files can also be removed from the library without manually deleting every database entry.

---

## ⌨️ Keyboard Shortcuts

MusicVault includes keyboard shortcuts for common actions.

| Shortcut   | Action                |
| ---------- | --------------------- |
| `1`        | Set rating to 1 star  |
| `2`        | Set rating to 2 stars |
| `3`        | Set rating to 3 stars |
| `4`        | Set rating to 4 stars |
| `5`        | Set rating to 5 stars |
| `Ctrl + I` | Open track details    |
| `Space`    | Play / Pause          |
| `←`        | Previous track        |
| `→`        | Next track            |
| `Ctrl + F` | Toggle favorite       |

Additional shortcuts may be added as MusicVault continues to evolve.

---

## 🔐 Local-First

MusicVault is designed around your local music collection.

There is:

* No required account
* No streaming subscription
* No required cloud library
* No requirement to upload your music

Your library database and music files remain on your computer.

---

## 🧪 Project Status

MusicVault is an actively evolving personal music player project.

The current version focuses on:

* Reliable local playback
* Large-library performance
* Library organization
* Search
* Playlists
* Queue management
* Ratings and reactions
* Metadata management
* Duplicate detection
* Library health
* Backup and export

Features and UI may continue to change as the project develops.

---

## 🗺️ Roadmap

Potential future improvements include:

* More playback controls
* Improved visualizations
* More advanced playlist tools
* Additional metadata editing
* More audio format support
* Improved library statistics
* Expanded keyboard shortcuts
* Better Windows integration
* More customization
* Additional backup and migration tools
* Improved installer and packaging

---

## 🤝 Contributing

MusicVault is primarily a personal project, but suggestions, bug reports, and improvements are welcome.

If you find a problem or have an idea for improving MusicVault, open an issue or submit a pull request.

---

## 📄 License

See the repository for the current license information.

---

## 🎵 Why MusicVault?

MusicVault is built around a simple idea:

> **Your music library should belong to you.**

Instead of treating local music as an afterthought, MusicVault treats it like a full library.

Scan it.
Organize it.
Rate it.
Favorite it.
Build playlists.
Manage your metadata.
Find duplicates.
Back it up.
And most importantly, **listen to it.**

---

**MusicVault**
*Your music. Your library. Your way.*
