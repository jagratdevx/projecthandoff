from __future__ import annotations

"""Minimal in-memory fake of the googleapiclient Drive v3 surface used by the backend."""

import re

FOLDER_MIME = "application/vnd.google-apps.folder"


def _media_bytes(media) -> bytes:
    if media is None:
        return b""
    fd = getattr(media, "_fd", None)
    if fd is not None and hasattr(fd, "getvalue"):
        return fd.getvalue()
    return getattr(media, "_content", b"") or b""


class FakeHttpError(Exception):
    def __init__(self, status: int):
        self.status = status
        super().__init__(f"fake http {status}")


class FakeCreds:
    def __init__(self, *, expired=False, invalid=False, refresh_fails=False):
        self.token = "tok-1"
        self.refresh_token = "refresh-1"
        self.token_uri = "https://oauth2.googleapis.com/token"
        self.client_id = "client"
        self.client_secret = "shh"
        self.scopes = ["https://www.googleapis.com/auth/drive.file"]
        self.expired = expired
        self.invalid = invalid
        self.valid = not (expired or invalid)
        self.refresh_fails = refresh_fails
        self.refresh_count = 0

    def refresh(self, request):
        self.refresh_count += 1
        if self.refresh_fails:
            raise RuntimeError("refresh network error")
        self.expired = False
        self.invalid = False
        self.valid = True
        self.token = f"tok-refreshed-{self.refresh_count}"


class FakeRequest:
    def __init__(self, state, func):
        self.state = state
        self.func = func

    def execute(self):
        try:
            return self.func()
        except FakeHttpError as exc:
            raise make_fake_http_error(exc.status)


class FakeFiles:
    def __init__(self, state):
        self.state = state

    # -- request builders -----------------------------------------------------
    def list(self, q: str, fields: str | None = None, pageSize: int | None = None, **_):
        parent = re.search(r"'([^']+)' in parents", q)
        name = re.search(r"name='([^']*)'", q)
        is_folder_q = FOLDER_MIME in q
        trashed_false = "trashed=false" in q

        def run():
            self.state["list_calls"] += 1
            if self.state.get("fail_list_with"):
                raise FakeHttpError(self.state.pop("fail_list_with"))
            results = []
            for fid, meta in self.state["files"].items():
                if meta.get("trashed"):
                    continue
                if trashed_false and meta.get("trashed"):
                    continue
                if parent and parent.group(1) not in meta.get("parents", []):
                    continue
                if name and name.group(1) != meta.get("name"):
                    continue
                if is_folder_q and meta.get("mimeType") != FOLDER_MIME:
                    continue
                results.append({"id": fid, "name": meta["name"], "headRevisionId": meta["headRevisionId"]})
            return {"files": results}

        return FakeRequest(self.state, run)

    def create(self, body, media_body=None, fields=None, **_):
        def run():
            fid = f"f{self.state['next_id']}"
            self.state["next_id"] += 1
            meta = {
                "name": body.get("name"),
                "parents": body.get("parents", []),
                "mimeType": body.get("mimeType", "application/octet-stream"),
                "content": _media_bytes(media_body),
                "headRevisionId": str(self.state["revision"]),
            }
            self.state["revision"] += 1
            self.state["files"][fid] = meta
            return {"id": fid, "name": meta["name"], "headRevisionId": meta["headRevisionId"]}

        return FakeRequest(self.state, run)

    def update(self, fileId, media_body=None, **_):
        def run():
            if fileId not in self.state["files"]:
                raise FakeHttpError(404)
            self.state["files"][fileId]["content"] = _media_bytes(media_body)
            self.state["files"][fileId]["headRevisionId"] = str(self.state["revision"])
            self.state["revision"] += 1
            return {"id": fileId, "headRevisionId": self.state["files"][fileId]["headRevisionId"]}

        return FakeRequest(self.state, run)

    def get(self, fileId, fields=None, **_):
        def run():
            if fileId not in self.state["files"]:
                raise FakeHttpError(404)
            meta = self.state["files"][fileId]
            return {"id": fileId, "name": meta["name"], "headRevisionId": meta["headRevisionId"]}

        return FakeRequest(self.state, run)

    def get_media(self, fileId, **_):
        def run():
            if fileId not in self.state["files"]:
                raise FakeHttpError(404)
            return self.state["files"][fileId]["content"]

        return FakeRequest(self.state, run)

    def delete(self, fileId, **_):
        def run():
            if fileId not in self.state["files"]:
                raise FakeHttpError(404)
            del self.state["files"][fileId]
            return {}

        return FakeRequest(self.state, run)


class FakeAbout:
    def __init__(self, state):
        self.state = state

    def get(self, fields=None, **_):
        def run():
            return {"user": {"emailAddress": self.state.get("account", "organizer@school.edu")}}

        return FakeRequest(self.state, run)


class FakeDriveService:
    def __init__(self, state=None):
        self.state = state or {"files": {}, "next_id": 1, "revision": 100, "list_calls": 0}

    def files(self):
        return FakeFiles(self.state)

    def about(self):
        return FakeAbout(self.state)


def make_fake_http_error(status: int):
    """Build a real googleapiclient HttpError so error translation paths are exercised."""
    import httplib2
    from googleapiclient.errors import HttpError

    resp = httplib2.Response({"status": str(status), "reason": "fake"})
    return HttpError(resp, b"fake error body")
