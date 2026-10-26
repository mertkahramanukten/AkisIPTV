"""Yollar, ayarlar ve parola saklama.

Kaynak koddan çalışırken tüm veriler proje içindeki ``data/`` klasöründe tutulur
(log okumak ve temizlemek kolay olsun diye). .exe olarak çalışırken
``%APPDATA%/AkisIPTV`` kullanılır.
"""
from __future__ import annotations

import base64
import copy
import hashlib
import json
import logging
import logging.handlers
import os
import sys
import threading
from pathlib import Path

from . import APP_ID

log = logging.getLogger(__name__)


# --------------------------------------------------------------------------- yollar
def project_root() -> Path:
    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
    return Path(__file__).resolve().parent.parent


def data_dir() -> Path:
    override = os.environ.get("AKIS_DATA_DIR")
    if override:
        p = Path(override)
    elif getattr(sys, "frozen", False):
        base = os.environ.get("APPDATA") or str(Path.home() / ".config")
        p = Path(base) / APP_ID
    else:
        p = project_root() / "data"
    p.mkdir(parents=True, exist_ok=True)
    return p


def cache_dir() -> Path:
    p = data_dir() / "cache"
    p.mkdir(parents=True, exist_ok=True)
    return p


def image_cache_dir() -> Path:
    p = data_dir() / "images"
    p.mkdir(parents=True, exist_ok=True)
    return p


def bin_dirs() -> list[Path]:
    """libmpv-2.dll'in aranacağı klasörler."""
    dirs = [project_root() / "bin", project_root()]
    if getattr(sys, "frozen", False):
        dirs.insert(0, Path(sys.executable).parent)
    return dirs


def setup_logging() -> Path:
    log_dir = data_dir() / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / "akis.log"
    fmt = logging.Formatter("%(asctime)s %(levelname)-7s %(name)s: %(message)s")
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    fh = logging.handlers.RotatingFileHandler(log_file, maxBytes=2_000_000, backupCount=2, encoding="utf-8")
    fh.setFormatter(fmt)
    root.addHandler(fh)
    if sys.stderr is not None:
        sh = logging.StreamHandler()
        sh.setFormatter(fmt)
        root.addHandler(sh)
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    return log_file


# --------------------------------------------------------------------------- parola
class _Secret:
    """Windows'ta DPAPI ile (kullanıcı hesabına bağlı) şifreler.

    Başka bir bilgisayara/kullanıcıya kopyalanan settings.json içindeki parolalar
    çözülemez. Windows dışında yalnızca base64 (gizleme değil!) kullanılır.
    """

    @staticmethod
    def _dpapi(data: bytes, protect: bool) -> bytes:
        import ctypes
        from ctypes import wintypes

        class DATA_BLOB(ctypes.Structure):
            _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]

        buf = ctypes.create_string_buffer(data, len(data))
        blob_in = DATA_BLOB(len(data), ctypes.cast(buf, ctypes.POINTER(ctypes.c_char)))
        blob_out = DATA_BLOB()
        crypt32 = ctypes.windll.crypt32
        kernel32 = ctypes.windll.kernel32
        fn = crypt32.CryptProtectData if protect else crypt32.CryptUnprotectData
        CRYPTPROTECT_UI_FORBIDDEN = 0x01
        ok = fn(ctypes.byref(blob_in), None, None, None, None, CRYPTPROTECT_UI_FORBIDDEN, ctypes.byref(blob_out))
        if not ok:
            raise ctypes.WinError()
        try:
            return ctypes.string_at(blob_out.pbData, blob_out.cbData)
        finally:
            kernel32.LocalFree(blob_out.pbData)

    @classmethod
    def encode(cls, plain: str) -> str:
        if not plain:
            return ""
        raw = plain.encode("utf-8")
        if os.name == "nt":
            try:
                return "dpapi:" + base64.b64encode(cls._dpapi(raw, True)).decode()
            except Exception as e:  # pragma: no cover - sadece Windows
                log.warning("DPAPI kullanılamadı: %s", e)
        return "b64:" + base64.b64encode(raw).decode()

    @classmethod
    def decode(cls, stored: str) -> str:
        if not stored:
            return ""
        try:
            if stored.startswith("dpapi:"):
                return cls._dpapi(base64.b64decode(stored[6:]), False).decode("utf-8")
            if stored.startswith("b64:"):
                return base64.b64decode(stored[4:]).decode("utf-8")
        except Exception as e:
            log.warning("Parola çözülemedi: %s", e)
            return ""
        return stored  # eski/düz metin


encode_secret = _Secret.encode
decode_secret = _Secret.decode


# --------------------------------------------------------------------------- ayarlar
USER_AGENTS = {
    "VLC (önerilen)": "VLC/3.0.21 LibVLC/3.0.21",
    "IPTV Smarters": "IPTVSmartersPlayer",
    "TiviMate": "TiviMate/5.1.6 (Android 12)",
    "Chrome": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36",
    "Kodi": "Kodi/21.1 (Windows NT 10.0.22631; Win64; x64) App_Bitness/64 Version/21.1",
}

DEFAULTS: dict = {
    "profiles": [],            # [{id, name, server, username, password(enc)}]
    "last_profile": None,
    "user_agent": USER_AGENTS["VLC (önerilen)"],
    "live_format": "auto",     # auto | ts | m3u8
    "buffer_profile": "dengeli",  # hizli | dengeli | saglam
    "adaptive_buffer": True,
    "hwdec": True,
    "full_epg": True,
    "show_stats": False,
    "volume": 80,
    "autoplay_last": False,
    "per_profile": {},         # profile_id -> {favorites, recent, resume, format_stats, last_channel}
    "window": {},
}

PROFILE_DEFAULTS: dict = {
    "favorites": {"live": [], "vod": [], "series": []},
    "recent": {"live": [], "vod": [], "series": []},
    "resume": {},              # "vod:123" / "ep:456" -> {"pos": s, "dur": s, "t": epoch}
    "format_stats": {"ts": 0, "m3u8": 0},
    "last_channel": None,
    "series_progress": {},     # series_id -> {"season": n, "ep": id, "t": epoch}
}


def profile_id(server: str, username: str) -> str:
    return hashlib.sha1(f"{server.strip().lower()}|{username.strip()}".encode()).hexdigest()[:12]


class Settings:
    """settings.json için küçük, thread-safe bir sarmalayıcı."""

    def __init__(self, path: Path | None = None):
        self.path = path or (data_dir() / "settings.json")
        self._lock = threading.RLock()
        self.data = copy.deepcopy(DEFAULTS)
        self.load()

    def load(self) -> None:
        if not self.path.exists():
            return
        try:
            loaded = json.loads(self.path.read_text(encoding="utf-8"))
            for k, v in loaded.items():
                self.data[k] = v
        except Exception as e:
            log.error("Ayarlar okunamadı, varsayılanlar kullanılacak: %s", e)

    def save(self) -> None:
        with self._lock:
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps(self.data, ensure_ascii=False, indent=2), encoding="utf-8")
            os.replace(tmp, self.path)

    def get(self, key, default=None):
        return self.data.get(key, DEFAULTS.get(key, default))

    def set(self, key, value, save: bool = True) -> None:
        with self._lock:
            self.data[key] = value
        if save:
            self.save()

    # ---- profiller
    def profiles(self) -> list[dict]:
        return list(self.data.get("profiles", []))

    def upsert_profile(self, name: str, server: str, username: str, password: str) -> dict:
        pid = profile_id(server, username)
        prof = {"id": pid, "name": name or username, "server": server, "username": username,
                "password": encode_secret(password)}
        with self._lock:
            profs = [p for p in self.data.get("profiles", []) if p.get("id") != pid]
            profs.insert(0, prof)
            self.data["profiles"] = profs
            self.data["last_profile"] = pid
        self.save()
        return prof

    def delete_profile(self, pid: str) -> None:
        with self._lock:
            self.data["profiles"] = [p for p in self.data.get("profiles", []) if p.get("id") != pid]
            self.data.get("per_profile", {}).pop(pid, None)
        self.save()

    def profile_store(self, pid: str) -> dict:
        """Profile özel kayıtlar (favori, devam et, vs.). Döndürülen dict doğrudan değiştirilebilir."""
        with self._lock:
            pp = self.data.setdefault("per_profile", {})
            store = pp.setdefault(pid, copy.deepcopy(PROFILE_DEFAULTS))
            for k, v in PROFILE_DEFAULTS.items():
                if k not in store:
                    store[k] = copy.deepcopy(v)
            return store
