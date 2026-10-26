"""Uygulama giriş noktası."""
from __future__ import annotations

import locale
import logging
import os
import sys
import threading
import traceback

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication, QDialog, QMessageBox

from . import APP_ID, APP_NAME, __version__
from .config import Settings, project_root, setup_logging
from .player import MpvMissing, load_mpv
from .ui import theme
from .workers import init_workers, shutdown_pools

log = logging.getLogger("akis")

MPV_HELP = (
    "Video motoru (libmpv-2.dll) bulunamadı.\n\n"
    "Çözüm: proje klasöründeki setup.bat dosyasını çalıştır; libmpv'yi otomatik indirip "
    "bin\\ klasörüne koyar.\n\n"
    "Elle kurmak istersen: https://github.com/shinchiro/mpv-winbuild-cmake/releases adresinden "
    "'mpv-dev-x86_64-...7z' dosyasını indir, içindeki libmpv-2.dll'i bin\\ klasörüne kopyala.\n\n"
    "Teknik ayrıntı: {err}"
)


def _start_demo_server() -> None:
    try:
        sys.path.insert(0, str(project_root()))
        from tests import mock_server
        srv = mock_server.make_server("127.0.0.1", 8899, channels=300, max_conn=1)
        threading.Thread(target=srv.serve_forever, daemon=True, name="mock-xtream").start()
        log.info("Demo sunucusu başlatıldı: http://127.0.0.1:8899 (demo/demo)")
    except OSError as e:
        log.warning("Demo sunucusu başlatılamadı (port dolu olabilir): %s", e)
    except Exception as e:
        log.warning("Demo sunucusu yok: %s", e)


def main() -> int:
    log_file = setup_logging()
    log.info("%s %s başlıyor (Python %s, log: %s)", APP_NAME, __version__, sys.version.split()[0], log_file)
    if os.name == "nt":
        try:
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(f"{APP_ID}.Player")
        except Exception:
            pass

    app = QApplication(sys.argv)
    app.setApplicationName(APP_ID)
    app.setApplicationDisplayName(APP_NAME)
    app.setWindowIcon(QIcon(str(project_root() / "assets" / "icon_256.png")))
    locale.setlocale(locale.LC_NUMERIC, "C")   # mpv bunu şart koşar
    theme.apply(app)
    init_workers()

    def excepthook(etype, value, tb):
        text = "".join(traceback.format_exception(etype, value, tb))
        log.error("Yakalanmamış hata:\n%s", text)
        try:
            QMessageBox.warning(None, APP_NAME, f"Beklenmeyen bir hata oluştu (uygulama çalışmaya devam ediyor):\n\n"
                                                f"{value}\n\nAyrıntılar: {log_file}")
        except Exception:
            pass

    sys.excepthook = excepthook

    try:
        load_mpv()
    except MpvMissing as e:
        log.error("libmpv yüklenemedi: %s", e)
        QMessageBox.critical(None, APP_NAME, MPV_HELP.format(err=e))
        return 1

    if "--demo" in sys.argv:
        _start_demo_server()

    settings = Settings()
    app.setQuitOnLastWindowClosed(False)
    holder: dict = {}

    def show_login():
        from .ui.login import LoginDialog
        from .ui.main_window import MainWindow

        dlg = LoginDialog(settings)
        if "--demo" in sys.argv and not holder.get("demo_filled"):
            holder["demo_filled"] = True
            dlg._fill_demo()
        if dlg.exec() != QDialog.Accepted:
            app.quit()
            return
        try:
            win = MainWindow(settings, dlg.client, dlg.account, dlg.profile)
        except Exception as e:
            log.exception("Ana pencere açılamadı")
            QMessageBox.critical(None, APP_NAME, f"Ana pencere açılamadı:\n\n{e}\n\nAyrıntılar: {log_file}")
            app.quit()
            return
        win.setAttribute(Qt.WA_DeleteOnClose)
        win.logout_requested.connect(lambda: QTimer.singleShot(0, show_login))
        win.quit_requested.connect(app.quit)
        holder["win"] = win
        win.show()

    QTimer.singleShot(0, show_login)
    code = app.exec()
    shutdown_pools()
    log.info("Çıkış (kod %s)", code)
    # Ayarlar pencere kapanırken kaydedildi. Uzun süren bir arka plan indirmesi (ör. dev XMLTV) ya da
    # cevap vermeyen bir sunucu isteği yüzünden süreç arkada asılı kalmasın: hemen çık.
    logging.shutdown()
    os._exit(code)


if __name__ == "__main__":
    sys.exit(main())
