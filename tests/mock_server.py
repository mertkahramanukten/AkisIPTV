"""Sahte Xtream Codes sunucusu — gerçek sağlayıcıya dokunmadan test için.

Sadece standart kütüphane kullanır.

    python tests/mock_server.py              # http://127.0.0.1:8899  kullanıcı: demo / parola: demo
    python tests/mock_server.py --channels 20000 --max-conn 1

"🧪 Test: Sorunlu Kanallar" kategorisi gerçek hayattaki sorunları taklit eder:
    9001  Kopan kanal        — 20 sn'de bir bağlantıyı koparır
    9002  Donan kanal        — 15 sn sonra veri göndermeyi bırakır (bağlantı açık kalır)
    9003  Yayın dışı         — 404
    9004  Yavaş açılan       — ilk byte 6 sn sonra gelir
    9005  Sadece HLS         — .ts 404 verir, .m3u8 çalışır
    9006  Kekeleyen          — yayın hızının altında veri gönderir (buffer erir)
"""
from __future__ import annotations

import argparse
import base64
import json
import math
import re
import threading
import time
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

FIX = Path(__file__).resolve().parent / "fixtures"
USER, PASS = "demo", "demo"
TS_DURATION = 60.0
HLS_SEG = 2.0

LIVE_CATS = ["Ulusal", "Spor", "Sinema", "Belgesel", "Haber", "Çocuk"]
SHOW_NAMES = ["Sabah Kuşağı", "Ana Haber", "Belgesel Kuşağı", "Maç Önü", "Canlı Maç", "Gece Sineması",
              "Çizgi Film", "Yemek Atölyesi", "Gündem Özel", "Müzik Kutusu", "Dizi Tekrarı", "Doğa Saati"]
SPECIAL = {
    9001: "⚠ Kopan Kanal (20 sn)",
    9002: "⚠ Donan Kanal (15 sn)",
    9003: "⚠ Yayın Dışı (404)",
    9004: "⚠ Yavaş Açılan (6 sn)",
    9005: "⚠ Sadece HLS (TS 404)",
    9006: "⚠ Kekeleyen Kanal",
}


class State:
    def __init__(self, n_channels: int, max_conn: int):
        self.max_conn = max_conn
        self.active = 0
        self.lock = threading.Lock()
        self.ts = (FIX / "live.ts").read_bytes()
        self.mp4 = (FIX / "movie.mp4").read_bytes()
        self.segments = sorted((FIX / "hls").glob("seg_*.ts"))
        self.seg_bytes = [p.read_bytes() for p in self.segments]
        self.epoch = time.time()
        self.live = []
        sid = 1
        for i in range(n_channels):
            cat = i % len(LIVE_CATS)
            self.live.append({
                "num": sid, "name": f"TR: {LIVE_CATS[cat]} {i // len(LIVE_CATS) + 1}" + (" HD" if i % 3 == 0 else ""),
                "stream_type": "live", "stream_id": sid, "stream_icon": f"/img/logo_{cat % 7}.png",
                "epg_channel_id": f"ch{sid}.tr", "added": "1700000000", "category_id": str(cat + 1),
                "custom_sid": "", "tv_archive": 0, "direct_source": "", "tv_archive_duration": 0,
            })
            sid += 1
        for k, name in SPECIAL.items():
            self.live.append({"num": k, "name": name, "stream_type": "live", "stream_id": k,
                              "stream_icon": "/img/logo_6.png", "epg_channel_id": f"ch{k}.tr",
                              "category_id": "99", "tv_archive": 0})
        self.vod = []
        vod_cats = ["Aksiyon", "Dram", "Bilim Kurgu"]
        names = ["Mavi Rota", "Gece Treni", "Son Sinyal", "Kuzey Işığı", "Sessiz Liman", "Kırmızı Vadi",
                 "Zaman Akışı", "Cam Şehir"]
        for i in range(36):
            self.vod.append({"num": i + 1, "name": f"{names[i % 8]} {i // 8 + 1 if i >= 8 else ''}".strip(),
                             "stream_type": "movie", "stream_id": 5000 + i,
                             "stream_icon": f"/img/poster_{i % 8}.png", "rating": str(5 + i % 5),
                             "added": str(1700000000 + i * 1000), "category_id": str(101 + i % 3),
                             "container_extension": "mp4"})
        self.vod_cats = [{"category_id": str(101 + i), "category_name": c, "parent_id": 0}
                         for i, c in enumerate(vod_cats)]
        self.series = []
        for i in range(10):
            self.series.append({"num": i + 1, "name": f"{names[i % 8]}: Dizi", "series_id": 7000 + i,
                                "cover": f"/img/poster_{(i + 3) % 8}.png", "plot": "Akış test dizisi.",
                                "rating": "8", "category_id": str(201 + i % 2), "last_modified": "1700000000"})

    def acquire(self) -> bool:
        with self.lock:
            if self.max_conn and self.active >= self.max_conn:
                return False
            self.active += 1
            return True

    def release(self) -> None:
        with self.lock:
            self.active = max(0, self.active - 1)


STATE: State | None = None


def b64(s: str) -> str:
    return base64.b64encode(s.encode()).decode()


def programs(stream_id: int, start: float, end: float):
    slot = 1800
    t = math.floor(start / slot) * slot
    while t < end:
        idx = (int(t // slot) + stream_id) % len(SHOW_NAMES)
        yield SHOW_NAMES[idx], t, t + slot
        t += slot


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "MockXtream/1.0"

    def log_message(self, fmt, *args):
        print("[mock] %s - %s" % (self.address_string(), fmt % args))

    # ---- yardımcılar
    def _send(self, code: int, body: bytes, ctype: str = "application/json", extra: dict | None = None):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _abs(self, item: dict, key: str) -> dict:
        v = item.get(key) or ""
        if v.startswith("/"):
            item = dict(item)
            item[key] = f"http://{self.headers.get('Host', '127.0.0.1')}{v}"
        return item

    def _json(self, obj):
        self._send(200, json.dumps(obj, ensure_ascii=False).encode("utf-8"))

    def do_HEAD(self):
        self.do_GET()

    def do_GET(self):
        u = urlparse(self.path)
        q = {k: v[0] for k, v in parse_qs(u.query).items()}
        path = u.path
        try:
            if path == "/player_api.php":
                return self.api(q)
            if path == "/xmltv.php":
                return self.xmltv(q)
            if path.startswith("/img/"):
                f = FIX / "img" / Path(path).name
                if f.exists():
                    return self._send(200, f.read_bytes(), "image/png", {"Cache-Control": "max-age=86400"})
                return self._send(404, b"", "text/plain")
            m = re.match(r"^/live/([^/]+)/([^/]+)/(\d+)\.(ts|m3u8)$", path)
            if m:
                if (m.group(1), m.group(2)) != (USER, PASS):
                    return self._send(401, b"unauthorized", "text/plain")
                return self.live(int(m.group(3)), m.group(4))
            m = re.match(r"^/hls/(\d+)/(\d+)\.ts$", path)
            if m:
                return self.hls_segment(int(m.group(1)), int(m.group(2)))
            m = re.match(r"^/(movie|series)/([^/]+)/([^/]+)/(\d+)\.(\w+)$", path)
            if m:
                if (m.group(2), m.group(3)) != (USER, PASS):
                    return self._send(401, b"unauthorized", "text/plain")
                return self.vod_file()
            self._send(404, b"not found", "text/plain")
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            pass

    # ---- API
    def api(self, q):
        st = STATE
        if q.get("username") != USER or q.get("password") != PASS:
            return self._json({"user_info": {"auth": 0}})
        action = q.get("action")
        cat = q.get("category_id")
        if not action:
            return self._json({
                "user_info": {"username": USER, "password": PASS, "auth": 1, "status": "Active",
                              "exp_date": str(int(time.time()) + 86400 * 90), "is_trial": "0",
                              "active_cons": str(st.active), "created_at": "1700000000",
                              "max_connections": str(st.max_conn or 1),
                              "allowed_output_formats": ["m3u8", "ts", "rtmp"]},
                "server_info": {"url": "127.0.0.1", "port": "8899", "https_port": "",
                                "server_protocol": "http", "timezone": "Europe/Istanbul",
                                "timestamp_now": int(time.time())},
            })
        if action == "get_live_categories":
            cats = [{"category_id": str(i + 1), "category_name": c, "parent_id": 0} for i, c in enumerate(LIVE_CATS)]
            cats.append({"category_id": "99", "category_name": "🧪 Test: Sorunlu Kanallar", "parent_id": 0})
            return self._json(cats)
        if action == "get_live_streams":
            return self._json([self._abs(s, "stream_icon") for s in st.live if not cat or s["category_id"] == cat])
        if action == "get_vod_categories":
            return self._json(st.vod_cats)
        if action == "get_vod_streams":
            return self._json([self._abs(s, "stream_icon") for s in st.vod if not cat or s["category_id"] == cat])
        if action == "get_series_categories":
            return self._json([{"category_id": "201", "category_name": "Yerli Diziler", "parent_id": 0},
                               {"category_id": "202", "category_name": "Yabancı Diziler", "parent_id": 0}])
        if action == "get_series":
            return self._json([self._abs(s, "cover") for s in st.series if not cat or s["category_id"] == cat])
        if action == "get_vod_info":
            vid = int(q.get("vod_id", 0))
            v = next((x for x in st.vod if x["stream_id"] == vid), None)
            if not v:
                return self._json([])
            return self._json({
                "info": {"name": v["name"], "plot": "Bir test filmi. Akış'ın kaldığın yerden devam etme ve "
                                                    "kopmada otomatik devam özelliklerini denemek için.",
                         "genre": "Test, Dram", "director": "Akış Stüdyo", "cast": "Motti, Limee, Obsid",
                         "releasedate": "2026-01-01", "rating": v["rating"], "duration": "00:01:00",
                         "duration_secs": 60, "movie_image": v["stream_icon"], "cover_big": v["stream_icon"]},
                "movie_data": {"stream_id": vid, "name": v["name"], "container_extension": "mp4"},
            })
        if action == "get_series_info":
            sid = int(q.get("series_id", 0))
            s = next((x for x in st.series if x["series_id"] == sid), None)
            if not s:
                return self._json([])
            eps = {}
            for season in (1, 2):
                eps[str(season)] = [{"id": str(sid * 100 + season * 10 + e), "episode_num": e,
                                     "title": f"{s['name']} - S{season:02d}E{e:02d}", "container_extension": "mp4",
                                     "season": season, "info": {"duration": "00:01:00", "plot": f"{e}. bölüm",
                                                                "movie_image": s["cover"]}}
                                    for e in range(1, 5)]
            return self._json({"seasons": [{"season_number": 1, "name": "Sezon 1"},
                                           {"season_number": 2, "name": "Sezon 2"}],
                               "info": {"name": s["name"], "plot": s["plot"], "cover": s["cover"],
                                        "genre": "Test", "rating": "8", "releaseDate": "2026-01-01"},
                               "episodes": eps})
        if action == "get_short_epg":
            sid = int(q.get("stream_id", 0))
            limit = int(q.get("limit", 4))
            now = time.time()
            out = []
            for title, a, b in programs(sid, now, now + 6 * 3600):
                out.append({"id": "1", "epg_id": "1", "title": b64(title), "lang": "tr",
                            "start": datetime.fromtimestamp(a).strftime("%Y-%m-%d %H:%M:%S"),
                            "end": datetime.fromtimestamp(b).strftime("%Y-%m-%d %H:%M:%S"),
                            "description": b64(f"{title} programının açıklaması."), "channel_id": f"ch{sid}.tr",
                            "start_timestamp": str(int(a)), "stop_timestamp": str(int(b))})
            return self._json({"epg_listings": out[:limit]})
        return self._json([])

    def xmltv(self, q):
        st = STATE
        now = time.time()
        parts = ['<?xml version="1.0" encoding="UTF-8"?>\n<tv generator-info-name="mock">']
        for s in st.live:
            parts.append(f'<channel id="{s["epg_channel_id"]}"><display-name>{s["name"]}</display-name></channel>')
        for s in st.live:
            for title, a, b in programs(s["stream_id"], now - 4 * 3600, now + 12 * 3600):
                fa = datetime.fromtimestamp(a, timezone.utc).strftime("%Y%m%d%H%M%S +0000")
                fb = datetime.fromtimestamp(b, timezone.utc).strftime("%Y%m%d%H%M%S +0000")
                parts.append(f'<programme start="{fa}" stop="{fb}" channel="{s["epg_channel_id"]}">'
                             f'<title lang="tr">{title}</title><desc lang="tr">{title} açıklaması</desc></programme>')
        parts.append("</tv>")
        self._send(200, "\n".join(parts).encode("utf-8"), "application/xml")

    # ---- canlı yayın
    def live(self, sid: int, ext: str):
        st = STATE
        if sid not in {s["stream_id"] for s in st.live} or sid == 9003:
            return self._send(404, b"stream not found", "text/plain")
        if ext == "m3u8":
            return self.hls_playlist(sid)
        if sid == 9005:
            return self._send(404, b"ts disabled", "text/plain")
        if not st.acquire():
            return self._send(403, b"max connections reached", "text/plain")
        try:
            self.stream_ts(sid)
        finally:
            st.release()

    def stream_ts(self, sid: int):
        st = STATE
        data = st.ts
        rate = len(data) / TS_DURATION        # bayt/sn (gerçek zamanlı)
        if sid == 9006:
            rate *= 0.8                        # yayın hızının altında → buffer erir
        self.send_response(200)
        self.send_header("Content-Type", "video/mp2t")
        self.send_header("Connection", "close")
        self.end_headers()
        if sid == 9004:
            time.sleep(6)
        pos = 0
        burst = int(rate * 2)                  # gerçek sunucular gibi ilk 2 sn'yi hemen gönder
        t0 = time.monotonic()
        sent = 0
        while True:
            elapsed = time.monotonic() - t0
            if sid == 9001 and elapsed > 20:
                return                          # bağlantıyı kopar
            if sid == 9002 and elapsed > 15:
                time.sleep(90)                  # veri yok, bağlantı açık
                return
            target = burst + int(rate * elapsed)
            n = target - sent
            if n > 0:
                n = (n // 188) * 188 or 188
                chunk = data[pos:pos + n]
                if len(chunk) < n:
                    chunk += data[: n - len(chunk)]
                pos = (pos + n) % len(data)
                self.wfile.write(chunk)
                sent += n
            time.sleep(0.05)

    def hls_playlist(self, sid: int):
        st = STATE
        n = len(st.seg_bytes)
        now_seq = int((time.time() - st.epoch) / HLS_SEG) + n   # her zaman >= n
        first = now_seq - 5
        lines = ["#EXTM3U", "#EXT-X-VERSION:3", f"#EXT-X-TARGETDURATION:{int(HLS_SEG) + 1}",
                 f"#EXT-X-MEDIA-SEQUENCE:{first}", f"#EXT-X-DISCONTINUITY-SEQUENCE:{first // n}"]
        for seq in range(first, now_seq):
            if seq % n == 0 and seq != first:
                lines.append("#EXT-X-DISCONTINUITY")
            lines.append(f"#EXTINF:{HLS_SEG:.3f},")
            lines.append(f"/hls/{sid}/{seq}.ts")
        body = ("\n".join(lines) + "\n").encode()
        self._send(200, body, "application/vnd.apple.mpegurl", {"Cache-Control": "no-cache"})

    def hls_segment(self, sid: int, seq: int):
        st = STATE
        self._send(200, st.seg_bytes[seq % len(st.seg_bytes)], "video/mp2t")

    # ---- VOD (Range destekli)
    def vod_file(self):
        st = STATE
        data = st.mp4
        total = len(data)
        rng = self.headers.get("Range")
        if rng:
            m = re.match(r"bytes=(\d*)-(\d*)", rng)
            a = int(m.group(1)) if m and m.group(1) else 0
            b = int(m.group(2)) if m and m.group(2) else total - 1
            b = min(b, total - 1)
            if a >= total:
                return self._send(416, b"", "text/plain", {"Content-Range": f"bytes */{total}"})
            return self._send(206, data[a:b + 1], "video/mp4",
                              {"Content-Range": f"bytes {a}-{b}/{total}", "Accept-Ranges": "bytes"})
        self._send(200, data, "video/mp4", {"Accept-Ranges": "bytes"})


def make_server(host: str = "127.0.0.1", port: int = 8899, channels: int = 300, max_conn: int = 1):
    global STATE
    STATE = State(channels, max_conn)
    srv = _QuietServer((host, port), Handler)
    srv.daemon_threads = True
    return srv


class _QuietServer(ThreadingHTTPServer):
    def handle_error(self, request, client_address):
        import sys
        if isinstance(sys.exc_info()[1], (ConnectionError, TimeoutError)):
            return   # istemci bağlantıyı kapattı (kanal değiştirme vb.) — normal
        super().handle_error(request, client_address)


def main():
    ap = argparse.ArgumentParser(description="Sahte Xtream sunucusu")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8899)
    ap.add_argument("--channels", type=int, default=300)
    ap.add_argument("--max-conn", type=int, default=1, help="0 = sınırsız")
    a = ap.parse_args()
    srv = make_server(a.host, a.port, a.channels, a.max_conn)
    print(f"Sahte Xtream sunucusu: http://{a.host}:{a.port}  (kullanıcı: {USER} / parola: {PASS})")
    print("Durdurmak için Ctrl+C")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
