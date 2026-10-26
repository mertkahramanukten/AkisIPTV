"""EPG (yayın akışı).

* Kısa EPG (get_short_epg): seçilen kanal için hızlı, anlık.
* Tam EPG (xmltv.php): arka planda indirilir, akış halinde (iterparse) işlenir;
  bellekte yalnızca [şimdi-3s, şimdi+18s] aralığı tutulur. Böylece 200 MB'lık
  XMLTV dosyaları bile arayüzü dondurmaz.
"""
from __future__ import annotations

import bisect
import gzip
import logging
import threading
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .xtream import EpgEntry

log = logging.getLogger(__name__)


def parse_xmltv_time(s: str) -> float | None:
    """'20261026180000 +0300' -> epoch. Saat dilimi yoksa yerel saat kabul edilir."""
    if not s:
        return None
    s = s.strip()
    try:
        base = datetime.strptime(s[:14], "%Y%m%d%H%M%S")
    except ValueError:
        return None
    rest = s[14:].strip()
    if rest and rest[0] in "+-" and len(rest) >= 5:
        try:
            sign = 1 if rest[0] == "+" else -1
            off = timedelta(hours=int(rest[1:3]), minutes=int(rest[3:5])) * sign
            return base.replace(tzinfo=timezone(off)).timestamp()
        except ValueError:
            pass
    if rest.upper() in ("Z", "UTC", "GMT", "+0000"):
        return base.replace(tzinfo=timezone.utc).timestamp()
    return base.timestamp()


def parse_xmltv_file(path: Path, window_before: float = 3 * 3600, window_after: float = 18 * 3600,
                     now: float | None = None, wanted: set[str] | None = None) -> dict[str, list[EpgEntry]]:
    now = now or time.time()
    lo, hi = now - window_before, now + window_after
    out: dict[str, list[EpgEntry]] = {}
    count = 0
    with open(path, "rb") as fh:
        gz = fh.read(2) == b"\x1f\x8b"
    src = gzip.open(path, "rb") if gz else open(path, "rb")
    with src:
        _parse_stream(src, out, lo, hi, wanted)
    for lst in out.values():
        lst.sort(key=lambda e: e.start)
        count += len(lst)
    log.info("XMLTV işlendi: %d kanal, %d program", len(out), count)
    return out


def _parse_stream(src, out, lo, hi, wanted) -> None:
    root = None
    for event, elem in ET.iterparse(src, events=("start", "end")):
        if root is None:
            root = elem
            continue
        if event != "end":
            continue
        if elem.tag == "programme":
            ch = (elem.get("channel") or "").lower()
            if wanted is None or ch in wanted:
                start = parse_xmltv_time(elem.get("start", ""))
                stop = parse_xmltv_time(elem.get("stop", ""))
                if start and stop and stop >= lo and start <= hi:
                    title = (elem.findtext("title") or "").strip()
                    desc = (elem.findtext("desc") or "").strip()
                    out.setdefault(ch, []).append(EpgEntry(title, start, stop, desc))
            root.clear()   # belleği serbest bırak (büyük XMLTV dosyaları için kritik)
        elif elem.tag == "channel":
            root.clear()


class EpgStore:
    """Kanal başına EPG listeleri. Thread-safe."""

    def __init__(self):
        self._lock = threading.Lock()
        self._by_channel: dict[str, list[EpgEntry]] = {}
        self._starts: dict[str, list[float]] = {}
        self._short: dict[str, tuple[float, list[EpgEntry]]] = {}

    @staticmethod
    def _key(epg_id) -> str:
        return str(epg_id or "").strip().lower()

    def load_full(self, data: dict[str, list[EpgEntry]]) -> None:
        with self._lock:
            self._by_channel = data
            self._starts = {k: [e.start for e in v] for k, v in data.items()}

    def put_short(self, stream_id, entries: list[EpgEntry]) -> None:
        with self._lock:
            self._short[str(stream_id)] = (time.time(), entries)

    def short_fresh(self, stream_id, max_age: float = 600) -> list[EpgEntry] | None:
        with self._lock:
            hit = self._short.get(str(stream_id))
        if hit and time.time() - hit[0] < max_age:
            return hit[1]
        return None

    def has_full(self) -> bool:
        return bool(self._by_channel)

    def now_next(self, epg_id=None, stream_id=None, now: float | None = None) -> tuple[EpgEntry | None, EpgEntry | None]:
        now = now or time.time()
        entries: list[EpgEntry] | None = None
        if stream_id is not None:
            sh = self.short_fresh(stream_id, max_age=3600)
            if sh:
                entries = sh
        if entries is None and epg_id:
            k = self._key(epg_id)
            with self._lock:
                lst = self._by_channel.get(k)
                starts = self._starts.get(k)
            if lst:
                i = bisect.bisect_right(starts, now) - 1
                cur = lst[i] if 0 <= i < len(lst) and lst[i].stop > now else None
                nxt = lst[i + 1] if i + 1 < len(lst) else None
                return cur, nxt
        if entries:
            cur = next((e for e in entries if e.start <= now < e.stop), None)
            nxt = next((e for e in entries if e.start > now), None)
            return cur, nxt
        return None, None

    def upcoming(self, epg_id=None, stream_id=None, limit: int = 6, now: float | None = None) -> list[EpgEntry]:
        now = now or time.time()
        if stream_id is not None:
            sh = self.short_fresh(stream_id, max_age=3600)
            if sh:
                return [e for e in sh if e.stop > now][:limit]
        k = self._key(epg_id)
        with self._lock:
            lst = self._by_channel.get(k) or []
        return [e for e in lst if e.stop > now][:limit]
