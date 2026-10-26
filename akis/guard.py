"""StreamGuard — yayın "doktoru".

mpv'den gelen olayları izleyen, saf Python (Qt/mpv bağımsız, test edilebilir)
bir durum makinesi. Donma, kopma, açılmama gibi durumları tespit eder ve
denetleyiciye (PlayerController) ne yapması gerektiğini söyler:

* Açılış zaman aşımı      → durdur, bekle, tekrar dene (artan bekleme süreleriyle)
* Görüntü dondu           → zaman (time-pos) ilerlemiyorsa yeniden bağlan
* Veri gelmiyor           → buffer uzun süre dolmuyorsa bağlantıyı yenile
* Yayın kesildi           → canlıda tekrar bağlan; filmde kaldığı saniyeden devam et
* Sık takılma             → buffer seviyesini otomatik yükselt (adaptif buffer)
* Aynı formatta tekrar hata → TS ↔ HLS (m3u8) arasında otomatik geçiş
* HTTP 403/458/509        → bağlantı limiti dolu olabilir, daha uzun bekle
* HTTP 401 (yetki yok)    → sunucu bu oynatıcıyı tanımıyor olabilir: farklı oynatıcı kimlikleri
                            (User-Agent) sırayla denenir, çalışan bulunursa hatırlanır
* HTTP 404                → kanal yayında değil; boşuna zorlamadan vazgeç
"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from enum import Enum

# cache-pause-wait değerleri (saniye). Seviye arttıkça başlangıç biraz gecikir
# ama takılma ihtimali ciddi düşer.
BUFFER_LEVELS = (1.0, 2.5, 4.0, 6.0, 9.0)
BUFFER_PROFILES = {"hizli": 0, "dengeli": 1, "saglam": 3}

FORMAT_NAMES = {"ts": "TS", "m3u8": "HLS"}


class GState(str, Enum):
    IDLE = "idle"
    OPENING = "opening"
    PLAYING = "playing"
    WAITING = "waiting"      # yeniden denemeden önce bekleniyor
    FAILED = "failed"
    FINISHED = "finished"


@dataclass
class GuardConfig:
    open_timeout_live: float = 15.0
    open_timeout_vod: float = 25.0
    stall_timeout: float = 8.0
    buffering_timeout_live: float = 10.0   # canlıda veri bu kadar gelmezse bağlantı ölü sayılır
    buffering_timeout_vod: float = 20.0
    max_retries: int = 8
    backoff: tuple = (0.6, 1.2, 2.0, 3.0, 5.0, 8.0)
    limit_backoff: float = 3.0        # bağlantı limiti şüphesinde minimum bekleme
    format_switch_after: int = 2
    stable_after: float = 25.0
    underrun_window: float = 120.0
    underrun_threshold: int = 2
    seek_grace: float = 6.0
    vod_end_margin: float = 25.0
    adaptive: bool = True


@dataclass
class Action:
    kind: str                 # reload | stop | status | raise_buffer | give_up | finished | format_ok | format_bad
    fmt: str | None = None
    start: float | None = None
    message: str = ""
    level: int = 0


@dataclass
class GuardStats:
    reconnects: int = 0
    underruns: int = 0
    format_switches: int = 0
    last_reason: str = ""


class StreamGuard:
    def __init__(self, config: GuardConfig | None = None, buffer_level: int = 1):
        self.cfg = config or GuardConfig()
        self.base_level = buffer_level
        self.buffer_level = buffer_level
        self.state = GState.IDLE
        self.stats = GuardStats()
        self._reset_stream(0.0)

    # ------------------------------------------------------------------ iç durum
    def _reset_stream(self, now: float) -> None:
        self.is_live = True
        self.formats: list[str] = ["ts"]
        self.fmt_index = 0
        self.start_pos = 0.0
        self.t_state = now
        self.last_pos: float | None = None
        self.last_progress_t = now
        self.duration: float | None = None
        self.cache_paused = False
        self.cache_pause_since = now
        self.user_paused = False
        self.retries = 0
        self.fails_on_fmt = 0
        self.reconnect_at = 0.0
        self.seen_active = False
        self.played_since = now
        self.last_seek_t = -1e9
        self.http_error: int | None = None
        self.underruns: deque[float] = deque()
        self.stable_reported = False
        self.switched_from: str | None = None
        self.ua_count = 1
        self.ua_index = 0
        self.ua_403 = 0            # bu kimlikle art arda gelen 403 sayısı
        self.saw_401 = False

    @property
    def fmt(self) -> str:
        return self.formats[self.fmt_index] if self.formats else "ts"

    def _resume_pos(self) -> float:
        if self.is_live:
            return 0.0
        if self.last_pos and self.last_pos > 5:
            return max(0.0, self.last_pos - 3.0)
        return self.start_pos

    def _set(self, state: GState, now: float) -> None:
        self.state = state
        self.t_state = now

    # ------------------------------------------------------------------ dış API
    def start(self, now: float, is_live: bool, formats: list[str], start_pos: float = 0.0,
              ua_count: int = 1) -> list[Action]:
        self._reset_stream(now)
        self.ua_count = max(1, int(ua_count))
        self.is_live = is_live
        self.formats = list(dict.fromkeys(formats)) or ["ts"]
        self.start_pos = float(start_pos or 0.0)
        self.stats = GuardStats()
        self._set(GState.OPENING, now)
        return [Action("reload", fmt=self.fmt, start=self.start_pos, message="Açılıyor…")]

    def stop(self, now: float) -> None:
        self._set(GState.IDLE, now)

    def mark_loading(self, now: float) -> None:
        """Denetleyici loadfile çağırmadan hemen önce bildirir."""
        self.seen_active = False
        self.http_error = None
        self.cache_paused = False
        self.last_progress_t = now
        self._set(GState.OPENING, now)

    @property
    def active(self) -> bool:
        return self.state in (GState.OPENING, GState.PLAYING)

    def on_idle(self, now: float, idle: bool) -> list[Action]:
        if not idle:
            self.seen_active = True
            return []
        if self.seen_active and self.active:
            return self._on_ended(now)
        return []

    def on_duration(self, duration) -> None:
        try:
            d = float(duration)
            self.duration = d if d > 0 else None
        except (TypeError, ValueError):
            self.duration = None

    def on_progress(self, now: float, pos) -> list[Action]:
        if pos is None or not self.active:
            return []
        try:
            pos = float(pos)
        except (TypeError, ValueError):
            return []
        out: list[Action] = []
        if self.state == GState.OPENING:
            self._set(GState.PLAYING, now)
            self.played_since = now
            self.last_progress_t = now
            self.stable_reported = False
            msg = "Oynatılıyor"
            if self.retries:
                msg = f"Yeniden bağlandı ({FORMAT_NAMES.get(self.fmt, self.fmt)})"
            out.append(Action("status", message=msg))
            if self.ua_index and self.saw_401:
                out.append(Action("ua_ok", level=self.ua_index))
        if self.last_pos is None or abs(pos - self.last_pos) > 1e-3:
            self.last_pos = pos
            self.last_progress_t = now
        return out

    def on_cache_pause(self, now: float, paused: bool) -> list[Action]:
        paused = bool(paused)
        out: list[Action] = []
        if paused and not self.cache_paused:
            self.cache_paused = True
            self.cache_pause_since = now
            in_grace = (now - self.last_seek_t) < self.cfg.seek_grace
            if self.state == GState.PLAYING and now - self.played_since > 3.0 and not in_grace:
                self.stats.underruns += 1
                self.underruns.append(now)
                while self.underruns and now - self.underruns[0] > self.cfg.underrun_window:
                    self.underruns.popleft()
                if (self.cfg.adaptive and len(self.underruns) >= self.cfg.underrun_threshold
                        and self.buffer_level < len(BUFFER_LEVELS) - 1):
                    self.buffer_level += 1
                    self.underruns.clear()
                    out.append(Action("raise_buffer", level=self.buffer_level,
                                      message=f"Sık takılma algılandı → buffer {BUFFER_LEVELS[self.buffer_level]:.1f} sn"))
        elif not paused and self.cache_paused:
            self.cache_paused = False
            self.last_progress_t = now
        return out

    def on_user_pause(self, now: float, paused: bool) -> None:
        self.user_paused = bool(paused)
        if not paused:
            self.last_progress_t = now
            self.cache_pause_since = now

    def on_seek(self, now: float) -> None:
        self.last_seek_t = now
        self.last_progress_t = now
        self.cache_pause_since = now

    def on_http_error(self, code: int) -> None:
        self.http_error = code

    def on_error(self, now: float, reason: str) -> list[Action]:
        if not self.active:
            return []
        return self._fail(now, reason)

    def tick(self, now: float) -> list[Action]:
        st = self.state
        if st == GState.OPENING:
            limit = self.cfg.open_timeout_live if self.is_live else self.cfg.open_timeout_vod
            if now - self.t_state > limit:
                return self._fail(now, "Açılış zaman aşımı")
        elif st == GState.PLAYING:
            if self.user_paused:
                return []
            if self.cache_paused:
                limit = self.cfg.buffering_timeout_live if self.is_live else self.cfg.buffering_timeout_vod
                if now - self.cache_pause_since > limit:
                    return self._fail(now, "Veri gelmiyor")
            elif now - self.last_progress_t > self.cfg.stall_timeout:
                return self._fail(now, "Görüntü dondu")
            if not self.stable_reported and now - self.played_since > self.cfg.stable_after:
                self.stable_reported = True
                self.retries = 0
                self.fails_on_fmt = 0
                out = []
                if self.is_live and len(self.formats) > 1:
                    out.append(Action("format_ok", fmt=self.fmt))
                    # Diğer formattan buraya geçip stabil oynadıysak, o format bu sunucuda sorunlu demektir
                    if self.switched_from and self.switched_from != self.fmt:
                        out.append(Action("format_bad", fmt=self.switched_from))
                    self.switched_from = None
                return out
        elif st == GState.WAITING:
            if now >= self.reconnect_at:
                self.seen_active = False
                self._set(GState.OPENING, now)
                return [Action("reload", fmt=self.fmt, start=self._resume_pos(),
                               message=f"Yeniden bağlanılıyor… ({self.retries}/{self.cfg.max_retries})")]
        return []

    # ------------------------------------------------------------------ hata yolu
    def _on_ended(self, now: float) -> list[Action]:
        if not self.is_live and self.duration and (self.last_pos or 0) >= self.duration - self.cfg.vod_end_margin:
            self._set(GState.FINISHED, now)
            return [Action("finished", message="Bitti")]
        return self._fail(now, "Yayın kesildi")

    def _fail(self, now: float, reason: str) -> list[Action]:
        code = self.http_error
        self.retries += 1
        self.fails_on_fmt += 1
        self.stats.reconnects += 1
        self.seen_active = False
        out: list[Action] = [Action("stop")]

        # Yetki hatası: önce farklı oynatıcı kimliği (User-Agent) dene.
        # 403 bağlantı limitinden de gelebilir → aynı kimlikle ikinci kez 403 gelirse döndür.
        if code == 401:
            self.saw_401 = True
        self.ua_403 = self.ua_403 + 1 if code == 403 else 0
        if self.ua_index + 1 < self.ua_count and (code == 401 or self.ua_403 >= 2):
            self.retries -= 1                 # kimlik denemeleri tekrar hakkından düşmez
            self.ua_index += 1
            self.fails_on_fmt = 0
            self.ua_403 = 0
            delay = 0.5 if code == 401 else self.cfg.limit_backoff
            self.reconnect_at = now + delay
            self._set(GState.WAITING, now)
            reason = f"Sunucu yetki vermedi (HTTP {code})"
            self.stats.last_reason = reason
            out.append(Action("switch_ua", level=self.ua_index))
            out.append(Action("status", message=f"{reason} → farklı oynatıcı kimliği deneniyor "
                                                f"({self.ua_index}/{self.ua_count - 1})"))
            return out

        if code in (401, 404, 410):
            # yayın yok / yetki yok: birkaç denemeden sonra pes et
            reason = "Kanal yayında değil (HTTP %d)" % code if code != 401 else "Sunucu yetki vermedi (HTTP 401)"
            if self.retries >= 2 and not (self.is_live and self.fmt_index == 0 and len(self.formats) > 1):
                self._set(GState.FAILED, now)
                self.stats.last_reason = reason
                return out + [Action("give_up", message=reason)]

        if self.retries > self.cfg.max_retries:
            self._set(GState.FAILED, now)
            self.stats.last_reason = reason
            return out + [Action("give_up", message=f"{reason}. {self.cfg.max_retries} deneme başarısız.")]

        extra = ""
        if self.is_live and len(self.formats) > 1 and (self.fails_on_fmt >= self.cfg.format_switch_after
                                                       or code in (401, 404, 410)):
            if code not in (401, 404, 410):    # 404 kanala özeldir, formatı suçlama
                self.switched_from = self.fmt
            self.fmt_index = (self.fmt_index + 1) % len(self.formats)
            self.fails_on_fmt = 0
            self.stats.format_switches += 1
            extra = f" → {FORMAT_NAMES.get(self.fmt, self.fmt)} deneniyor"

        delay = self.cfg.backoff[min(self.retries - 1, len(self.cfg.backoff) - 1)]
        if code in (403, 429, 458, 503, 509):
            delay = max(delay, self.cfg.limit_backoff)
            reason += " (bağlantı limiti dolu olabilir)"
        self.stats.last_reason = reason
        self.reconnect_at = now + delay
        self._set(GState.WAITING, now)
        out.append(Action("status", message=f"{reason}{extra} — {delay:.1f} sn sonra tekrar ({self.retries}/{self.cfg.max_retries})"))
        return out
