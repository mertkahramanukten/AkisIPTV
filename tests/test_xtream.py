"""Xtream istemcisi, önbellek ve EPG testleri — sahte sunucuya karşı çalışır."""
import socket
import tempfile
import threading
import time
import unittest
from pathlib import Path

import requests

from akis.cache import DiskCache
from akis.epg import EpgStore, parse_xmltv_file, parse_xmltv_time
from akis.xtream import (AuthError, XtreamClient, XtreamError, as_list, b64_text, normalize_series_info,
                         normalize_server, parse_m3u_link, parse_short_epg, search_key)
from tests import mock_server


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class PureTests(unittest.TestCase):
    def test_normalize_server(self):
        self.assertEqual(normalize_server("example.com:8080"), "http://example.com:8080")
        self.assertEqual(normalize_server(" http://x.tv:80/ "), "http://x.tv:80")
        self.assertEqual(normalize_server("https://x.tv/player_api.php?username=a"), "https://x.tv")
        self.assertEqual(normalize_server("http://x.tv:8000/get.php?username=a&password=b"), "http://x.tv:8000")
        self.assertEqual(normalize_server("http://x.tv/live/u/p/1.ts"), "http://x.tv")
        with self.assertRaises(XtreamError):
            normalize_server("   ")

    def test_parse_m3u_link(self):
        r = parse_m3u_link("http://srv.tv:8080/get.php?username=ali&password=123&type=m3u_plus&output=ts")
        self.assertEqual(r, ("http://srv.tv:8080", "ali", "123"))
        self.assertIsNone(parse_m3u_link("http://srv.tv:8080"))

    def test_search_key_turkish(self):
        self.assertEqual(search_key("SİNEMA"), "sinema")
        self.assertEqual(search_key("Işık Çocuk Şov"), "isik cocuk sov")
        self.assertIn(search_key("spor"), search_key("TR: BEIN SPORTS / SPOR HD"))

    def test_as_list_variants(self):
        self.assertEqual(as_list({"0": {"a": 1}, "1": {"a": 2}}), [{"a": 1}, {"a": 2}])
        self.assertEqual(as_list(None), [])
        self.assertEqual(as_list([{"a": 1}, "x", None]), [{"a": 1}])

    def test_b64_text(self):
        self.assertEqual(b64_text("QW5hIEhhYmVy"), "Ana Haber")
        self.assertEqual(b64_text("Ana Haber"), "Ana Haber")
        self.assertEqual(b64_text("Test"), "Test")  # 4 karakter ama base64 çözümü yazdırılamaz

    def test_short_epg_parse(self):
        data = {"epg_listings": [{"title": "QW5hIEhhYmVy", "description": "", "start_timestamp": "200",
                                  "stop_timestamp": "300"},
                                 {"title": "Maç", "start": "2026-10-26 20:00:00", "end": "2026-10-26 22:00:00"}]}
        e = parse_short_epg(data)
        self.assertEqual(len(e), 2)
        self.assertEqual(e[0].title, "Ana Haber")

    def test_series_info_normalization(self):
        d = normalize_series_info({"episodes": [[{"id": "2", "episode_num": 2, "season": 1},
                                                 {"id": "1", "episode_num": 1, "season": 1}],
                                                [{"id": "3", "episode_num": 1, "season": 2}]]})
        self.assertEqual(list(d["episodes"].keys()), [1, 2])
        self.assertEqual(d["episodes"][1][0]["id"], "1")
        d2 = normalize_series_info({"episodes": {"1": [{"id": "9"}]}, "info": []})
        self.assertEqual(d2["episodes"][1][0]["id"], "9")
        self.assertEqual(d2["info"], {})

    def test_decode_json_with_garbage(self):
        self.assertEqual(XtreamClient._decode_json(b"\xef\xbb\xbf[1,2]"), [1, 2])
        self.assertEqual(XtreamClient._decode_json(b"Warning: x in y\n{\"a\": 1}"), {"a": 1})
        self.assertEqual(XtreamClient._decode_json(b""), [])
        with self.assertRaises(XtreamError):
            XtreamClient._decode_json(b"<html>502 Bad Gateway</html>")

    def test_urls_are_escaped(self):
        c = XtreamClient("srv.tv:80", "ali veli", "p@ss/1")
        self.assertEqual(c.live_url(5, "m3u8"), "http://srv.tv:80/live/ali%20veli/p%40ss%2F1/5.m3u8")
        self.assertTrue(c.vod_url(9, "mkv").endswith("/movie/ali%20veli/p%40ss%2F1/9.mkv"))

    def test_xmltv_time(self):
        self.assertEqual(parse_xmltv_time("20260101000000 +0000"), 1767225600.0)
        self.assertEqual(parse_xmltv_time("20260101030000 +0300"), 1767225600.0)
        self.assertIsNone(parse_xmltv_time("bozuk"))

    def test_cache_roundtrip_and_expiry(self):
        with tempfile.TemporaryDirectory() as d:
            c = DiskCache(Path(d), "p1")
            c.set("k", {"x": [1, 2, "ş"]})
            v, age = c.get("k")
            self.assertEqual(v, {"x": [1, 2, "ş"]})
            self.assertLess(age, 5)
            self.assertEqual(c.get("k", max_age=-1), (None, None))
            self.assertEqual(DiskCache(Path(d), "p2").get("k"), (None, None))
            # bozuk dosya sessizce temizlenir
            c._path("bad").write_bytes(b"not gzip")
            self.assertEqual(c.get("bad"), (None, None))


class MockServerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.port = free_port()
        cls.srv = mock_server.make_server("127.0.0.1", cls.port, channels=120, max_conn=1)
        cls.th = threading.Thread(target=cls.srv.serve_forever, daemon=True)
        cls.th.start()
        cls.base = f"http://127.0.0.1:{cls.port}"

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()
        cls.srv.server_close()

    def client(self, user="demo", pw="demo"):
        return XtreamClient(self.base, user, pw)

    def test_auth_ok(self):
        acc = self.client().authenticate()
        self.assertEqual(acc.status, "Active")
        self.assertEqual(acc.max_connections, 1)
        self.assertIn("ts", acc.allowed_formats)
        self.assertNotEqual(acc.expiry_text, "Sınırsız")

    def test_auth_adopts_server_case(self):
        # API "DEMO"yu kabul eder ama yayın sunucusu birebir "demo" ister
        c = self.client(pw="DEMO")
        self.assertEqual(requests.get(c.live_url(1, "m3u8"), timeout=5).status_code, 401)
        acc = c.authenticate()
        self.assertTrue(c.credentials_fixed)
        self.assertEqual(c.password, "demo")
        self.assertIn("parola", acc.cred_note)
        self.assertEqual(requests.get(c.live_url(1, "m3u8"), timeout=5).status_code, 200)
        ok = self.client()
        ok.authenticate()
        self.assertFalse(ok.credentials_fixed)
        self.assertEqual(ok.account.cred_note, "")

    def test_adopt_only_equivalent_credentials(self):
        c = XtreamClient("srv.tv", "Ali", "Şifre1")
        note = c._adopt_server_credentials({"username": "ali", "password": "sifre1 "})
        self.assertEqual((c.username, c.password), ("ali", "sifre1"))
        self.assertIn("parola", note)
        c2 = XtreamClient("srv.tv", "ali", "gizli")
        note2 = c2._adopt_server_credentials({"username": "ali", "password": "********"})
        self.assertEqual(c2.password, "gizli")
        self.assertIn("değiştirilmedi", note2)
        self.assertFalse(c2.credentials_fixed)
        self.assertEqual(c2._adopt_server_credentials({"username": "", "password": None}), "")

    def test_auth_wrong_password(self):
        with self.assertRaises(AuthError):
            self.client(pw="yanlis").authenticate()

    def test_unreachable_server_message(self):
        c = XtreamClient(f"http://127.0.0.1:{free_port()}", "a", "b", timeout=(1, 1))
        c.session.adapters["http://"].max_retries.total = 0
        with self.assertRaises(XtreamError) as cm:
            c.authenticate()
        self.assertIn("bağlanılamadı", str(cm.exception))

    def test_catalog(self):
        c = self.client()
        cats = c.live_categories()
        self.assertTrue(any(x["category_id"] == "99" for x in cats))
        streams = c.live_streams()
        self.assertEqual(len(streams), 120 + len(mock_server.SPECIAL))
        self.assertTrue(streams[0]["stream_icon"].startswith("http://"))
        self.assertEqual(len(c.live_streams(category_id="99")), len(mock_server.SPECIAL))
        self.assertTrue(c.vod_streams())
        self.assertTrue(c.series())

    def test_info_endpoints(self):
        c = self.client()
        vi = c.vod_info(5000)
        self.assertEqual(vi["movie_data"]["container_extension"], "mp4")
        si = c.series_info(7000)
        self.assertEqual(sorted(si["episodes"].keys()), [1, 2])
        self.assertEqual(len(si["episodes"][1]), 4)

    def test_short_epg(self):
        e = self.client().short_epg(3, limit=3)
        self.assertEqual(len(e), 3)
        self.assertTrue(e[0].title)
        now = time.time()
        self.assertTrue(e[0].start <= now < e[0].stop)

    def test_full_xmltv_parse_and_store(self):
        c = self.client()
        r = requests.get(c.xmltv_url(), timeout=10)
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "x.xml"
            p.write_bytes(r.content)
            data = parse_xmltv_file(p)
        self.assertIn("ch1.tr", data)
        store = EpgStore()
        store.load_full(data)
        cur, nxt = store.now_next(epg_id="CH1.tr")
        self.assertIsNotNone(cur)
        self.assertIsNotNone(nxt)
        self.assertLessEqual(cur.start, time.time())

    def test_stream_urls_respond(self):
        c = self.client()
        r = requests.get(c.live_url(1, "m3u8"), timeout=5)
        self.assertEqual(r.status_code, 200)
        self.assertIn("#EXTM3U", r.text)
        r = requests.get(c.live_url(9003, "ts"), timeout=5)
        self.assertEqual(r.status_code, 404)
        r = requests.get(c.live_url(9007, "m3u8"), timeout=5)
        self.assertEqual(r.status_code, 401)
        r = requests.get(c.live_url(9007, "m3u8"), headers={"User-Agent": "okhttp/4.12.0"}, timeout=5)
        self.assertEqual(r.status_code, 200)
        r = requests.get(c.vod_url(5000, "mp4"), headers={"Range": "bytes=0-99"}, timeout=5)
        self.assertEqual(r.status_code, 206)
        self.assertEqual(len(r.content), 100)

    def test_connection_limit(self):
        c = self.client()
        r1 = requests.get(c.live_url(1, "ts"), stream=True, timeout=5)
        try:
            self.assertEqual(r1.status_code, 200)
            next(r1.iter_content(4096))
            r2 = requests.get(c.live_url(2, "ts"), stream=True, timeout=5)
            self.assertEqual(r2.status_code, 403)
            r2.close()
        finally:
            r1.close()


if __name__ == "__main__":
    unittest.main()
