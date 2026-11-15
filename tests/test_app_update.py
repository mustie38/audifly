import hashlib
import os
from unittest.mock import MagicMock

import pytest

from mustiefly_qt.helpers import app_update as au

BASE = au.DOWNLOAD_PREFIX + "v9.9.9/"
SHA = hashlib.sha256(b"installer-bytes").hexdigest()


def release(**over):
    data = {"tag_name": "v9.9.9", "html_url": f"https://github.com/{au.REPO}/releases/tag/v9.9.9",
            "body": "Yenilikler", "draft": False, "prerelease": False,
            "assets": [{"name": au.INSTALLER_NAME, "browser_download_url": BASE + au.INSTALLER_NAME,
                        "size": 15, "digest": f"sha256:{SHA}"}]}
    data.update(over)
    return data


def response(json_data=None, status=200, text="", chunks=None, headers=None):
    r = MagicMock()
    r.status_code = status
    r.json.return_value = json_data
    r.text = text
    r.headers = headers or {}
    r.iter_content.return_value = chunks or []
    r.__enter__ = lambda self: r
    r.__exit__ = lambda *a: False
    return r


def test_version_compare():
    assert au.is_newer("0.5.0", "0.4.2") and au.is_newer("v0.4.10", "0.4.9")
    assert not au.is_newer("0.4.2", "0.4.2") and not au.is_newer("0.4.1", "0.4.2")
    assert not au.is_newer("abc", "0.4.2") and not au.is_newer("0.5.0", "bozuk")


def test_parse_release_uses_digest_and_rejects_draft_prerelease_and_foreign_urls():
    info, extra = au.parse_release(release())
    assert info.version == "9.9.9" and info.sha256 == SHA and info.can_auto_install and extra is None
    assert au.parse_release(release(draft=True)) == (None, None)
    assert au.parse_release(release(prerelease=True)) == (None, None)
    assert au.parse_release(release(tag_name="sürüm-x")) == (None, None)
    evil = release(assets=[{"name": au.INSTALLER_NAME, "browser_download_url": "https://evil.example/a.exe",
                            "digest": f"sha256:{SHA}"}])
    info, _ = au.parse_release(evil)
    assert info.installer_url is None and not info.can_auto_install
    off = release(html_url="https://evil.example/")
    assert au.parse_release(off)[0].page_url == au.RELEASES_PAGE


def test_checksum_sidecar_is_fetched_when_no_digest():
    data = release(assets=[
        {"name": au.INSTALLER_NAME, "browser_download_url": BASE + au.INSTALLER_NAME},
        {"name": au.CHECKSUM_NAME, "browser_download_url": BASE + au.CHECKSUM_NAME}])
    calls = []

    def get(url, **kw):
        calls.append(url)
        return response(data) if url == au.API_LATEST else response(text=f"{SHA.upper()}  AudiflySetup.exe\n")

    info = au.fetch_latest_release(get)
    assert info.sha256 == SHA and info.can_auto_install and len(calls) == 2


def test_check_for_update_statuses_and_errors():
    assert au.check_for_update("0.4.2", lambda *a, **k: response(release()))[0] == au.AVAILABLE
    assert au.check_for_update("9.9.9", lambda *a, **k: response(release()))[0] == au.UP_TO_DATE
    assert au.check_for_update("0.4.2", lambda *a, **k: response(status=404)) == (au.NO_RELEASE, None)
    with pytest.raises(au.UpdateError):
        au.check_for_update("0.4.2", MagicMock(side_effect=OSError("ağ yok")))


def _info():
    return au.parse_release(release())[0]


def test_download_verifies_and_reports_progress(tmp_path):
    seen = []
    get = lambda *a, **k: response(chunks=[b"installer-", b"bytes"], headers={"Content-Length": "15"})
    path = au.download_installer(_info(), str(tmp_path), progress=seen.append, get=get)
    assert os.path.basename(path) == "AudiflySetup-9.9.9.exe" and open(path, "rb").read() == b"installer-bytes"
    assert seen[-1] == 100 and not os.path.exists(path + ".part")


def test_download_rejects_hash_mismatch_and_cleans_up(tmp_path):
    get = lambda *a, **k: response(chunks=[b"tampered"], headers={"Content-Length": "8"})
    with pytest.raises(au.UpdateError, match="doğrulanamadı"):
        au.download_installer(_info(), str(tmp_path), get=get)
    assert os.listdir(tmp_path) == []


def test_download_cancel_and_missing_hash(tmp_path):
    get = lambda *a, **k: response(chunks=[b"x" * 10], headers={"Content-Length": "10"})
    with pytest.raises(au.UpdateError, match="iptal"):
        au.download_installer(_info(), str(tmp_path), cancelled=lambda: True, get=get)
    nohash = au.ReleaseInfo("9.9.9", "v9.9.9", "", au.RELEASES_PAGE, BASE + au.INSTALLER_NAME, None)
    with pytest.raises(au.UpdateError, match="doğrulanabilir"):
        au.download_installer(nohash, str(tmp_path), get=get)
    assert not au.launch_installer(str(tmp_path / "yok.exe"))


def test_updater_service_emits_results(library_store):
    from mustiefly_qt.services.app_updater import AppUpdater
    info = _info()
    updater = AppUpdater(check_fn=lambda: (au.AVAILABLE, info),
                         download_fn=lambda i, progress=None, cancelled=None: (_ for _ in ()).throw(
                             au.UpdateError("İndirme başarısız: x")))
    got, failed = [], []
    updater.checkFinished.connect(lambda s, i, m: got.append((s, i, m)))
    updater.downloadFailed.connect(failed.append)
    from PySide6.QtCore import QEventLoop, QTimer
    from PySide6.QtWidgets import QApplication
    updater.check()
    updater.download(info)
    loop = QEventLoop()
    QTimer.singleShot(400, loop.quit)
    loop.exec()
    QApplication.processEvents()
    assert got == [("available", info, "")] and failed == ["İndirme başarısız: x"]
