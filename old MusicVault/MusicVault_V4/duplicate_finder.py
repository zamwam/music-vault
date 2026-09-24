import hashlib
import os
import re


def normalized(value):
    return re.sub(r"[^a-z0-9]+", " ", str(value or "").lower()).strip()


def file_hash(path, chunk_size=1024 * 1024):
    digest = hashlib.sha256()
    with open(path, "rb") as stream:
        while chunk := stream.read(chunk_size):
            digest.update(chunk)
    return digest.hexdigest()


def find_duplicate_groups(songs):
    existing = [song for song in songs if os.path.isfile(song["path"])]
    by_size = {}
    for song in existing:
        by_size.setdefault(os.path.getsize(song["path"]), []).append(song)

    exact = {}
    for candidates in by_size.values():
        if len(candidates) < 2:
            continue
        for song in candidates:
            try:
                exact.setdefault(file_hash(song["path"]), []).append(song)
            except OSError:
                continue
    exact_groups = [group for group in exact.values() if len(group) > 1]

    likely = {}
    for song in existing:
        key = (normalized(song["title"]), normalized(song["artist"]),
               normalized(song["album"]), round(float(song["duration"] or 0)))
        likely.setdefault(key, []).append(song)
    likely_groups = [group for group in likely.values() if len(group) > 1]
    return {"exact": exact_groups, "likely": likely_groups}
