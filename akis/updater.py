"""Otomatik güncelleme: GitHub'daki son sürümü kontrol eder, kurulum dosyasını indirir ve sessizce kurar.

Akış:
  1. ``check()`` → GitHub Releases API'den son sürümü okur (anahtar gerektirmez, repo herkese açık).
  2. Yeni sürüm varsa arayüz kullanıcıya sorar.
  3. ``download()`` → ``AkisIPTV-Setup-X.Y.Z.exe`` geçici klasöre iner (ilerleme bildirir).
  4. ``install()`` → kurulum /SILENT kipinde başlar, uygulama kapanır; kurulum bitince Akış yeniden açılır
     (installer/akis.iss içindeki /AKISUPDATE=1 satırı).
"""
from __future__ import annotations

import logging
import os
import re
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from typing import Callable

import requests

from . import __version__

log = logging.getLogger(__name__)

REPO = "mertkahramanukten/AkisIPTV"
API = f"https://api.github.com/repos/{REPO}/releases/latest"
RELEASES_PAGE = f"https://github.com/{REPO}/releases/latest"


def parse_version(v: str) -> tuple[int, ...]:
    """'v1.2.10' → (1, 2, 10). Sayı olmayan kısımlar yok sayılır."""
    nums = re.findall(r"\d+", v or "")
    return tuple(int(n) for n in nums[:4]) or (0,)


def is_newer(remote: str, local: str = __version__) -> bool:
    a, b = parse_version(remote), parse_version(local)
    n = max(len(a), len(b))
    return a + (0,) * (n - len(a)) > b + (0,) * (n - len(b))


@dataclass
class Release:
    version: str          # "1.2.0"
    notes: str            # sürüm notları (GitHub'daki açıklama)
    asset_url: str | None # Setup.exe indirme adresi (yoksa None → sayfaya yönlendir)
    asset_name: str
    size: int
    page: str


def check(timeout: float = 10.0) -> Release | None:
    """Daha yeni bir sürüm varsa döndürür; yoksa ya da ağ hatasında None."""
    try:
        r = requests.get(API, timeout=timeout,
                         headers={"Accept": "application/vnd.github+json", "User-Agent": f"AkisIPTV/{__version__}"})
        if r.status_code != 200:
            log.info("Güncelleme kontrolü: HTTP %s", r.status_code)
            return None
        d = r.json()
    except Exception as e:  # çevrimdışı vb. — sessizce geç
        log.info("Güncelleme kontrolü yapılamadı: %s", e)
        return None
    if d.get("draft") or d.get("prerelease"):
        return None
    tag = str(d.get("tag_name") or "")
    if not is_newer(tag):
        return None
    asset = next((a for a in d.get("assets") or []
                  if str(a.get("name", "")).lower().endswith(".exe") and "setup" in str(a.get("name", "")).lower()),
                 None)
    ver = ".".join(str(x) for x in parse_version(tag))
    return Release(
        version=ver,
        notes=str(d.get("body") or "").strip(),
        asset_url=asset.get("browser_download_url") if asset else None,
        asset_name=str(asset.get("name")) if asset else "",
        size=int(asset.get("size") or 0) if asset else 0,
        page=str(d.get("html_url") or RELEASES_PAGE),
    )


def can_self_install() -> bool:
    """Yalnızca kurulmuş .exe sürümü kendini güncelleyebilir (geliştirme ortamında Python'dan çalışırken değil)."""
    return bool(getattr(sys, "frozen", False)) and sys.platform == "win32"


def download(rel: Release, progress: Callable[[int, int], bool] | None = None) -> str:
    """Kurulum dosyasını indirir; yolunu döndürür. ``progress(alınan, toplam)`` False dönerse iptal edilir."""
    if not rel.asset_url:
        raise RuntimeError("Bu sürümde kurulum dosyası yok.")
    dest = os.path.join(tempfile.gettempdir(), rel.asset_name or f"AkisIPTV-Setup-{rel.version}.exe")
    part = dest + ".part"
    with requests.get(rel.asset_url, stream=True, timeout=30,
                      headers={"User-Agent": f"AkisIPTV/{__version__}"}) as r:
        r.raise_for_status()
        total = int(r.headers.get("Content-Length") or rel.size or 0)
        got = 0
        with open(part, "wb") as f:
            for chunk in r.iter_content(chunk_size=256 * 1024):
                if not chunk:
                    continue
                f.write(chunk)
                got += len(chunk)
                if progress and progress(got, total) is False:
                    raise InterruptedError("İndirme iptal edildi.")
    if total and os.path.getsize(part) != total:
        raise RuntimeError("İndirme yarım kaldı; tekrar dene.")
    os.replace(part, dest)
    return dest


def install(path: str) -> None:
    """Kurulumu sessiz kipte başlatır. Çağıran taraf hemen ardından uygulamayı kapatmalı."""
    args = [path, "/SILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/CLOSEAPPLICATIONS", "/AKISUPDATE=1"]
    flags = 0
    if sys.platform == "win32":
        flags = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP  # type: ignore[attr-defined]
    subprocess.Popen(args, close_fds=True, creationflags=flags)
