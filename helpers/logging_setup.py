"""
Mustiefly (Qt) - Merkezi loglama kurulumu.

Öncesinde hemen her modülde `except Exception as e: print(...)` deseni
kullanılıyordu. Bu, uygulama pencereli (konsolsuz) bir .exe olarak
paketlendiğinde tüm hataları sessizce yutar — kullanıcı bir şey
bozulduğunda hiçbir iz bulamaz.

Bu modül:
- Kullanıcının kendi klasöründe (AppPaths.dir/logs/audifly.log) dönen
  (rotating) bir dosya logu tutar (max 1 MB x 3 yedek).
- Geliştirme sırasında konsola da basar.
- `get_logger(__name__)` ile her modül kendi logger'ını alır.

Kullanım:
    from mustiefly_qt.helpers.logging_setup import get_logger
    log = get_logger(__name__)
    ...
    except Exception:
        log.exception("Ayarlar okunamadı")   # traceback dahil, dosyaya yazılır
"""
from __future__ import annotations

import logging
import logging.handlers
import os
import sys

_LOG_FORMAT = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"

_configured = False


def configure_logging(log_dir: str | None = None, level: int = logging.INFO) -> None:
    """Uygulama başlarken bir kez çağrılır (main.py). Tekrar çağrılırsa no-op.

    log_dir verilmezse sadece konsola loglanır (log_dir henüz bilinmiyorsa,
    örn. giriş ekranından önce).
    """
    global _configured
    if _configured:
        # get_logger modül yüklenirken klasörsüz yapılandırmış olabilir; klasör
        # sonradan verildiyse dosya kaydını şimdi ekle (aksi halde açılış hataları kaybolur).
        if log_dir:
            attach_log_dir(log_dir)
        return

    root = logging.getLogger("mustiefly")
    root.setLevel(level)
    root.propagate = False

    formatter = logging.Formatter(_LOG_FORMAT, datefmt=_DATE_FORMAT)

    console = logging.StreamHandler(sys.stdout)
    console.setFormatter(formatter)
    root.addHandler(console)

    if log_dir:
        try:
            os.makedirs(log_dir, exist_ok=True)
            file_handler = logging.handlers.RotatingFileHandler(
                os.path.join(log_dir, "audifly.log"),
                maxBytes=1_000_000,
                backupCount=3,
                encoding="utf-8",
            )
            file_handler.setFormatter(formatter)
            root.addHandler(file_handler)
        except Exception:
            # Log dosyası açılamazsa bile uygulama konsol logu ile çalışmaya devam eder.
            root.addHandler(console)

    _configured = True


def attach_log_dir(log_dir: str) -> None:
    """Kullanıcı giriş yaptıktan SONRA (yani log_dir belli olduğunda) dosya
    handler'ını sonradan ekler. main.py: login akışından hemen sonra çağrılır.
    """
    root = logging.getLogger("mustiefly")
    target = os.path.abspath(os.path.join(log_dir, "audifly.log"))
    if any(isinstance(h, logging.handlers.RotatingFileHandler) and h.baseFilename == target
           for h in root.handlers):
        return          # aynı dosya zaten bağlı; farklı klasör (kullanıcıya özel) ayrıca eklenir
    try:
        os.makedirs(log_dir, exist_ok=True)
        formatter = logging.Formatter(_LOG_FORMAT, datefmt=_DATE_FORMAT)
        file_handler = logging.handlers.RotatingFileHandler(
            os.path.join(log_dir, "audifly.log"),
            maxBytes=1_000_000,
            backupCount=3,
            encoding="utf-8",
        )
        file_handler.setFormatter(formatter)
        root.addHandler(file_handler)
    except Exception:
        pass  # dosyaya log yazılamazsa sessizce konsol logu ile devam


def get_logger(name: str) -> logging.Logger:
    """Her modülün kendi alt-logger'ını almasını sağlar: mustiefly.<module>."""
    if not _configured:
        configure_logging()  # en azından konsola bassın
    return logging.getLogger(f"mustiefly.{name}")
