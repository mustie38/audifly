from unittest.mock import MagicMock
from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QMouseEvent, QPixmap
from PySide6.QtWidgets import QApplication

from mustiefly_qt.widgets.hud_overlay import HudOverlay


def test_hud_overlay_lifecycle_and_settings(qapp=None):
    if QApplication.instance() is None:
        _app = QApplication([])

    playback = MagicMock()
    thumbnails = MagicMock()
    thumbnails.pixmap_for.return_value = QPixmap(50, 50)
    settings = {
        "hud_overlay_enabled": True,
        "hud_overlay_duration": 4,
        "hud_overlay_position": "top-right",
        "hud_overlay_only_background": False,
    }

    hud = HudOverlay(playback, thumbnails, settings)

    song = {
        "title": "Bengü - Saat 3 (Official Video)",
        "uploader": "Avrupa Müzik",
        "webpage_url": "https://www.youtube.com/watch?v=HEtNpNSpTwc",
    }

    # Şarkı gösterimi
    hud.show_song(song)
    assert hud.isVisible()
    assert "Saat 3" in hud.title_label.text()
    assert "Bengü" in hud.artist_label.text()
    assert hud._hide_timer.isActive()
    assert hud._hide_timer.interval() == 4000

    # Farklı köşe konumları
    for pos in ["bottom-right", "top-left", "top-center", "top-right"]:
        settings["hud_overlay_position"] = pos
        hud._reposition()
        assert hud.x() >= 0
        assert hud.y() >= 0

    # Hover olayları
    hud.enterEvent(None)
    assert not hud._hide_timer.isActive()  # fare üzerindeyken sayaç durmalı

    hud.leaveEvent(None)
    assert hud._hide_timer.isActive()  # fare ayrılınca sayaç tekrar başlamalı

    # Tıklama sinyali
    clicked_events = []
    hud.clicked.connect(lambda: clicked_events.append(1))
    center_pt = QPointF(hud.rect().center())
    press_event = QMouseEvent(QMouseEvent.Type.MouseButtonPress, center_pt, center_pt, Qt.LeftButton, Qt.LeftButton, Qt.NoModifier)
    hud.mousePressEvent(press_event)
    assert clicked_events == [1]

    # Kapatma / dismiss
    hud.dismiss()
    assert hud._is_dismissed is True

    # Devre dışıyken gösterilmemeli
    settings["hud_overlay_enabled"] = False
    hud.show_song(song)
    # enabled=False olduğu için yeni gösterim tetiklenmemeli
    assert hud._is_dismissed is True
