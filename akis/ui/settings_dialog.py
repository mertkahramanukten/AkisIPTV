"""Ayarlar penceresi."""
from __future__ import annotations

from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFormLayout, QGroupBox,
                               QHBoxLayout, QLabel, QPushButton, QVBoxLayout)

from ..config import USER_AGENTS, Settings

BUFFER_CHOICES = [
    ("hizli", "Hızlı açılış — az buffer (iyi internet)"),
    ("dengeli", "Dengeli — önerilen"),
    ("saglam", "Sağlam — zayıf/dalgalı internet, en az takılma"),
]
FORMAT_CHOICES = [
    ("auto", "Otomatik — hangisi daha stabilse onu öğrenir (önerilen)"),
    ("ts", "Her zaman TS (MPEG-TS) ile başla"),
    ("m3u8", "Her zaman HLS (m3u8) ile başla"),
]


class SettingsDialog(QDialog):
    def __init__(self, settings: Settings, account=None, on_clear_cache=None, parent=None):
        super().__init__(parent)
        self.settings = settings
        self.setWindowTitle("Ayarlar")
        self.setMinimumWidth(620)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(20, 16, 20, 16)

        g1 = QGroupBox("Akıcılık (donma önleme)")
        f1 = QFormLayout(g1)
        self.buffer = QComboBox()
        for k, v in BUFFER_CHOICES:
            self.buffer.addItem(v, k)
        keys_b = [k for k, _ in BUFFER_CHOICES]
        cur_b = settings.get("buffer_profile")
        self.buffer.setCurrentIndex(keys_b.index(cur_b) if cur_b in keys_b else 1)
        self.adaptive = QCheckBox("Sık takılırsa buffer'ı otomatik büyüt (adaptif buffer)")
        self.adaptive.setChecked(bool(settings.get("adaptive_buffer", True)))
        self.fmt = QComboBox()
        for k, v in FORMAT_CHOICES:
            self.fmt.addItem(v, k)
        keys = [k for k, _ in FORMAT_CHOICES]
        self.fmt.setCurrentIndex(keys.index(settings.get("live_format")) if settings.get("live_format") in keys else 0)
        self.hwdec = QCheckBox("Donanımsal video çözme (GPU) — CPU kaynaklı kasmayı önler")
        self.hwdec.setChecked(bool(settings.get("hwdec", True)))
        f1.addRow("Buffer profili", self.buffer)
        f1.addRow("", self.adaptive)
        f1.addRow("Canlı yayın formatı", self.fmt)
        f1.addRow("", self.hwdec)
        lay.addWidget(g1)

        g2 = QGroupBox("Bağlantı")
        f2 = QFormLayout(g2)
        self.ua = QComboBox()
        self.ua.setEditable(True)
        for k, v in USER_AGENTS.items():
            self.ua.addItem(k, v)
        cur_ua = settings.get("user_agent")
        idx = next((i for i in range(self.ua.count()) if self.ua.itemData(i) == cur_ua), -1)
        if idx >= 0:
            self.ua.setCurrentIndex(idx)
        else:
            self.ua.setEditText(cur_ua or "")
        ua_hint = QLabel("Bazı sağlayıcılar tanımadıkları uygulamaları engeller. Kanal açılmıyorsa farklı bir "
                         "User-Agent dene. (Değişiklik yeniden girişte API için de geçerli olur.)")
        ua_hint.setObjectName("Muted")
        ua_hint.setWordWrap(True)
        f2.addRow("User-Agent", self.ua)
        f2.addRow("", ua_hint)
        lay.addWidget(g2)

        g3 = QGroupBox("Arayüz")
        f3 = QFormLayout(g3)
        self.full_epg = QCheckBox("Tüm kanalların yayın akışını indir (listede 'şimdi' bilgisi)")
        self.full_epg.setChecked(bool(settings.get("full_epg", True)))
        self.stats = QCheckBox("Yayın sağlığı panelini video üzerinde göster (I tuşu)")
        self.stats.setChecked(bool(settings.get("show_stats", False)))
        self.autoplay = QCheckBox("Açılışta son izlenen kanalı başlat")
        self.autoplay.setChecked(bool(settings.get("autoplay_last", False)))
        f3.addRow(self.full_epg)
        f3.addRow(self.stats)
        f3.addRow(self.autoplay)
        lay.addWidget(g3)

        if account is not None:
            g4 = QGroupBox("Hesap")
            f4 = QFormLayout(g4)
            f4.addRow("Kullanıcı", QLabel(account.username))
            f4.addRow("Durum", QLabel(account.status + (" (deneme)" if account.is_trial else "")))
            f4.addRow("Bitiş", QLabel(account.expiry_text))
            f4.addRow("Bağlantı", QLabel(f"{account.active_cons} aktif / en fazla {account.max_connections or '?'}"))
            f4.addRow("Formatlar", QLabel(", ".join(account.allowed_formats)))
            lay.addWidget(g4)

        row = QHBoxLayout()
        clr = QPushButton("Önbelleği temizle")
        clr.setToolTip("Kanal/film listelerini ve EPG'yi sıfırdan indirir")
        if on_clear_cache:
            clr.clicked.connect(lambda: (on_clear_cache(), clr.setText("Temizlendi ✓"), clr.setEnabled(False)))
        row.addWidget(clr)
        row.addStretch(1)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.button(QDialogButtonBox.Ok).setText("Kaydet")
        bb.button(QDialogButtonBox.Ok).setObjectName("Primary")
        bb.button(QDialogButtonBox.Cancel).setText("Vazgeç")
        bb.accepted.connect(self._save)
        bb.rejected.connect(self.reject)
        row.addWidget(bb)
        lay.addLayout(row)

    def _save(self) -> None:
        s = self.settings
        ua = self.ua.currentData() if self.ua.currentText() == self.ua.itemText(self.ua.currentIndex()) else None
        ua = ua or self.ua.currentText().strip()
        s.set("buffer_profile", self.buffer.currentData(), save=False)
        s.set("adaptive_buffer", self.adaptive.isChecked(), save=False)
        s.set("live_format", self.fmt.currentData(), save=False)
        s.set("hwdec", self.hwdec.isChecked(), save=False)
        s.set("user_agent", ua or USER_AGENTS["VLC (önerilen)"], save=False)
        s.set("full_epg", self.full_epg.isChecked(), save=False)
        s.set("show_stats", self.stats.isChecked(), save=False)
        s.set("autoplay_last", self.autoplay.isChecked(), save=False)
        s.save()
        self.accept()
