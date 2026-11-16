from __future__ import annotations

"""Parsing helpers for team Drive folder links.

Users paste a Google Drive folder URL (or a bare folder ID) when creating a
team; these helpers turn that into the folder ID the Drive API works with.
"""

import re

FOLDER_URL_RE = re.compile(r"drive\.google\.com/(?:drive|docs)(?:/u/\d+)?/(?:folders|drive)/([A-Za-z0-9_-]{10,})")
BARE_ID_RE = re.compile(r"^[A-Za-z0-9_-]{10,}$")


def extract_drive_folder_id(text: str) -> str:
    """Return the Drive folder ID from a pasted link or bare ID.

    Accepts, for example:
      - https://drive.google.com/drive/folders/1AbC_dEf-123
      - https://drive.google.com/drive/u/0/folders/1AbC_dEf-123?usp=sharing
      - 1AbC_dEf-123
    Raises ValueError for anything else non-empty.
    """
    value = (text or "").strip()
    if not value:
        return ""
    match = FOLDER_URL_RE.search(value)
    if match:
        return match.group(1)
    if BARE_ID_RE.match(value):
        return value
    raise ValueError(
        "That doesn't look like a Google Drive folder link. Paste a link like "
        "https://drive.google.com/drive/folders/<folder-id> (Drive → open the "
        "folder → copy the link) or the folder ID itself."
    )


def drive_folder_url(folder_id: str) -> str:
    """Canonical link to a Drive folder."""
    return f"https://drive.google.com/drive/folders/{folder_id}" if folder_id else ""
