# MusicVault V2

A local-first Python Windows music library/player.

## Major additions

- Multiple folders
- Recursive scanning
- SQLite persistent library
- Scrollbars on library and settings folder lists
- Horizontal scrollbar for the song table
- Automatic album detection from metadata
- Artist detection
- Genre detection
- Year detection
- Track/disc number detection
- Album grouping
- Album strip with horizontally scrollable album cards
- Embedded artwork
- Search across title, artist, album, genre and year
- Favorites
- Real persistent playlists
- Add/remove songs from playlists
- Delete playlists
- Recently Added
- Most Played history
- Play Next
- Open File Location
- Shuffle
- Repeat off/all/one
- Seek
- Volume
- Keyboard Return to play
- Automatic scan at startup
- Manual Scan button
- Missing-file cleanup
- Duplicate-path protection
- Local-only architecture
- No manual individual-file uploads

## Install

1. Install Python 3.10+.
2. Extract this folder.
3. Double-click `run_musicvault.bat`.
4. Open Settings.
5. Add as many folders as you need.
6. Click Save & Scan.

## Recommended folder layout

You can add completely different folders and drives:

D:\Music
D:\Downloads\Music
E:\FLAC
F:\Albums
C:\Users\YourName\Music

The scanner searches subfolders automatically.

## Important

This is a local player. It does not upload or copy your music.

Metadata quality depends on the tags already embedded in your files. Files with good ID3/Vorbis/MP4 tags will have the best album/artist/title detection.
