"""Çoklu izleme: ana oynatıcının yanına ek kanallar (ızgara: 1x2 / 2x2).

Her ek kare kendi mpv örneğiyle çalışır ve sağlayıcıdan AYRI bir bağlantı harcar. Bu yüzden
ek kare sayısı hesabın bağlantı limitine göre sınırlanır (limit - 1; ana oynatıcı 1 harcar).
Ses tek karede çalar: bir kareyi "sese al" diğerlerini susturur.
"""
from __future__ import annotations

import logging

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtWidgets import QGridLayout, QLabel, QMenu, QVBoxLayout, QWidget

from ..player import PlayerController, PlayItem, VideoSurface

log = logging.getLogger(__name__)

MAX_TILES = 4   # ana oynatıcı dahil


class Tile(QWidget):
    """Tek bir ek kanal karesi: başlık + video yüzeyi + kendi oynatıcısı."""
    menu_requested = Signal(object)        # Tile
    promote_requested = Signal(object)     # Tile → ana ekrana al

    def __init__(self, settings, item: dict, item_play: PlayItem, ua: str | None, parent=None):
        super().__init__(parent)
        self.item = item
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        self.title = QLabel(item.get("name", ""))
        self.title.setObjectName("Muted")
        self.title.setFixedHeight(20)
        self.title.setContentsMargins(6, 0, 6, 0)
        lay.addWidget(self.title)
        self.surface = VideoSurface()
        lay.addWidget(self.surface, 1)
        self.player = PlayerController(self.surface, settings, self)
        self.player.preferred_ua = ua
        self.player.status.connect(self._on_status)
        self.surface.key.connect(self._on_key)
        self.player.play(item_play)
        self.set_audio(False)

    def _on_status(self, msg: str, level: str) -> None:
        dot = {"ok": "🟢", "warn": "🟡", "error": "🔴"}.get(level, "⚪")
        self.title.setText(f"{dot}  {self.item.get('name', '')}  ·  {msg[:40]}")

    def _on_key(self, k: str) -> None:
        if k == "MBTN_RIGHT":
            self.menu_requested.emit(self)
        elif k == "MBTN_LEFT_DBL":
            self.promote_requested.emit(self)

    def set_audio(self, on: bool) -> None:
        self.player._set("mute", not on)
        self.title.setStyleSheet("color:#3FE0BE;" if on else "")

    def close_tile(self) -> None:
        try:
            self.player.shutdown()
        except Exception:
            pass
        self.setParent(None)
        self.deleteLater()


class MultiView(QObject):
    """Ana yüzeyi ve ek kareleri bir ızgarada yönetir."""
    promote = Signal(dict)                 # bu kanalı ana oynatıcıda aç
    changed = Signal(int)                  # ek kare sayısı

    def __init__(self, grid_host: QWidget, main_surface: QWidget, main_player: PlayerController | None, settings):
        super().__init__(grid_host)
        self.host = grid_host
        self.grid = QGridLayout(grid_host)
        self.grid.setContentsMargins(0, 0, 0, 0)
        self.grid.setSpacing(2)
        self.main_surface = main_surface
        self.main_player = main_player
        self.settings = settings
        self.tiles: list[Tile] = []
        self.audio_tile: Tile | None = None
        self._relayout()

    def capacity(self, max_connections) -> int:
        """Bağlantı limitine göre açılabilecek EK kare sayısı."""
        try:
            limit = int(max_connections or 1)
        except (TypeError, ValueError):
            limit = 1
        return max(0, min(MAX_TILES, limit) - 1)

    def has(self, item_id: str) -> bool:
        return any(t.item["id"] == item_id for t in self.tiles)

    def add(self, item: dict, play_item: PlayItem, ua: str | None) -> Tile:
        t = Tile(self.settings, item, play_item, ua, self.host)
        t.menu_requested.connect(self._tile_menu)
        t.promote_requested.connect(self._promote)
        self.tiles.append(t)
        self._relayout()
        self.changed.emit(len(self.tiles))
        return t

    def remove(self, t: Tile) -> None:
        if t in self.tiles:
            self.tiles.remove(t)
            if self.audio_tile is t:
                self.give_audio(None)
            self.grid.removeWidget(t)
            t.close_tile()
            self._relayout()
            self.changed.emit(len(self.tiles))

    def clear(self) -> None:
        for t in list(self.tiles):
            self.remove(t)

    def give_audio(self, t: Tile | None) -> None:
        """t=None → ses ana oynatıcıya döner."""
        self.audio_tile = t
        for x in self.tiles:
            x.set_audio(x is t)
        if self.main_player:
            self.main_player._set("mute", t is not None)

    def _promote(self, t: Tile) -> None:
        item = t.item
        self.remove(t)
        self.promote.emit(item)

    def _tile_menu(self, t: Tile) -> None:
        from PySide6.QtGui import QCursor
        m = QMenu(self.host)
        if self.audio_tile is t:
            m.addAction("🔈 Sesi ana ekrana ver", lambda: self.give_audio(None))
        else:
            m.addAction("🔊 Sesi buraya al", lambda: self.give_audio(t))
        m.addAction("⤢ Ana ekrana al  (çift tık)", lambda: self._promote(t))
        m.addSeparator()
        m.addAction("✕ Kareyi kapat", lambda: self.remove(t))
        m.exec(QCursor.pos())

    def _relayout(self) -> None:
        widgets = [self.main_surface, *self.tiles]
        for w in widgets:
            self.grid.removeWidget(w)
        n = len(widgets)
        cols = 1 if n == 1 else 2
        for i, w in enumerate(widgets):
            self.grid.addWidget(w, i // cols, i % cols)
        # 3 karede ana ekran üst satırı boydan kaplasın
        if n == 3:
            self.grid.removeWidget(self.main_surface)
            self.grid.addWidget(self.main_surface, 0, 0, 1, 2)
            for i, t in enumerate(self.tiles):
                self.grid.removeWidget(t)
                self.grid.addWidget(t, 1, i)
