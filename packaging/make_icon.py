"""Marka ikonundan Windows .ico üretir (PyInstaller ve Inno Setup için).

Kullanım (proje üst dizininden):  python mustiefly_qt/packaging/make_icon.py
Çıktı: mustiefly_qt/packaging/audifly.ico
"""
import io
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from PIL import Image
from PySide6.QtCore import QBuffer, QIODevice
from PySide6.QtGui import QGuiApplication

from mustiefly_qt.helpers.brand_icon import ICON_SIZES, build_pixmap

app = QGuiApplication.instance() or QGuiApplication([])
frames = []
for size in ICON_SIZES:
    buf = QBuffer()
    buf.open(QIODevice.WriteOnly)
    build_pixmap(size).save(buf, "PNG")
    frames.append(Image.open(io.BytesIO(bytes(buf.data()))).convert("RGBA"))
out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "audifly.ico")
frames[-1].save(out, format="ICO", sizes=[(s, s) for s in ICON_SIZES], append_images=frames[:-1])
print("yazıldı:", out)
