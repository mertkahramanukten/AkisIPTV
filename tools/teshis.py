"""Yayın açılmama (HTTP 401/403) teşhisi.

Uygulamada kayıtlı profilin bilgileriyle sağlayıcıya birkaç deneme isteği atar ve
proje klasörüne ``teshis_raporu.txt`` yazar. Rapora kullanıcı adı ve parola YAZILMAZ
(her yerde *** ile maskelenir).

Ne denenir?
  1) Hesap bilgisi (player_api.php): durum, bitiş, bağlantı limiti / aktif bağlantı, izinli formatlar
  2) Sağlayıcının kendi M3U listesindeki yayın adresi biçimi (bizim kurduğumuz adresle aynı mı?)
  3) Python ile doğrudan istek: TS / HLS × farklı oynatıcı kimlikleri (User-Agent), yönlendirmeler adım adım
  4) mpv ile gerçek açılış: normal (curl) ve ffmpeg'in kendi HTTP katmanıyla (lavf://)

Kullanım: teshis.bat  (ya da  .venv\\Scripts\\python tools\\teshis.py [sunucu-filtresi] [--kisa])
"""
from __future__ import annotations

import json
import os
import re
import sys
import time
import traceback
from pathlib import Path
from urllib.parse import quote, urlsplit

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import requests  # noqa: E402

from akis.config import decode_secret  # noqa: E402
from akis.xtream import XtreamClient, as_list  # noqa: E402

REPORT = ROOT / "teshis_raporu.txt"
OUT: list[str] = []
SECRETS: list[tuple[str, str]] = []

UAS = [
    ("VLC", "VLC/3.0.21 LibVLC/3.0.21"),
    ("okhttp", "okhttp/4.12.0"),
    ("Smarters", "IPTVSmartersPlayer"),
    ("Lavf", "Lavf/61.7.100"),
    ("Chrome", "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
               "Chrome/130.0 Safari/537.36"),
]


def mask(s) -> str:
    s = str(s)
    for secret, rep in SECRETS:
        if secret:
            s = s.replace(secret, rep)
    return s


def p(*parts) -> None:
    line = mask(" ".join(str(x) for x in parts))
    OUT.append(line)
    print(line, flush=True)


def section(title: str) -> None:
    p("")
    p("=" * 70)
    p(title)
    p("=" * 70)


def save() -> None:
    REPORT.write_text("\n".join(OUT) + "\n", encoding="utf-8")


# --------------------------------------------------------------------------- profil
def find_profile(filt: str | None):
    cands = []
    appdata = os.environ.get("APPDATA")
    if appdata:
        cands.append(Path(appdata) / "AkisIPTV" / "settings.json")
    cands.append(ROOT / "data" / "settings.json")
    for path in cands:
        if not path.exists():
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        profs = data.get("profiles") or []
        if filt:
            profs = [x for x in profs if filt.lower() in str(x.get("server", "")).lower()]
        else:
            last = data.get("last_profile")
            profs.sort(key=lambda x: x.get("id") != last)
            profs = [x for x in profs if "127.0.0.1" not in str(x.get("server", ""))] or profs
        for prof in profs:
            pw = decode_secret(prof.get("password", ""))
            if pw:
                store = (data.get("per_profile") or {}).get(prof.get("id"), {})
                return path, prof, pw, store
    return None


# --------------------------------------------------------------------------- python istekleri
def show_headers(r: requests.Response) -> str:
    keep = ("server", "content-type", "content-length", "location", "www-authenticate", "x-powered-by",
            "cf-ray", "via", "x-cache", "retry-after", "connection")
    parts = [f"{k}={v[:120]}" for k, v in r.headers.items() if k.lower() in keep]
    cookies = [c.split("=", 1)[0] for c in r.headers.get("set-cookie", "").split(",") if "=" in c]
    if cookies:
        parts.append("set-cookie(adlar)=" + ",".join(c.strip() for c in cookies[:5]))
    return "; ".join(parts)


def body_hint(r: requests.Response, ext: str) -> str:
    try:
        chunk = next(r.iter_content(2048), b"")
    except Exception as e:
        return f"(gövde okunamadı: {e.__class__.__name__})"
    if not chunk:
        return "(boş gövde)"
    if chunk[:1] == b"\x47":
        return f"MPEG-TS verisi geliyor ({len(chunk)} bayt okundu) ✓"
    text = chunk.decode("utf-8", "replace")
    if text.lstrip().startswith("#EXTM3U"):
        lines = [x for x in text.splitlines() if x.strip()][:6]
        return "HLS listesi ✓ | " + " | ".join(lines)
    text = re.sub(r"\s+", " ", text)[:300]
    return f"gövde: {text!r}"


def probe(url: str, ua: str | None, label: str, method: str = "GET", extra: dict | None = None) -> int | None:
    headers = {"Accept": "*/*", "Connection": "close"}
    if ua:
        headers["User-Agent"] = ua
    if extra:
        headers.update(extra)
    cur = url
    code = None
    for hop in range(6):
        try:
            r = requests.request(method, cur, headers=headers, allow_redirects=False, stream=True, timeout=(8, 10))
        except requests.RequestException as e:
            p(f"  [{label}] hop{hop}: BAĞLANTI HATASI {e.__class__.__name__}: {str(e)[:160]}")
            return None
        code = r.status_code
        host = urlsplit(cur).netloc
        p(f"  [{label}] hop{hop} {method} {host} → HTTP {code} {r.reason} | {show_headers(r)}")
        if code in (301, 302, 303, 307, 308) and r.headers.get("location"):
            loc = r.headers["location"]
            if loc.startswith("/"):
                sp = urlsplit(cur)
                loc = f"{sp.scheme}://{sp.netloc}{loc}"
            p(f"      → yönlendirme: {loc[:200]}")
            r.close()
            cur = loc
            continue
        if method != "HEAD":
            p("      " + body_hint(r, url.rsplit(".", 1)[-1]))
        r.close()
        break
    time.sleep(1.5)  # tek bağlantılı hesapta sunucu eski bağlantıyı düşürsün
    return code


# --------------------------------------------------------------------------- mpv
def load_mpv():
    for d in (ROOT / "bin", ROOT):
        if (d / "libmpv-2.dll").exists():
            os.environ["PATH"] = str(d) + os.pathsep + os.environ.get("PATH", "")
            if hasattr(os, "add_dll_directory"):
                os.add_dll_directory(str(d))
            break
    import mpv  # noqa: WPS433
    return mpv


KEEP_RE = re.compile(r"http|curl|header|location|redirect|opening|failed|error|40\d|50\d|content-|range|"
                     r"user-agent|stream|protocol|lavf|ffmpeg|tcp|connect", re.I)


def mpv_probe(mpvmod, url: str, ua: str, label: str, seconds: float = 14.0) -> bool:
    lines: list[str] = []

    def lh(level, comp, msg):
        lines.append(f"[{level}] {comp}: {msg.rstrip()}")

    m = mpvmod.MPV(vo="null", ao="null", ytdl=False, load_scripts=False, idle="yes", log_handler=lh,
                   loglevel="debug", user_agent=ua, network_timeout=10, cache="yes",
                   demuxer_lavf_analyzeduration=1.5,
                   stream_lavf_o="reconnect=1,reconnect_streamed=1,reconnect_on_network_error=1,"
                                 "reconnect_delay_max=4")
    ok = False
    try:
        try:
            p(f"  [{label}] mpv sürümü: {m.mpv_version}")
        except Exception:
            pass
        m.play(url)
        t0 = time.time()
        while time.time() - t0 < seconds:
            time.sleep(0.5)
            try:
                pt = m.playback_time
            except Exception:
                pt = None
            if pt is not None and pt > 0.5:
                ok = True
                break
            if time.time() - t0 > 3 and any("Failed to open" in x or "HTTP error" in x for x in lines):
                break
    finally:
        try:
            m.terminate()
        except Exception:
            pass
    p(f"  [{label}] SONUÇ: {'OYNADI ✓' if ok else 'açılmadı ✗'}")
    rel = [x for x in lines if KEEP_RE.search(x) and "[trace]" not in x]
    for x in rel[:70]:
        p("      " + x[:260])
    if len(rel) > 70:
        p(f"      … (+{len(rel) - 70} satır)")
    time.sleep(2)
    return ok


# --------------------------------------------------------------------------- ana akış
def main() -> int:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    filt = args[0] if args else None
    p(f"Akış IPTV yayın teşhisi — {time.strftime('%Y-%m-%d %H:%M:%S')}")
    found = find_profile(filt)
    if not found:
        p("Kayıtlı ve parolası okunabilen bir profil bulunamadı. Uygulamada 'Beni hatırla' ile bir kez giriş yap.")
        return 1
    path, prof, pw, store = found
    user = prof.get("username", "")
    SECRETS.extend([(pw, "***"), (quote(pw, safe=""), "***"), (quote(pw), "***"),
                    (user, "<kullanici>"), (quote(user, safe=""), "<kullanici>")])
    server = prof.get("server", "")
    p(f"Profil: {prof.get('name')} | sunucu: {server} | ayar dosyası: {path}")

    c = XtreamClient(server, user, pw, user_agent=UAS[0][1])

    section("1) Hesap bilgisi (player_api.php)")
    acc = c.authenticate()
    ui = acc.raw.get("user_info") or {}
    # sunucunun kayıtlı hali de maskelensin (yazılandan farklı olabilir)
    for v, rep in ((str(ui.get("password") or ""), "***"), (c.password, "***"), (c.username, "<kullanici>"),
                   (str(ui.get("username") or ""), "<kullanici>")):
        if v.strip():
            SECRETS.extend([(v, rep), (quote(v, safe=""), rep), (quote(v), rep)])
    for key, mine in (("username", user), ("password", pw)):
        srv = ui.get(key)
        if not isinstance(srv, str) or not srv:
            rel = "sunucu bildirmiyor"
        elif srv == mine:
            rel = "yazılanla birebir aynı ✓"
        elif srv.strip().casefold() == mine.strip().casefold():
            rel = "SADECE büyük/küçük harf ya da boşluk farkı var ✗ (yayınlar 401 verir)"
        else:
            rel = "yazılandan tamamen farklı ✗"
        p(f"  user_info.{key} (sunucudaki kayıt) → {rel}")
    if acc.cred_note:
        p(f"  uygulama: {acc.cred_note}")
    si = acc.raw.get("server_info") or {}
    for k in ("auth", "status", "exp_date", "is_trial", "active_cons", "max_connections",
              "allowed_output_formats", "created_at"):
        p(f"  user_info.{k} = {ui.get(k)!r}")
    for k in ("url", "port", "https_port", "server_protocol", "rtmp_port", "timezone", "time_now", "xui",
              "version", "revision"):
        if k in si:
            p(f"  server_info.{k} = {si.get(k)!r}")
    if acc.exp_date:
        p(f"  bitiş: {time.strftime('%d.%m.%Y %H:%M', time.localtime(acc.exp_date))}")

    if "--kisa" in sys.argv:
        return 0

    section("2) Kanal seçimi")
    streams = [s for s in as_list(c.live_streams()) if s.get("stream_id")]
    p(f"  toplam canlı kanal: {len(streams)}")
    picked = []
    recent = [str(x) for x in (store.get("recent", {}) or {}).get("live", [])][:2]
    by_id = {str(s.get("stream_id")): s for s in streams}
    for sid in recent:
        if sid in by_id:
            picked.append(by_id[sid])
    for s in streams:
        name = str(s.get("name", ""))
        if len(picked) >= 3:
            break
        if s not in picked and not re.search(r"info|bilgi|önemli", name, re.I):
            picked.append(s)
    for s in picked:
        ds = s.get("direct_source") or ""
        p(f"  id={s.get('stream_id')} ad={s.get('name')!r} tür={s.get('stream_type')!r} "
          f"direct_source={'VAR: ' + ds[:120] if ds else 'yok'} custom_sid={s.get('custom_sid')!r}")
    if not picked:
        p("  kanal yok")
        return 1
    sid = picked[0]["stream_id"]

    section("3) Sağlayıcının kendi M3U listesindeki adres biçimi")
    m3u_urls = []
    for out in ("ts", "m3u8"):
        u = f"{c.base}/get.php?username={quote(user)}&password={quote(pw)}&type=m3u_plus&output={out}"
        try:
            r = requests.get(u, headers={"User-Agent": UAS[0][1]}, stream=True, timeout=(8, 20))
            p(f"  get.php output={out} → HTTP {r.status_code} | {show_headers(r)}")
            buf = b""
            for chunk in r.iter_content(16384):
                buf += chunk
                if len(buf) > 200_000:
                    break
            r.close()
            text = buf.decode("utf-8", "replace")
            urls = [x.strip() for x in text.splitlines() if x.strip().startswith("http")]
            for x in urls[:3]:
                p(f"    örnek: {x[:200]}")
            live = [x for x in urls if f"/{sid}." in x or x.rstrip("/").endswith(f"/{sid}")]
            if live:
                p(f"    seçilen kanalın listedeki adresi: {live[0][:200]}")
                m3u_urls.append(live[0])
            elif urls:
                m3u_urls.append(urls[0])
        except requests.RequestException as e:
            p(f"  get.php output={out} → HATA {e.__class__.__name__}: {str(e)[:160]}")
        time.sleep(1)
    p(f"  bizim kurduğumuz adres: {c.live_url(sid, 'ts')}")

    section(f"4) Python ile doğrudan istek (kanal id={sid})")
    results = {}
    for ext in ("ts", "m3u8"):
        url = c.live_url(sid, ext)
        for name, ua in UAS:
            results[(ext, name)] = probe(url, ua, f"{ext}/{name}")
    p("  -- ek denemeler --")
    probe(c.live_url(sid, "ts"), None, "ts/python-varsayılan-UA")
    probe(c.live_url(sid, "ts"), UAS[0][1], "ts/VLC + Range", extra={"Range": "bytes=0-", "Icy-MetaData": "1"})
    probe(c.live_url(sid, "ts"), UAS[0][1], "ts/VLC HEAD", method="HEAD")
    probe(f"{c.base}/{quote(user, safe='')}/{quote(pw, safe='')}/{sid}", UAS[0][1], "eski-biçim /u/p/id")
    host = urlsplit(c.base).hostname
    if si.get("url") and (str(si.get("url")) != host or str(si.get("port", "80")) != str(urlsplit(c.base).port or 80)):
        proto = si.get("server_protocol") or "http"
        alt = f"{proto}://{si.get('url')}:{si.get('port') or 80}"
        p(f"  server_info farklı bir yayın sunucusu gösteriyor: {alt}")
        probe(f"{alt}/live/{quote(user, safe='')}/{quote(pw, safe='')}/{sid}.ts", UAS[0][1], "server_info-adresi")
    for i, mu in enumerate(m3u_urls[:2]):
        probe(mu, UAS[0][1], f"M3U-adresi-{i + 1}")
    if len(picked) > 1:
        sid2 = picked[1]["stream_id"]
        probe(c.live_url(sid2, "ts"), UAS[0][1], f"2.kanal id={sid2} ts/VLC")
        probe(c.live_url(sid2, "m3u8"), UAS[0][1], f"2.kanal id={sid2} m3u8/VLC")
    save()

    section("5) mpv ile gerçek açılış denemesi")
    try:
        mpvmod = load_mpv()
    except Exception as e:
        p(f"  mpv yüklenemedi: {e}")
        return 0
    url_ts = c.live_url(sid, "ts")
    url_hls = c.live_url(sid, "m3u8")
    mpv_probe(mpvmod, url_ts, UAS[0][1], "mpv ts VLC (normal)")
    mpv_probe(mpvmod, "lavf://" + url_ts, UAS[0][1], "mpv ts VLC (ffmpeg http, lavf://)")
    mpv_probe(mpvmod, url_hls, UAS[0][1], "mpv m3u8 VLC (normal)")
    mpv_probe(mpvmod, "lavf://" + url_hls, UAS[0][1], "mpv m3u8 VLC (ffmpeg http, lavf://)")
    ok_ua = [n for (e, n), code in results.items() if code == 200 and n != "VLC"]
    if ok_ua:
        ua = dict(UAS)[ok_ua[0]]
        mpv_probe(mpvmod, url_ts, ua, f"mpv ts {ok_ua[0]} (normal)")
    return 0


if __name__ == "__main__":
    rc = 1
    try:
        rc = main()
    except Exception:
        p("BEKLENMEYEN HATA:")
        for line in traceback.format_exc().splitlines():
            p("  " + line)
    finally:
        save()
        print(f"\nRapor yazıldı: {REPORT}")
    sys.exit(rc)
