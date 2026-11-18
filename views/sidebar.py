from __future__ import annotations

import hashlib
import json
import os

from PIL import Image
from PySide6.QtCore import QSize, Qt, QTimer, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QFileDialog, QFrame, QHBoxLayout, QInputDialog, QLabel, QLineEdit,
    QListWidget, QListWidgetItem, QMenu, QMessageBox, QPushButton, QScrollArea,
    QVBoxLayout, QWidget,
)

from mustiefly_qt.helpers.constants import APP_DISPLAY_NAME
from mustiefly_qt.services.playlist_store import PlaylistStore
from mustiefly_qt.services.thumbnails import ThumbnailService, crop_to_square, pil_to_qimage
from mustiefly_qt.widgets.player_icons import icon as vicon
from mustiefly_qt.widgets.song_row import SONG_MIME
from mustiefly_qt.helpers.logging_setup import get_logger

SMART_FOLDER_KEYS = {
    "most_played", "recent", "new_added", "mixes", "fav_artists", "forgotten", "smart_rules"
}



log = get_logger(__name__)
class _PlaylistList(QListWidget):
    """Playlist listesi; şarkı satırını buraya sürükleyip bırakınca şarkı o
    listeye KOPLANIR (orijinal liste kalır — Spotify bırakma davranışı)."""

    def __init__(self, sidebar: "SidebarWidget", parent=None):
        super().__init__(parent)
        self.sidebar = sidebar
        self.setAcceptDrops(True)
        self.setDropIndicatorShown(True)

    def _accepts(self, event) -> bool:
        return event.mimeData().hasFormat(SONG_MIME)

    def dragEnterEvent(self, event):  # noqa: N802
        if self._accepts(event):
            event.acceptProposedAction()
        else:
            super().dragEnterEvent(event)

    def dragMoveEvent(self, event):  # noqa: N802
        if self._accepts(event):
            event.acceptProposedAction()
        else:
            super().dragMoveEvent(event)

    def dropEvent(self, event):  # noqa: N802
        if not self._accepts(event):
            super().dropEvent(event)
            return
        item = self.itemAt(event.pos())
        if item is None:
            return
        try:
            payload = json.loads(bytes(event.mimeData().data(SONG_MIME)).decode("utf-8"))
        except Exception:
            return
        event.acceptProposedAction()
        self.sidebar.handle_song_drop(payload.get("playlist"),
                                      payload.get("index", -1),
                                      item.data(Qt.UserRole))


class _PlaylistRow(QWidget):
    """Sidebar'daki tek playlist satırı: mini kapak + ad + sağa yaslı gri sayı.
    QListWidgetItem metni yerine setItemWidget ile yerleşir (şarkı sayısı
    zarif şekilde sağda, aktif liste vurgulu görünür)."""

    def __init__(self, name: str, count: int, cover_pm=None, parent=None):
        super().__init__(parent)
        self.setObjectName("PlaylistRowItem")
        row = QHBoxLayout(self)
        row.setContentsMargins(8, 5, 10, 5)
        row.setSpacing(8)

        cover = QLabel()
        cover.setFixedSize(26, 26)
        cover.setAlignment(Qt.AlignCenter)
        if cover_pm is not None and not cover_pm.isNull():
            from PySide6.QtCore import Qt as _Qt
            from mustiefly_qt.services.thumbnails import _rounded_pixmap
            scaled = cover_pm.scaled(26, 26, _Qt.KeepAspectRatioByExpanding,
                                     _Qt.SmoothTransformation)
            cover.setPixmap(_rounded_pixmap(scaled, 6))
        else:
            from mustiefly_qt.helpers.constants import cover_color_for
            cover.setText("🎵")
            cover.setStyleSheet(
                f"background: {cover_color_for(name)}; border-radius: 6px; font-size: 12px;")
        row.addWidget(cover)

        self.name_label = QLabel(name)
        self.name_label.setObjectName("PlaylistRowName")
        row.addWidget(self.name_label, stretch=1)

        self.count_label = QLabel(str(count))
        self.count_label.setObjectName("PlaylistRowCount")
        row.addWidget(self.count_label)

    def set_active(self, active: bool):
        """Aktif playlist'in adını vurgu renginde gösterir."""
        self.name_label.setProperty("active", "true" if active else "false")
        self.name_label.style().unpolish(self.name_label)
        self.name_label.style().polish(self.name_label)


class SidebarWidget(QWidget):
    navSelected = Signal(str)          # "home" | "explore" | "library" | "liked" | ...
    playlistSelected = Signal(str)
    menuRequested = Signal()
    settingsRequested = Signal()
    equalizerRequested = Signal()
    lyricsRequested = Signal()
    miniPlayerRequested = Signal()
    reportRequested = Signal()

    COVER_SIZE = 36  # listedeki mini kapak boyutu

    def __init__(self, store: PlaylistStore, thumbnails: ThumbnailService | None = None,
                 paths=None, parent=None):
        super().__init__(parent)
        self.store = store
        self.thumbnails = thumbnails
        self.paths = paths
        self.setObjectName("Sidebar")
        self.setFixedWidth(240)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Pencere kısaltıldığında (tam ekran değilken) nav butonları + liste
        # toplam boyu mevcut alandan büyük olabiliyordu; bu da alttaki araç
        # satırının (⚙ Ayarlar vb.) son playlist satırıyla iç içe geçmesine
        # yol açıyordu. Çözüm: üst kısmı (marka + nav + listeler) kaydırılabilir
        # bir alana koy, araç satırını ayrı, sabit yükseklikli, üstü çizgili bir
        # alt bölmeye taşı — bu bölme boyut ne olursa olsun asla ezilmez.
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setStyleSheet("QScrollArea { background: transparent; border: none; }")
        scroll.setAttribute(Qt.WA_StyledBackground, True)
        scroll.viewport().setAutoFillBackground(False)

        top_content = QWidget()
        top_content.setAttribute(Qt.WA_StyledBackground, True)
        top_content.setStyleSheet("background: transparent;")
        top = QVBoxLayout(top_content)
        top.setContentsMargins(14, 18, 14, 12)
        top.setSpacing(2)

        # --- Marka bloğu ---
        brand_row = QHBoxLayout()
        brand_row.setContentsMargins(4, 0, 4, 0)
        brand_row.setSpacing(10)
        brand_icon = QLabel("🎵")
        brand_icon.setObjectName("BrandIcon")
        brand_icon.setAlignment(Qt.AlignCenter)
        brand_icon.setFixedSize(40, 40)
        brand_row.addWidget(brand_icon)
        brand_box = QVBoxLayout()
        brand_box.setSpacing(0)
        brand_title = QLabel(APP_DISPLAY_NAME)
        brand_title.setObjectName("BrandTitle")
        brand_box.addWidget(brand_title)
        brand_tag = QLabel("music is freedom")
        brand_tag.setObjectName("Muted")
        brand_tag.setStyleSheet("font-size: 10px;")
        brand_box.addWidget(brand_tag)
        brand_row.addLayout(brand_box, stretch=1)

        self.menu_btn = QPushButton("☰")
        self.menu_btn.setObjectName("IconSquare")
        self.menu_btn.setFixedSize(32, 32)
        self.menu_btn.setToolTip("Ana Menü (Audifly, Araçlar, Ses, Yardım)")
        self.menu_btn.setCursor(Qt.PointingHandCursor)
        self.menu_btn.setStyleSheet(
            "QPushButton#IconSquare { font-size: 15px; color: #cfc9e6; "
            "background: rgba(255,255,255,0.05); border: 1px solid rgba(255,255,255,0.08); "
            "border-radius: 10px; }"
            "QPushButton#IconSquare:hover { background: rgba(255,255,255,0.12); color: #ffffff; }"
        )
        self.menu_btn.clicked.connect(self.menuRequested.emit)
        brand_row.addWidget(self.menu_btn)

        top.addLayout(brand_row)
        top.addSpacing(14)

        # --- Navigasyon ---
        self._nav_buttons: dict[str, QPushButton] = {}
        self._nav_icons: dict[str, str] = {}

        primary_nav = (
            ("home", "  Ana Sayfa", "home"),
            ("explore", "  Keşfet", "compass"),
            ("library", "  Kütüphane", "grid"),
            ("liked", "  Beğenilenler", "heart"),
            ("queue", "  Sırada", "queue"),
            ("downloads", "  İndirmeler", "download"),
        )
        for key, label, ic_name in primary_nav:
            btn = QPushButton(label)
            btn.setObjectName("NavButton")
            btn.setIcon(vicon(ic_name, 16, "#9e98b8"))
            btn.setIconSize(QSize(16, 16))
            btn.setCursor(Qt.PointingHandCursor)
            btn.clicked.connect(lambda _=False, k=key: self._select_nav(k))
            top.addWidget(btn)
            self._nav_buttons[key] = btn
            self._nav_icons[key] = ic_name

        # --- Katlanabilir Klasör: Akıllı Listeler & Mix'ler ---
        self._smart_folder_open = False
        self.smart_folder_btn = QPushButton("  Akıllı Listeler & Mix'ler   ▸")
        self.smart_folder_btn.setObjectName("NavFolderButton")
        self.smart_folder_btn.setIcon(vicon("folder", 16, "#b497ff"))
        self.smart_folder_btn.setIconSize(QSize(16, 16))
        self.smart_folder_btn.setCursor(Qt.PointingHandCursor)
        self.smart_folder_btn.setToolTip(
            "En Çok Dinlenen, Son Çalınanlar, Yeni Eklenenler, Mix'ler, Favori Sanatçılar ve Unutulanlar klasörünü aç/kapat"
        )
        self.smart_folder_btn.clicked.connect(self.toggle_smart_folder)
        top.addWidget(self.smart_folder_btn)

        self.smart_folder_container = QWidget()
        self.smart_folder_container.setObjectName("SmartFolderContainer")
        self.smart_folder_container.setVisible(False)
        folder_layout = QVBoxLayout(self.smart_folder_container)
        folder_layout.setContentsMargins(12, 3, 4, 4)
        folder_layout.setSpacing(2)

        smart_nav = (
            ("most_played", "  En Çok Dinlenen", "star"),
            ("recent", "  Son Çalınanlar", "clock"),
            ("new_added", "  Yeni Eklenenler", "sparkle"),
            ("mixes", "  Senin İçin Mix'ler", "disc"),
            ("fav_artists", "  Favori Sanatçılar", "user"),
            ("forgotten", "  Unutulanlar", "archive"),
            ("smart_rules", "  Kural Listeleri", "sliders"),
        )
        for key, label, ic_name in smart_nav:
            btn = QPushButton(label)
            btn.setObjectName("NavSubButton")
            btn.setIcon(vicon(ic_name, 14, "#9e98b8"))
            btn.setIconSize(QSize(14, 14))
            btn.setCursor(Qt.PointingHandCursor)
            btn.clicked.connect(lambda _=False, k=key: self._select_nav(k))
            folder_layout.addWidget(btn)
            self._nav_buttons[key] = btn
            self._nav_icons[key] = ic_name

        top.addWidget(self.smart_folder_container)

        # --- Alt Ana Navigasyon ---
        secondary_nav = (
            ("radio", "  Canlı Radyo", "radio"),
            ("stats", "  İstatistikler", "chart"),
            ("wrapped", "  Wrapped Özeti", "gift"),
        )
        for key, label, ic_name in secondary_nav:
            btn = QPushButton(label)
            btn.setObjectName("NavButton")
            btn.setIcon(vicon(ic_name, 16, "#9e98b8"))
            btn.setIconSize(QSize(16, 16))
            btn.setCursor(Qt.PointingHandCursor)
            btn.clicked.connect(lambda _=False, k=key: self._select_nav(k))
            top.addWidget(btn)
            self._nav_buttons[key] = btn
            self._nav_icons[key] = ic_name

        top.addSpacing(12)

        # --- Listeler bölümü ---
        header_row = QHBoxLayout()
        header_row.setContentsMargins(4, 0, 4, 0)
        header = QLabel("LİSTELER")
        header.setObjectName("SectionHeader")
        header_row.addWidget(header)
        header_row.addStretch(1)
        top.addLayout(header_row)

        new_btn = QPushButton("  Yeni Liste Oluştur")
        new_btn.setObjectName("LinkButton")
        new_btn.setIcon(vicon("plus", 13, "#a980f9"))
        new_btn.setIconSize(QSize(13, 13))
        new_btn.setCursor(Qt.PointingHandCursor)
        new_btn.clicked.connect(self._create_playlist)
        top.addWidget(new_btn)

        self.playlist_list = _PlaylistList(self)
        self.playlist_list.itemClicked.connect(self._on_playlist_clicked)
        self.playlist_list.setContextMenuPolicy(Qt.CustomContextMenu)
        self.playlist_list.customContextMenuRequested.connect(self._on_context_menu)
        # 72px kolaj pixmap'i satır yüksekliğini bozup ikinci satırı ezmesin:
        # ikon boyutunu sabitle, her satıra düzgün yükseklik ver.
        self.playlist_list.setIconSize(QSize(26, 26))
        # Kaydırma artık dış QScrollArea'da olduğu için burada sabit bir
        # minimum yükseklik yeterli; QListWidget kendi taşmasını üretmiyor,
        # sadece kendi doğal boyutunu talep ediyor.
        self.playlist_list.setMinimumHeight(160)
        top.addWidget(self.playlist_list, stretch=1)

        scroll.setWidget(top_content)
        layout.addWidget(scroll, stretch=1)

        self.store.playlistsChanged.connect(self._on_structure_changed)
        self.store.activePlaylistChanged.connect(lambda _: self.refresh())
        if self.thumbnails is not None:
            # Bir thumbnail indiğinde kolajları/mini kapakları debounce'lu tazele —
            # her indirme olayında tam refresh yapmak liste titremesine yol açıyordu.
            self._thumb_debounce = QTimer(self)
            self._thumb_debounce.setSingleShot(True)
            self._thumb_debounce.setInterval(300)
            self._thumb_debounce.timeout.connect(self._refresh_stale_covers)
            self.thumbnails.thumbnailReady.connect(lambda _key: self._thumb_debounce.start())
        # Kolaj önbelleği: playlist adı → (son-4 URL imzası, pixmap|None)
        # İmza, orijinaldeki gibi son şarkılar değişince bayatlamayı engeller.
        self._cover_pixmaps: dict[str, QPixmap | None] = {}
        self._cover_signatures: dict[str, tuple] = {}
        self._custom_cover_cache: dict[str, tuple] = {}
        self.refresh()

    def toggle_smart_folder(self):
        self.set_smart_folder_open(not self._smart_folder_open)

    def set_smart_folder_open(self, opened: bool):
        self._smart_folder_open = bool(opened)
        self.smart_folder_container.setVisible(self._smart_folder_open)
        arrow = "▾" if self._smart_folder_open else "▸"
        self.smart_folder_btn.setText(f"  Akıllı Listeler & Mix'ler   {arrow}")
        ic_kind = "folder_open" if self._smart_folder_open else "folder"
        has_act = self.smart_folder_btn.property("has_active") == "true"
        self.smart_folder_btn.setIcon(vicon(ic_kind, 16, "#ffffff" if has_act else "#b497ff"))

    def set_active_nav(self, key: str | None):
        """Navigasyon butonlarının aktif görünümünü ve vektör ikon renklerini günceller."""
        for k, btn in self._nav_buttons.items():
            is_act = (k == key)
            btn.setProperty("active", "true" if is_act else "false")
            ic_name = self._nav_icons.get(k)
            if ic_name:
                sz = 14 if k in SMART_FOLDER_KEYS else 16
                btn.setIcon(vicon(ic_name, sz, "#ffffff" if is_act else "#9e98b8"))
            btn.style().unpolish(btn)
            btn.style().polish(btn)

        in_folder = bool(key in SMART_FOLDER_KEYS)
        self.smart_folder_btn.setProperty("has_active", "true" if in_folder else "false")
        ic_kind = "folder_open" if self._smart_folder_open else "folder"
        self.smart_folder_btn.setIcon(vicon(ic_kind, 16, "#ffffff" if in_folder else "#b497ff"))
        self.smart_folder_btn.style().unpolish(self.smart_folder_btn)
        self.smart_folder_btn.style().polish(self.smart_folder_btn)

    def _select_nav(self, key: str):
        self.set_active_nav(key)
        self.playlist_list.clearSelection()
        self.navSelected.emit(key)

    def _on_playlist_clicked(self, item: QListWidgetItem):
        name = item.data(Qt.UserRole)
        self.set_active_nav(None)
        self.store.switch_playlist(name)
        self.playlistSelected.emit(name)

    # --- Şarkı sürükle → listeye bırak (kopyalama) ---
    def handle_song_drop(self, source_playlist: str | None,
                         index: int, target_playlist: str):
        store = self.store
        songs = store.playlists.get(source_playlist) if source_playlist else None
        if not songs or not (0 <= index < len(songs)) or target_playlist is None:
            return
        song = songs[index]
        if source_playlist == target_playlist:
            return  # kendi listesine bırakmak anlamsız
        if store.add_song(target_playlist, song):
            store.statusMessage.emit(
                f"📂 '{song.get('title', '?')}' → '{target_playlist}' listesine eklendi.",
                "success")
        else:
            store.statusMessage.emit(
                f"⚠️ '{song.get('title', '?')}' zaten '{target_playlist}' listesinde.",
                "warning")

    def _on_structure_changed(self):
        """Şarkı ekleme/çıkarma/liste değişimi: kolaj imzaları artık güvenilmez."""
        # Her değişimde (beğeni, ekleme…) tüm kolajları yeniden üretmek pahalıydı.
        # İçerik değişimi zaten "son 4 şarkı" imzasıyla algılanıyor; burada yalnız
        # artık var olmayan listelerin kayıtları temizlenir.
        for stale in [n for n in self._cover_pixmaps if n not in self.store.playlists]:
            self._cover_pixmaps.pop(stale, None)
            self._cover_signatures.pop(stale, None)
        self.refresh()

    def refresh(self):
        current_name = None
        selected_items = self.playlist_list.selectedItems()
        if selected_items:
            current_name = selected_items[0].data(Qt.UserRole)

        self.playlist_list.clear()
        for name, songs in self.store.playlists.items():
            item = QListWidgetItem()
            item.setData(Qt.UserRole, name)
            item.setSizeHint(QSize(0, 38))  # sabit satır yüksekliği

            pm = self._playlist_cover_pixmap(name, songs)
            row = _PlaylistRow(name, len(songs), pm)
            row.set_active(name == self.store.active_playlist or name == current_name)
            self.playlist_list.addItem(item)
            self.playlist_list.setItemWidget(item, row)
            if name == self.store.active_playlist or name == current_name:
                item.setSelected(True)

    def _refresh_stale_covers(self):
        """Thumbnail indikçe çağrılır: henüz kolajı olmayan playlistler için TEK
        deneme yapar; yeni bir kolaj üretilebildiyse listeyi tazeler."""
        if self.thumbnails is None:
            return
        changed = False
        for name, songs in self.store.playlists.items():
            if name in self._cover_pixmaps or not songs:
                continue  # zaten çözümlendi
            pm = self._build_collage_pixmap(songs)
            if pm is None:
                continue  # kapaklar hâlâ inmedi: sıradaki thumbnail olayında yeniden denenir
            self._cover_signatures[name] = tuple(s.get('webpage_url') for s in songs[-4:])
            self._cover_pixmaps[name] = pm
            changed = True
        if changed:
            self.refresh()

    # --- Kapak üretimi: özel kapak > thumbnail kolajı ---
    def _playlist_cover_pixmap(self, name: str, songs: list[dict]) -> QPixmap | None:
        custom = self._custom_cover_pixmap(name)
        if custom is not None:
            return custom

        sig = tuple(s.get('webpage_url') for s in songs[-4:])
        cached_sig = self._cover_signatures.get(name)
        if cached_sig == sig and name in self._cover_pixmaps:
            return self._cover_pixmaps[name]

        pm = self._build_collage_pixmap(songs)
        if pm is not None:
            self._cover_signatures[name] = sig
            self._cover_pixmaps[name] = pm
        else:
            # Kapaklar henüz inmediyse None'ı KALICI cache'leme: eskiden kolaj,
            # bir yapı değişikliği olana dek hiç gelmiyordu.
            self._cover_pixmaps.pop(name, None)
            self._cover_signatures.pop(name, None)
        return pm

    def _on_thumb_ready(self):
        """Geriye dönük uyumluluk — debounce'lu _refresh_stale_covers kullanılıyor."""
        self._thumb_debounce.start()

    def _custom_cover_pixmap(self, name: str) -> QPixmap | None:
        path = self.store.playlist_covers.get(name)
        if not path or not os.path.exists(path):
            return None
        try:
            # Her sidebar yenilemesinde diskten okuyup yeniden ölçeklemek yerine
            # (yol, değişim zamanı) anahtarlı önbellek.
            mtime = os.path.getmtime(path)
            cache = self._custom_cover_cache
            hit = cache.get(name)
            if hit is not None and hit[0] == path and hit[1] == mtime:
                return hit[2]
            pil_img = Image.open(path).convert("RGB")
            square = crop_to_square(pil_img).resize(
                (self.COVER_SIZE * 2, self.COVER_SIZE * 2), Image.Resampling.LANCZOS)
            pm = QPixmap.fromImage(pil_to_qimage(square))
            cache[name] = (path, mtime, pm)
            return pm
        except Exception as e:
            log.error("%s %s", "Playlist kapağı yüklenemedi:", e)
            return None

    def _build_collage_pixmap(self, songs: list[dict]) -> QPixmap | None:
        """Son 4 şarkının kapağından 2x2 kolaj. Thumbnail'ler hazır değilse None —
        indikçe _on_thumb_ready üzerinden tekrar denenir."""
        if self.thumbnails is None or not songs:
            return None
        recent = songs[-4:]
        imgs = []
        missing = False
        for s in recent:
            img = self.thumbnails.pil_for(s)
            if img is None:
                self.thumbnails.request(s)   # disk önbelleğinden / ağdan yüklenmesini tetikle
                missing = True
            else:
                imgs.append(img)
        if missing:
            return None
        try:
            cell = self.COVER_SIZE * 2
            size = cell * 2
            collage = Image.new('RGB', (size, size), '#282828')
            positions = [(0, 0), (cell, 0), (0, cell), (cell, cell)]
            for i, img in enumerate(imgs[:4]):
                resized = crop_to_square(img).resize((cell, cell), Image.Resampling.BILINEAR)
                collage.paste(resized, positions[i])
            return QPixmap.fromImage(pil_to_qimage(collage))
        except Exception as e:
            log.error("%s %s", "Kolaj oluşturulamadı:", e)
            return None

    # --- Liste işlemleri ---
    def _create_playlist(self):
        name, ok = QInputDialog.getText(self, "Yeni Çalma Listesi", "Liste adı:")
        if not ok or not name.strip():
            return
        success, err = self.store.create_playlist(name)
        if not success:
            QMessageBox.warning(self, "Hata", err)
        else:
            self.playlistSelected.emit(name)

    def _on_context_menu(self, pos):
        item = self.playlist_list.itemAt(pos)
        if item is None:
            return
        name = item.data(Qt.UserRole)
        menu = QMenu(self)
        rename_action = menu.addAction("✏ Yeniden adlandır")
        change_cover_action = menu.addAction("🖼 Kapak Değiştir…")
        remove_cover_action = menu.addAction("❌ Kapağı Kaldır")
        export_m3u_action = menu.addAction("📤 M3U olarak dışa aktar")
        delete_action = menu.addAction("🗑 Sil")

        has_custom = bool(self.store.playlist_covers.get(name))
        remove_cover_action.setEnabled(has_custom)

        chosen = menu.exec(self.playlist_list.mapToGlobal(pos))
        if chosen == rename_action:
            new_name, ok = QInputDialog.getText(self, "Yeniden Adlandır", "Yeni ad:",
                                                QLineEdit.Normal, name)
            if ok and new_name.strip():
                success, err = self.store.rename_playlist(name, new_name)
                if not success and err:
                    QMessageBox.warning(self, "Hata", err)
                else:
                    self._cover_pixmaps.pop(name, None)
                    self._custom_cover_cache.pop(name, None)
                    self._cover_signatures.pop(name, None)
        elif chosen == delete_action:
            confirm = QMessageBox.question(
                self, "Listeyi Sil", f"\"{name}\" listesini silmek istediğine emin misin?")
            if confirm == QMessageBox.Yes:
                success, err = self.store.delete_playlist(name)
                if not success and err:
                    QMessageBox.warning(self, "Hata", err)
                else:
                    self._cover_pixmaps.pop(name, None)
                    self._custom_cover_cache.pop(name, None)
                    self._cover_signatures.pop(name, None)
                    self.playlistSelected.emit(self.store.active_playlist)
        elif chosen == change_cover_action:
            self._change_playlist_cover(name)
        elif chosen == remove_cover_action:
            self._remove_playlist_cover(name)
        elif chosen == export_m3u_action:
            from mustiefly_qt.views.import_dialogs import export_playlist_m3u_dialog
            export_playlist_m3u_dialog(self.store, name, self)

    # --- Özel kapak yönetimi ---
    def _change_playlist_cover(self, name: str):
        if self.paths is None:
            return
        path, _ = QFileDialog.getOpenFileName(
            self, f"'{name}' için kapak resmi seç", "",
            "Görsel dosyaları (*.png *.jpg *.jpeg *.webp *.bmp);;Tüm dosyalar (*.*)")
        if not path:
            return
        try:
            pil_img = Image.open(path).convert("RGB")
        except Exception as e:
            QMessageBox.critical(self, "Görsel Açılamadı",
                                 f"Seçilen dosya bir görsel olarak açılamadı:\n\n{e}")
            return

        os.makedirs(self.paths.covers_dir, exist_ok=True)
        dest_filename = f"{hashlib.md5(name.encode('utf-8')).hexdigest()}.jpg"
        dest_path = os.path.join(self.paths.covers_dir, dest_filename)
        try:
            square_img = crop_to_square(pil_img).resize((300, 300), Image.Resampling.LANCZOS)
            square_img.save(dest_path, "JPEG", quality=90)
        except Exception as e:
            QMessageBox.critical(self, "Kaydedilemedi",
                                 f"Kapak resmi kaydedilirken hata oluştu:\n\n{e}")
            return

        self.store.playlist_covers[name] = dest_path
        self._cover_pixmaps.pop(name, None)
        self._custom_cover_cache.pop(name, None)
        self.store.save()
        self.store.playlistsChanged.emit()
        self.store.statusMessage.emit(f"'{name}' listesinin kapağı güncellendi.", "success")

    def _remove_playlist_cover(self, name: str):
        old_path = self.store.playlist_covers.pop(name, None)
        if old_path and os.path.exists(old_path):
            try:
                os.remove(old_path)
            except Exception:
                pass
        self._cover_pixmaps.pop(name, None)
        self._custom_cover_cache.pop(name, None)
        self.store.save()
        self.store.playlistsChanged.emit()
        self.store.statusMessage.emit(f"'{name}' listesinin kapağı kaldırıldı.", "info")
