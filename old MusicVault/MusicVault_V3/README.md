# MusicVault V3

A local-first Spotify-inspired Python music player with a blue interface.

## New in V3

- Spotify-style dark layout with blue accent
- Much larger player
- Persistent SQLite music database
- Multiple music folders and drives
- Faster incremental scanning using file modification times
- Recursive library scanning
- Automatic album/artist/genre/year detection
- Album artwork
- Scrollable album carousel
- Vertical + horizontal library scrollbars
- Scrollable playlist sidebar
- Persistent playlists
- Add/remove playlist songs
- Playlist deletion
- Favorites
- Recently Added
- Most Played
- Play history
- Resume playback position
- Search
- Sort by title, artist, album, year, duration, date added
- Click table headings to sort
- Play Next
- Queue
- Shuffle
- Repeat all / repeat one
- Volume
- Keyboard shortcuts
- Open file location
- Context menus
- Manual scanning
- Automatic startup scanning
- Missing-file cleanup
- No individual uploads
- No cloud music storage

## Keyboard shortcuts

Space = play/pause
Ctrl+F = focus search
Ctrl+L = scan library
Left Arrow = previous
Right Arrow = next
Ctrl+Shift+F = favorite current song

## Correct seeking

The seek bar now has three states:
1. Press = pause automatic position updates while dragging.
2. Drag = preview the target time.
3. Release = reload the file and seek to the selected second.

The database also remembers the last playback position.

Some codecs/containers do not expose reliable seeking through the SDL audio backend used by pygame. For those files, the app reports that seeking is unavailable rather than silently moving only the UI.

## Install

Extract the folder and double-click:

run_musicvault.bat

Then:
Settings -> Add Folder -> add as many folders as desired -> Save & Scan.

Music is played directly from its existing location. The app does not upload or copy the music.
