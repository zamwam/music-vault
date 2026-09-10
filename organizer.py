import os
import shutil


def destination_for(song, root, template):
    extension = os.path.splitext(song["path"])[1].lstrip(".")
    values = {
        "Artist": str(song.get("artist") or "Unknown Artist").strip() or "Unknown Artist",
        "Album": str(song.get("album") or "Unknown Album").strip() or "Unknown Album",
        "Year": str(song.get("year") or "Unknown Year").strip() or "Unknown Year",
        "Track": f'{int(song.get("track") or 0):02d}' if song.get("track") else "00",
        "Title": str(song.get("title") or "Untitled").strip() or "Untitled",
        "ext": extension,
    }
    relative = template.format(**values)
    return os.path.normpath(os.path.join(root, relative))


def build_plan(songs, root, template):
    plan = []
    for song in songs:
        destination = destination_for(song, root, template)
        plan.append({"source": song["path"], "destination": destination})
    return plan


def apply_plan(plan):
    moved = []
    for item in plan:
        source = os.path.abspath(item["source"])
        destination = os.path.abspath(item["destination"])
        if source == destination or not os.path.isfile(source):
            continue
        if os.path.exists(destination):
            raise FileExistsError(f"Destination already exists: {destination}")
        os.makedirs(os.path.dirname(destination), exist_ok=True)
        shutil.move(source, destination)
        moved.append({"source": source, "destination": destination})
    return moved
