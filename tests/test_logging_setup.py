import logging
import os

import pytest

from mustiefly_qt.helpers import logging_setup as ls


@pytest.fixture()
def clean_logger():
    root = logging.getLogger("mustiefly")
    saved, flag = list(root.handlers), ls._configured
    root.handlers.clear()
    ls._configured = False
    yield root
    for h in list(root.handlers):
        h.close()
    root.handlers[:] = saved
    ls._configured = flag


def test_log_dir_given_after_early_get_logger_still_writes_file(clean_logger, tmp_path):
    log = ls.get_logger("x")                     # modül yüklenirken: klasörsüz yapılandırma
    ls.configure_logging(str(tmp_path / "startup"))   # sonradan verilen klasör yok sayılmamalı
    log.error("açılış hatası")
    for h in clean_logger.handlers:
        h.flush()
    text = (tmp_path / "startup" / "audifly.log").read_text(encoding="utf-8")
    assert "açılış hatası" in text


def test_user_dir_is_added_besides_startup_dir_and_not_duplicated(clean_logger, tmp_path):
    ls.configure_logging(str(tmp_path / "startup"))
    ls.attach_log_dir(str(tmp_path / "user"))
    ls.attach_log_dir(str(tmp_path / "user"))     # tekrar: çift handler olmamalı
    files = [h.baseFilename for h in clean_logger.handlers
             if isinstance(h, logging.handlers.RotatingFileHandler)]
    assert sorted(os.path.dirname(f) for f in files) == sorted(
        [str(tmp_path / "startup"), str(tmp_path / "user")])
    ls.get_logger("y").warning("iki yere")
    for h in clean_logger.handlers:
        h.flush()
    assert "iki yere" in (tmp_path / "user" / "audifly.log").read_text(encoding="utf-8")
    assert "iki yere" in (tmp_path / "startup" / "audifly.log").read_text(encoding="utf-8")
