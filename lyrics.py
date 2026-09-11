import os
import re

try:
    from mutagen import File as MutagenFile
except ImportError:
    MutagenFile = None


LRC_LINE = re.compile(r"\[(\d+):(\d{1,2})(?:[.:](\d{1,3}))?\]\s*(.*)$")


def _decode(data):
    if isinstance(data, str):
        return data
    for encoding in ("utf-8-sig", "utf-16", "cp1252"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="replace")


def parse_lyrics(text):
    lines = []
    plain = []
    for raw_line in text.splitlines():
        match = LRC_LINE.match(raw_line.strip())
        if not match:
            if raw_line.strip():
                plain.append(raw_line.rstrip())
            continue
        minutes, seconds, fraction, lyric = match.groups()
        fraction = fraction or "0"
        timestamp = int(minutes) * 60 + int(seconds) + int(fraction.ljust(3, "0")[:3]) / 1000
        lines.append((timestamp, lyric.strip()))
    if not lines:
        return [], text.strip()
    return sorted(lines), "\n".join(lyric for _, lyric in lines).strip()


def load_lyrics(path, tags=None):
    if tags is None and MutagenFile:
        try:
            audio = MutagenFile(path, easy=False)
            tags = getattr(audio, "tags", None) if audio else None
        except Exception:
            tags = None
    embedded = _embedded_text(tags)
    if embedded:
        lines, plain = parse_lyrics(embedded)
        return {"source": "Embedded", "path": path, "text": embedded,
                "lines": lines, "plain": plain}

    base, _ = os.path.splitext(path)
    for candidate, source in ((base + ".lrc", "LRC file"), (base + ".txt", "Text file")):
        if not os.path.isfile(candidate):
            continue
        try:
            with open(candidate, "rb") as stream:
                text = _decode(stream.read())
            lines, plain = parse_lyrics(text)
            return {"source": source, "path": candidate, "text": text,
                    "lines": lines, "plain": plain}
        except OSError:
            pass
    return None


def _embedded_text(tags):
    if not tags:
        return ""
    for key in ("USLT::eng", "USLT", "lyrics", "LYRICS", "©lyr", "----:com.apple.iTunes:LYRICS"):
        try:
            value = tags.get(key)
            if isinstance(value, list):
                value = value[0] if value else ""
            value = getattr(value, "text", value)
            if isinstance(value, list):
                value = value[0] if value else ""
            if value:
                return str(value)
        except Exception:
            continue
    return ""


def format_lrc(lines):
    return "\n".join(
        f"[{int(seconds) // 60:02d}:{seconds % 60:05.2f}] {text}"
        for seconds, text in lines
    )
