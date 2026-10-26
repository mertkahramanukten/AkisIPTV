"""libmpv-2.dll'i indirip proje içindeki bin/ klasörüne koyar.

Sırayla dener:
  1) shinchiro/mpv-winbuild-cmake (resmi önerilen Windows derlemesi) .7z → py7zr / 7-Zip / tar ile açılır
  2) mpv.net taşınabilir .zip (içinde libmpv-2.dll var) → standart zipfile ile açılır
Hiçbiri olmazsa elle kurulum talimatı yazar.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BIN = ROOT / "bin"
HDR = {"User-Agent": "AkisIPTV-setup", "Accept": "application/vnd.github+json"}


def http_json(url: str):
    req = urllib.request.Request(url, headers=HDR)
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode("utf-8"))


def download(url: str, dest: Path) -> None:
    req = urllib.request.Request(url, headers={"User-Agent": HDR["User-Agent"]})
    with urllib.request.urlopen(req, timeout=60) as r, open(dest, "wb") as f:
        total = int(r.headers.get("Content-Length") or 0)
        done = 0
        while True:
            chunk = r.read(1 << 16)
            if not chunk:
                break
            f.write(chunk)
            done += len(chunk)
            if total:
                pct = done * 100 // total
                print(f"\r  indiriliyor: {done / 1e6:6.1f} / {total / 1e6:.1f} MB  (%{pct})", end="", flush=True)
    print()


def find_dll(folder: Path) -> Path | None:
    for name in ("libmpv-2.dll", "mpv-2.dll"):
        hits = list(folder.rglob(name))
        if hits:
            return hits[0]
    return None


def extract_7z(archive: Path, out: Path) -> bool:
    try:
        import py7zr  # noqa: WPS433
        with py7zr.SevenZipFile(archive, "r") as z:
            names = [n for n in z.getnames() if n.lower().endswith("libmpv-2.dll")]
            if names:
                z.extract(path=out, targets=names)
                if find_dll(out):
                    return True
    except Exception as e:  # BCJ2 gibi desteklenmeyen sıkıştırmalar
        print(f"  py7zr ile açılamadı: {e}")
    candidates = [shutil.which("7z"), r"C:\Program Files\7-Zip\7z.exe", r"C:\Program Files (x86)\7-Zip\7z.exe"]
    for exe in candidates:
        if exe and Path(exe).exists():
            print(f"  7-Zip deneniyor: {exe}")
            subprocess.run([exe, "e", str(archive), f"-o{out}", "libmpv-2.dll", "-r", "-y"],
                           stdout=subprocess.DEVNULL, check=False)
            if find_dll(out):
                return True
    if shutil.which("tar"):
        print("  Windows tar deneniyor…")
        subprocess.run(["tar", "-xf", str(archive), "-C", str(out)], stdout=subprocess.DEVNULL,
                       stderr=subprocess.DEVNULL, check=False)
        if find_dll(out):
            return True
    return False


def try_shinchiro(tmp: Path) -> Path | None:
    print("1) shinchiro/mpv-winbuild-cmake son sürümü aranıyor…")
    rel = http_json("https://api.github.com/repos/shinchiro/mpv-winbuild-cmake/releases/latest")
    assets = [a for a in rel.get("assets", [])
              if a["name"].startswith("mpv-dev-x86_64-") and "-v3-" not in a["name"] and a["name"].endswith(".7z")]
    if not assets:
        print("  uygun dosya bulunamadı")
        return None
    a = assets[0]
    print(f"  {a['name']}")
    arc = tmp / a["name"]
    download(a["browser_download_url"], arc)
    out = tmp / "x1"
    out.mkdir()
    return find_dll(out) if extract_7z(arc, out) else None


def try_mpvnet(tmp: Path) -> Path | None:
    print("2) mpv.net taşınabilir paketi aranıyor…")
    rel = http_json("https://api.github.com/repos/mpvnet-player/mpv.net/releases/latest")
    assets = [a for a in rel.get("assets", [])
              if a["name"].lower().endswith(".zip") and "portable" in a["name"].lower() and "x64" in a["name"].lower()]
    if not assets:
        print("  uygun dosya bulunamadı")
        return None
    a = assets[0]
    print(f"  {a['name']}")
    arc = tmp / a["name"]
    download(a["browser_download_url"], arc)
    out = tmp / "x2"
    with zipfile.ZipFile(arc) as z:
        for n in z.namelist():
            if n.lower().endswith("libmpv-2.dll"):
                z.extract(n, out)
    return find_dll(out) if out.exists() else None


def main() -> int:
    BIN.mkdir(exist_ok=True)
    target = BIN / "libmpv-2.dll"
    if target.exists() and "--force" not in sys.argv:
        print(f"libmpv zaten var: {target}")
        return 0
    # Windows'ta antivirüs indirilen arşivi bir süre kilitleyebilir → temizlik hatalarını yok say
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as td:
        tmp = Path(td)
        dll = None
        for fn in (try_shinchiro, try_mpvnet):
            try:
                dll = fn(tmp)
            except Exception as e:
                print(f"  başarısız: {e}")
                dll = None
            if dll:
                break
        if not dll:
            print("\nlibmpv otomatik indirilemedi. Elle kurulum:")
            print("  https://github.com/shinchiro/mpv-winbuild-cmake/releases adresinden")
            print("  'mpv-dev-x86_64-<tarih>.7z' indir, içindeki libmpv-2.dll dosyasını şuraya kopyala:")
            print(f"  {BIN}")
            return 1
        shutil.copy2(dll, target)
    size = os.path.getsize(target) / 1e6
    print(f"libmpv hazır: {target} ({size:.0f} MB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
