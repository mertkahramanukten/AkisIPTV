"""Logo/afiş yükleyici: disk + bellek önbelleği, sınırlı eşzamanlılık, kırık adres hafızası."""
from __future__ import annotations

import hashlib
import logging
from collections import OrderedDict
from urllib.parse import urljoin

import requests
from requests.adapters import HTTPAdapter
from PySide6.QtCore import QObject, QSize, Qt, Signal
from PySide6.QtGui import QImage, QPixmap

from .config import image_cache_dir
from .workers import run_async

log = logging.getLogger(__name__)


class ImageLoader(QObject):
    loaded = Signal(str)       # url

    def __init__(self, user_agent: str, base: str = "", max_items: int = 1500):
        super().__init__()
        self.base = base.rstrip("/") + "/"
        self.dir = image_cache_dir()
        self.mem: OrderedDict[tuple, QPixmap] = OrderedDict()
        self.max_items = max_items
        self.pending: set[tuple] = set()
        self.failed: set[str] = set()
        self.session = requests.Session()
        self.session.headers["User-Agent"] = user_agent
        adapter = HTTPAdapter(pool_connections=6, pool_maxsize=12, max_retries=1)
        self.session.mount("http://", adapter)
        self.session.mount("https://", adapter)

    def resolve(self, url: str) -> str:
        url = (url or "").strip()
        if not url:
            return ""
        if url.startswith("//"):
            return "http:" + url
        if not url.lower().startswith(("http://", "https://")):
            return urljoin(self.base, url.lstrip("/"))
        return url

    def get(self, url: str, size: QSize) -> QPixmap | None:
        """Bellekte varsa hemen döner; yoksa arka planda yüklemeyi başlatır ve None döner."""
        url = self.resolve(url)
        if not url or url in self.failed:
            return None
        key = (url, size.width(), size.height())
        pm = self.mem.get(key)
        if pm is not None:
            self.mem.move_to_end(key)
            return pm
        if key not in self.pending:
            self.pending.add(key)
            run_async(self._load, url, size.width(), size.height(), pool_name="img",
                      on_done=lambda img, k=key: self._done(k, img),
                      on_error=lambda _msg, k=key: self._done(k, None))
        return None

    # ---- worker thread
    def _load(self, url: str, w: int, h: int) -> QImage | None:
        p = self.dir / (hashlib.sha1(url.encode()).hexdigest()[:20] + ".img")
        try:
            if p.exists() and p.stat().st_size > 0:
                data = p.read_bytes()
            else:
                r = self.session.get(url, timeout=(5, 10))
                if r.status_code != 200 or not r.content or len(r.content) > 6_000_000:
                    return None
                data = r.content
                try:
                    p.write_bytes(data)
                except OSError:
                    pass
        except Exception as e:
            log.debug("Görsel indirilemedi %s: %s", url, e)
            return None
        img = QImage()
        if not img.loadFromData(data):
            try:
                p.unlink()
            except OSError:
                pass
            return None
        return img.scaled(w, h, Qt.KeepAspectRatio, Qt.SmoothTransformation)

    # ---- GUI thread
    def _done(self, key, img: QImage | None):
        self.pending.discard(key)
        if img is None or img.isNull():
            self.failed.add(key[0])
            return
        self.mem[key] = QPixmap.fromImage(img)
        while len(self.mem) > self.max_items:
            self.mem.popitem(last=False)
        self.loaded.emit(key[0])
