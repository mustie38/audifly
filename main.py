"""
Mustiefly (Qt) - Ana giriş dosyası.

Akış (orijinal mustiefly.py'deki _bootstrap_and_run ile aynı fikir, Qt sinyal/
widget yaşam döngüsüne uyarlanmış): önce QApplication oluşturulur (login
diyalogu da bir Qt widget'ı olduğu için bu şart), sonra "beni hatırla" ile
kayıtlı bir kullanıcı var mı bakılır, yoksa giriş/kayıt diyaloğu gösterilir,
sonunda o kullanıcının yolları + teması uygulanıp MainWindow açılır.

Ayrıca: uygulama ikonu programatik üretilir ve tek örnek kilidi (ikinci
başlatma denemesi mevcut pencereyi öne getirir) QLocalServer ile sağlanır.
"""
from __future__ import annotations

import os
import sys
import threading
from pathlib import Path
sys.path.append(str(Path(__file__).resolve().parent.parent))

# --- Önyükleme: yt_dlp / vlc HİÇ import edilmeden önce yapılmalı -------------
# 1) Paketle gelen libVLC'yi kullan (kullanıcı ayrıca VLC kurmak zorunda kalmaz).
# 2) Uygulama içinden indirilmiş daha yeni bir yt-dlp varsa onu devreye al.
from mustiefly_qt.helpers import dependencies, ytdlp_runtime  # noqa: E402  (yalnız stdlib)
dependencies.configure_bundled_vlc()
try:
    ytdlp_runtime.activate()
except Exception:   # güncelleme katmanı asla açılışı engellememeli
    pass

from PySide6.QtGui import QIcon
from PySide6.QtNetwork import QLocalServer, QLocalSocket
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication, QCheckBox, QMessageBox

from mustiefly_qt.helpers.brand_icon import build_icon
from mustiefly_qt.helpers.constants import APP_DISPLAY_NAME
from mustiefly_qt.app_window import MainWindow
from mustiefly_qt.auth import service
from mustiefly_qt.auth.login_dialog import run_login_flow
from mustiefly_qt.theme import build_qss
from mustiefly_qt.helpers.logging_setup import attach_log_dir, configure_logging, get_logger


log = get_logger(__name__)
INSTANCE_KEY = "mustiefly-instance-v1"
INSTANCE_CONNECT_TIMEOUT_MS = 1500


def _check_vlc_available() -> tuple[bool, str]:
    """VLC Python bağlayıcısının ve sistemdeki VLC kurulumunun çalışır
    durumda olup olmadığını kontrol eder. (ok, hata_mesajı) döner.

    Bu kontrol olmadan, VLC kurulu değilse uygulama MainWindow oluşturma
    sırasında anlaşılmaz bir traceback ile çöküyordu — kullanıcı neyin
    eksik olduğunu asla anlayamıyordu.
    """
    try:
        import vlc  # python-vlc
    except Exception as e:
        if dependencies.bundled_vlc_dir():
            return False, (
                f"{APP_DISPLAY_NAME} ile gelen ses motoru (libVLC) başlatılamadı.\n\n"
                f"Ayrıntı: {e}\n\n"
                f"Çözüm: {APP_DISPLAY_NAME}'ı yeniden kur. Sorun sürerse "
                "Yardım → Sorun Bildir ile raporu gönder."
            )
        return False, (
            "'python-vlc' paketi kurulu değil veya yüklenemedi.\n\n"
            f"Ayrıntı: {e}\n\n"
            "Çözüm: `pip install python-vlc` komutunu çalıştır."
        )
    try:
        instance = vlc.Instance()
        if instance is None:
            raise RuntimeError("vlc.Instance() None döndü")
        player = instance.media_player_new()
        player.release()
        instance.release()
    except Exception as e:
        if dependencies.bundled_vlc_dir():
            return False, (
                f"{APP_DISPLAY_NAME} ile gelen ses motoru (libVLC) başlatılamadı.\n\n"
                f"Ayrıntı: {e}\n\n"
                f"Çözüm: {APP_DISPLAY_NAME}'ı yeniden kur. Sorun sürerse "
                "Yardım → Sorun Bildir ile raporu gönder."
            )
        return False, (
            "VLC Media Player sistemde bulunamadı ya da başlatılamadı.\n\n"
            f"Ayrıntı: {e}\n\n"
            "Çözüm: https://www.videolan.org/vlc/ adresinden VLC Media "
            "Player'ı (masaüstü uygulamasını, python-vlc paketini DEĞİL) "
            "kurup uygulamayı yeniden başlat. 64-bit Python kullanıyorsan "
            "64-bit VLC gerekir."
        )
    return True, ""


_crash_dialog_shown = False


def _show_crash_dialog(exc_type, exc_value, exc_tb) -> None:
    """Beklenmeyen hatada kullanıcıya tek bir bilgilendirme gösterir (kaskad hatalarda
    ikinci kez açılmaz). Tanılama metni kopyalanabilir; kişisel veri içermez."""
    global _crash_dialog_shown
    if _crash_dialog_shown or QApplication.instance() is None:
        return
    if threading.current_thread() is not threading.main_thread():
        return                                   # arayüz yalnızca ana thread'den açılır
    _crash_dialog_shown = True
    import traceback
    from PySide6.QtGui import QGuiApplication
    from mustiefly_qt.helpers.diagnostics import collect_diagnostics
    log_dir = LOG_DIR_HINT[0]
    report = collect_diagnostics(log_dir, "".join(traceback.format_exception(exc_type, exc_value, exc_tb)))
    box = QMessageBox(QMessageBox.Critical, f"{APP_DISPLAY_NAME} - Beklenmeyen hata",
                      "Beklenmeyen bir hata oluştu. Uygulama çalışmaya devam edebilir; "
                      "sorun sürerse yeniden başlat.\n\n"
                      f"Kayıt klasörü: {log_dir or 'bilinmiyor'}")
    box.setDetailedText(report)
    copy_btn = box.addButton("Tanılama bilgisini kopyala", QMessageBox.ActionRole)
    box.addButton(QMessageBox.Close)
    box.exec()
    if box.clickedButton() is copy_btn:
        QGuiApplication.clipboard().setText(report)


# Hata kaydının yazıldığı klasör (başlangıçta ve girişten sonra güncellenir)
LOG_DIR_HINT: list = [None]


def _install_global_excepthook():
    """Beklenmeyen (yakalanmamış) hataların log dosyasına düşmesini ve kullanıcıya
    bildirilmesini sağlar — aksi halde pencereli/paketlenmiş bir .exe'de kullanıcı
    hiçbir iz görmeden sessizce çöker. Thread'lerdeki hatalar da kaydedilir."""
    def _hook(exc_type, exc_value, exc_tb):
        if issubclass(exc_type, KeyboardInterrupt):
            sys.__excepthook__(exc_type, exc_value, exc_tb)
            return
        log.critical("Yakalanmamış hata:", exc_info=(exc_type, exc_value, exc_tb))
        if sys.__excepthook__ is not None and sys.stderr:
            sys.__excepthook__(exc_type, exc_value, exc_tb)
        try:
            _show_crash_dialog(exc_type, exc_value, exc_tb)
        except Exception:
            log.exception("Hata penceresi gösterilemedi")
    sys.excepthook = _hook

    def _thread_hook(args):
        log.critical("Thread'de yakalanmamış hata (%s):", getattr(args.thread, "name", "?"),
                     exc_info=(args.exc_type, args.exc_value, args.exc_traceback))
    threading.excepthook = _thread_hook


def _build_app_icon() -> QIcon:
    """Marka ikonu (bkz. helpers/brand_icon.py)."""
    return build_icon()


def _show_dependency_notice(window) -> None:
    """Eksik isteğe bağlı bileşenleri (FFmpeg/Node.js) tek bir uyarıyla bildirir.
    "Bir daha gösterme" seçilirse ayarlara yazılır."""
    if window.settings.get("dependency_notice_dismissed"):
        return
    text = dependencies.missing_message(dependencies.check_dependencies())
    if not text:
        return
    log.warning(text.replace("\n", " "))
    box = QMessageBox(window)
    box.setIcon(QMessageBox.Warning)
    box.setWindowTitle("Eksik bileşenler")
    box.setText(text)
    again = QCheckBox("Bir daha gösterme")
    box.setCheckBox(again)
    box.exec()
    if again.isChecked():
        window.settings["dependency_notice_dismissed"] = True
        window.save_settings()


def _connect_existing_and_raise(key: str = INSTANCE_KEY) -> bool:
    """Zaten çalışan bir örnek varsa 'öne çık' mesajı yollar, True döner."""
    sock = QLocalSocket()
    sock.connectToServer(key)
    if sock.waitForConnected(INSTANCE_CONNECT_TIMEOUT_MS):
        sock.write(b"raise\n")
        sock.flush()
        sock.waitForBytesWritten(INSTANCE_CONNECT_TIMEOUT_MS)
        sock.disconnectFromServer()
        return True
    return False


def _become_primary(app: QApplication, key: str = INSTANCE_KEY) -> QLocalServer:
    """Tek örnek sunucusunu kurar (çökme kalıntısı varsa temizler)."""
    QLocalServer.removeServer(key)
    server = QLocalServer()
    server.listen(key)
    server.setParent(app)
    return server


def _raise_existing_window(window: MainWindow, server: QLocalServer):
    """İkinci örnek 'raise' yolladığında mevcut pencereyi öne getirir."""
    sock = server.nextPendingConnection()
    if sock is not None:
        sock.readAll()
        sock.disconnectFromServer()
    if window.isMinimized():
        window.showNormal()
    window.show()
    window.raise_()
    window.activateWindow()


def _startup_update_check(window):
    """Uygulama açılışında arka planda yt-dlp güncellemesi kontrol eder;
    varsa (ayara göre) otomatik indirir ve durum çubuğunda bildirir (asla UI'ı bloklamaz)."""
    try:
        from mustiefly_qt.helpers.updates import installed_version, run_update, update_available
        has_new, inst, latest = update_available()
        if has_new:
            if window.settings.get("auto_ytdlp_update", True):
                ok, _ = run_update()
                if ok:
                    window.updateNotice.emit(
                        f"⬆ yt-dlp otomatik güncellendi ({inst} → {installed_version() or latest}). "
                        "Sonraki açılışta devreye girer.")
                else:
                    window.updateNotice.emit(
                        f"⬆ yt-dlp güncellemesi var: {inst} → {latest} — "
                        "Ayarlar'dan güncelleyebilirsin.")
            else:
                window.updateNotice.emit(
                    f"⬆ yt-dlp güncellemesi var: {inst} → {latest} — "
                    "Ayarlar'dan güncelleyebilirsin (şarkı çözümleme sorunlarını önler).")
    except Exception:
        pass  # güncelleme kontrolü kritik değil
    try:
        if window.settings.get("auto_update_check", True):
            window.app_updater.check()      # arka plan thread'i başlatır; sonuç sinyalle gelir
    except Exception:
        pass


def main():
    # Girişten ÖNCE de dosyaya yaz: pencereli .exe'de konsol yok, açılış hataları kaybolmasın
    startup_log_dir = os.path.join(service.BASE_DIR, "logs")
    configure_logging(startup_log_dir)
    LOG_DIR_HINT[0] = startup_log_dir
    _install_global_excepthook()

    app = QApplication(sys.argv)
    app.setApplicationName(APP_DISPLAY_NAME)
    app.setWindowIcon(_build_app_icon())

    vlc_ok, vlc_error = _check_vlc_available()
    if not vlc_ok:
        log.error("VLC kullanılamıyor: %s", vlc_error)
        QMessageBox.critical(None, "VLC Bulunamadı", vlc_error)
        sys.exit(1)

    if _connect_existing_and_raise():
        log.info(f"{APP_DISPLAY_NAME} zaten çalışıyor — mevcut pencere öne getirildi.")
        sys.exit(0)
    server = _become_primary(app)

    username = run_login_flow()
    if not username:
        sys.exit(0)

    paths = service.user_data_paths(username)
    paths.ensure_dirs()
    LOG_DIR_HINT[0] = paths.logs_dir
    attach_log_dir(paths.logs_dir)  # artık kullanıcıya özel log dosyasına da yazılıyor
    settings = service.load_settings_for(paths)
    theme = service.theme_for(paths)
    app.setStyleSheet(build_qss(theme))

    try:
        window = MainWindow(username, paths, settings)
    except Exception as e:
        log.exception("MainWindow oluşturulamadı")
        QMessageBox.critical(None, "Başlatma Hatası", f"Uygulama başlatılamadı:\n{e}")
        sys.exit(1)

    server.newConnection.connect(lambda: _raise_existing_window(window, server))
    window.show()
    QTimer.singleShot(1200, lambda: _show_dependency_notice(window))
    threading.Thread(target=_startup_update_check, args=(window,), daemon=True).start()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
