"""Ana pencere."""
from __future__ import annotations

import logging
import time

from PySide6.QtCore import QByteArray, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QCursor, QGuiApplication, QIcon, QKeySequence, QShortcut
from PySide6.QtWidgets import (QButtonGroup, QHBoxLayout, QLabel, QLineEdit, QListView, QListWidget,
                               QListWidgetItem, QMainWindow, QMenu, QProgressBar, QPushButton, QSplitter,
                               QStackedWidget, QToolButton, QVBoxLayout, QWidget)

from ..config import Settings, project_root
from ..images import ImageLoader
from ..library import MODES, Library
from ..player import PlayerController, PlayItem, VideoSurface
from ..workers import run_async
from ..xtream import Account, XtreamClient
from .icons import icon
from .models import (CAT_ALL, CAT_FAV, CAT_RECENT, CAT_RESUME, ChannelDelegate, ItemListModel, ItemRole,
                     PosterDelegate)
from .panels import LiveInfoPanel, PlayerBar, SeriesPanel, VodInfoPanel, WelcomePanel, fmt_time
from .settings_dialog import SettingsDialog
from .theme import C

log = logging.getLogger(__name__)

MODE_TITLES = {"live": "Canlı TV", "vod": "Filmler", "series": "Diziler"}
NOUN = {"live": "kanal", "vod": "film", "series": "dizi"}


class MainWindow(QMainWindow):
    logout_requested = Signal()
    quit_requested = Signal()

    def __init__(self, settings: Settings, client: XtreamClient, account: Account, profile: dict):
        super().__init__()
        self.settings = settings
        self.client = client
        self.account = account
        self.profile = profile
        self.pid = profile["id"]
        self.store = settings.profile_store(self.pid)
        self.setWindowTitle(profile.get("name") or profile.get("username") or "")
        self.setWindowIcon(QIcon(str(project_root() / "assets" / "icon_256.png")))
        self.resize(1440, 860)

        self.images = ImageLoader(settings.get("user_agent"), client.base)
        self.images.loaded.connect(self._on_image_loaded)
        self.lib = Library(client, self.pid)
        self.epg = self.lib.epg
        self.models = {m: ItemListModel(m, self.images, self) for m in MODES}
        self.mode = "live"
        self.cat_sel = {m: CAT_ALL for m in MODES}
        self.selected: dict[str, dict | None] = {m: None for m in MODES}
        self._vod_info: dict[str, dict] = {}
        self._series_info: dict[str, dict] = {}
        self._zap_list: list[dict] = []
        self._num_buf = ""
        self._fullscreen = False
        self._was_maximized = False
        self._saved_sizes = None
        self._dirty = False
        self._first_live = True
        self._panel_img: tuple[str, str] | None = None   # (url, hedef)
        self._next_ep: tuple | None = None
        self._logout = False
        self._info_shown: tuple | None = None
        self._pending_info: tuple | None = None
        self._sigs: dict[str, tuple] = {}

        self._build_ui()
        self._build_player()
        self._build_shortcuts()
        self._build_timers()

        self.lib.loaded.connect(self._on_loaded)
        self.lib.failed.connect(self._on_load_failed)
        self.lib.progress.connect(self._on_progress)
        self.lib.epg_ready.connect(self._on_epg_ready)

        self._restore_window()
        self._log_account()
        self.switch_mode("live")
        if getattr(self.client, "credentials_fixed", False):
            QTimer.singleShot(4000, lambda: self._status(
                "Parolan sunucudaki kayıtla harfi harfine aynı değildi (büyük/küçük harf); yayınlar için "
                "düzeltildi ve kaydedildi", "ok"))
        QTimer.singleShot(5000, self._preload_others)

    # ================================================================== arayüz
    def _build_ui(self) -> None:
        central = QWidget()
        v = QVBoxLayout(central)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(0)

        # ---- üst bar
        self.topbar = QWidget()
        self.topbar.setObjectName("TopBar")
        tl = QHBoxLayout(self.topbar)
        tl.setContentsMargins(14, 0, 10, 0)
        tl.setSpacing(4)
        logo = QLabel()
        logo.setPixmap(QIcon(str(project_root() / "assets" / "icon_256.png")).pixmap(26, 26))
        tl.addWidget(logo)
        title = QLabel("Akış")
        title.setObjectName("AppTitle")
        tl.addWidget(title)
        self.mode_group = QButtonGroup(self)
        self.mode_btns = {}
        for m in MODES:
            b = QPushButton(MODE_TITLES[m])
            b.setObjectName("Mode")
            b.setCheckable(True)
            b.setCursor(Qt.PointingHandCursor)
            b.clicked.connect(lambda _=False, mm=m: self.switch_mode(mm))
            self.mode_group.addButton(b)
            self.mode_btns[m] = b
            tl.addWidget(b)
        tl.addStretch(1)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Ara…   (Ctrl+F)")
        self.search.setClearButtonEnabled(True)
        self.search.setFixedWidth(300)
        self.search.addAction(icon("search", C["muted"], 16), QLineEdit.LeadingPosition)
        self.search.textChanged.connect(lambda _: self._search_timer.start(220))
        tl.addWidget(self.search)
        self.refresh_btn = QToolButton()
        self.refresh_btn.setIcon(icon("refresh", C["text"], 18))
        self.refresh_btn.setToolTip("Listeyi sunucudan yenile")
        self.refresh_btn.clicked.connect(lambda: self.lib.load(self.mode, force=True))
        tl.addWidget(self.refresh_btn)
        self.acc_btn = QToolButton()
        self.acc_btn.setIcon(icon("user", C["text"], 18))
        self.acc_btn.setText(f" {self.profile.get('name') or self.account.username}")
        self.acc_btn.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self.acc_btn.setPopupMode(QToolButton.InstantPopup)
        menu = QMenu(self)
        menu.addAction(f"Bitiş: {self.account.expiry_text}").setEnabled(False)
        menu.addAction(f"Bağlantı limiti: {self.account.max_connections or '?'}").setEnabled(False)
        menu.addSeparator()
        menu.addAction("Ayarlar…", self.open_settings)
        menu.addAction("Profil değiştir…", self._request_logout)
        self.acc_btn.setMenu(menu)
        tl.addWidget(self.acc_btn)
        gear = QToolButton()
        gear.setIcon(icon("gear", C["text"], 18))
        gear.setToolTip("Ayarlar")
        gear.clicked.connect(self.open_settings)
        tl.addWidget(gear)
        v.addWidget(self.topbar)

        # ---- gövde
        self.split = QSplitter(Qt.Horizontal)
        self.split.setChildrenCollapsible(False)

        self.cat_panel = QWidget()
        self.cat_panel.setObjectName("SidePanel")
        cl = QVBoxLayout(self.cat_panel)
        cl.setContentsMargins(0, 4, 0, 6)
        cl.setSpacing(0)
        t = QLabel("KATEGORİLER")
        t.setObjectName("SectionTitle")
        cl.addWidget(t)
        self.cats = QListWidget()
        self.cats.setObjectName("Categories")
        self.cats.currentItemChanged.connect(self._on_category)
        cl.addWidget(self.cats, 1)
        self.cat_panel.setMinimumWidth(170)

        self.list_panel = QWidget()
        self.list_panel.setObjectName("ListPanel")
        ll = QVBoxLayout(self.list_panel)
        ll.setContentsMargins(0, 4, 0, 0)
        ll.setSpacing(0)
        hdr = QHBoxLayout()
        hdr.setContentsMargins(12, 6, 12, 6)
        self.list_title = QLabel("")
        self.list_title.setObjectName("H2")
        self.list_count = QLabel("")
        self.list_count.setObjectName("Muted")
        hdr.addWidget(self.list_title)
        hdr.addStretch(1)
        hdr.addWidget(self.list_count)
        ll.addLayout(hdr)
        self.list_stack = QStackedWidget()
        self.views: dict[str, QListView] = {}
        for m in MODES:
            view = QListView()
            view.setModel(self.models[m])
            view.setUniformItemSizes(True)
            view.setMouseTracking(True)
            view.setVerticalScrollMode(QListView.ScrollPerPixel)
            view.verticalScrollBar().setSingleStep(24)
            view.setSelectionMode(QListView.SingleSelection)
            view.setContextMenuPolicy(Qt.CustomContextMenu)
            view.customContextMenuRequested.connect(lambda pos, mm=m: self._item_menu(mm, pos))
            if m == "live":
                view.setItemDelegate(ChannelDelegate(self.models[m], self.epg, lambda i: self._is_fav("live", i), view))
                view.clicked.connect(self._on_live_clicked)
                view.activated.connect(self._on_live_clicked)
            else:
                view.setViewMode(QListView.IconMode)
                view.setResizeMode(QListView.Adjust)
                view.setMovement(QListView.Static)
                view.setWrapping(True)
                view.setGridSize(PosterDelegate.CELL)
                view.setSpacing(0)
                view.setItemDelegate(PosterDelegate(self.models[m], lambda i, mm=m: self._is_fav(mm, i),
                                                    (lambda i: self._vod_resume(i)) if m == "vod" else (lambda i: None),
                                                    view))
                if m == "vod":
                    view.clicked.connect(self._on_vod_clicked)
                    view.activated.connect(self._on_vod_activated)
                else:
                    view.clicked.connect(self._on_series_clicked)
                    view.activated.connect(self._on_series_clicked)
            view.selectionModel().currentChanged.connect(lambda cur, _prev, mm=m: self._on_current(mm, cur))
            self.views[m] = view
            self.list_stack.addWidget(view)
        # mesaj sayfası
        self.msg_page = QWidget()
        mp = QVBoxLayout(self.msg_page)
        mp.addStretch(1)
        self.msg_label = QLabel("")
        self.msg_label.setAlignment(Qt.AlignCenter)
        self.msg_label.setWordWrap(True)
        self.msg_label.setObjectName("Muted")
        self.msg_bar = QProgressBar()
        self.msg_bar.setRange(0, 0)
        self.msg_bar.setFixedWidth(160)
        self.msg_retry = QPushButton("Tekrar dene")
        self.msg_retry.clicked.connect(lambda: self.lib.load(self.mode, force=True))
        mp.addWidget(self.msg_label)
        mp.addWidget(self.msg_bar, 0, Qt.AlignHCenter)
        mp.addWidget(self.msg_retry, 0, Qt.AlignHCenter)
        mp.addStretch(1)
        self.list_stack.addWidget(self.msg_page)
        ll.addWidget(self.list_stack, 1)
        self.list_panel.setMinimumWidth(300)

        # ---- sağ: video + bilgi
        self.right = QSplitter(Qt.Vertical)
        self.right.setChildrenCollapsible(False)
        video_box = QWidget()
        vb = QVBoxLayout(video_box)
        vb.setContentsMargins(0, 0, 0, 0)
        vb.setSpacing(0)
        self.surface = VideoSurface()
        vb.addWidget(self.surface, 1)
        self.bar = PlayerBar()
        vb.addWidget(self.bar)
        self.right.addWidget(video_box)

        self.info_stack = QStackedWidget()
        self.info_stack.setMinimumHeight(190)
        self.welcome = WelcomePanel()
        self.live_info = LiveInfoPanel()
        self.vod_info = VodInfoPanel()
        self.series_panel = SeriesPanel()
        for w in (self.welcome, self.live_info, self.vod_info, self.series_panel):
            self.info_stack.addWidget(w)
        self.live_info.fav_clicked.connect(lambda: self._toggle_selected_fav("live"))
        self.live_info.copy_clicked.connect(self._copy_selected_live)
        self.vod_info.fav_clicked.connect(lambda: self._toggle_selected_fav("vod"))
        self.vod_info.play_clicked.connect(lambda from_start: self._play_selected_vod(from_start))
        self.series_panel.fav_clicked.connect(lambda: self._toggle_selected_fav("series"))
        self.series_panel.episode_activated.connect(self._on_episode_activated)
        self.right.addWidget(self.info_stack)
        self.right.setStretchFactor(0, 3)
        self.right.setStretchFactor(1, 1)

        self.split.addWidget(self.cat_panel)
        self.split.addWidget(self.list_panel)
        self.split.addWidget(self.right)
        self.split.setStretchFactor(2, 1)
        self.split.setSizes([210, 380, 850])
        v.addWidget(self.split, 1)
        self.setCentralWidget(central)

        # ---- durum çubuğu
        sb = self.statusBar()
        sb.setSizeGripEnabled(False)
        self.st_msg = QLabel("Hazır")
        self.st_buf = QLabel("")
        self.st_acc = QLabel(f"{self.account.username} · Bitiş: {self.account.expiry_text} · "
                             f"Limit: {self.account.max_connections or '?'} bağlantı")
        sb.addWidget(self.st_msg, 1)
        sb.addPermanentWidget(self.st_buf)
        sb.addPermanentWidget(self.st_acc)

    def _build_player(self) -> None:
        self.player = PlayerController(self.surface, self.settings, self)
        p = self.player
        p.status.connect(self._on_status)
        p.stats.connect(self._on_stats)
        p.position.connect(self.bar.set_position)
        p.started.connect(self._on_started)
        p.finished.connect(self._on_finished)
        p.gave_up.connect(self._on_gave_up)
        self.surface.key.connect(self._on_mpv_key)
        p.resume_point.connect(self._on_resume_point)
        p.format_feedback.connect(self._on_format_feedback)
        p.ua_learned.connect(self._on_ua_learned)
        p.preferred_ua = self.store.get("stream_ua") or None
        b = self.bar
        b.play_pause.connect(self.toggle_pause)
        b.seek_rel.connect(p.seek)
        b.seek_abs.connect(p.seek_to)
        b.go_live.connect(p.go_live)
        b.retry.connect(p.retry)
        b.volume_changed.connect(self._set_volume)
        b.mute_clicked.connect(self.toggle_mute)
        b.menu_clicked.connect(lambda: self.show_video_menu(QCursor.pos()))
        b.fullscreen_clicked.connect(self.toggle_fullscreen)
        b.set_volume(int(self.settings.get("volume", 80)))

    def _build_shortcuts(self) -> None:
        def sc(keys, fn):
            for k in (keys if isinstance(keys, (list, tuple)) else [keys]):
                s = QShortcut(k if isinstance(k, QKeySequence) else QKeySequence(k), self)
                s.setContext(Qt.WindowShortcut)
                s.activated.connect(fn)

        sc(["F11", "F"], self.toggle_fullscreen)
        sc("Escape", self.on_escape)
        sc("Ctrl+F", lambda: (self.search.setFocus(), self.search.selectAll()))
        sc("Space", self.toggle_pause)
        sc("PgUp", lambda: self.channel_step(-1))
        sc("PgDown", lambda: self.channel_step(1))
        sc("Ctrl+Left", lambda: self.player.seek(-10))
        sc("Ctrl+Right", lambda: self.player.seek(10))
        sc("M", self.toggle_mute)
        sc("I", self.toggle_stats)
        sc("S", self.player.screenshot)
        sc([QKeySequence(Qt.Key_Plus), QKeySequence(Qt.Key_Equal)], lambda: self._change_volume(5))
        sc(QKeySequence(Qt.Key_Minus), lambda: self._change_volume(-5))
        sc(["F5", "Ctrl+R"], self.player.retry)
        for d in "0123456789":
            sc(d, lambda dd=d: self._num_input(dd))

    def _build_timers(self) -> None:
        self._search_timer = QTimer(self)
        self._search_timer.setSingleShot(True)
        self._search_timer.timeout.connect(self._apply_search)
        self._num_timer = QTimer(self)
        self._num_timer.setSingleShot(True)
        self._num_timer.timeout.connect(self._num_commit)
        self._save_timer = QTimer(self)
        self._save_timer.setInterval(15000)
        self._save_timer.timeout.connect(self._save_if_dirty)
        self._save_timer.start()
        self._epg_timer = QTimer(self)
        self._epg_timer.setInterval(60000)
        self._epg_timer.timeout.connect(self._epg_tick)
        self._epg_timer.start()
        self._next_timer = QTimer(self)
        self._next_timer.setSingleShot(True)
        self._next_timer.timeout.connect(self._play_next_episode)
        self._info_timer = QTimer(self)
        self._info_timer.setSingleShot(True)
        self._info_timer.setInterval(250)
        self._info_timer.timeout.connect(self._show_pending_info)

    # ================================================================== mod / kategori
    def switch_mode(self, mode: str) -> None:
        self.mode = mode
        self.mode_btns[mode].setChecked(True)
        self.search.blockSignals(True)
        self.search.clear()
        self.search.blockSignals(False)
        self.models[mode].set_filter(query="")
        self.search.setPlaceholderText(f"{MODE_TITLES[mode]} içinde ara…   (Ctrl+F)")
        if mode in self.lib.data:
            self._populate_categories(mode)
            self.list_stack.setCurrentWidget(self.views[mode])
            self._update_header()
        else:
            self._show_message("Liste hazırlanıyor…", busy=True)
            self.lib.load(mode)
        sel = self.selected.get(mode)
        if sel is not None:
            self._show_info(mode, sel)
        else:
            self.info_stack.setCurrentWidget(self.welcome)
            self._info_shown = None

    def _preload_others(self) -> None:
        for m in ("vod", "series"):
            if m not in self.lib.data:
                self.lib.load(m)

    def _special_ids(self, mode: str, cat: str) -> list[str]:
        st = self.store
        if cat == CAT_FAV:
            return list(st["favorites"].get(mode, []))
        if cat == CAT_RECENT:
            return list(st["recent"].get(mode, []))
        if cat == CAT_RESUME:
            pref = "vod:" if mode == "vod" else "ep:"
            items = [(k, v) for k, v in st["resume"].items() if k.startswith(pref) and not v.get("done")]
            items.sort(key=lambda kv: kv[1].get("t", 0), reverse=True)
            return [k.split(":", 1)[1] for k, _ in items]
        return []

    def _populate_categories(self, mode: str) -> None:
        cats, items = self.lib.data.get(mode, ([], []))
        counts: dict[str, int] = {}
        for it in items:
            for c in it["cats"]:
                counts[c] = counts.get(c, 0) + 1
        self.cats.blockSignals(True)
        self.cats.clear()

        def add(text, cid, tip=""):
            it = QListWidgetItem(text)
            it.setData(Qt.UserRole, cid)
            if tip:
                it.setToolTip(tip)
            self.cats.addItem(it)
            return it

        add(f"Tümü  ({len(items)})", CAT_ALL)
        add(f"★  Favoriler  ({len(self.store['favorites'].get(mode, []))})", CAT_FAV)
        if mode == "live":
            add("🕘  Son izlenenler", CAT_RECENT)
        elif mode == "vod":
            add("▶  İzlemeye devam et", CAT_RESUME)
        else:
            add("🕘  Son izlenen diziler", CAT_RECENT)
        for c in cats:
            n = counts.get(c["id"], 0)
            if n:
                add(f"{c['name']}  ({n})", c["id"], c["name"])
        sel = self.cat_sel.get(mode, CAT_ALL)
        for i in range(self.cats.count()):
            if self.cats.item(i).data(Qt.UserRole) == sel:
                self.cats.setCurrentRow(i)
                break
        else:
            self.cats.setCurrentRow(0)
            self.cat_sel[mode] = CAT_ALL
        self.cats.blockSignals(False)
        self._apply_filter(mode)

    def _on_category(self, cur, _prev) -> None:
        if not cur:
            return
        cid = cur.data(Qt.UserRole)
        self.cat_sel[self.mode] = cid
        if self.search.text():
            self.search.blockSignals(True)
            self.search.clear()
            self.search.blockSignals(False)
        self._apply_filter(self.mode)

    def _apply_filter(self, mode: str) -> None:
        cat = self.cat_sel.get(mode, CAT_ALL)
        q = self.search.text() if mode == self.mode else ""
        self.models[mode].set_filter(cat=cat, query=q, special_ids=self._special_ids(mode, cat))
        self._restore_selection(mode)
        if mode == self.mode:
            self._update_header()

    def _apply_search(self) -> None:
        self._apply_filter(self.mode)

    def _update_header(self) -> None:
        m = self.models[self.mode]
        q = self.search.text().strip()
        if q:
            self.list_title.setText(f"“{q}”")
            self.list_count.setText(f"{len(m.view)} sonuç")
        else:
            cur = self.cats.currentItem()
            name = cur.text().rsplit("  (", 1)[0].strip() if cur else MODE_TITLES[self.mode]
            self.list_title.setText(name.replace("★  ", "").replace("🕘  ", "").replace("▶  ", ""))
            self.list_count.setText(f"{len(m.view)} {NOUN[self.mode]}")
        if not m.view and self.mode in self.lib.data:
            empty = {"__fav__": "Henüz favori yok. Sağ tık → Favorilere ekle.",
                     "__recent__": "Henüz bir şey izlemedin.",
                     "__resume__": "Yarım kalan film yok."}.get(self.cat_sel.get(self.mode), "Sonuç yok.")
            self.list_count.setText(empty if not q else "Sonuç yok")

    def _restore_selection(self, mode: str) -> None:
        sel = self.selected.get(mode)
        if not sel:
            return
        r = self.models[mode].row_of(sel["id"])
        if r >= 0:
            view = self.views[mode]
            view.selectionModel().blockSignals(True)
            view.setCurrentIndex(self.models[mode].index(r))
            view.selectionModel().blockSignals(False)

    def _show_message(self, text: str, busy: bool = False, retry: bool = False) -> None:
        self.msg_label.setText(text)
        self.msg_bar.setVisible(busy)
        self.msg_retry.setVisible(retry)
        self.list_stack.setCurrentWidget(self.msg_page)
        self.list_title.setText(MODE_TITLES[self.mode])
        self.list_count.setText("")

    # ================================================================== kütüphane olayları
    def _on_loaded(self, mode: str, cats, items, fresh: bool) -> None:
        sig = (len(items), len(cats), hash(tuple(x["id"] for x in items)), hash(tuple(x["name"] for x in items)))
        same = self._sigs.get(mode) == sig
        self._sigs[mode] = sig
        if not same:
            view = self.views[mode]
            scroll = view.verticalScrollBar().value()
            self.models[mode].set_items(items)
            if mode == self.mode:
                self._populate_categories(mode)
                self.list_stack.setCurrentWidget(self.views[mode])
            else:
                self._apply_filter(mode)
            QTimer.singleShot(0, lambda: view.verticalScrollBar().setValue(scroll))
        elif mode == self.mode and self.list_stack.currentWidget() is self.msg_page:
            self.list_stack.setCurrentWidget(self.views[mode])
        self._status(f"{MODE_TITLES[mode]}: {len(items)} {NOUN[mode]} "
                     f"{'güncellendi' if fresh else 'önbellekten yüklendi'}", "info")
        if mode == "live":
            if self.settings.get("full_epg", True) and not self.epg.has_full():
                self.lib.load_full_epg()
            if self._first_live:
                self._first_live = False
                last = self.store.get("last_channel")
                if self.settings.get("autoplay_last") and last:
                    it = next((x for x in items if x["id"] == last), None)
                    if it:
                        self.play_live(it)

    def _on_load_failed(self, mode: str, msg: str) -> None:
        if mode == self.mode:
            self._show_message(f"Liste yüklenemedi:\n{msg}", retry=True)
        self._status(f"{MODE_TITLES[mode]} yüklenemedi: {msg}", "error")

    def _on_progress(self, mode: str, msg: str) -> None:
        if mode == self.mode and self.list_stack.currentWidget() is self.msg_page:
            self._show_message(msg, busy=True)
        else:
            self._status(msg, "info")

    def _on_epg_ready(self) -> None:
        self.models["live"].repaint_all()
        sel = self.selected.get("live")
        if sel and self.info_stack.currentWidget() is self.live_info:
            self._refresh_live_epg(sel)
        self._status("Yayın akışı (EPG) yüklendi", "info")

    def _epg_tick(self) -> None:
        self.models["live"].repaint_all()
        sel = self.selected.get("live")
        if sel and self.info_stack.currentWidget() is self.live_info:
            self._refresh_live_epg(sel)

    def _on_image_loaded(self, url: str) -> None:
        if self._panel_img and self._panel_img[0] == url:
            self._apply_panel_image()

    # ================================================================== seçim / bilgi
    def _on_current(self, mode: str, index) -> None:
        it = index.data(ItemRole) if index.isValid() else None
        if not it:
            return
        self.selected[mode] = it
        # klavyeyle hızlı gezinirken her satır için istek atmamak için kısa gecikme
        self._pending_info = (mode, it)
        self._info_timer.start()

    def _show_pending_info(self) -> None:
        if self._pending_info:
            mode, it = self._pending_info
            self._pending_info = None
            if mode == self.mode:
                self._show_info(mode, it)

    def _show_info(self, mode: str, it: dict, force: bool = False) -> None:
        panel = {"live": self.live_info, "vod": self.vod_info, "series": self.series_panel}[mode]
        if not force and self._info_shown == (mode, it["id"]) and self.info_stack.currentWidget() is panel:
            return
        self._info_shown = (mode, it["id"])
        if mode == "live":
            self.info_stack.setCurrentWidget(self.live_info)
            self.live_info.set_channel(it)
            self.live_info.set_fav(self._is_fav("live", it["id"]))
            self._set_panel_image(it.get("icon_r"), "live")
            self._refresh_live_epg(it)
            if self.epg.short_fresh(it["id"]) is None:
                sid = it["id"]
                run_async(self.client.short_epg, sid, 10,
                          on_done=lambda e, s=sid: self._short_epg_done(s, e), on_error=lambda _m: None)
        elif mode == "vod":
            self.info_stack.setCurrentWidget(self.vod_info)
            self.vod_info.set_item(it, self._vod_resume(it["id"]))
            self.vod_info.set_fav(self._is_fav("vod", it["id"]))
            self._set_panel_image(it.get("icon_r"), "vod")
            info = self._vod_info.get(it["id"])
            if info is not None:
                self.vod_info.set_info(info)
            else:
                vid = it["id"]
                run_async(self.client.vod_info, vid, on_done=lambda d, v=vid: self._vod_info_done(v, d),
                          on_error=lambda m: self.vod_info.meta.setText(f"Bilgi alınamadı: {m}"))
        else:
            self.info_stack.setCurrentWidget(self.series_panel)
            self.series_panel.set_item(it)
            self.series_panel.set_fav(self._is_fav("series", it["id"]))
            self._set_panel_image(it.get("icon_r"), "series")
            info = self._series_info.get(it["id"])
            if info is not None:
                self._fill_series(it, info)
            else:
                sid = it["id"]
                run_async(self.client.series_info, sid, on_done=lambda d, s=sid: self._series_info_done(s, d),
                          on_error=lambda m: self.series_panel.meta.setText(f"Bölümler alınamadı: {m}"))

    def _set_panel_image(self, url: str | None, target: str) -> None:
        self._panel_img = (url, target) if url else None
        if not url:
            {"live": self.live_info.logo, "vod": self.vod_info.poster,
             "series": self.series_panel.poster}[target].set_pixmap(None)
            return
        self._apply_panel_image()

    def _apply_panel_image(self) -> None:
        if not self._panel_img:
            return
        url, target = self._panel_img
        size = QSize(128, 128) if target == "live" else QSize(272, 408)
        pm = self.images.get(url, size)
        if pm is not None:
            {"live": self.live_info.logo, "vod": self.vod_info.poster,
             "series": self.series_panel.poster}[target].set_pixmap(pm)

    def _refresh_live_epg(self, it: dict) -> None:
        cur, nxt = self.epg.now_next(it.get("epg"), it["id"])
        ups = self.epg.upcoming(it.get("epg"), it["id"], limit=8)
        if cur or ups or self.epg.short_fresh(it["id"]) is not None:
            self.live_info.set_epg(cur, nxt, ups)

    def _short_epg_done(self, sid: str, entries) -> None:
        self.epg.put_short(sid, entries)
        sel = self.selected.get("live")
        if sel and sel["id"] == sid and self.info_stack.currentWidget() is self.live_info:
            self.live_info.set_epg(*self.epg.now_next(sel.get("epg"), sid),
                                   self.epg.upcoming(sel.get("epg"), sid, limit=8))
        r = self.models["live"].row_of(sid)
        if r >= 0:
            idx = self.models["live"].index(r)
            self.models["live"].dataChanged.emit(idx, idx)

    def _vod_info_done(self, vid: str, data: dict) -> None:
        self._vod_info[vid] = data
        sel = self.selected.get("vod")
        if sel and sel["id"] == vid and self.info_stack.currentWidget() is self.vod_info:
            self.vod_info.set_info(data)

    def _series_info_done(self, sid: str, data: dict) -> None:
        self._series_info[sid] = data
        sel = self.selected.get("series")
        if sel and sel["id"] == sid and self.info_stack.currentWidget() is self.series_panel:
            self._fill_series(sel, data)

    def _fill_series(self, it: dict, info: dict) -> None:
        prog = self.store["series_progress"].get(it["id"]) or {}
        self.series_panel.set_info(info, self._episode_resume, prog.get("season"))
        ep_id = prog.get("ep")
        if ep_id:
            lw = self.series_panel.episodes
            for i in range(lw.count()):
                if str(lw.item(i).data(Qt.UserRole).get("id")) == str(ep_id):
                    lw.setCurrentRow(i)
                    break

    # ================================================================== tıklamalar
    def _on_live_clicked(self, index) -> None:
        it = index.data(ItemRole)
        if it:
            self.selected["live"] = it
            self._show_info("live", it)
            self.play_live(it)

    def _on_vod_clicked(self, index) -> None:
        it = index.data(ItemRole)
        if it:
            self.selected["vod"] = it
            self._show_info("vod", it)

    def _on_vod_activated(self, index) -> None:
        it = index.data(ItemRole)
        if it:
            self.selected["vod"] = it
            self._show_info("vod", it)
            self.play_vod(it, from_start=False)

    def _on_series_clicked(self, index) -> None:
        it = index.data(ItemRole)
        if it:
            self.selected["series"] = it
            self._show_info("series", it)

    def _play_selected_vod(self, from_start: bool) -> None:
        it = self.selected.get("vod")
        if it:
            self.play_vod(it, from_start)

    def _on_episode_activated(self, ep: dict) -> None:
        series = self.selected.get("series")
        if series and ep:
            self.play_episode(series, ep, self.series_panel.current_season())

    # ================================================================== oynatma
    def _live_formats(self) -> list[str]:
        pref = self.settings.get("live_format", "auto")
        if pref == "ts":
            order = ["ts", "m3u8"]
        elif pref == "m3u8":
            order = ["m3u8", "ts"]
        else:
            fs = self.store.get("format_stats") or {}
            order = ["m3u8", "ts"] if fs.get("m3u8", 0) > fs.get("ts", 0) else ["ts", "m3u8"]
        allowed = [f.lower() for f in (self.account.allowed_formats or [])]
        if allowed:
            order.sort(key=lambda f: f not in allowed)   # izin verilenler öne
        return order

    def play_live(self, it: dict, force: bool = False) -> None:
        cur = self.player.current
        if (not force and cur and cur.is_live and cur.item_id == it["id"] and self.player.guard.active):
            return   # aynı kanala tekrar tıklama/çift tık: yayını boşuna yeniden başlatma
        self._cancel_next_episode()
        fmts = self._live_formats()
        urls = {f: self.client.live_url(it["id"], f) for f in fmts}
        self.player.play(PlayItem("live", it["id"], it["name"], urls, fmts, meta={"item": it}))
        model = self.models["live"]
        model.set_playing(it["id"])
        view_ids = {x["id"] for x in model.view}
        if it["id"] in view_ids:
            self._zap_list = list(model.view)
        elif not self._zap_list:
            self._zap_list = list(model.all)
        self._push_recent("live", it["id"])
        self.store["last_channel"] = it["id"]
        self._dirty = True
        self.bar.set_mode(True)
        cur, _ = self.epg.now_next(it.get("epg"), it["id"])
        num = f"{it['num']}  " if it.get("num") else ""
        self.player.osd(f"{num}{it['name']}" + (f"\nŞimdi: {cur.title}" if cur else ""), 2500)

    def channel_step(self, delta: int) -> None:
        lst = self._zap_list or self.models["live"].view
        if not lst:
            return
        cur = self.player.current
        idx = 0
        if cur and cur.is_live:
            idx = next((i for i, x in enumerate(lst) if x["id"] == cur.item_id), -1)
            idx = (idx + delta) % len(lst) if idx >= 0 else 0
        it = lst[idx]
        self.selected["live"] = it
        r = self.models["live"].row_of(it["id"])
        if r >= 0:
            view = self.views["live"]
            view.setCurrentIndex(self.models["live"].index(r))
            view.scrollTo(self.models["live"].index(r))
        self.play_live(it)

    def play_vod(self, it: dict, from_start: bool = False) -> None:
        self._cancel_next_episode()
        info = self._vod_info.get(it["id"]) or {}
        ext = (info.get("movie_data") or {}).get("container_extension") or it.get("ext") or "mp4"
        key = f"vod:{it['id']}"
        res = self.store["resume"].get(key) or {}
        start = 0.0 if from_start or res.get("done") else float(res.get("pos", 0) or 0)
        url = self.client.vod_url(it["id"], ext)
        self.player.play(PlayItem("vod", it["id"], it["name"], {ext: url}, [ext], start, key, {"item": it}))
        self.models["live"].set_playing(None)
        self._push_recent("vod", it["id"])
        self.bar.set_mode(False)
        msg = it["name"] + (f"\nKaldığın yerden: {fmt_time(start)}" if start > 0 else "")
        self.player.osd(msg, 2500)

    def play_episode(self, series: dict, ep: dict, season: int | None) -> None:
        self._cancel_next_episode()
        ep_id = str(ep.get("id"))
        ext = ep.get("container_extension") or "mp4"
        key = f"ep:{ep_id}"
        res = self.store["resume"].get(key) or {}
        start = 0.0 if res.get("done") else float(res.get("pos", 0) or 0)
        title = f"{series['name']} · S{int(season or ep.get('season') or 0):02d}E{int(ep.get('episode_num') or 0):02d}"
        url = self.client.episode_url(ep_id, ext)
        self.player.play(PlayItem("episode", ep_id, title, {ext: url}, [ext], start, key,
                                  {"series": series, "season": season, "ep": ep}))
        self.models["live"].set_playing(None)
        self.store["series_progress"][series["id"]] = {"season": season, "ep": ep_id, "t": time.time()}
        self._push_recent("series", series["id"])
        self.bar.set_mode(False)
        self.player.osd(title + (f"\nKaldığın yerden: {fmt_time(start)}" if start > 0 else ""), 2500)

    def _next_episode_of(self, pi: PlayItem):
        series = pi.meta.get("series")
        info = self._series_info.get(series["id"]) if series else None
        if not info:
            return None
        flat = [(sn, ep) for sn, eps in info.get("episodes", {}).items() for ep in eps]
        for i, (_sn, ep) in enumerate(flat):
            if str(ep.get("id")) == pi.item_id and i + 1 < len(flat):
                return series, flat[i + 1][1], flat[i + 1][0]
        return None

    def _on_finished(self, pi: PlayItem) -> None:
        if pi.kind == "episode":
            nxt = self._next_episode_of(pi)
            if self.series_panel.isVisible():
                self.series_panel.refresh_marks()
            if nxt:
                self._next_ep = nxt
                self.player.osd(f"Sonraki bölüm 6 sn içinde başlıyor…\n{nxt[1].get('title', '')}\n(Esc: iptal)", 6000)
                self._next_timer.start(6000)
                return
        self._status(f"Bitti: {pi.title}", "info")

    def _play_next_episode(self) -> None:
        if self._next_ep:
            series, ep, season = self._next_ep
            self._next_ep = None
            self.play_episode(series, ep, season)

    def _cancel_next_episode(self) -> None:
        if self._next_timer.isActive():
            self._next_timer.stop()
            self._next_ep = None
            return True
        return False

    def _on_started(self, pi: PlayItem) -> None:
        self.bar.set_paused(False)
        self.setWindowTitle(pi.title)

    def _on_gave_up(self, pi: PlayItem, msg: str) -> None:
        self._status(f"{pi.title}: {msg}  (F5 ile tekrar dene)", "error")
        if "401" in msg or "403" in msg:
            # Yetki hatası: hesabın o anki durumunu sunucudan tekrar sorup sebebi daralt
            run_async(self.client.authenticate, on_done=lambda acc, t=pi.title: self._diagnose_auth(t, acc),
                      on_error=lambda m: self._status(f"Yetki hatası; hesap bilgisi de alınamadı: {m}", "error"))

    def _diagnose_auth(self, title: str, acc: Account) -> None:
        self.account = acc
        self._log_account()
        if acc.cred_note and "değiştirilmedi" in acc.cred_note:
            why = ("Sunucunun kayıtlı parolası girdiğin paroladan farklı görünüyor. Sağlayıcının panelindeki "
                   "M3U linkinden parolayı kontrol edip (büyük/küçük harf dahil) aynen gir.")
        elif acc.max_connections and acc.active_cons >= acc.max_connections:
            why = (f"Hesabın şu an başka bir cihazda açık görünüyor (aktif bağlantı {acc.active_cons}/"
                   f"{acc.max_connections}). Diğer cihazdaki yayını kapatıp F5'e bas.")
        else:
            why = ("Hesap aktif ve boşta görünüyor; sunucu bu oynatıcıyı yayına yetkilendirmiyor. Sağlayıcı "
                   "üçüncü parti uygulamaları, IP ya da cihazı kısıtlıyor olabilir. Kanal üstünde sağ tık → "
                   "\"Yayın adresini kopyala\" ile VLC'de dene: VLC'de de açılmıyorsa sorun sağlayıcı tarafında.")
        log.warning("Yetki teşhisi (%s): %s", title, why)
        self._status(why, "error")
        self.player.osd(why, 9000)

    def _on_ua_learned(self, ua: str) -> None:
        if self.store.get("stream_ua") != ua:
            self.store["stream_ua"] = ua
            self._dirty = True
            self._save_if_dirty()
            log.info("Bu sunucu için çalışan oynatıcı kimliği kaydedildi: %s", ua)
            self._status("Sunucunun kabul ettiği oynatıcı kimliği bulundu ve kaydedildi", "ok")

    def _log_account(self) -> None:
        a = self.account
        si = (a.raw or {}).get("server_info") or {}
        log.info("Hesap: durum=%s, bitiş=%s, deneme=%s, bağlantı=%s/%s, formatlar=%s, "
                 "server_info=%s://%s:%s (https:%s)", a.status, a.expiry_text, a.is_trial, a.active_cons,
                 a.max_connections, ",".join(a.allowed_formats), si.get("server_protocol"), si.get("url"),
                 si.get("port"), si.get("https_port"))

    # ================================================================== kontroller
    def toggle_pause(self) -> None:
        self.player.toggle_pause()
        self.bar.set_paused(bool(self.player._get("pause")))

    def toggle_mute(self) -> None:
        self.bar.set_muted(self.player.toggle_mute())

    def _set_volume(self, v: int) -> None:
        self.player.set_volume(v)
        self.bar.set_muted(False)
        self.settings.data["volume"] = int(v)
        self._dirty = True

    def _change_volume(self, delta: int) -> None:
        v = self.player.change_volume(delta)
        self.bar.set_volume(v)
        self.settings.data["volume"] = int(v)
        self._dirty = True

    def toggle_stats(self) -> None:
        on = self.player.toggle_stats()
        self.settings.data["show_stats"] = on
        self._dirty = True

    def toggle_fullscreen(self) -> None:
        chrome = (self.topbar, self.cat_panel, self.list_panel, self.info_stack, self.bar, self.statusBar())
        if not self._fullscreen:
            self._was_maximized = self.isMaximized()
            self._saved_sizes = (self.split.sizes(), self.right.sizes())
            for w in chrome:
                w.hide()
            self._fullscreen = True
            self.showFullScreen()
            self.player.osd("Tam ekran — çıkmak için Esc ya da çift tık", 1500)
        else:
            for w in chrome:
                w.show()
            self._fullscreen = False
            self.showNormal()
            if self._was_maximized:
                self.showMaximized()
            if self._saved_sizes:
                self.split.setSizes(self._saved_sizes[0])
                self.right.setSizes(self._saved_sizes[1])

    def on_escape(self) -> None:
        if self._cancel_next_episode():
            self.player.osd("Otomatik geçiş iptal edildi", 1200)
        elif self._fullscreen:
            self.toggle_fullscreen()
        elif self.search.text():
            self.search.clear()

    def _num_input(self, d: str) -> None:
        if self.mode != "live" and not (self.player.current and self.player.current.is_live):
            return
        self._num_buf = (self._num_buf + d)[-4:]
        self.player.osd(f"Kanal: {self._num_buf}_", 1500)
        self._num_timer.start(1300)

    def _num_commit(self) -> None:
        buf, self._num_buf = self._num_buf, ""
        if not buf:
            return
        it = self.models["live"].find_by_num(int(buf))
        if it:
            self.selected["live"] = it
            self._zap_list = list(self.models["live"].all)
            self.play_live(it)
        else:
            self.player.osd(f"{buf} numaralı kanal yok", 1500)

    def _on_mpv_key(self, k: str) -> None:
        live = bool(self.player.current and self.player.current.is_live)
        actions = {
            "MBTN_LEFT_DBL": self.toggle_fullscreen, "f": self.toggle_fullscreen, "F": self.toggle_fullscreen,
            "F11": self.toggle_fullscreen, "ENTER": self.toggle_fullscreen,
            "ESC": self.on_escape, "SPACE": self.toggle_pause,
            "UP": (lambda: self.channel_step(-1)) if live else (lambda: self._change_volume(5)),
            "DOWN": (lambda: self.channel_step(1)) if live else (lambda: self._change_volume(-5)),
            "PGUP": lambda: self.channel_step(-1), "PGDWN": lambda: self.channel_step(1),
            "LEFT": lambda: self.player.seek(-10), "RIGHT": lambda: self.player.seek(10),
            "HOME": self.player.go_live, "END": self.player.go_live,
            "m": self.toggle_mute, "i": self.toggle_stats, "s": self.player.screenshot,
            "a": self._cycle_audio,
            "WHEEL_UP": lambda: self._change_volume(5), "WHEEL_DOWN": lambda: self._change_volume(-5),
            "+": lambda: self._change_volume(5), "-": lambda: self._change_volume(-5),
            "MBTN_RIGHT": lambda: self.show_video_menu(QCursor.pos()),
        }
        if k.isdigit():
            self._num_input(k)
            return
        fn = actions.get(k)
        if fn:
            fn()

    def _cycle_audio(self) -> None:
        tracks = self.player.tracks("audio")
        if len(tracks) < 2:
            self.player.osd("Tek ses parçası var", 1000)
            return
        cur = next((i for i, t in enumerate(tracks) if t.get("selected")), 0)
        t = tracks[(cur + 1) % len(tracks)]
        self.player.set_track("audio", t.get("id"))
        self.player.osd(f"Ses: {t.get('title') or t.get('lang') or t.get('id')}", 1500)

    def show_video_menu(self, pos) -> None:
        m = QMenu(self)
        am = m.addMenu("Ses parçası")
        tracks = self.player.tracks("audio")
        if not tracks:
            am.addAction("(yok)").setEnabled(False)
        for t in tracks:
            label = " · ".join(str(x) for x in (t.get("title"), t.get("lang"), t.get("codec")) if x) or f"Parça {t.get('id')}"
            a = am.addAction(label)
            a.setCheckable(True)
            a.setChecked(bool(t.get("selected")))
            a.triggered.connect(lambda _=False, tid=t.get("id"): self.player.set_track("audio", tid))
        sm = m.addMenu("Altyazı")
        off = sm.addAction("Kapalı")
        off.triggered.connect(lambda: self.player.set_track("sub", None))
        for t in self.player.tracks("sub"):
            label = " · ".join(str(x) for x in (t.get("title"), t.get("lang")) if x) or f"Altyazı {t.get('id')}"
            a = sm.addAction(label)
            a.setCheckable(True)
            a.setChecked(bool(t.get("selected")))
            a.triggered.connect(lambda _=False, tid=t.get("id"): self.player.set_track("sub", tid))
        asp = m.addMenu("Görüntü oranı")
        for label, val in (("Otomatik", "no"), ("16:9", "16:9"), ("4:3", "4:3"), ("21:9", "2.33"),
                           ("Ekrana yay", "stretch")):
            asp.addAction(label).triggered.connect(lambda _=False, v=val: self.player.set_aspect(v))
        m.addSeparator()
        st = m.addAction("Yayın sağlığı paneli  (I)")
        st.setCheckable(True)
        st.setChecked(self.player._show_stats)
        st.triggered.connect(self.toggle_stats)
        m.addAction("Ekran görüntüsü  (S)", self.player.screenshot)
        m.addAction("Yeniden bağlan  (F5)", self.player.retry)
        m.addAction("Durdur", self.player.stop)
        m.addAction("Tam ekran  (F)", self.toggle_fullscreen)
        m.exec(pos)

    # ================================================================== öğe menüsü / favori
    def _item_menu(self, mode: str, pos) -> None:
        view = self.views[mode]
        idx = view.indexAt(pos)
        it = idx.data(ItemRole) if idx.isValid() else None
        if not it:
            return
        m = QMenu(self)
        if mode == "live":
            m.addAction("Oynat", lambda: self.play_live(it))
        elif mode == "vod":
            m.addAction("Oynat", lambda: self.play_vod(it))
            m.addAction("Baştan oynat", lambda: self.play_vod(it, from_start=True))
        else:
            m.addAction("Bölümleri göster", lambda: (self.selected.__setitem__("series", it),
                                                 self._show_info("series", it)))
        fav = self._is_fav(mode, it["id"])
        m.addAction("Favorilerden çıkar" if fav else "Favorilere ekle", lambda: self._toggle_fav(mode, it["id"]))
        if mode in ("live", "vod"):
            m.addAction("Yayın adresini kopyala", lambda: self._copy_url(mode, it))
        if mode == "vod" and self._vod_resume(it["id"]):
            m.addAction("İzleme kaydını sil", lambda: self._clear_resume(f"vod:{it['id']}"))
        m.exec(view.viewport().mapToGlobal(pos))

    def _is_fav(self, mode: str, item_id: str) -> bool:
        return item_id in self.store["favorites"].get(mode, [])

    def _toggle_fav(self, mode: str, item_id: str) -> None:
        lst = self.store["favorites"].setdefault(mode, [])
        if item_id in lst:
            lst.remove(item_id)
        else:
            lst.insert(0, item_id)
        self._dirty = True
        self._save_if_dirty()
        self.models[mode].repaint_all()
        if self.cat_sel.get(mode) == CAT_FAV:
            self._apply_filter(mode)
        sel = self.selected.get(mode)
        if sel and sel["id"] == item_id:
            {"live": self.live_info, "vod": self.vod_info, "series": self.series_panel}[mode].set_fav(
                self._is_fav(mode, item_id))
        if mode == self.mode:
            # kategori sayacını güncelle
            for i in range(self.cats.count()):
                if self.cats.item(i).data(Qt.UserRole) == CAT_FAV:
                    self.cats.item(i).setText(f"★  Favoriler  ({len(lst)})")

    def _toggle_selected_fav(self, mode: str) -> None:
        it = self.selected.get(mode)
        if it:
            self._toggle_fav(mode, it["id"])

    def _copy_url(self, mode: str, it: dict) -> None:
        if mode == "live":
            url = self.client.live_url(it["id"], self._live_formats()[0])
        else:
            url = self.client.vod_url(it["id"], it.get("ext") or "mp4")
        QGuiApplication.clipboard().setText(url)
        self._status("Yayın adresi panoya kopyalandı", "info")

    def _copy_selected_live(self) -> None:
        it = self.selected.get("live")
        if it:
            self._copy_url("live", it)

    def _push_recent(self, mode: str, item_id: str) -> None:
        lst = self.store["recent"].setdefault(mode, [])
        if item_id in lst:
            lst.remove(item_id)
        lst.insert(0, item_id)
        del lst[40:]
        self._dirty = True

    # ================================================================== devam et
    def _vod_resume(self, vid: str):
        r = self.store["resume"].get(f"vod:{vid}")
        if r and not r.get("done") and r.get("pos", 0) > 0:
            return float(r["pos"]), float(r.get("dur") or 0)
        return None

    def _episode_resume(self, ep_id: str):
        r = self.store["resume"].get(f"ep:{ep_id}")
        if not r:
            return None
        if r.get("done"):
            return "done"
        return (float(r.get("pos", 0)), float(r.get("dur") or 0)) if r.get("pos", 0) > 0 else None

    def _on_resume_point(self, key: str, pos: float, dur: float) -> None:
        res = self.store["resume"]
        if pos < 0:
            if key.startswith("ep:"):
                res[key] = {"pos": 0, "dur": dur, "done": True, "t": time.time()}
            else:
                res.pop(key, None)
        else:
            if dur and pos > dur - 25:     # neredeyse bitmiş
                if key.startswith("ep:"):
                    res[key] = {"pos": 0, "dur": dur, "done": True, "t": time.time()}
                else:
                    res.pop(key, None)
            else:
                res[key] = {"pos": round(pos, 1), "dur": round(dur, 1), "t": time.time()}
        if len(res) > 400:
            for k, _ in sorted(res.items(), key=lambda kv: kv[1].get("t", 0))[: len(res) - 400]:
                res.pop(k, None)
        self._dirty = True
        if key.startswith("vod:"):
            vid = key[4:]
            r = self.models["vod"].row_of(vid)
            if r >= 0:
                i = self.models["vod"].index(r)
                self.models["vod"].dataChanged.emit(i, i)
            sel = self.selected.get("vod")
            if sel and sel["id"] == vid and self.info_stack.currentWidget() is self.vod_info:
                self.vod_info.set_resume(self._vod_resume(vid))

    def _clear_resume(self, key: str) -> None:
        self.store["resume"].pop(key, None)
        self._dirty = True
        self.models["vod"].repaint_all()

    def _on_format_feedback(self, fmt: str, ok: bool) -> None:
        fs = self.store.setdefault("format_stats", {"ts": 0, "m3u8": 0})
        fs[fmt] = max(-20, min(20, fs.get(fmt, 0) + (1 if ok else -2)))
        self._dirty = True
        log.info("Format istatistiği: %s", fs)

    # ================================================================== durum
    def _status(self, msg: str, level: str = "info") -> None:
        col = {"ok": C["ok"], "warn": C["warn"], "error": C["error"]}.get(level, C["muted"])
        self.st_msg.setText(f"<span style='color:{col}'>●</span>  {msg}")

    def _on_status(self, msg: str, level: str) -> None:
        self._status(msg, level)
        short = msg if len(msg) < 48 else msg[:46] + "…"
        self.bar.set_health(short, level)

    def _on_stats(self, st: dict) -> None:
        txt = f"Buffer {st['buffer_s']:.1f} sn · {st['speed_kbps']:.0f} kbps · {st['format']}"
        if st.get("res"):
            txt += f" · {st['res']}"
        if st.get("reconnects"):
            txt += f" · ⟳ {st['reconnects']}"
        self.st_buf.setText(txt)

    # ================================================================== ayarlar / çıkış
    def open_settings(self) -> None:
        def clear():
            self.lib.clear_cache()
            self._status("Önbellek temizlendi; listeler yeniden indirilecek", "info")

        old_ua = self.settings.get("user_agent")
        dlg = SettingsDialog(self.settings, self.account, on_clear_cache=clear, parent=self)
        if dlg.exec():
            if self.settings.get("user_agent") != old_ua:
                # elle seçilen kimlik, otomatik öğrenilenin önüne geçsin
                self.store["stream_ua"] = None
                self.player.preferred_ua = None
            self.player.apply_settings()
            ua = self.settings.get("user_agent")
            self.client.user_agent = ua
            self.client.session.headers["User-Agent"] = ua
            self.images.session.headers["User-Agent"] = ua
            if self.settings.get("full_epg") and not self.epg.has_full():
                self.lib.load_full_epg()
            self._status("Ayarlar kaydedildi", "ok")

    def _request_logout(self) -> None:
        self._logout = True
        self.close()

    def _save_if_dirty(self) -> None:
        if self._dirty:
            self._dirty = False
            try:
                self.settings.save()
            except Exception as e:
                log.warning("Ayarlar kaydedilemedi: %s", e)

    def _restore_window(self) -> None:
        w = self.settings.get("window") or {}
        geo = w.get("geometry")
        if geo:
            try:
                self.restoreGeometry(QByteArray.fromBase64(geo.encode()))
            except Exception:
                pass
        if w.get("split"):
            self.split.setSizes(w["split"])
        if w.get("rsplit"):
            self.right.setSizes(w["rsplit"])

    def closeEvent(self, e) -> None:
        if self._fullscreen:
            self.toggle_fullscreen()
        self.settings.data["window"] = {
            "geometry": bytes(self.saveGeometry().toBase64()).decode(),
            "split": self.split.sizes(),
            "rsplit": self.right.sizes(),
        }
        try:
            self.player.shutdown()
        except Exception:
            pass
        self._dirty = True
        self._save_if_dirty()
        self.client.close()
        super().closeEvent(e)
        if self._logout:
            self.logout_requested.emit()
        else:
            self.quit_requested.emit()
