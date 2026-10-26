"""Bilgi panelleri (canlı/film/dizi) ve oynatıcı kontrol çubuğu."""
from __future__ import annotations

import time
from datetime import datetime

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtWidgets import (QComboBox, QFrame, QHBoxLayout, QLabel, QListWidget, QListWidgetItem,
                               QProgressBar, QPushButton, QSlider, QToolButton, QVBoxLayout, QWidget)

from .icons import icon
from .theme import C


def fmt_time(sec: float) -> str:
    sec = int(max(0, sec or 0))
    h, rem = divmod(sec, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"


def hm(ts: float) -> str:
    return datetime.fromtimestamp(ts).strftime("%H:%M")


def _label(text="", obj=None, wrap=False):
    lb = QLabel(text)
    if obj:
        lb.setObjectName(obj)
    if wrap:
        lb.setWordWrap(True)
    lb.setTextInteractionFlags(Qt.TextSelectableByMouse)
    return lb


class _ImageLabel(QLabel):
    def __init__(self, w, h, radius=10):
        super().__init__()
        self.setFixedSize(w, h)
        self.setAlignment(Qt.AlignCenter)
        self.setStyleSheet(f"background:{C['panel2']}; border-radius:{radius}px; color:{C['dim']};")

    def set_pixmap(self, pm):
        if pm is None or pm.isNull():
            self.clear()
            return
        self.setPixmap(pm.scaled(self.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation))


# --------------------------------------------------------------------------- boş durum
class WelcomePanel(QWidget):
    def __init__(self):
        super().__init__()
        self.setObjectName("InfoPanel")
        lay = QHBoxLayout(self)
        lay.setContentsMargins(22, 16, 22, 16)
        col = QVBoxLayout()
        t = _label("Hoş geldin 👋", "H1")
        col.addWidget(t)
        col.addWidget(_label("Soldan bir kategori, ortadan bir kanal seç. Kanala tıklamak yeterli.", "Muted", True))
        col.addStretch(1)
        lay.addLayout(col, 1)
        keys = [("F / çift tık", "Tam ekran"), ("Boşluk", "Duraklat"), ("PgUp / PgDn", "Kanal değiştir"),
                ("Rakamlar", "Kanal numarası"), ("← / →", "10 sn geri/ileri (canlıda da)"),
                ("I", "Yayın sağlığı paneli"), ("M", "Sessiz"), ("Sağ tık", "Ses/altyazı/görüntü")]
        grid = QVBoxLayout()
        for k, v in keys:
            row = QHBoxLayout()
            kl = QLabel(k)
            kl.setObjectName("Badge")
            kl.setMinimumWidth(110)
            kl.setAlignment(Qt.AlignCenter)
            row.addWidget(kl)
            row.addWidget(_label(v, "Muted"))
            row.addStretch(1)
            grid.addLayout(row)
        lay.addLayout(grid)


# --------------------------------------------------------------------------- canlı
class LiveInfoPanel(QWidget):
    fav_clicked = Signal()
    copy_clicked = Signal()

    def __init__(self):
        super().__init__()
        self.setObjectName("InfoPanel")
        lay = QHBoxLayout(self)
        lay.setContentsMargins(18, 14, 18, 14)
        lay.setSpacing(16)
        self.logo = _ImageLabel(64, 64, 12)
        lay.addWidget(self.logo, 0, Qt.AlignTop)

        mid = QVBoxLayout()
        mid.setSpacing(4)
        self.name = _label("", "H1")
        self.now_title = _label("", "H2", True)
        self.now_time = _label("", "Muted")
        self.prog = QProgressBar()
        self.prog.setTextVisible(False)
        self.prog.setRange(0, 1000)
        self.prog.setFixedHeight(4)
        self.desc = _label("", "Muted", True)
        self.desc.setMaximumHeight(54)
        self.next = _label("", "Muted")
        mid.addWidget(self.name)
        mid.addWidget(self.now_title)
        row = QHBoxLayout()
        row.addWidget(self.now_time)
        row.addWidget(self.prog, 1)
        mid.addLayout(row)
        mid.addWidget(self.desc)
        mid.addWidget(self.next)
        mid.addStretch(1)
        btns = QHBoxLayout()
        self.fav_btn = QPushButton(icon("star_o", C["warn"], 16), " Favori")
        self.fav_btn.clicked.connect(self.fav_clicked)
        self.copy_btn = QPushButton("Adresi kopyala")
        self.copy_btn.setToolTip("Yayın adresini panoya kopyalar (ör. VLC'de denemek için)")
        self.copy_btn.clicked.connect(self.copy_clicked)
        btns.addWidget(self.fav_btn)
        btns.addWidget(self.copy_btn)
        btns.addStretch(1)
        mid.addLayout(btns)
        lay.addLayout(mid, 1)

        right = QVBoxLayout()
        right.addWidget(_label("SIRADAKİLER", "SectionTitle"))
        self.upcoming = QListWidget()
        self.upcoming.setObjectName("Upcoming")
        self.upcoming.setFixedWidth(260)
        self.upcoming.setFocusPolicy(Qt.NoFocus)
        right.addWidget(self.upcoming, 1)
        lay.addLayout(right)

    def set_channel(self, item: dict) -> None:
        self.name.setText(item.get("name", ""))
        self.now_title.setText("Yayın akışı yükleniyor…")
        self.now_time.setText("")
        self.prog.setValue(0)
        self.desc.setText("")
        self.next.setText("")
        self.upcoming.clear()

    def set_fav(self, fav: bool) -> None:
        self.fav_btn.setIcon(icon("star" if fav else "star_o", C["warn"], 16))
        self.fav_btn.setText(" Favorilerde" if fav else " Favori")

    def set_epg(self, cur, nxt, upcoming) -> None:
        now = time.time()
        if cur:
            self.now_title.setText(cur.title or "—")
            left = max(0, int((cur.stop - now) / 60))
            self.now_time.setText(f"{hm(cur.start)} – {hm(cur.stop)}  ·  {left} dk kaldı")
            self.prog.setValue(int(cur.progress(now) * 1000))
            self.desc.setText(cur.description or "")
        else:
            self.now_title.setText("Yayın akışı bilgisi yok")
            self.now_time.setText("")
            self.prog.setValue(0)
            self.desc.setText("")
        self.next.setText(f"Sonra: {hm(nxt.start)}  {nxt.title}" if nxt else "")
        self.upcoming.clear()
        for e in upcoming:
            if cur and e.start == cur.start:
                continue
            QListWidgetItem(f"{hm(e.start)}   {e.title}", self.upcoming)


# --------------------------------------------------------------------------- film
class VodInfoPanel(QWidget):
    play_clicked = Signal(bool)          # from_start
    fav_clicked = Signal()

    def __init__(self):
        super().__init__()
        self.setObjectName("InfoPanel")
        lay = QHBoxLayout(self)
        lay.setContentsMargins(18, 14, 18, 14)
        lay.setSpacing(18)
        self.poster = _ImageLabel(130, 195)
        lay.addWidget(self.poster, 0, Qt.AlignTop)
        col = QVBoxLayout()
        col.setSpacing(6)
        self.title = _label("", "H1", True)
        self.meta = _label("", "Muted", True)
        self.plot = _label("", None, True)
        self.plot.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        self.people = _label("", "Muted", True)
        col.addWidget(self.title)
        col.addWidget(self.meta)
        col.addWidget(self.plot, 1)
        col.addWidget(self.people)
        btns = QHBoxLayout()
        self.resume_btn = QPushButton(icon("play", "#06261F", 16), " Devam et")
        self.resume_btn.setObjectName("Primary")
        self.resume_btn.clicked.connect(lambda: self.play_clicked.emit(False))
        self.play_btn = QPushButton(icon("play", C["text"], 16), " Baştan oynat")
        self.play_btn.clicked.connect(lambda: self.play_clicked.emit(True))
        self.fav_btn = QPushButton(icon("star_o", C["warn"], 16), " Favori")
        self.fav_btn.clicked.connect(self.fav_clicked)
        btns.addWidget(self.resume_btn)
        btns.addWidget(self.play_btn)
        btns.addWidget(self.fav_btn)
        btns.addStretch(1)
        col.addLayout(btns)
        lay.addLayout(col, 1)

    def set_item(self, item: dict, resume: tuple | None) -> None:
        self.title.setText(item.get("name", ""))
        self.meta.setText("Bilgiler yükleniyor…")
        self.plot.setText("")
        self.people.setText("")
        self.poster.set_pixmap(None)
        self.set_resume(resume)

    def set_resume(self, resume: tuple | None) -> None:
        if resume and resume[0] > 0:
            self.resume_btn.setText(f" Devam et ({fmt_time(resume[0])})")
            self.resume_btn.show()
            self.play_btn.setText(" Baştan oynat")
            self.play_btn.setObjectName("")
        else:
            self.resume_btn.hide()
            self.play_btn.setText(" Oynat")
            self.play_btn.setObjectName("Primary")
        self.play_btn.style().unpolish(self.play_btn)
        self.play_btn.style().polish(self.play_btn)
        self.play_btn.setIcon(icon("play", "#06261F" if self.play_btn.objectName() == "Primary" else C["text"], 16))

    def set_fav(self, fav: bool) -> None:
        self.fav_btn.setIcon(icon("star" if fav else "star_o", C["warn"], 16))
        self.fav_btn.setText(" Favorilerde" if fav else " Favori")

    def set_info(self, info: dict) -> None:
        i = info.get("info") or {}
        bits = []
        year = str(i.get("releasedate") or i.get("release_date") or i.get("year") or "")[:4]
        if year.strip():
            bits.append(year)
        if i.get("genre"):
            bits.append(str(i["genre"]))
        if i.get("duration"):
            bits.append(str(i["duration"]))
        if i.get("rating"):
            bits.append(f"★ {i['rating']}")
        self.meta.setText("  ·  ".join(bits))
        self.plot.setText(str(i.get("plot") or i.get("description") or ""))
        people = []
        if i.get("director"):
            people.append(f"Yönetmen: {i['director']}")
        if i.get("cast") or i.get("actors"):
            people.append(f"Oyuncular: {i.get('cast') or i.get('actors')}")
        self.people.setText("\n".join(people))


# --------------------------------------------------------------------------- dizi
class SeriesPanel(QWidget):
    episode_activated = Signal(dict)
    fav_clicked = Signal()
    season_changed = Signal(int)

    def __init__(self):
        super().__init__()
        self.setObjectName("InfoPanel")
        lay = QHBoxLayout(self)
        lay.setContentsMargins(18, 14, 18, 14)
        lay.setSpacing(18)
        self.poster = _ImageLabel(110, 165)
        lay.addWidget(self.poster, 0, Qt.AlignTop)
        col = QVBoxLayout()
        col.setSpacing(6)
        self.title = _label("", "H1", True)
        self.meta = _label("", "Muted", True)
        self.plot = _label("", None, True)
        self.plot.setMaximumHeight(90)
        self.plot.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        col.addWidget(self.title)
        col.addWidget(self.meta)
        col.addWidget(self.plot)
        col.addStretch(1)
        self.fav_btn = QPushButton(icon("star_o", C["warn"], 16), " Favori")
        self.fav_btn.clicked.connect(self.fav_clicked)
        self.play_btn = QPushButton(icon("play", "#06261F", 16), " İzlemeye başla")
        self.play_btn.setObjectName("Primary")
        self.play_btn.clicked.connect(self._play_selected)
        b = QHBoxLayout()
        b.addWidget(self.play_btn)
        b.addWidget(self.fav_btn)
        b.addStretch(1)
        col.addLayout(b)
        lay.addLayout(col, 1)

        right = QVBoxLayout()
        top = QHBoxLayout()
        top.addWidget(_label("BÖLÜMLER", "SectionTitle"))
        top.addStretch(1)
        self.season = QComboBox()
        self.season.setMinimumWidth(120)
        self.season.currentIndexChanged.connect(self._season_idx)
        top.addWidget(self.season)
        right.addLayout(top)
        self.episodes = QListWidget()
        self.episodes.setObjectName("Episodes")
        self.episodes.setMinimumWidth(340)
        self.episodes.itemActivated.connect(lambda it: self.episode_activated.emit(it.data(Qt.UserRole)))
        right.addWidget(self.episodes, 1)
        lay.addLayout(right, 1)
        self._seasons: dict[int, list] = {}
        self._resume_of = None

    def set_item(self, item: dict) -> None:
        self.title.setText(item.get("name", ""))
        self.meta.setText("Bölümler yükleniyor…")
        self.plot.setText(item.get("plot", ""))
        self.poster.set_pixmap(None)
        self.season.blockSignals(True)
        self.season.clear()
        self.season.blockSignals(False)
        self.episodes.clear()
        self._seasons = {}

    def set_fav(self, fav: bool) -> None:
        self.fav_btn.setIcon(icon("star" if fav else "star_o", C["warn"], 16))
        self.fav_btn.setText(" Favorilerde" if fav else " Favori")

    def set_info(self, info: dict, resume_of, preferred_season: int | None = None) -> None:
        self._resume_of = resume_of
        i = info.get("info") or {}
        bits = []
        if i.get("genre"):
            bits.append(str(i["genre"]))
        if i.get("releaseDate") or i.get("releasedate"):
            bits.append(str(i.get("releaseDate") or i.get("releasedate"))[:4])
        if i.get("rating"):
            bits.append(f"★ {i['rating']}")
        self._seasons = info.get("episodes") or {}
        n_eps = sum(len(v) for v in self._seasons.values())
        bits.append(f"{len(self._seasons)} sezon · {n_eps} bölüm")
        self.meta.setText("  ·  ".join(bits))
        if i.get("plot"):
            self.plot.setText(str(i["plot"]))
        self.season.blockSignals(True)
        self.season.clear()
        for sn in self._seasons:
            self.season.addItem(f"Sezon {sn}", sn)
        self.season.blockSignals(False)
        if self._seasons:
            idx = 0
            if preferred_season is not None:
                for k in range(self.season.count()):
                    if self.season.itemData(k) == preferred_season:
                        idx = k
            self.season.setCurrentIndex(idx)
            self._season_idx(idx)
        else:
            self.meta.setText("Bu dizide bölüm bulunamadı")

    def current_season(self) -> int | None:
        return self.season.currentData()

    def _season_idx(self, idx: int) -> None:
        sn = self.season.itemData(idx)
        self.episodes.clear()
        if sn is None:
            return
        for ep in self._seasons.get(sn, []):
            dur = (ep.get("info") or {}).get("duration") or ""
            mark = ""
            if self._resume_of:
                r = self._resume_of(str(ep.get("id")))
                if r == "done":
                    mark = "✓ "
                elif r:
                    mark = f"▶ {fmt_time(r[0])} · "
            title = str(ep.get("title") or f"Bölüm {ep.get('episode_num')}")
            it = QListWidgetItem(f"{mark}{ep.get('episode_num', '')}. {title}" + (f"   ({dur})" if dur else ""))
            it.setData(Qt.UserRole, ep)
            self.episodes.addItem(it)
        self.season_changed.emit(int(sn))

    def refresh_marks(self) -> None:
        self._season_idx(self.season.currentIndex())

    def _play_selected(self) -> None:
        it = self.episodes.currentItem() or (self.episodes.item(0) if self.episodes.count() else None)
        if it:
            self.episode_activated.emit(it.data(Qt.UserRole))


# --------------------------------------------------------------------------- kontrol çubuğu
class PlayerBar(QWidget):
    play_pause = Signal()
    seek_rel = Signal(int)
    seek_abs = Signal(float)
    go_live = Signal()
    retry = Signal()
    volume_changed = Signal(int)
    mute_clicked = Signal()
    menu_clicked = Signal()
    fullscreen_clicked = Signal()

    def __init__(self):
        super().__init__()
        self.setObjectName("PlayerBar")
        self.setFixedHeight(46)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(10, 4, 10, 4)
        lay.setSpacing(4)

        def tb(name, tip, sig):
            b = QToolButton()
            b.setIcon(icon(name, C["text"], 20))
            b.setIconSize(QSize(20, 20))
            b.setToolTip(tip)
            b.clicked.connect(sig)
            lay.addWidget(b)
            return b

        self.pp = tb("pause", "Duraklat / Devam (Boşluk)", self.play_pause.emit)
        self.back = tb("back", "10 sn geri (←)", lambda: self.seek_rel.emit(-10))
        self.fwd = tb("fwd", "10 sn ileri (→)", lambda: self.seek_rel.emit(10))
        self.live_btn = QPushButton(icon("live", "#FF5A5A", 14), " CANLI")
        self.live_btn.setToolTip("Canlı yayına dön")
        self.live_btn.setStyleSheet("QPushButton{background:transparent;border:none;font-weight:700;color:%s;"
                                    "padding:4px 8px;} QPushButton:hover{color:%s;}" % (C["muted"], C["text"]))
        self.live_btn.clicked.connect(self.go_live.emit)
        lay.addWidget(self.live_btn)
        self.retry_btn = tb("refresh", "Yeniden bağlan", self.retry.emit)

        self.pos_lbl = QLabel("00:00")
        self.pos_lbl.setObjectName("Muted")
        lay.addWidget(self.pos_lbl)
        self.slider = QSlider(Qt.Horizontal)
        self.slider.setRange(0, 1000)
        self.slider.sliderReleased.connect(self._released)
        self._dur = 0.0
        self._dragging = False
        self.slider.sliderPressed.connect(lambda: setattr(self, "_dragging", True))
        lay.addWidget(self.slider, 1)
        self.dur_lbl = QLabel("00:00")
        self.dur_lbl.setObjectName("Muted")
        lay.addWidget(self.dur_lbl)
        self.spacer = QWidget()
        lay.addWidget(self.spacer, 1)

        self.health = QLabel("")
        self.health.setObjectName("Muted")
        self.health.setMinimumWidth(10)
        lay.addWidget(self.health)

        self.mute_btn = tb("volume", "Sessiz (M)", self.mute_clicked.emit)
        self.vol = QSlider(Qt.Horizontal)
        self.vol.setRange(0, 150)
        self.vol.setFixedWidth(90)
        self.vol.valueChanged.connect(self.volume_changed.emit)
        lay.addWidget(self.vol)
        tb("dots", "Ses, altyazı, görüntü (sağ tık)", self.menu_clicked.emit)
        tb("fullscreen", "Tam ekran (F)", self.fullscreen_clicked.emit)
        self.set_mode(True)

    def _released(self):
        self._dragging = False
        if self._dur > 0:
            self.seek_abs.emit(self.slider.value() / 1000 * self._dur)

    def set_mode(self, live: bool) -> None:
        for w in (self.slider, self.pos_lbl, self.dur_lbl):
            w.setVisible(not live)
        self.spacer.setVisible(live)
        self.live_btn.setVisible(live)

    def set_paused(self, paused: bool) -> None:
        self.pp.setIcon(icon("play" if paused else "pause", C["text"], 20))

    def set_muted(self, muted: bool) -> None:
        self.mute_btn.setIcon(icon("mute" if muted else "volume", C["text"], 20))

    def set_volume(self, v: int) -> None:
        self.vol.blockSignals(True)
        self.vol.setValue(v)
        self.vol.blockSignals(False)

    def set_position(self, pos: float, dur: float) -> None:
        self._dur = dur
        self.pos_lbl.setText(fmt_time(pos))
        self.dur_lbl.setText(fmt_time(dur))
        if not self._dragging and dur > 0:
            self.slider.blockSignals(True)
            self.slider.setValue(int(pos / dur * 1000))
            self.slider.blockSignals(False)

    def set_health(self, text: str, level: str) -> None:
        col = {"ok": C["ok"], "warn": C["warn"], "error": C["error"]}.get(level, C["muted"])
        self.health.setText(f"<span style='color:{col}'>●</span> {text}")


class Divider(QFrame):
    def __init__(self):
        super().__init__()
        self.setFixedWidth(1)
        self.setStyleSheet(f"background:{C['line']};")
