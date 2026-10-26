"""Arka plan işleri. Ağ ve ağır işler asla arayüz thread'inde çalışmaz → pencere donmaz."""
from __future__ import annotations

import logging
import threading

from PySide6.QtCore import QObject, QRunnable, Qt, QThreadPool, Signal, Slot

from .xtream import XtreamError

log = logging.getLogger(__name__)


class _Dispatcher(QObject):
    """Worker thread'lerinden gelen sonuçları GUI thread'inde çalıştırır."""
    sig = Signal(object, object)

    def __init__(self):
        super().__init__()
        self.sig.connect(self._deliver, Qt.QueuedConnection)

    @Slot(object, object)
    def _deliver(self, cb, args):
        try:
            cb(*args)
        except Exception:
            log.exception("Geri çağrı hatası")


_dispatcher: _Dispatcher | None = None
_pools: dict[str, QThreadPool] = {}
_pool_lock = threading.Lock()


def init_workers() -> None:
    """GUI thread'inde, QApplication oluşturulduktan sonra bir kez çağrılmalı."""
    global _dispatcher
    if _dispatcher is None:
        _dispatcher = _Dispatcher()


def pool(name: str = "api") -> QThreadPool:
    with _pool_lock:
        p = _pools.get(name)
        if p is None:
            p = QThreadPool()
            p.setMaxThreadCount({"api": 4, "img": 6, "epg": 2}.get(name, 3))
            p.setExpiryTimeout(30000)
            _pools[name] = p
        return p


def post(cb, *args) -> None:
    """Herhangi bir thread'den GUI thread'inde cb(*args) çalıştırır."""
    if cb is not None and _dispatcher is not None:
        _dispatcher.sig.emit(cb, args)


class _Task(QRunnable):
    def __init__(self, fn, args, kwargs, on_done, on_error):
        super().__init__()
        self.fn, self.args, self.kwargs = fn, args, kwargs
        self.on_done, self.on_error = on_done, on_error
        self.setAutoDelete(True)

    def run(self):
        try:
            res = self.fn(*self.args, **self.kwargs)
        except XtreamError as e:
            post(self.on_error, str(e))
            return
        except Exception as e:
            log.exception("Arka plan işi başarısız: %s", getattr(self.fn, "__name__", self.fn))
            post(self.on_error, f"Beklenmeyen hata: {e}")
            return
        post(self.on_done, res)


def run_async(fn, *args, on_done=None, on_error=None, pool_name: str = "api", **kwargs) -> None:
    pool(pool_name).start(_Task(fn, args, kwargs, on_done, on_error))


def shutdown_pools(timeout_ms: int = 1500) -> None:
    for p in _pools.values():
        p.clear()
        p.waitForDone(timeout_ms)
