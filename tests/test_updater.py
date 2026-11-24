"""Güncelleyicinin sürüm karşılaştırması (ağ kullanmaz)."""
from akis import updater


def test_parse_version():
    assert updater.parse_version("v1.2.10") == (1, 2, 10)
    assert updater.parse_version("1.2") == (1, 2)
    assert updater.parse_version("") == (0,)


def test_is_newer():
    assert updater.is_newer("v1.2.0", "1.1.0")
    assert updater.is_newer("1.10.0", "1.9.9")          # metin değil sayı olarak karşılaştır
    assert not updater.is_newer("v1.1.0", "1.1.0")
    assert not updater.is_newer("1.0.9", "1.1.0")
    assert updater.is_newer("1.1.1", "1.1")             # eksik hane sıfır sayılır
    assert not updater.is_newer("1.1", "1.1.0")


def test_check_ignores_older_and_drafts(monkeypatch):
    class R:
        status_code = 200

        def __init__(self, d):
            self._d = d

        def json(self):
            return self._d

    rel = {"tag_name": "v9.0.0", "body": "notlar", "html_url": "https://x",
           "assets": [{"name": "AkisIPTV-Setup-9.0.0.exe", "browser_download_url": "https://x/s.exe", "size": 5}]}
    monkeypatch.setattr(updater.requests, "get", lambda *a, **k: R(rel))
    r = updater.check()
    assert r and r.version == "9.0.0" and r.asset_url.endswith("s.exe") and r.notes == "notlar"

    monkeypatch.setattr(updater.requests, "get", lambda *a, **k: R({**rel, "draft": True}))
    assert updater.check() is None
    monkeypatch.setattr(updater.requests, "get", lambda *a, **k: R({**rel, "tag_name": "v0.0.1"}))
    assert updater.check() is None
