"""Tek dosyalık Windows kurulum sihirbazı üretir: dist/AkisIPTV-Setup-<sürüm>.exe

Adımlar:
  1) bin/libmpv-2.dll yoksa indirir (tools/get_libmpv.py)
  2) PyInstaller ile uygulamayı paketler → dist/AkisIPTV/  (Python gerektirmez)
  3) Inno Setup derleyicisini (ISCC) bulur; yoksa taşınabilir halini build/ altına indirir
     (kurulum yapmaz). O da olmazsa yalnızca bu kullanıcıya sessizce kurar
  4) installer/akis.iss ile Türkçe kurulum sihirbazını derler

Hem yerelde (build_installer.bat) hem GitHub Actions'ta aynı betik kullanılır.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DIST = ROOT / "dist"
BUILD = ROOT / "build"
INNO_URL = "https://jrsoftware.org/download.php/is.exe"


def step(msg: str) -> None:
    print(f"\n=== {msg} ===", flush=True)


def version() -> str:
    text = (ROOT / "akis" / "__init__.py").read_text(encoding="utf-8")
    m = re.search(r'__version__\s*=\s*"([^"]+)"', text)
    return m.group(1) if m else "0.0.0"


def run(cmd: list[str], **kw) -> None:
    print("> " + " ".join(f'"{c}"' if " " in c else c for c in cmd), flush=True)
    subprocess.run(cmd, check=True, **kw)


# --------------------------------------------------------------------------- 1) libmpv
def ensure_libmpv() -> Path:
    dll = ROOT / "bin" / "libmpv-2.dll"
    if not dll.exists():
        step("libmpv indiriliyor")
        run([sys.executable, str(ROOT / "tools" / "get_libmpv.py")])
    if not dll.exists():
        sys.exit("libmpv-2.dll bulunamadı; bin/ klasörüne elle koyup tekrar dene.")
    return dll


# --------------------------------------------------------------------------- 2) PyInstaller
def write_version_file(ver: str) -> Path:
    nums = [int(x) for x in re.findall(r"\d+", ver)[:3]] + [0, 0, 0]
    t = tuple(nums[:3] + [0])
    BUILD.mkdir(exist_ok=True)
    p = BUILD / "version_info.txt"
    p.write_text(f"""# UTF-8
VSVersionInfo(
  ffi=FixedFileInfo(filevers={t}, prodvers={t}, mask=0x3f, flags=0x0, OS=0x40004,
                    fileType=0x1, subtype=0x0, date=(0, 0)),
  kids=[
    StringFileInfo([StringTable('041F04B0', [
      StringStruct('CompanyName', 'Mert Kahraman Ükten'),
      StringStruct('FileDescription', 'Akış IPTV'),
      StringStruct('FileVersion', '{ver}'),
      StringStruct('InternalName', 'AkisIPTV'),
      StringStruct('OriginalFilename', 'AkisIPTV.exe'),
      StringStruct('ProductName', 'Akış IPTV'),
      StringStruct('ProductVersion', '{ver}')])]),
    VarFileInfo([VarStruct('Translation', [0x041F, 1200])])
  ]
)
""", encoding="utf-8")
    return p


def stop_running_build(out: Path) -> None:
    """dist\\AkisIPTV içinden açılmış eski bir kopya çalışıyorsa dosyaları kilitler; onu kapatır."""
    if os.name != "nt" or not out.exists():
        return
    prefix = str(out).replace("'", "''") + "\\"
    ps = ("Get-Process -ErrorAction SilentlyContinue | Where-Object { $_.Path -and $_.Path.StartsWith("
          f"'{prefix}', [System.StringComparison]::OrdinalIgnoreCase) }} | "
          "ForEach-Object { $_.Id; Stop-Process -Id $_.Id -Force }")
    r = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", ps],
                       capture_output=True, text=True, check=False)
    ids = r.stdout.split()
    if ids:
        print(f"dist klasöründen çalışan eski Akış IPTV kapatıldı (PID {', '.join(ids)})")
        time.sleep(1.5)


def remove_tree(path: Path) -> None:
    for attempt in range(5):
        try:
            shutil.rmtree(path)
            return
        except FileNotFoundError:
            return
        except PermissionError as e:
            if attempt == 4:
                sys.exit(f"{path} silinemedi ({e}).\nAkış IPTV ya da bu klasörde açık bir pencere varsa kapatıp tekrar dene.")
            time.sleep(1.5)


def pyinstaller(ver: str, dll: Path) -> Path:
    step("Uygulama paketleniyor (PyInstaller)")
    try:
        import PyInstaller  # noqa: F401
    except ImportError:
        run([sys.executable, "-m", "pip", "install", "--disable-pip-version-check", "-q", "pyinstaller"])
    out = DIST / "AkisIPTV"
    stop_running_build(out)
    remove_tree(out)
    sep = os.pathsep
    cmd = [
        sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--windowed",
        "--name", "AkisIPTV",
        "--icon", str(ROOT / "assets" / "icon.ico"),
        "--version-file", str(write_version_file(ver)),
        "--add-data", f"{ROOT / 'assets'}{sep}assets",
        "--add-binary", f"{dll}{sep}.",
        "--distpath", str(DIST), "--workpath", str(BUILD / "pyi"), "--specpath", str(BUILD),
        # uygulamanın kullanmadığı ağır modülleri dışarıda bırak
        "--exclude-module", "tkinter", "--exclude-module", "tests", "--exclude-module", "pytest",
        "--exclude-module", "PySide6.QtWebEngineCore", "--exclude-module", "PySide6.QtWebEngineWidgets",
        "--exclude-module", "PySide6.QtQml", "--exclude-module", "PySide6.QtQuick",
        "--exclude-module", "PySide6.QtPdf", "--exclude-module", "PySide6.Qt3DCore",
        str(ROOT / "run_akis.py"),
    ]
    run(cmd, cwd=str(ROOT))
    exe = out / "AkisIPTV.exe"
    if not exe.exists():
        sys.exit("PyInstaller çıktısı bulunamadı: " + str(exe))
    size = sum(f.stat().st_size for f in out.rglob("*") if f.is_file()) / 1e6
    print(f"Paket hazır: {out} ({size:.0f} MB)")
    return out


# --------------------------------------------------------------------------- 3) Inno Setup
INNO_NUGET = "https://www.nuget.org/api/v2/package/Tools.InnoSetup/6.7.3"
PORTABLE_INNO = BUILD / "innosetup"


def find_iscc() -> str | None:
    cands = [shutil.which("iscc"), shutil.which("ISCC")]
    if PORTABLE_INNO.exists():
        cands += [str(p) for p in PORTABLE_INNO.rglob("ISCC.exe")]
    for env in ("LOCALAPPDATA", "ProgramFiles(x86)", "ProgramFiles"):
        base = os.environ.get(env)
        if not base:
            continue
        if env == "LOCALAPPDATA":
            base = os.path.join(base, "Programs")
        for name in ("Inno Setup 6", "Inno Setup 7"):
            cands.append(os.path.join(base, name, "ISCC.exe"))
    for c in cands:
        if c and os.path.isfile(c):
            return c
    return None


def _download(url: str, dest: Path) -> None:
    req = urllib.request.Request(url, headers={"User-Agent": "AkisIPTV-build"})
    with urllib.request.urlopen(req, timeout=180) as r, open(dest, "wb") as f:
        shutil.copyfileobj(r, f)
    print(f"İndirildi: {dest.name} ({dest.stat().st_size / 1e6:.1f} MB)")


def get_portable_inno() -> None:
    """Inno Setup derleyicisini kurulum yapmadan, NuGet paketinden (zip) build/ altına açar."""
    import zipfile
    step("Inno Setup derleyicisi indiriliyor (taşınabilir, kurulum yapılmaz)")
    BUILD.mkdir(exist_ok=True)
    pkg = BUILD / "innosetup.nupkg"
    _download(INNO_NUGET, pkg)
    if PORTABLE_INNO.exists():
        shutil.rmtree(PORTABLE_INNO, ignore_errors=True)
    with zipfile.ZipFile(pkg) as z:
        z.extractall(PORTABLE_INNO)


def install_inno() -> None:
    step("Inno Setup kuruluyor (yalnızca bu kullanıcıya, yönetici izni gerekmez)")
    BUILD.mkdir(exist_ok=True)
    exe = BUILD / "innosetup-installer.exe"
    _download(INNO_URL, exe)
    for attempt in range(3):
        try:
            run([str(exe), "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/SP-", "/CURRENTUSER"])
            return
        except (OSError, subprocess.CalledProcessError) as e:
            print(f"  kurulum başlatılamadı ({e}); tekrar deneniyor…")
            time.sleep(3)


def ensure_iscc() -> str | None:
    iscc = find_iscc()
    if iscc:
        return iscc
    for fn in (get_portable_inno, install_inno):
        try:
            fn()
        except Exception as e:
            print(f"  başarısız: {e}")
        iscc = find_iscc()
        if iscc:
            return iscc
    if shutil.which("winget"):
        print("winget deneniyor…")
        subprocess.run(["winget", "install", "--id", "JRSoftware.InnoSetup", "-e", "--silent",
                        "--accept-package-agreements", "--accept-source-agreements"], check=False)
    return find_iscc()


def compile_installer(ver: str) -> Path:
    iscc = ensure_iscc()
    if not iscc:
        sys.exit("Inno Setup (ISCC.exe) bulunamadı. https://jrsoftware.org/isdl.php adresinden kurup tekrar dene.")
    step("Kurulum sihirbazı derleniyor (Inno Setup)")
    print("ISCC:", iscc)
    run([iscc, f"/DMyAppVersion={ver}", "/Qp", str(ROOT / "installer" / "akis.iss")])
    setup = DIST / f"AkisIPTV-Setup-{ver}.exe"
    if not setup.exists():
        sys.exit("Kurulum dosyası üretilemedi.")
    return setup


def main() -> int:
    if os.name != "nt":
        sys.exit("Kurulum dosyası yalnızca Windows'ta derlenebilir.")
    ver = version()
    print(f"Akış IPTV {ver} kurulum dosyası hazırlanıyor…")
    dll = ensure_libmpv()
    pyinstaller(ver, dll)
    setup = compile_installer(ver)
    print(f"\nHAZIR: {setup}  ({setup.stat().st_size / 1e6:.0f} MB)")
    print("Bu tek dosyayı diğer bilgisayara kopyalayıp çift tıklaman yeterli.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
