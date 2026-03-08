# -*- coding: utf-8 -*-
from pathlib import Path
from datetime import datetime


def export_to_txt(text: str, path: Path | None = None) -> Path:
    path = path or Path(f"transcripcion_{datetime.now():%Y%m%d_%H%M%S}.txt")
    path.write_text(text, encoding="utf-8")
    return path


def export_to_srt(lines: list[tuple[str, float, float]], path: Path | None = None) -> Path:
    """lines = [(texto, start_seconds, end_seconds), ...]"""
    path = path or Path(f"transcripcion_{datetime.now():%Y%m%d_%H%M%S}.srt")

    def fmt_time(seconds: float) -> str:
        h = int(seconds // 3600)
        m = int((seconds % 3600) // 60)
        s = int(seconds % 60)
        ms = int((seconds % 1) * 1000)
        return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"

    content = ""
    for i, (text, start, end) in enumerate(lines, 1):
        content += f"{i}\n{fmt_time(start)} --> {fmt_time(end)}\n{text}\n\n"

    path.write_text(content, encoding="utf-8")
    return path
