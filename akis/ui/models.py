"""Sanal liste modelleri ve çizim delegeleri.

50.000 kanallık listelerde bile akıcı kalması için:
* Model yalnızca görünen satırlar için veri üretir (QListView + uniformItemSizes).
* Arama anahtarları önceden hesaplanır (Türkçe/aksan duyarsız).
* Logolar yalnızca ekranda görünen satırlar için, arka planda yüklenir.
"""
from __future__ import annotations

import time

from PySide6.QtCore import QAbstractListModel, QModelIndex, QRect, QRectF, QSize, Qt
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QStyle, QStyledItemDelegate

from ..xtream import search_key
from .theme import C

ItemRole = Qt.UserRole + 1

CAT_ALL = "__all__"
CAT_FAV = "__fav__"
CAT_RECENT = "__recent__"
CAT_RESUME = "__resume__"


class ItemListModel(QAbstractListModel):
    def __init__(self, mode: str, images, parent=None):
        super().__init__(parent)
        self.mode = mode
        self.images = images
        self.all: list[dict] = []
        self.view: list[dict] = []
        self.url_rows: dict[str, list[int]] = {}
        self.cat = CAT_ALL
        self.query = ""
        self.special_ids: list[str] = []
        self.playing_id: str | None = None
        images.loaded.connect(self._img_loaded)

    # ---- Qt API
    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.view)

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid() or index.row() >= len(self.view):
            return None
        it = self.view[index.row()]
        if role == Qt.DisplayRole:
            return it["name"]
        if role == ItemRole:
            return it
        if role == Qt.ToolTipRole:
            return it["name"]
        return None

    # ---- veri
    def set_items(self, items: list[dict]) -> None:
        for it in items:
            if "icon_r" not in it:
                it["icon_r"] = self.images.resolve(it.get("icon") or "")
        self.all = items
        self.refilter()

    def set_filter(self, cat: str | None = None, query: str | None = None, special_ids: list[str] | None = None):
        if cat is not None:
            self.cat = cat
        if query is not None:
            self.query = query
        if special_ids is not None:
            self.special_ids = special_ids
        self.refilter()

    def refilter(self) -> None:
        q = search_key(self.query).strip()
        if q:
            tokens = q.split()
            view = [it for it in self.all if all(t in it["k"] for t in tokens)]
        elif self.cat == CAT_ALL:
            view = list(self.all)
        elif self.cat in (CAT_FAV, CAT_RECENT, CAT_RESUME):
            by_id = {it["id"]: it for it in self.all}
            view = [by_id[i] for i in self.special_ids if i in by_id]
        else:
            view = [it for it in self.all if self.cat in it["cats"]]
        self.beginResetModel()
        self.view = view
        rows: dict[str, list[int]] = {}
        for r, it in enumerate(view):
            u = it.get("icon_r")
            if u:
                rows.setdefault(u, []).append(r)
        self.url_rows = rows
        self.endResetModel()

    def row_of(self, item_id: str) -> int:
        for r, it in enumerate(self.view):
            if it["id"] == item_id:
                return r
        return -1

    def item_at(self, row: int) -> dict | None:
        return self.view[row] if 0 <= row < len(self.view) else None

    def find_by_num(self, num: int) -> dict | None:
        for it in self.all:
            if it.get("num") == num:
                return it
        return None

    def set_playing(self, item_id: str | None) -> None:
        old = self.playing_id
        self.playing_id = item_id
        for i in (old, item_id):
            if i:
                r = self.row_of(i)
                if r >= 0:
                    idx = self.index(r)
                    self.dataChanged.emit(idx, idx)

    def _img_loaded(self, url: str) -> None:
        for r in self.url_rows.get(url, ()):
            if r < len(self.view):
                idx = self.index(r)
                self.dataChanged.emit(idx, idx)

    def repaint_all(self) -> None:
        if self.view:
            self.dataChanged.emit(self.index(0), self.index(len(self.view) - 1))


def _rounded_pixmap(p: QPainter, rect: QRectF, pm, radius: float, cover: bool = False) -> None:
    path = QPainterPath()
    path.addRoundedRect(rect, radius, radius)
    p.save()
    p.setClipPath(path)
    if cover:
        scaled = pm.size().scaled(rect.size().toSize(), Qt.KeepAspectRatioByExpanding)
    else:
        scaled = pm.size().scaled(rect.size().toSize(), Qt.KeepAspectRatio)
    x = rect.x() + (rect.width() - scaled.width()) / 2
    y = rect.y() + (rect.height() - scaled.height()) / 2
    p.drawPixmap(QRect(int(x), int(y), scaled.width(), scaled.height()), pm)
    p.restore()


def _initials(name: str) -> str:
    parts = [w for w in name.replace(":", " ").replace("|", " ").split() if w[:1].isalnum()]
    if not parts:
        return "?"
    if len(parts) >= 2 and len(parts[0]) <= 3 and parts[0].isupper():
        parts = parts[1:]
    return "".join(w[0] for w in parts[:2]).upper()


class ChannelDelegate(QStyledItemDelegate):
    ROW_H = 54
    LOGO = 40

    def __init__(self, model: ItemListModel, epg, is_fav, parent=None):
        super().__init__(parent)
        self.model = model
        self.epg = epg
        self.is_fav = is_fav
        self.f_name = QFont("Segoe UI", 10)
        self.f_name.setWeight(QFont.DemiBold)
        self.f_small = QFont("Segoe UI", 8)
        self.f_num = QFont("Segoe UI", 8)

    def sizeHint(self, option, index):
        return QSize(option.rect.width(), self.ROW_H)

    def paint(self, p: QPainter, option, index):
        it = index.data(ItemRole)
        if not it:
            return
        p.save()
        p.setRenderHint(QPainter.Antialiasing)
        r = option.rect.adjusted(6, 2, -6, -2)
        selected = bool(option.state & QStyle.State_Selected)
        hover = bool(option.state & QStyle.State_MouseOver)
        playing = self.model.playing_id == it["id"]
        if selected or hover or playing:
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(C["sel"] if (selected or playing) else C["hover"]))
            p.drawRoundedRect(QRectF(r), 8, 8)
        if playing:
            p.setBrush(QColor(C["accent"]))
            p.drawRoundedRect(QRectF(r.x(), r.y() + 10, 3, r.height() - 20), 1.5, 1.5)

        x = r.x() + 8
        # numara
        p.setFont(self.f_num)
        p.setPen(QColor(C["dim"]))
        if it.get("num"):
            p.drawText(QRect(x, r.y(), 30, r.height()), Qt.AlignVCenter | Qt.AlignRight, str(it["num"]))
        x += 38
        # logo
        lr = QRectF(x, r.y() + (r.height() - self.LOGO) / 2, self.LOGO, self.LOGO)
        pm = self.model.images.get(it.get("icon_r", ""), QSize(self.LOGO * 2, self.LOGO * 2)) if it.get("icon_r") else None
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(C["panel2"]))
        p.drawRoundedRect(lr, 8, 8)
        if pm is not None and not pm.isNull():
            _rounded_pixmap(p, lr.adjusted(3, 3, -3, -3), pm, 5)
        else:
            p.setPen(QColor(C["muted"]))
            p.setFont(self.f_small)
            p.drawText(lr, Qt.AlignCenter, _initials(it["name"]))
        x += self.LOGO + 12

        fav = self.is_fav(it["id"])
        right_pad = 26 if fav else 8
        tw = r.right() - x - right_pad
        cur, _nxt = (None, None)
        if self.epg is not None:
            cur, _nxt = self.epg.now_next(it.get("epg"), it["id"])
        p.setFont(self.f_name)
        p.setPen(QColor(C["text"]))
        fm = QFontMetrics(self.f_name)
        name_y = r.y() + (8 if cur else (r.height() - fm.height()) // 2)
        p.drawText(QRect(x, name_y, tw, fm.height()), Qt.AlignLeft | Qt.AlignVCenter,
                   fm.elidedText(it["name"], Qt.ElideRight, tw))
        if cur:
            p.setFont(self.f_small)
            fs = QFontMetrics(self.f_small)
            p.setPen(QColor(C["muted"]))
            line = fs.elidedText(cur.title, Qt.ElideRight, tw)
            p.drawText(QRect(x, name_y + fm.height() + 1, tw, fs.height()), Qt.AlignLeft | Qt.AlignVCenter, line)
            prog = cur.progress(time.time())
            by = r.bottom() - 6
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(C["line"]))
            p.drawRoundedRect(QRectF(x, by, min(tw, 120), 2.5), 1, 1)
            p.setBrush(QColor(C["accent"]))
            p.drawRoundedRect(QRectF(x, by, min(tw, 120) * prog, 2.5), 1, 1)
        if fav:
            p.setPen(QColor(C["warn"]))
            p.setFont(self.f_name)
            p.drawText(QRect(r.right() - 24, r.y(), 20, r.height()), Qt.AlignCenter, "★")
        p.restore()


class PosterDelegate(QStyledItemDelegate):
    CELL = QSize(156, 270)
    POSTER = QSize(136, 204)

    def __init__(self, model: ItemListModel, is_fav, resume_of, parent=None):
        super().__init__(parent)
        self.model = model
        self.is_fav = is_fav
        self.resume_of = resume_of
        self.f_title = QFont("Segoe UI", 9)
        self.f_title.setWeight(QFont.DemiBold)
        self.f_small = QFont("Segoe UI", 8)

    def sizeHint(self, option, index):
        return self.CELL

    def paint(self, p: QPainter, option, index):
        it = index.data(ItemRole)
        if not it:
            return
        p.save()
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        cell = option.rect
        selected = bool(option.state & QStyle.State_Selected)
        hover = bool(option.state & QStyle.State_MouseOver)
        px = cell.x() + (cell.width() - self.POSTER.width()) / 2
        pr = QRectF(px, cell.y() + 8, self.POSTER.width(), self.POSTER.height())
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(C["panel2"]))
        p.drawRoundedRect(pr, 10, 10)
        pm = self.model.images.get(it.get("icon_r", ""), QSize(self.POSTER.width() * 2, self.POSTER.height() * 2)) \
            if it.get("icon_r") else None
        if pm is not None and not pm.isNull():
            _rounded_pixmap(p, pr, pm, 10, cover=True)
        else:
            p.setPen(QColor(C["dim"]))
            f = QFont("Segoe UI", 18)
            f.setWeight(QFont.Bold)
            p.setFont(f)
            p.drawText(pr, Qt.AlignCenter, _initials(it["name"]))
        # devam çubuğu
        res = self.resume_of(it["id"])
        if res:
            pos, dur = res
            if dur > 0:
                frac = max(0.02, min(1.0, pos / dur))
                br = QRectF(pr.x() + 8, pr.bottom() - 10, pr.width() - 16, 4)
                p.setPen(Qt.NoPen)
                p.setBrush(QColor(0, 0, 0, 160))
                p.drawRoundedRect(br, 2, 2)
                p.setBrush(QColor(C["accent"]))
                p.drawRoundedRect(QRectF(br.x(), br.y(), br.width() * frac, br.height()), 2, 2)
        # puan rozeti
        rating = it.get("rating")
        try:
            rv = float(rating) if rating not in (None, "", "0") else 0
        except ValueError:
            rv = 0
        if rv:
            badge = QRectF(pr.x() + 6, pr.y() + 6, 40, 18)
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(0, 0, 0, 170))
            p.drawRoundedRect(badge, 9, 9)
            p.setPen(QColor(C["warn"]))
            p.setFont(self.f_small)
            p.drawText(badge, Qt.AlignCenter, f"★ {rv:.1f}".replace(".0", ""))
        if self.is_fav(it["id"]):
            star = QRectF(pr.right() - 26, pr.y() + 6, 20, 20)
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(0, 0, 0, 170))
            p.drawEllipse(star)
            p.setPen(QColor(C["warn"]))
            p.drawText(star, Qt.AlignCenter, "★")
        if selected or hover:
            p.setBrush(Qt.NoBrush)
            p.setPen(QPen(QColor(C["accent"] if selected else C["muted"]), 2))
            p.drawRoundedRect(pr.adjusted(-1, -1, 1, 1), 11, 11)
        # başlık
        p.setFont(self.f_title)
        p.setPen(QColor(C["text"]))
        fm = QFontMetrics(self.f_title)
        tr = QRect(int(pr.x()), int(pr.bottom() + 6), int(pr.width()), fm.height() * 2 + 2)
        words = it["name"]
        line1 = fm.elidedText(words, Qt.ElideRight, tr.width())
        if fm.horizontalAdvance(words) > tr.width():
            # iki satıra böl
            cut = len(words)
            while cut > 0 and fm.horizontalAdvance(words[:cut]) > tr.width():
                cut = words.rfind(" ", 0, cut)
            if cut > 0:
                line1 = words[:cut]
                line2 = fm.elidedText(words[cut + 1:], Qt.ElideRight, tr.width())
                p.drawText(QRect(tr.x(), tr.y(), tr.width(), fm.height()), Qt.AlignHCenter, line1)
                p.drawText(QRect(tr.x(), tr.y() + fm.height(), tr.width(), fm.height()), Qt.AlignHCenter, line2)
                p.restore()
                return
        p.drawText(QRect(tr.x(), tr.y(), tr.width(), fm.height()), Qt.AlignHCenter, line1)
        p.restore()
