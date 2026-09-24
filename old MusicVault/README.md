# MusicVault

A local Windows music player written in Python.

## Features

- Add multiple music folders
- Recursive scanning
- Automatically detects common audio formats
- Reads title, artist, album, year and duration metadata
- Reads embedded album artwork when available
- Search
- Favorites
- Playlists
- Shuffle
- Repeat
- Volume control
- Seek bar
- Remembers music folders and settings
- No manual song uploading
- Music stays on your computer

## Run

1. Install Python 3.10+.
2. Open Command Prompt in this folder.
3. Run:

    python -m pip install -r requirements.txt

4. Then:

    python musicvault.py

5. Open Settings.
6. Click Add Folder and select your music directories.
7. You can add as many folders as you want.
8. Click Save & Scan.

Example folders:

D:\Music
D:\Downloads\Music
E:\FLAC
C:\Users\YourName\Music

The app scans all subfolders automatically.

## Notes

The library is rebuilt from your selected folders when scanning, so deleted/moved files do not remain as ghost entries.

Supported extensions include:
MP3, WAV, FLAC, M4A, AAC, OGG, OPUS, WMA, AIFF and APE.

Some formats may depend on the installed pygame/SDL audio support.
