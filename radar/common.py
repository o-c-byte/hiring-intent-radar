"""Shared helpers: polite HTTP (per-host pacing, project User-Agent), paths, text cleanup."""
from __future__ import annotations

import gzip
import html
import json
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
RAW = DATA / "raw"
SITE = ROOT / "site"

USER_AGENT = "HiringIntentRadar/0.1 (research project; reads public job boards only)"
MIN_INTERVAL = 1.1  # seconds between requests to the same host

_host_last: dict[str, float] = {}
_registry_lock = threading.Lock()


def _host_key(url: str) -> str:
    host = urllib.parse.urlparse(url).hostname or ""
    # Personio / Recruitee / Teamtailor use one subdomain per company but share servers: pace them as one host.
    for shared in ("jobs.personio.com", "jobs.personio.de", "recruitee.com", "teamtailor.com"):
        if host.endswith(shared):
            return shared
    return host


MAX_SECONDS = 30.0  # hard cap per download, so a slow server cannot stall a worker


def get(url: str, timeout: float = 20.0, accept: str = "application/json, text/html;q=0.9, */*;q=0.5") -> tuple[int, str]:
    """GET with per-host pacing. Returns (status, body). status 0 = network error.

    Pacing: each request to a host reserves a start time at least MIN_INTERVAL after the previous one, so request
    starts to one host stay >= 1.1 s apart even when many threads share it, and a slow response blocks nobody else.
    """
    key = _host_key(url)
    with _registry_lock:
        start = max(time.monotonic(), _host_last.get(key, 0.0) + MIN_INTERVAL)
        _host_last[key] = start
    wait = start - time.monotonic()
    if wait > 0:
        time.sleep(wait)
    try:
        req = urllib.request.Request(url, headers={
            "User-Agent": USER_AGENT, "Accept": accept, "Accept-Encoding": "gzip",
            "Accept-Language": "en;q=0.9, *;q=0.5"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            chunks, t0 = [], time.monotonic()
            while chunk := r.read(65536):
                chunks.append(chunk)
                if time.monotonic() - t0 > MAX_SECONDS:
                    return 0, ""
            body = b"".join(chunks)
            if r.headers.get("Content-Encoding") == "gzip":
                body = gzip.decompress(body)
            return r.status, body.decode("utf-8", errors="replace")
    except urllib.error.HTTPError as e:
        return e.code, ""
    except Exception:
        return 0, ""


def get_json(url: str, timeout: float = 20.0):
    status, body = get(url, timeout)
    if status != 200 or not body:
        return None
    try:
        return json.loads(body)
    except json.JSONDecodeError:
        return None


_TAG = re.compile(r"<[^>]+>")
_WS = re.compile(r"[ \t\r\f\v]+")


def html_to_text(s: str | None) -> str:
    if not s:
        return ""
    s = html.unescape(s)  # Greenhouse double-escapes
    s = re.sub(r"(?i)<\s*(br|/p|/li|/h\d|/div)\s*/?>", "\n", s)
    s = re.sub(r"(?i)<\s*li[^>]*>", "\n- ", s)
    s = _TAG.sub(" ", s)
    s = html.unescape(s)
    s = _WS.sub(" ", s)
    s = re.sub(r"\n\s*\n+", "\n", s)
    return s.strip()


def slugify(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


def read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with path.open(encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def write_jsonl(path: Path, rows) -> None:
    with path.open("w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
