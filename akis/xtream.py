"""Xtream Codes API istemcisi.

Yükleme hatalarına karşı alınan önlemler:
* Bağlantı havuzu + otomatik yeniden deneme (exponential backoff, 429/5xx/Cloudflare 52x).
* Ayrı bağlan/oku zaman aşımları (büyük listeler için uzun okuma süresi).
* Ayarlanabilir User-Agent (birçok sağlayıcı "python-requests"i engeller).
* Bozuk/BOM'lu/HTML dönen yanıtlara tolerans, dict-veya-list biçim farklarını normalize etme.
"""
from __future__ import annotations

import base64
import json
import logging
import re
import time
import unicodedata
from dataclasses import dataclass, field
from datetime import datetime
from urllib.parse import parse_qs, quote, urlparse

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

log = logging.getLogger(__name__)

DEFAULT_UA = "VLC/3.0.21 LibVLC/3.0.21"


class XtreamError(Exception):
    """Kullanıcıya gösterilebilir hata mesajı taşır."""


class AuthError(XtreamError):
    pass


# --------------------------------------------------------------------------- yardımcılar
def normalize_server(url: str) -> str:
    """Kullanıcının yazdığı adresi ``http(s)://host:port`` biçimine getirir."""
    url = (url or "").strip().strip("/")
    if not url:
        raise XtreamError("Sunucu adresi boş olamaz.")
    if not re.match(r"^https?://", url, re.I):
        url = "http://" + url
    p = urlparse(url)
    if not p.hostname:
        raise XtreamError("Sunucu adresi geçersiz.")
    path = p.path or ""
    # yapıştırılmış tam adresleri temizle
    path = re.sub(r"/(player_api|get|xmltv|panel_api)\.php.*$", "", path, flags=re.I)
    path = re.sub(r"/(live|movie|series)/.*$", "", path, flags=re.I)
    netloc = p.netloc
    return f"{p.scheme.lower()}://{netloc}{path.rstrip('/')}"


def parse_m3u_link(url: str) -> tuple[str, str, str] | None:
    """``http://host:port/get.php?username=U&password=P&type=m3u_plus`` → (server, U, P)."""
    try:
        p = urlparse(url.strip())
        q = parse_qs(p.query)
        if "username" in q and "password" in q:
            server = normalize_server(f"{p.scheme or 'http'}://{p.netloc}{p.path}")
            return server, q["username"][0], q["password"][0]
    except Exception:
        pass
    return None


_TR_MAP = str.maketrans({"ı": "i", "İ": "i", "I": "i"})


def search_key(text: str) -> str:
    """Türkçe ve aksan duyarsız arama anahtarı: 'SİNEMA Ş' -> 'sinema s'."""
    if not text:
        return ""
    t = text.translate(_TR_MAP)
    t = unicodedata.normalize("NFKD", t)
    t = "".join(ch for ch in t if not unicodedata.combining(ch))
    return t.casefold()


def as_list(data) -> list:
    """Bazı paneller listeyi {"0": {...}, "1": {...}} biçiminde döndürür."""
    if data is None:
        return []
    if isinstance(data, list):
        return [x for x in data if isinstance(x, dict)]
    if isinstance(data, dict):
        vals = list(data.values())
        if vals and all(isinstance(v, dict) for v in vals):
            return vals
    return []


def to_int(v, default: int = 0) -> int:
    try:
        return int(float(v))
    except (TypeError, ValueError):
        return default


def b64_text(s) -> str:
    """EPG başlık/açıklamaları genelde base64'tür; değilse olduğu gibi döner."""
    if not s or not isinstance(s, str):
        return s or ""
    st = s.strip()
    if len(st) % 4 == 0 and re.fullmatch(r"[A-Za-z0-9+/=\s]+", st):
        try:
            out = base64.b64decode(st, validate=False).decode("utf-8")
            if out and all(ch.isprintable() or ch in "\n\r\t" for ch in out):
                return out
        except Exception:
            pass
    return s


def _parse_dt(s) -> float | None:
    if not s:
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y%m%d%H%M%S"):
        try:
            return datetime.strptime(str(s)[:19], fmt).timestamp()
        except ValueError:
            continue
    return None


@dataclass
class EpgEntry:
    title: str
    start: float
    stop: float
    description: str = ""

    def progress(self, now: float | None = None) -> float:
        now = now or time.time()
        if self.stop <= self.start:
            return 0.0
        return max(0.0, min(1.0, (now - self.start) / (self.stop - self.start)))


def parse_short_epg(data) -> list[EpgEntry]:
    listings = []
    if isinstance(data, dict):
        listings = data.get("epg_listings") or []
    elif isinstance(data, list):
        listings = data
    out: list[EpgEntry] = []
    for it in as_list(listings):
        start = to_int(it.get("start_timestamp"), 0) or _parse_dt(it.get("start")) or 0
        stop = (to_int(it.get("stop_timestamp"), 0) or to_int(it.get("end_timestamp"), 0)
                or _parse_dt(it.get("end")) or _parse_dt(it.get("stop")) or 0)
        if not start or not stop:
            continue
        out.append(EpgEntry(b64_text(it.get("title", "")), float(start), float(stop),
                            b64_text(it.get("description", ""))))
    out.sort(key=lambda e: e.start)
    return out


# --------------------------------------------------------------------------- istemci
@dataclass
class Account:
    username: str = ""
    status: str = ""
    exp_date: float | None = None
    is_trial: bool = False
    max_connections: int = 0
    active_cons: int = 0
    allowed_formats: list[str] = field(default_factory=lambda: ["ts", "m3u8"])
    server_timezone: str = ""
    raw: dict = field(default_factory=dict)

    @property
    def expiry_text(self) -> str:
        if not self.exp_date:
            return "Sınırsız"
        return datetime.fromtimestamp(self.exp_date).strftime("%d.%m.%Y")


class XtreamClient:
    def __init__(self, server: str, username: str, password: str,
                 user_agent: str = DEFAULT_UA, timeout: tuple[float, float] = (8.0, 45.0)):
        self.base = normalize_server(server)
        self.username = username.strip()
        self.password = password.strip()
        self.user_agent = user_agent or DEFAULT_UA
        self.timeout = timeout
        self.account: Account | None = None
        self.session = self._make_session()

    def _make_session(self) -> requests.Session:
        s = requests.Session()
        retry = Retry(
            total=4, connect=4, read=1, status=3,
            backoff_factor=0.7,
            status_forcelist=(408, 429, 500, 502, 503, 504, 520, 521, 522, 523, 524),
            allowed_methods=frozenset({"GET", "HEAD"}),
            respect_retry_after_header=True,
            raise_on_status=False,
        )
        adapter = HTTPAdapter(max_retries=retry, pool_connections=8, pool_maxsize=16)
        s.mount("http://", adapter)
        s.mount("https://", adapter)
        s.headers.update({
            "User-Agent": self.user_agent,
            "Accept": "application/json, text/plain, */*",
            "Accept-Encoding": "gzip, deflate",
            "Connection": "keep-alive",
        })
        return s

    def close(self) -> None:
        try:
            self.session.close()
        except Exception:
            pass

    # ---- düşük seviye
    def _api(self, action: str | None = None, timeout: tuple[float, float] | None = None, **params):
        q = {"username": self.username, "password": self.password}
        if action:
            q["action"] = action
        q.update({k: v for k, v in params.items() if v is not None})
        url = f"{self.base}/player_api.php"
        t0 = time.monotonic()
        try:
            r = self.session.get(url, params=q, timeout=timeout or self.timeout)
        except requests.exceptions.SSLError as e:
            raise XtreamError(f"SSL hatası. Adresi http:// ile denemeyi dene. ({e.__class__.__name__})") from e
        except requests.exceptions.ConnectTimeout as e:
            raise XtreamError("Sunucuya bağlanılamadı (zaman aşımı). Adres/port doğru mu?") from e
        except requests.exceptions.ReadTimeout as e:
            raise XtreamError("Sunucu çok yavaş yanıt veriyor (okuma zaman aşımı).") from e
        except requests.exceptions.ConnectionError as e:
            if "timed out" in str(e).lower():
                raise XtreamError("Sunucu çok yavaş yanıt veriyor (zaman aşımı). Biraz sonra tekrar dene.") from e
            raise XtreamError("Sunucuya bağlanılamadı. İnternet bağlantını ve adresi kontrol et.") from e
        except requests.exceptions.RequestException as e:
            raise XtreamError(f"Ağ hatası: {e}") from e

        log.info("API %s -> %s (%d bayt, %.2fs)", action or "auth", r.status_code,
                 len(r.content), time.monotonic() - t0)
        if r.status_code in (401, 403):
            raise AuthError("Kullanıcı adı/parola hatalı veya erişim engellendi (HTTP %d)." % r.status_code)
        if r.status_code == 404:
            raise XtreamError("player_api.php bulunamadı. Sunucu adresi Xtream uyumlu değil gibi.")
        if r.status_code >= 400:
            raise XtreamError(f"Sunucu hata döndürdü: HTTP {r.status_code}")
        return self._decode_json(r.content)

    @staticmethod
    def _decode_json(content: bytes):
        text = content.decode("utf-8-sig", errors="replace").strip()
        if not text or text in ("null", "false"):
            return []
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            # Başına/sonuna PHP uyarısı vs. eklenmiş yanıtları kurtarmaya çalış
            starts = [i for i in (text.find("{"), text.find("[")) if i >= 0]
            if starts:
                s = min(starts)
                end = max(text.rfind("}"), text.rfind("]"))
                if end > s:
                    try:
                        return json.loads(text[s:end + 1])
                    except json.JSONDecodeError:
                        pass
            snippet = re.sub(r"\s+", " ", text[:120])
            raise XtreamError(f"Sunucu geçersiz yanıt döndürdü: {snippet!r}") from None

    # ---- kimlik doğrulama
    def authenticate(self) -> Account:
        data = self._api(timeout=(8.0, 20.0))
        if not isinstance(data, dict) or "user_info" not in data:
            raise AuthError("Sunucu Xtream yanıtı vermedi. Adresi ve bilgileri kontrol et.")
        ui = data.get("user_info") or {}
        if str(ui.get("auth", "1")) in ("0", "False", "false"):
            raise AuthError("Kullanıcı adı veya parola hatalı.")
        status = str(ui.get("status") or "")
        if status and status.lower() not in ("active", "aktif"):
            raise AuthError(f"Hesap aktif değil (durum: {status}).")
        formats = ui.get("allowed_output_formats") or ["ts", "m3u8"]
        formats = [f.lower() for f in formats if isinstance(f, str)]
        exp = to_int(ui.get("exp_date"), 0) or None
        si = data.get("server_info") or {}
        self.account = Account(
            username=str(ui.get("username") or self.username),
            status=status or "Active",
            exp_date=float(exp) if exp else None,
            is_trial=str(ui.get("is_trial", "0")) == "1",
            max_connections=to_int(ui.get("max_connections"), 0),
            active_cons=to_int(ui.get("active_cons"), 0),
            allowed_formats=formats or ["ts", "m3u8"],
            server_timezone=str(si.get("timezone") or ""),
            raw=data,
        )
        return self.account

    # ---- katalog
    def live_categories(self):
        return as_list(self._api("get_live_categories"))

    def vod_categories(self):
        return as_list(self._api("get_vod_categories"))

    def series_categories(self):
        return as_list(self._api("get_series_categories"))

    def live_streams(self, category_id=None):
        return as_list(self._api("get_live_streams", category_id=category_id, timeout=(8.0, 90.0)))

    def vod_streams(self, category_id=None):
        return as_list(self._api("get_vod_streams", category_id=category_id, timeout=(8.0, 90.0)))

    def series(self, category_id=None):
        return as_list(self._api("get_series", category_id=category_id, timeout=(8.0, 90.0)))

    def vod_info(self, vod_id) -> dict:
        d = self._api("get_vod_info", vod_id=vod_id)
        return d if isinstance(d, dict) else {}

    def series_info(self, series_id) -> dict:
        d = self._api("get_series_info", series_id=series_id)
        return normalize_series_info(d if isinstance(d, dict) else {})

    def short_epg(self, stream_id, limit: int = 6) -> list[EpgEntry]:
        try:
            return parse_short_epg(self._api("get_short_epg", stream_id=stream_id, limit=limit,
                                             timeout=(5.0, 12.0)))
        except XtreamError as e:
            log.info("Kısa EPG alınamadı (%s): %s", stream_id, e)
            return []

    # ---- yayın adresleri
    def _cred(self) -> str:
        return f"{quote(self.username, safe='')}/{quote(self.password, safe='')}"

    def live_url(self, stream_id, ext: str = "ts") -> str:
        return f"{self.base}/live/{self._cred()}/{stream_id}.{ext}"

    def vod_url(self, stream_id, ext: str = "mp4") -> str:
        return f"{self.base}/movie/{self._cred()}/{stream_id}.{ext or 'mp4'}"

    def episode_url(self, episode_id, ext: str = "mp4") -> str:
        return f"{self.base}/series/{self._cred()}/{episode_id}.{ext or 'mp4'}"

    def xmltv_url(self) -> str:
        return f"{self.base}/xmltv.php?username={quote(self.username)}&password={quote(self.password)}"


def normalize_series_info(d: dict) -> dict:
    """``episodes`` alanını her zaman {sezon_no(int): [bölüm,...]} biçimine getirir."""
    eps = d.get("episodes") or {}
    seasons: dict[int, list[dict]] = {}
    if isinstance(eps, dict):
        for k, lst in eps.items():
            items = as_list(lst)
            sn = to_int(k, 0) or (to_int(items[0].get("season"), 0) if items else 0)
            seasons.setdefault(sn, []).extend(items)
    elif isinstance(eps, list):
        flat: list[dict] = []
        for x in eps:
            if isinstance(x, list):
                flat.extend(as_list(x))
            elif isinstance(x, dict):
                flat.append(x)
        for ep in flat:
            seasons.setdefault(to_int(ep.get("season"), 1), []).append(ep)
    for sn in seasons:
        seasons[sn].sort(key=lambda e: to_int(e.get("episode_num"), 0))
    d["episodes"] = dict(sorted(seasons.items()))
    if not isinstance(d.get("info"), dict):
        d["info"] = {}
    return d
