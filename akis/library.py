"""Katalog yönetimi: önbellekten anında göster, arkada tazele, gerekirse kategori kategori indir."""
from __future__ import annotations

import logging
import os
import time
from pathlib import Path

import requests
from PySide6.QtCore import QObject, Signal

from .cache import DiskCache
from .config import cache_dir
from .epg import EpgStore, parse_xmltv_file
from .workers import post, run_async
from .xtream import XtreamClient, XtreamError, search_key, to_int

log = logging.getLogger(__name__)

MODES = ("live", "vod", "series")
REFRESH_AFTER = 30 * 60          # bu kadar eski önbellek arkada tazelenir
XMLTV_MAX_AGE = 6 * 3600
XMLTV_MAX_BYTES = 400 * 1024 * 1024


def _cats_of(raw: dict) -> list[str]:
    ids = raw.get("category_ids")
    out = []
    if isinstance(ids, list):
        out = [str(x) for x in ids if x is not None]
    cid = raw.get("category_id")
    if cid is not None and str(cid) not in out:
        out.insert(0, str(cid))
    return out


def normalize_items(mode: str, raw_items: list[dict]) -> list[dict]:
    out = []
    for r in raw_items:
        name = str(r.get("name") or r.get("title") or "").strip()
        if mode == "live":
            sid = r.get("stream_id")
            if sid is None:
                continue
            out.append({"id": str(sid), "name": name or f"Kanal {sid}", "icon": r.get("stream_icon") or "",
                        "cats": _cats_of(r), "num": to_int(r.get("num"), 0),
                        "epg": str(r.get("epg_channel_id") or ""), "archive": to_int(r.get("tv_archive"), 0),
                        "k": search_key(name)})
        elif mode == "vod":
            sid = r.get("stream_id")
            if sid is None:
                continue
            out.append({"id": str(sid), "name": name, "icon": r.get("stream_icon") or r.get("cover") or "",
                        "cats": _cats_of(r), "ext": str(r.get("container_extension") or "mp4"),
                        "rating": str(r.get("rating") or ""), "added": to_int(r.get("added"), 0),
                        "k": search_key(name)})
        else:
            sid = r.get("series_id")
            if sid is None:
                continue
            out.append({"id": str(sid), "name": name, "icon": r.get("cover") or r.get("stream_icon") or "",
                        "cats": _cats_of(r), "rating": str(r.get("rating") or ""),
                        "plot": str(r.get("plot") or ""), "added": to_int(r.get("last_modified"), 0),
                        "k": search_key(name)})
    return out


def normalize_categories(raw: list[dict]) -> list[dict]:
    return [{"id": str(c.get("category_id")), "name": str(c.get("category_name") or "Adsız")}
            for c in raw if c.get("category_id") is not None]


class Library(QObject):
    loaded = Signal(str, object, object, bool)     # mode, categories, items, fresh
    failed = Signal(str, str)                      # mode, mesaj
    progress = Signal(str, str)                    # mode, mesaj
    epg_ready = Signal()

    def __init__(self, client: XtreamClient, profile_id: str):
        super().__init__()
        self.client = client
        self.profile_id = profile_id
        self.cache = DiskCache(cache_dir(), profile_id)
        self.epg = EpgStore()
        self.data: dict[str, tuple[list, list]] = {}
        self._loading: set[str] = set()
        self._epg_loading = False

    # ------------------------------------------------------------------ katalog
    def load(self, mode: str, force: bool = False) -> None:
        cats, cage = self.cache.get(f"{mode}:cats")
        items, iage = self.cache.get(f"{mode}:items")
        if cats is not None and items is not None and not force:
            self.data[mode] = (cats, items)
            self.loaded.emit(mode, cats, items, False)
            if max(cage or 0, iage or 0) < REFRESH_AFTER:
                return
            log.info("%s önbelleği %.0f dk eski, arkada tazeleniyor", mode, (iage or 0) / 60)
        if mode in self._loading:
            return
        self._loading.add(mode)
        if mode not in self.data:
            self.progress.emit(mode, "Liste indiriliyor…")
        run_async(self._fetch, mode,
                  on_done=lambda res, m=mode: self._fetched(m, res),
                  on_error=lambda msg, m=mode: self._fetch_failed(m, msg))

    def _fetch(self, mode: str):
        c = self.client
        t0 = time.monotonic()
        raw_cats = {"live": c.live_categories, "vod": c.vod_categories, "series": c.series_categories}[mode]()
        cats = normalize_categories(raw_cats)
        getter = {"live": c.live_streams, "vod": c.vod_streams, "series": c.series}[mode]
        try:
            raw = getter()
        except XtreamError as e:
            # Büyük listelerde bazı sunucular tümünü tek seferde veremez → kategori kategori dene
            log.warning("%s tam liste alınamadı (%s), kategori bazlı deneniyor", mode, e)
            raw = []
            for i, cat in enumerate(cats):
                post(self.progress.emit, mode, f"Kategori {i + 1}/{len(cats)}: {cat['name']}")
                try:
                    part = getter(category_id=cat["id"])
                except XtreamError as e2:
                    log.warning("Kategori %s alınamadı: %s", cat["id"], e2)
                    continue
                for r in part:
                    if r.get("category_id") is None:
                        r["category_id"] = cat["id"]
                raw.extend(part)
            if not raw:
                raise
        items = normalize_items(mode, raw)
        self.cache.set(f"{mode}:cats", cats)
        self.cache.set(f"{mode}:items", items)
        log.info("%s: %d kategori, %d öğe (%.1fs)", mode, len(cats), len(items), time.monotonic() - t0)
        return cats, items

    def _fetched(self, mode, res):
        self._loading.discard(mode)
        cats, items = res
        self.data[mode] = (cats, items)
        self.loaded.emit(mode, cats, items, True)

    def _fetch_failed(self, mode, msg):
        self._loading.discard(mode)
        if mode in self.data:
            self.progress.emit(mode, f"Güncellenemedi, önbellekteki liste gösteriliyor ({msg})")
        else:
            self.failed.emit(mode, msg)

    def items(self, mode: str) -> list[dict]:
        return self.data.get(mode, ([], []))[1]

    def clear_cache(self) -> None:
        self.cache.clear()

    # ------------------------------------------------------------------ EPG
    def load_full_epg(self, force: bool = False) -> None:
        if self._epg_loading:
            return
        live = self.items("live")
        wanted = {i["epg"].lower() for i in live if i.get("epg")}
        if not wanted:
            return
        self._epg_loading = True
        run_async(self._xmltv_job, wanted, force, pool_name="epg",
                  on_done=self._xmltv_done, on_error=self._xmltv_failed)

    def _xmltv_job(self, wanted: set, force: bool):
        path = cache_dir() / f"xmltv_{self.profile_id}.xml"
        fresh = path.exists() and time.time() - path.stat().st_mtime < XMLTV_MAX_AGE and path.stat().st_size > 100
        if force or not fresh:
            self._download_xmltv(path)
        return parse_xmltv_file(path, wanted=wanted)

    def _download_xmltv(self, path: Path) -> None:
        tmp = path.with_suffix(".part")
        t0 = time.monotonic()
        try:
            with self.client.session.get(self.client.xmltv_url(), stream=True, timeout=(10, 120)) as r:
                if r.status_code != 200:
                    raise XtreamError(f"XMLTV indirilemedi (HTTP {r.status_code})")
                total = 0
                with open(tmp, "wb") as f:
                    for chunk in r.iter_content(256 * 1024):
                        f.write(chunk)
                        total += len(chunk)
                        if total > XMLTV_MAX_BYTES:
                            raise XtreamError("XMLTV dosyası çok büyük, atlandı")
            if total < 100:
                raise XtreamError("XMLTV boş döndü")
            os.replace(tmp, path)
            log.info("XMLTV indirildi: %.1f MB (%.1fs)", total / 1e6, time.monotonic() - t0)
        except requests.RequestException as e:
            raise XtreamError(f"XMLTV indirilemedi: {e.__class__.__name__}") from e
        finally:
            if tmp.exists():
                try:
                    tmp.unlink()
                except OSError:
                    pass

    def _xmltv_done(self, data):
        self._epg_loading = False
        self.epg.load_full(data)
        self.epg_ready.emit()

    def _xmltv_failed(self, msg):
        self._epg_loading = False
        log.warning("Tam EPG yüklenemedi: %s", msg)
