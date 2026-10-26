"""Giriş penceresi: sunucu + kullanıcı adı + parola (ya da M3U linki yapıştır)."""
from __future__ import annotations

import sys

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction, QPixmap
from PySide6.QtWidgets import (QDialog, QFormLayout, QHBoxLayout, QLabel, QLineEdit, QListWidget,
                               QListWidgetItem, QMessageBox, QPushButton, QVBoxLayout, QWidget)

from .. import APP_NAME
from ..config import Settings, decode_secret, project_root
from ..workers import run_async
from ..xtream import XtreamClient, XtreamError, normalize_server, parse_m3u_link
from .icons import icon
from .theme import C


class LoginDialog(QDialog):
    def __init__(self, settings: Settings, parent=None):
        super().__init__(parent)
        self.settings = settings
        self.client: XtreamClient | None = None
        self.account = None
        self.profile: dict | None = None
        self.setWindowTitle("Giriş")
        self.setMinimumWidth(720)
        self._busy = False

        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # sol: kayıtlı profiller
        side = QWidget()
        side.setObjectName("SidePanel")
        side.setFixedWidth(230)
        sl = QVBoxLayout(side)
        sl.setContentsMargins(10, 16, 10, 12)
        logo = QLabel()
        pm = QPixmap(str(project_root() / "assets" / "icon_256.png"))
        if not pm.isNull():
            logo.setPixmap(pm.scaled(72, 72, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        logo.setAlignment(Qt.AlignCenter)
        sl.addWidget(logo)
        name = QLabel(APP_NAME)
        name.setObjectName("AppTitle")
        name.setAlignment(Qt.AlignCenter)
        sl.addWidget(name)
        tag = QLabel("donmayan IPTV")
        tag.setObjectName("Muted")
        tag.setAlignment(Qt.AlignCenter)
        sl.addWidget(tag)
        sec = QLabel("KAYITLI PROFİLLER")
        sec.setObjectName("SectionTitle")
        sl.addWidget(sec)
        self.profiles = QListWidget()
        self.profiles.setObjectName("Categories")
        self.profiles.currentItemChanged.connect(self._profile_selected)
        self.profiles.itemDoubleClicked.connect(lambda _: self._connect())
        sl.addWidget(self.profiles, 1)
        self.del_btn = QPushButton("Profili sil")
        self.del_btn.clicked.connect(self._delete_profile)
        sl.addWidget(self.del_btn)
        root.addWidget(side)

        # sağ: form
        main = QWidget()
        ml = QVBoxLayout(main)
        ml.setContentsMargins(28, 24, 28, 22)
        ml.setSpacing(10)
        h = QLabel("Xtream Codes ile bağlan")
        h.setObjectName("H1")
        ml.addWidget(h)
        sub = QLabel("Sağlayıcının verdiği sunucu adresi, kullanıcı adı ve parolayı gir. "
                     "Elinde sadece M3U linki varsa sunucu kutusuna yapıştır, gerisini ben ayıklarım.")
        sub.setObjectName("Muted")
        sub.setWordWrap(True)
        ml.addWidget(sub)

        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignRight | Qt.AlignVCenter)
        form.setHorizontalSpacing(14)
        form.setVerticalSpacing(10)
        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText("örn. Ev IPTV (isteğe bağlı)")
        self.server_edit = QLineEdit()
        self.server_edit.setPlaceholderText("http://sunucu.com:8080  ya da M3U linki")
        self.server_edit.textChanged.connect(self._server_changed)
        self.user_edit = QLineEdit()
        self.user_edit.setPlaceholderText("kullanıcı adı")
        self.pass_edit = QLineEdit()
        self.pass_edit.setPlaceholderText("parola")
        self.pass_edit.setEchoMode(QLineEdit.Password)
        self._eye = QAction(icon("eye", C["muted"], 18), "Göster", self.pass_edit)
        self._eye.setToolTip("Parolayı göster/gizle")
        self._eye.triggered.connect(self._toggle_eye)
        self.pass_edit.addAction(self._eye, QLineEdit.TrailingPosition)
        form.addRow("Profil adı", self.name_edit)
        form.addRow("Sunucu", self.server_edit)
        form.addRow("Kullanıcı adı", self.user_edit)
        form.addRow("Parola", self.pass_edit)
        ml.addLayout(form)

        self.msg = QLabel("")
        self.msg.setWordWrap(True)
        self.msg.setMinimumHeight(40)
        ml.addWidget(self.msg)
        ml.addStretch(1)

        btns = QHBoxLayout()
        self.demo_btn = QPushButton("Demo sunucusu")
        self.demo_btn.setToolTip("tests/mock_server.py çalışıyorsa onunla bağlanır (127.0.0.1:8899, demo/demo)")
        self.demo_btn.clicked.connect(self._fill_demo)
        # Kurulu (.exe) sürümde sahte sunucu paketlenmez → düğmeyi gösterme
        self.demo_btn.setVisible(not getattr(sys, "frozen", False))
        btns.addWidget(self.demo_btn)
        btns.addStretch(1)
        self.cancel_btn = QPushButton("Çık")
        self.cancel_btn.clicked.connect(self.reject)
        self.ok_btn = QPushButton("Bağlan")
        self.ok_btn.setObjectName("Primary")
        self.ok_btn.setDefault(True)
        self.ok_btn.clicked.connect(self._connect)
        btns.addWidget(self.cancel_btn)
        btns.addWidget(self.ok_btn)
        ml.addLayout(btns)
        root.addWidget(main, 1)

        for e in (self.name_edit, self.server_edit, self.user_edit, self.pass_edit):
            e.returnPressed.connect(self._connect)
        self._load_profiles()

    # ------------------------------------------------------------------ profiller
    def _load_profiles(self) -> None:
        self.profiles.clear()
        last = self.settings.get("last_profile")
        sel = None
        for p in self.settings.profiles():
            it = QListWidgetItem(p.get("name") or p.get("username"))
            it.setToolTip(f"{p.get('server')}\n{p.get('username')}")
            it.setData(Qt.UserRole, p)
            self.profiles.addItem(it)
            if p.get("id") == last:
                sel = it
        self.del_btn.setEnabled(self.profiles.count() > 0)
        if sel is not None:
            self.profiles.setCurrentItem(sel)
        elif self.profiles.count():
            self.profiles.setCurrentRow(0)

    def _profile_selected(self, cur, _prev) -> None:
        if not cur:
            return
        p = cur.data(Qt.UserRole)
        self.name_edit.setText(p.get("name", ""))
        self.server_edit.setText(p.get("server", ""))
        self.user_edit.setText(p.get("username", ""))
        self.pass_edit.setText(decode_secret(p.get("password", "")))
        self._set_msg("")

    def _delete_profile(self) -> None:
        it = self.profiles.currentItem()
        if not it:
            return
        p = it.data(Qt.UserRole)
        if QMessageBox.question(self, "Profili sil", f"“{p.get('name')}” profili silinsin mi?") == QMessageBox.Yes:
            self.settings.delete_profile(p["id"])
            for e in (self.name_edit, self.server_edit, self.user_edit, self.pass_edit):
                e.clear()
            self._load_profiles()

    def _fill_demo(self) -> None:
        self.name_edit.setText("Demo (sahte sunucu)")
        self.server_edit.setText("http://127.0.0.1:8899")
        self.user_edit.setText("demo")
        self.pass_edit.setText("demo")

    # ------------------------------------------------------------------ form
    def _toggle_eye(self) -> None:
        hidden = self.pass_edit.echoMode() == QLineEdit.Password
        self.pass_edit.setEchoMode(QLineEdit.Normal if hidden else QLineEdit.Password)

    def _server_changed(self, text: str) -> None:
        if "username=" in text and "password=" in text:
            parsed = parse_m3u_link(text)
            if parsed:
                server, user, pw = parsed
                self.server_edit.blockSignals(True)
                self.server_edit.setText(server)
                self.server_edit.blockSignals(False)
                self.user_edit.setText(user)
                self.pass_edit.setText(pw)
                self._set_msg("M3U linkinden sunucu, kullanıcı adı ve parola ayıklandı ✓", "ok")

    def _set_msg(self, text: str, level: str = "info") -> None:
        col = {"ok": C["ok"], "error": C["error"], "warn": C["warn"]}.get(level, C["muted"])
        self.msg.setStyleSheet(f"color:{col};")
        self.msg.setText(text)

    def _set_busy(self, busy: bool) -> None:
        self._busy = busy
        for w in (self.ok_btn, self.server_edit, self.user_edit, self.pass_edit, self.name_edit, self.profiles,
                  self.demo_btn):
            w.setEnabled(not busy)
        self.ok_btn.setText("Bağlanıyor…" if busy else "Bağlan")

    def _connect(self) -> None:
        if self._busy:
            return
        server = self.server_edit.text().strip()
        user = self.user_edit.text().strip()
        pw = self.pass_edit.text()
        if not server or not user or not pw:
            self._set_msg("Sunucu, kullanıcı adı ve parola gerekli.", "error")
            return
        try:
            server = normalize_server(server)
        except XtreamError as e:
            self._set_msg(str(e), "error")
            return
        self.server_edit.setText(server)
        client = XtreamClient(server, user, pw, user_agent=self.settings.get("user_agent"))
        self._set_busy(True)
        self._set_msg("Sunucuya bağlanılıyor…")
        run_async(client.authenticate,
                  on_done=lambda acc: self._ok(client, acc, server, user, pw),
                  on_error=self._fail)

    def _ok(self, client, account, server, user, pw) -> None:
        self._set_busy(False)
        self.client = client
        self.account = account
        # Sunucu parolayı farklı harf büyüklüğüyle tutuyorsa (bkz. XtreamClient._adopt_server_credentials)
        # profili düzeltilmiş haliyle kaydet; kullanıcı adı profil kimliğinde olduğu için yazıldığı gibi kalır.
        self.profile = self.settings.upsert_profile(self.name_edit.text().strip(), server, user, client.password)
        self.accept()

    def _fail(self, msg: str) -> None:
        self._set_busy(False)
        self._set_msg(msg, "error")
