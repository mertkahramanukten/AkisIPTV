"""mpv tabanlı oynatıcı + StreamGuard entegrasyonu.

Donma/açılmama sorunlarına karşı katmanlar:
1. ffmpeg seviyesinde: reconnect, reconnect_streamed, reconnect_on_network_error (anlık kopmalar).
2. mpv seviyesinde: büyük demuxer cache, cache-pause-wait (takılınca birkaç saniye biriktirip devam),
   donanımsal çözme (CPU kaynaklı kasma), User-Agent.
3. Uygulama seviyesinde (StreamGuard): donma/kopma tespiti, artan beklemeli yeniden bağlanma,
   TS↔HLS geçişi, adaptif buffer, filmde kaldığı saniyeden devam.
4. Bağlantı limiti: kanal değiştirirken önce eski bağlantı kapatılır, kısa beklenir, sonra
   yenisi açılır (1 bağlantılı hesaplarda "kanal açılmıyor" sorununun en yaygın sebebi).
"""
from __future__ import annotations

import logging
import os
import re
import time
from dataclasses import dataclass, field

from PySide6.QtCore import QObject, Qt, QTimer, Signal
from PySide6.QtWidgets import QFrame, QSizePolicy

from .config import bin_dirs
from .guard import BUFFER_LEVELS, BUFFER_PROFILES, FORMAT_NAMES, GState, GuardConfig, StreamGuard

log = logging.getLogger(__name__)

_mpv_module = None


class MpvMissing(RuntimeError):
    pass


def load_mpv():
    """libmpv-2.dll'i bin/ klasöründen bulup python-mpv'yi yükler."""
    global _mpv_module
    if _mpv_module is not None:
        return _mpv_module
    for d in bin_dirs():
        if any((d / n).exists() for n in ("libmpv-2.dll", "mpv-2.dll", "mpv-1.dll")):
            os.environ["PATH"] = str(d) + os.pathsep + os.environ.get("PATH", "")
            if hasattr(os, "add_dll_directory"):
                try:
                    os.add_dll_directory(str(d))
                except OSError:
                    pass
            break
    try:
        import mpv  # noqa: WPS433
    except (OSError, ImportError) as e:
        raise MpvMissing(str(e)) from e
    _mpv_module = mpv
    return mpv


@dataclass
class PlayItem:
    kind: str                    # live | vod | episode
    item_id: str
    title: str
    urls: dict                   # format -> url
    formats: list                # tercih sırası
    start: float = 0.0
    resume_key: str | None = None
    meta: dict = field(default_factory=dict)

    @property
    def is_live(self) -> bool:
        return self.kind == "live"


class VideoSurface(QFrame):
    """mpv'nin çizim yaptığı yerel (native) pencere.

    mpv'nin kendi alt penceresi girişe kapatılır (bkz. PlayerController._release_input);
    böylece fare ve klavye olayları doğrudan buraya, yani Qt'ye gelir. mpv-tarzı tuş adları
    yayınlanır ("MBTN_LEFT_DBL", "MBTN_RIGHT", "WHEEL_UP", "LEFT"…) ve ana pencere işler.
    """
    key = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WA_DontCreateNativeAncestors)
        self.setAttribute(Qt.WA_NativeWindow)
        self.setAttribute(Qt.WA_NoSystemBackground)
        self.setStyleSheet("background-color: #000;")
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.setMinimumSize(320, 180)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setMouseTracking(True)
        self._hide_timer = QTimer(self)
        self._hide_timer.setSingleShot(True)
        self._hide_timer.setInterval(2000)
        self._hide_timer.timeout.connect(lambda: self.setCursor(Qt.BlankCursor))

    def mouseMoveEvent(self, e):
        self.unsetCursor()
        self._hide_timer.start()
        super().mouseMoveEvent(e)

    def leaveEvent(self, e):
        self._hide_timer.stop()
        self.unsetCursor()
        super().leaveEvent(e)

    def mousePressEvent(self, e):
        self.setFocus(Qt.MouseFocusReason)
        if e.button() == Qt.RightButton:
            self.key.emit("MBTN_RIGHT")
        elif e.button() == Qt.MiddleButton:
            self.key.emit("m")
        super().mousePressEvent(e)

    def mouseDoubleClickEvent(self, e):
        if e.button() == Qt.LeftButton:
            self.key.emit("MBTN_LEFT_DBL")

    def wheelEvent(self, e):
        dy = e.angleDelta().y()
        if dy:
            self.key.emit("WHEEL_UP" if dy > 0 else "WHEEL_DOWN")
        e.accept()

    def keyPressEvent(self, e):
        names = {Qt.Key_Left: "LEFT", Qt.Key_Right: "RIGHT", Qt.Key_Up: "UP", Qt.Key_Down: "DOWN",
                 Qt.Key_Return: "ENTER", Qt.Key_Enter: "ENTER", Qt.Key_Home: "HOME", Qt.Key_End: "END",
                 Qt.Key_A: "a"}
        n = names.get(e.key())
        if n and not (e.modifiers() & (Qt.ControlModifier | Qt.AltModifier)):
            self.key.emit(n)
            e.accept()
            return
        super().keyPressEvent(e)


# HTTP 401 alınca sırayla denenecek oynatıcı kimlikleri (User-Agent). Birçok sağlayıcı yalnızca
# tanıdığı uygulamalara yayın verir; çalışan kimlik bulununca profil için hatırlanır.
UA_FALLBACKS = [
    "IPTVSmartersPlayer",
    "okhttp/4.12.0",
    "Lavf/61.7.100",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36",
    "TiviMate/5.1.6 (Android 12)",
    "Kodi/21.1 (Windows NT 10.0.22631; Win64; x64) App_Bitness/64 Version/21.1",
]

HTTP_RE = re.compile(r"(?:HTTP error|Server returned)\s+(\d{3})")


class PlayerController(QObject):
    status = Signal(str, str)              # mesaj, seviye: info|ok|warn|error
    stats = Signal(object)
    position = Signal(float, float)        # pos, duration
    started = Signal(object)               # PlayItem
    finished = Signal(object)              # PlayItem
    gave_up = Signal(object, str)
    resume_point = Signal(str, float, float)
    format_feedback = Signal(str, bool)
    buffer_changed = Signal(int)
    ua_learned = Signal(str)               # 401 sonrası çalışan User-Agent

    _prop = Signal(str, object)
    _logsig = Signal(str, str, str)

    def __init__(self, surface: VideoSurface, settings, parent=None):
        super().__init__(parent)
        self.surface = surface
        self.settings = settings
        mpv = load_mpv()
        level = BUFFER_PROFILES.get(settings.get("buffer_profile"), 1)
        self.guard = StreamGuard(GuardConfig(adaptive=bool(settings.get("adaptive_buffer", True))), level)
        self.current: PlayItem | None = None
        self._pending: tuple | None = None
        self._last_resume_emit = 0.0
        self._last_pos = None
        self._show_stats = bool(settings.get("show_stats", False))
        self._log_counts: dict[str, int] = {}
        self._ffmpeg_reconnects = 0
        self._last_status = ""
        self._last_load_t = 0.0
        self.preferred_ua: str | None = None   # profil için daha önce çalıştığı görülen kimlik
        self.ua_list: list[str] = []

        opts = self._base_options()
        log.info("mpv seçenekleri: %s", {k: v for k, v in opts.items() if k != "user_agent"})
        self.mpv = mpv.MPV(wid=str(int(surface.winId())), log_handler=self._log_cb, loglevel="warn", **opts)
        try:
            log.info("mpv sürümü: %s", self.mpv.mpv_version)
        except Exception:
            pass

        self._prop.connect(self._on_prop)
        self._logsig.connect(self._on_log)
        for name in ("idle-active", "paused-for-cache"):
            self.mpv.observe_property(name, self._obs)
        self._release_input()

        self._load_timer = QTimer(self)
        self._load_timer.setSingleShot(True)
        self._load_timer.timeout.connect(self._do_load)

        self._tick = QTimer(self)
        self._tick.setInterval(500)
        self._tick.timeout.connect(self._on_tick)
        self._tick.start()
        self._stats_n = 0

    # ------------------------------------------------------------------ mpv ayarları
    def _base_options(self) -> dict:
        s = self.settings
        level = BUFFER_PROFILES.get(s.get("buffer_profile"), 1)
        analyze = {0: 0.8, 1: 1.5, 3: 3.0}.get(level, 1.5)
        return dict(
            idle="yes",
            force_window="yes",
            keep_open="no",
            input_default_bindings=False,
            input_vo_keyboard=False,
            input_cursor=False,
            osc=False,
            ytdl=False,
            load_scripts=False,
            hwdec="auto-safe" if s.get("hwdec", True) else "no",
            cache="yes",
            cache_pause="yes",
            cache_pause_initial="yes",
            cache_pause_wait=BUFFER_LEVELS[level],
            demuxer_max_bytes="192MiB",
            demuxer_max_back_bytes="96MiB",
            demuxer_readahead_secs=20,
            demuxer_lavf_analyzeduration=analyze,
            network_timeout=15,
            user_agent=s.get("user_agent"),
            stream_lavf_o="reconnect=1,reconnect_streamed=1,reconnect_on_network_error=1,reconnect_delay_max=4",
            hls_bitrate="max",
            framedrop="vo",
            volume=int(s.get("volume", 80)),
            volume_max=150,
            cursor_autohide="no",
            osd_font="Segoe UI",
            osd_font_size=30,
            osd_border_size=2,
            osd_duration=1800,
            sub_auto="no",
            audio_file_auto="no",
            screenshot_directory="~~desktop/",
        )

    def apply_settings(self) -> None:
        """Ayarlar penceresinden sonra çalışırken uygulanabilenler."""
        s = self.settings
        self._set("hwdec", "auto-safe" if s.get("hwdec", True) else "no")
        self._set("user-agent", s.get("user_agent"))
        level = BUFFER_PROFILES.get(s.get("buffer_profile"), 1)
        self.guard.base_level = level
        self.guard.buffer_level = level
        self.guard.cfg.adaptive = bool(s.get("adaptive_buffer", True))
        self._apply_buffer(level)
        self._show_stats = bool(s.get("show_stats", False))
        if not self._show_stats:
            self._clear_overlay()

    def _apply_buffer(self, level: int) -> None:
        level = max(0, min(level, len(BUFFER_LEVELS) - 1))
        wait = BUFFER_LEVELS[level]
        self._set("cache-pause-wait", wait)
        live = self.current.is_live if self.current else True
        self._set("demuxer-readahead-secs", max(20, int(wait * 6)) if live else 90)
        self.buffer_changed.emit(level)

    # ------------------------------------------------------------------ güvenli erişim
    # Not: python-mpv'de mpv["x"] *seçenek* (options/x) okur; çalışma zamanı *özellikleri*
    # (time-pos, idle-active, demuxer-cache-duration…) ancak öznitelik olarak okunabilir.
    def _get(self, name):
        try:
            return getattr(self.mpv, name.replace("-", "_"))
        except Exception:
            return None

    def _set(self, name, value) -> None:
        try:
            setattr(self.mpv, name.replace("-", "_"), value)
        except Exception as e:
            log.debug("mpv.%s = %r başarısız: %s", name, value, e)

    def _cmd(self, *args) -> None:
        try:
            self.mpv.command(*[str(a) for a in args])
        except Exception as e:
            log.debug("mpv komutu başarısız %s: %s", args, e)

    def osd(self, text: str, ms: int = 2200) -> None:
        self._cmd("show-text", text, ms)

    # ------------------------------------------------------------------ mpv thread → Qt thread
    def _obs(self, name, value):
        self._prop.emit(name, value)

    def _log_cb(self, level, component, message):
        self._logsig.emit(str(level), str(component), str(message).strip())

    def _release_input(self) -> None:
        """mpv'nin alt pencerelerini girişe kapatır → fare/klavye Qt'deki VideoSurface'e düşer.

        (Windows'ta devre dışı bırakılmış bir alt pencerenin fare mesajları üst pencereye iletilir.)
        """
        if os.name != "nt":
            return
        try:
            import ctypes
            from ctypes import wintypes
            user32 = ctypes.windll.user32
            parent = int(self.surface.winId())
            found = []
            proc_t = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

            def cb(hwnd, _lp):
                found.append(hwnd)
                return True

            user32.EnumChildWindows(wintypes.HWND(parent), proc_t(cb), 0)
            for hwnd in found:
                if user32.IsWindowEnabled(hwnd):
                    user32.EnableWindow(hwnd, False)
                    log.info("mpv penceresi girişe kapatıldı (hwnd=%s)", hwnd)
        except Exception as e:
            log.debug("mpv penceresi ayarlanamadı: %s", e)

    # ------------------------------------------------------------------ oynatma
    def play(self, item: PlayItem) -> None:
        self._save_resume()
        self.current = item
        self._ffmpeg_reconnects = 0
        self._log_counts.clear()
        self._last_pos = None
        self.guard.buffer_level = self.guard.base_level
        self._apply_buffer(self.guard.base_level)
        self._set("force-seekable", "yes" if item.is_live else "no")
        first = self.preferred_ua or self.settings.get("user_agent")
        self.ua_list = list(dict.fromkeys([u for u in [first, self.settings.get("user_agent"), *UA_FALLBACKS] if u]))
        self._set("user-agent", self.ua_list[0])
        self._run(self.guard.start(time.monotonic(), item.is_live, item.formats, item.start,
                                   ua_count=len(self.ua_list)))
        self.started.emit(item)

    def stop(self) -> None:
        self._save_resume()
        self._load_timer.stop()
        self.guard.stop(time.monotonic())
        self.current = None
        self._cmd("stop")
        self._clear_overlay()
        self.status.emit("Durduruldu", "info")

    def retry(self) -> None:
        if self.current:
            item = self.current
            if not item.is_live and self._last_pos:
                item.start = max(0.0, self._last_pos - 3)
            self.play(item)

    def _run(self, actions) -> None:
        for a in actions:
            k = a.kind
            if k == "reload":
                self._schedule_load(a.fmt, a.start or 0.0, a.message)
            elif k == "stop":
                self._load_timer.stop()
                self._cmd("stop")
            elif k == "status":
                lvl = "ok" if a.message.startswith(("Oynatılıyor", "Yeniden bağlandı")) else "warn"
                self._emit_status(a.message, lvl)
                if lvl == "warn":
                    self.osd(a.message, 3000)
            elif k == "raise_buffer":
                self._apply_buffer(a.level)
                self._emit_status(a.message, "warn")
                self.osd(a.message, 2500)
            elif k == "give_up":
                self._cmd("stop")
                self._emit_status(a.message, "error")
                self.osd(a.message, 6000)
                if self.current:
                    self.gave_up.emit(self.current, a.message)
            elif k == "finished":
                self._save_resume(finished=True)
                if self.current:
                    self.finished.emit(self.current)
            elif k in ("format_ok", "format_bad"):
                self.format_feedback.emit(a.fmt or "", k == "format_ok")
            elif k == "switch_ua":
                if 0 <= a.level < len(self.ua_list):
                    ua = self.ua_list[a.level]
                    self._set("user-agent", ua)
                    log.info("401 sonrası oynatıcı kimliği değiştirildi: %s", ua)
            elif k == "ua_ok":
                if 0 <= a.level < len(self.ua_list):
                    self.preferred_ua = self.ua_list[a.level]
                    self.ua_learned.emit(self.preferred_ua)

    def _emit_status(self, msg: str, level: str) -> None:
        if msg != self._last_status:
            log.log(logging.WARNING if level in ("warn", "error") else logging.INFO, "Durum: %s", msg)
        self._last_status = msg
        self.status.emit(msg, level)

    def _schedule_load(self, fmt: str, start: float, message: str) -> None:
        if not self.current:
            return
        url = self.current.urls.get(fmt) or next(iter(self.current.urls.values()), None)
        if not url:
            self._emit_status("Oynatılacak adres yok", "error")
            return
        self._cmd("stop")   # bağlantı limitini boşa çıkar
        self._pending = (url, start, fmt)
        # Daha önce bir yayın açıldıysa sunucunun o bağlantıyı düşürmesi için nefes payı bırak.
        # Hızlı zaplamada her yeni istek zamanlayıcıyı sıfırlar → yalnızca son seçilen kanal açılır
        # (1 bağlantılı hesaplarda "kanal açılmıyor / 403" sorununun ana sebebi buydu).
        self._load_timer.start(0 if self._last_load_t == 0 else 400)
        self._emit_status(f"{message or 'Bağlanıyor…'} [{FORMAT_NAMES.get(fmt, fmt.upper())}]", "info")

    def _do_load(self) -> None:
        if not self._pending or not self.current:
            return
        url, start, fmt = self._pending
        self._pending = None
        self._last_load_t = time.monotonic()
        self.guard.mark_loading(self._last_load_t)
        self._set("start", f"{start:.1f}" if start and start > 1 else "none")
        self._set("pause", False)
        safe = re.sub(r"/(live|movie|series)/[^/]+/[^/]+/", r"/\1/***/***/", url)
        log.info("loadfile %s (fmt=%s, start=%.1f)", safe, fmt, start or 0)
        self._cmd("loadfile", url, "replace")

    # ------------------------------------------------------------------ olaylar
    def _on_prop(self, name, value) -> None:
        now = time.monotonic()
        if name == "idle-active":
            self._run(self.guard.on_idle(now, bool(value)))
        elif name == "paused-for-cache":
            self._run(self.guard.on_cache_pause(now, bool(value)))
            if value and self.guard.state == GState.PLAYING:
                self._emit_status("Buffer dolduruluyor…", "warn")
            elif not value and self.guard.state == GState.PLAYING and self._last_status.startswith("Buffer"):
                self._emit_status("Oynatılıyor", "ok")

    def _on_log(self, level, component, message) -> None:
        m = HTTP_RE.search(message)
        if m:
            code = int(m.group(1))
            self.guard.on_http_error(code)
        if level in ("error", "fatal") and component == "stream" and message.startswith("Failed to open"):
            # Açılış hatasını idle olayını beklemeden hemen bildir (hızlı yeniden deneme)
            self._run(self.guard.on_error(time.monotonic(), "Yayın açılamadı"))
        if "reconnect" in message.lower():
            self._ffmpeg_reconnects += 1
        key = re.sub(r"\d+", "#", message)[:80]
        n = self._log_counts.get(key, 0)
        self._log_counts[key] = n + 1
        if n < 3:
            log.log(logging.ERROR if level in ("error", "fatal") else logging.INFO,
                    "mpv[%s] %s", component, re.sub(r"/(live|movie|series)/[^/\s]+/[^/\s]+/", r"/\1/***/***/", message))

    def _on_tick(self) -> None:
        now = time.monotonic()
        g = self.guard
        if g.state in (GState.OPENING, GState.PLAYING):
            pos = self._get("time-pos")
            if pos is not None:
                self._run(g.on_progress(now, pos))
                self._last_pos = float(pos)
            dur = self._get("duration")
            g.on_duration(dur)
            if self.current and not self.current.is_live and pos is not None:
                self.position.emit(float(pos), float(dur or 0))
                if now - self._last_resume_emit > 10:
                    self._last_resume_emit = now
                    self._save_resume()
        self._run(g.tick(now))

        self._stats_n += 1
        if self._stats_n % 4 == 1:
            self._release_input()   # mpv pencereyi yeniden oluşturmuş olabilir
        if self._stats_n % 2 == 0 and self.current is not None:
            st = self.collect_stats()
            self.stats.emit(st)
            if self._show_stats:
                self._draw_overlay(st)

    # ------------------------------------------------------------------ istatistik
    def collect_stats(self) -> dict:
        g = self.guard
        w, h = self._get("width"), self._get("height")
        return {
            "state": g.state.value,
            "format": FORMAT_NAMES.get(g.fmt, g.fmt),
            "buffer_s": float(self._get("demuxer-cache-duration") or 0.0),
            "speed_kbps": float(self._get("cache-speed") or 0.0) * 8 / 1000,
            "vbitrate_kbps": float(self._get("video-bitrate") or 0.0) / 1000,
            "res": f"{w}x{h}" if w and h else "",
            "fps": self._get("estimated-vf-fps") or self._get("container-fps") or 0,
            "hwdec": self._get("hwdec-current") or "yok",
            "dropped": self._get("frame-drop-count") or 0,
            "reconnects": g.stats.reconnects,
            "underruns": g.stats.underruns,
            "ffmpeg_reconnects": self._ffmpeg_reconnects,
            "buffer_level": g.buffer_level,
            "buffer_target": BUFFER_LEVELS[g.buffer_level],
            "paused_for_cache": g.cache_paused,
        }

    def _draw_overlay(self, st: dict) -> None:
        lines = [
            r"{\b1}Akış • Yayın Sağlığı{\b0}",
            f"Durum: {st['state']}   Format: {st['format']}",
            f"Buffer: {st['buffer_s']:.1f} sn  (hedef {st['buffer_target']:.1f} sn)",
            f"İndirme: {st['speed_kbps']:.0f} kbps   Video: {st['vbitrate_kbps']:.0f} kbps",
            f"Çözünürlük: {st['res'] or '-'}  {float(st['fps'] or 0):.0f} fps   HW: {st['hwdec']}",
            f"Kopma/yeniden bağlanma: {st['reconnects']}   Takılma: {st['underruns']}",
            f"ffmpeg iç reconnect: {st['ffmpeg_reconnects']}   Düşen kare: {st['dropped']}",
        ]
        text = r"{\an9}{\fs22}{\bord2}{\shad0}{\1c&HFFFFFF&}" + r"\N".join(lines)
        self._cmd("osd-overlay", 1, "ass-events", text, 0, 720, 0, "no", "no")

    def _clear_overlay(self) -> None:
        self._cmd("osd-overlay", 1, "none", "", 0, 0, 0, "no", "no")

    def toggle_stats(self) -> bool:
        self._show_stats = not self._show_stats
        if not self._show_stats:
            self._clear_overlay()
        return self._show_stats

    # ------------------------------------------------------------------ kontroller
    def toggle_pause(self) -> None:
        if not self.current:
            return
        paused = not bool(self._get("pause"))
        self._set("pause", paused)
        self.guard.on_user_pause(time.monotonic(), paused)
        self.osd("⏸ Duraklatıldı" if paused else "▶ Devam", 1000)

    def set_volume(self, v: int) -> None:
        v = max(0, min(150, int(v)))
        self._set("volume", v)
        self._set("mute", False)
        bars = int(v / 10)
        self.osd(f"Ses  {'█' * min(bars, 10)}{'░' * max(0, 10 - bars)}  {v}%", 900)

    def volume(self) -> int:
        return int(self._get("volume") or 0)

    def change_volume(self, delta: int) -> int:
        v = self.volume() + delta
        self.set_volume(v)
        return max(0, min(150, v))

    def toggle_mute(self) -> bool:
        m = not bool(self._get("mute"))
        self._set("mute", m)
        self.osd("🔇 Sessiz" if m else "🔊 Ses açık", 900)
        return m

    def seek(self, seconds: float) -> None:
        if not self.current:
            return
        pos = self._get("time-pos")
        if pos is None:
            return
        target = float(pos) + seconds
        if self.current.is_live:
            cache_end = self._get("demuxer-cache-time")
            if cache_end is not None:
                target = min(target, float(cache_end) - 1.0)
        target = max(0.0, target)
        self.guard.on_seek(time.monotonic())
        self._cmd("seek", f"{target:.2f}", "absolute")

    def seek_to(self, seconds: float) -> None:
        self.guard.on_seek(time.monotonic())
        self._cmd("seek", f"{max(0.0, seconds):.2f}", "absolute")

    def go_live(self) -> None:
        if self.current and self.current.is_live:
            end = self._get("demuxer-cache-time")
            if end is not None:
                self.seek_to(float(end) - 1.5)
                self.osd("● Canlı", 1000)

    def tracks(self, kind: str) -> list[dict]:
        out = []
        for t in self._get("track-list") or []:
            if t.get("type") == kind:
                out.append(t)
        return out

    def set_track(self, kind: str, tid) -> None:
        prop = {"audio": "aid", "sub": "sid", "video": "vid"}[kind]
        self._set(prop, tid if tid is not None else "no")

    def set_aspect(self, value: str) -> None:
        """value: 'no' (otomatik) | '16:9' | '4:3' | 'stretch' (ekrana yay)."""
        if value == "stretch":
            self._set("video-aspect-override", "no")
            self._set("keepaspect", False)
        else:
            self._set("keepaspect", True)
            self._set("video-aspect-override", value)

    def screenshot(self) -> None:
        self._cmd("screenshot")
        self.osd("📷 Ekran görüntüsü masaüstüne kaydedildi", 1500)

    # ------------------------------------------------------------------ devam et
    def _save_resume(self, finished: bool = False) -> None:
        it = self.current
        if not it or it.is_live or not it.resume_key:
            return
        pos = self._last_pos
        dur = self.guard.duration or 0.0
        if finished:
            self.resume_point.emit(it.resume_key, -1.0, dur)
        elif pos and pos > 15:
            self.resume_point.emit(it.resume_key, float(pos), float(dur))

    def shutdown(self) -> None:
        self._save_resume()
        self._tick.stop()
        try:
            self.mpv.terminate()
        except Exception:
            pass
