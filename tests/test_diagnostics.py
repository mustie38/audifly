import re
from pathlib import Path

from mustiefly_qt.helpers import diagnostics
from mustiefly_qt.helpers.constants import APP_VERSION


def test_version_constant_matches_pyproject():
    text = (Path(__file__).resolve().parents[1] / "pyproject.toml").read_text(encoding="utf-8")
    assert re.search(r'^version = "([^"]+)"', text, re.M).group(1) == APP_VERSION


def test_diagnostics_contain_context_and_redact_home(tmp_path, monkeypatch):
    log_dir = tmp_path / "logs"
    log_dir.mkdir()
    (log_dir / "audifly.log").write_text("\n".join(f"satır {i}" for i in range(200)), encoding="utf-8")
    monkeypatch.setattr(diagnostics.Path, "home", staticmethod(lambda: tmp_path))
    text = diagnostics.collect_diagnostics(str(log_dir), f"Traceback ... {tmp_path}/secret/file.py")
    assert APP_VERSION in text and "Bileşenler:" in text and "FFmpeg" in text
    assert "satır 199" in text and "satır 100" not in text          # yalnızca son 60 satır
    assert str(tmp_path) not in text and "~/secret/file.py" in text


def test_missing_log_dir_is_fine():
    assert "Audifly" in diagnostics.collect_diagnostics(None)
    assert diagnostics.tail_of_latest_log("/yok/boyle/klasor") == ""


def test_crash_dialog_shows_once_and_never_raises(qapp, monkeypatch):
    from PySide6.QtWidgets import QMessageBox
    from mustiefly_qt import main as app_main
    shown = []
    monkeypatch.setattr(QMessageBox, "exec", lambda self: shown.append(self.detailedText()) or 0)
    monkeypatch.setattr(app_main, "_crash_dialog_shown", False)
    try:
        raise ValueError("deneme hatası")
    except ValueError as e:
        info = (type(e), e, e.__traceback__)
    app_main._show_crash_dialog(*info)
    app_main._show_crash_dialog(*info)                    # kaskad: ikinci pencere açılmaz
    assert len(shown) == 1 and "deneme hatası" in shown[0] and "Audifly" in shown[0]
