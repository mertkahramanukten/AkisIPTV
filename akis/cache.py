"""Disk önbelleği (gzip'li JSON).

"Önce önbellekten göster, arkada tazele" (stale-while-revalidate) stratejisi için:
uygulama açılır açılmaz son kanal listesi ekrandadır, güncel liste arkada iner.
"""
from __future__ import annotations

import gzip
import hashlib
import json
import logging
import os
import time
from pathlib import Path

log = logging.getLogger(__name__)


class DiskCache:
    def __init__(self, root: Path, namespace: str = ""):
        self.root = Path(root)
        self.namespace = namespace
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, key: str) -> Path:
        h = hashlib.sha1(f"{self.namespace}|{key}".encode()).hexdigest()[:24]
        return self.root / f"{h}.json.gz"

    def get(self, key: str, max_age: float | None = None):
        """(değer, yaş_saniye) döner; yoksa / çok eskiyse (None, None)."""
        p = self._path(key)
        try:
            with gzip.open(p, "rt", encoding="utf-8") as f:
                payload = json.load(f)
        except FileNotFoundError:
            return None, None
        except Exception as e:
            log.warning("Önbellek bozuk, siliniyor (%s): %s", key, e)
            try:
                p.unlink()
            except OSError:
                pass
            return None, None
        age = time.time() - float(payload.get("t", 0))
        if max_age is not None and age > max_age:
            return None, None
        return payload.get("v"), age

    def set(self, key: str, value) -> None:
        p = self._path(key)
        tmp = p.with_suffix(".tmp")
        try:
            with gzip.open(tmp, "wt", encoding="utf-8", compresslevel=4) as f:
                json.dump({"t": time.time(), "k": key, "v": value}, f, ensure_ascii=False)
            os.replace(tmp, p)
        except Exception as e:
            log.warning("Önbelleğe yazılamadı (%s): %s", key, e)

    def clear(self) -> int:
        n = 0
        for p in self.root.glob("*.json.gz"):
            try:
                p.unlink()
                n += 1
            except OSError:
                pass
        return n
