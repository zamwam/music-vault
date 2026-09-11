# MusicVault

Spotify-style local music player for Windows.

## Improvements
- Much smoother UI on large libraries
- Debounced search instead of refreshing on every keystroke
- Incremental table rendering so thousands of songs do not freeze the window
- Cached album artwork
- Cached library data between views
- Better playback position tracking after seeking
- Visible Shuffle button
- Favorite button in the player and action bar
- Like / Dislike buttons
- Right-click Like / Dislike / Clear reaction
- Persistent shuffle and repeat settings
- More settings for album carousel, status bar, and playback preferences
- Spotify-style track details popup from any song row or the current player
- Track metadata, artwork, format, queue, favorite, and file-location actions
- Optional hidden-file scanning and favorite-removal confirmation
- Expanded Settings with startup view, player height, Home artwork size, library result limits,
  and independent Home-section visibility toggles
- Embedded Now Playing page is the default; Separate Window remains optional
- Home dashboard with Continue Listening, Recently Played, Recently Added, Most Played,
  Favorites, Likes, and Never Played rails
- Five-star ratings with keyboard shortcuts (`1` through `5`) and rating sorting/filtering
- Search operators such as `artist:"Juice WRLD" rating:5 format:flac favorite:true`
- Queue drawer with double-click play, clear, and Save Queue as Playlist
- Random, Smart, Artist Variety, and Album Variety shuffle strategies
- SQLite database backup, restore with automatic pre-restore backup, JSON export, and M3U export
- Dedicated in-window album and artist pages with track lists and queue actions
- Queue reorder, remove, shuffle, reverse, deduplicate, clear-after-current, and save controls
- Library Health statistics, safe dead-entry cleanup, Mutagen metadata editing with file backups,
  and on-demand exact-hash/metadata duplicate detection
- Playlist, queue, favorites, history, resume playback, sorting, and multi-folder scanning
- Local account dashboard with profile name, optional PIN authentication, favorites, recent plays,
  likes, dislikes, and quick playback actions
- Smart views for recently played, liked, never played, top rated, and long tracks
- Listening-time and top-artist account statistics, toast notifications, sleep timer, crossfade,
  media-key controls, keyboard shortcut help, and optional Windows system-tray mode
- Artist, album, and genre browsing surfaces now display grouped entity names instead of generic
    track rows; unqualified search matches titles only, while operators target metadata fields
- Configurable navigation visibility with a compact default order, selectable interface fonts,
    default initials avatars, cropped profile-picture uploads, and opt-in automatic album-art downloads
- Developer startup flags: `--dev`, `--debug`, `--no-scan`, `--no-auth`, `--view Account`,
  `--profile-name "Name"`, and `--data-dir PATH`

## Architecture

The database API now lives in `database.py`, duplicate detection is isolated in
`duplicate_finder.py`, and safe path planning/moves live in `organizer.py`. The existing
`musicvault.py` UI continues to use the same DB method names, preserving existing settings and
database data while the remaining UI boundaries are refactored incrementally.

## Track details
Use the current track in the player or press `Ctrl+I` to inspect the active song in the optional
details window. In the library, single click selects a song and double click plays it in the
embedded Now Playing page.

Use the right-click menu for details and management actions.

## Run
1. Extract the ZIP.
2. Run `run_musicvault.bat`.
3. Open Settings and add your music folders.
4. Click Save & Scan.

For example, a developer can run an isolated profile without scanning or authentication:
`run_musicvault.bat --dev --no-scan --no-auth --data-dir .\\.musicvault-dev --view Account`

Dependencies are installed automatically by the launcher.
