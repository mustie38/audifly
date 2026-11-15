import hashlib
import importlib.util
import io
import json
import zipfile
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parent.parent / "packaging" / "fetch_node.py"


@pytest.fixture(scope="module")
def fn():
    spec = importlib.util.spec_from_file_location("fetch_node", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


INDEX = [
    {"version": "v25.1.0", "lts": False, "files": ["win-x64-zip"]},          # LTS değil
    {"version": "v24.2.0", "lts": "Krypton", "files": ["linux-x64"]},        # win zip yok
    {"version": "v22.11.0", "lts": "Jod", "files": ["win-x64-zip", "win-x64-msi"]},
    {"version": "v18.20.0", "lts": "Hydrogen", "files": ["win-x64-zip"]},    # çok eski
]


def test_pick_lts_skips_non_lts_missing_zip_and_old_versions(fn):
    assert fn.pick_lts(INDEX) == "v22.11.0"
    with pytest.raises(RuntimeError):
        fn.pick_lts([INDEX[0], INDEX[3]])


def test_parse_shasums(fn):
    h = "a" * 64
    text = f"{h}  node-v22.11.0-win-x64.zip\n{'b' * 64} *node-v22.11.0-linux-x64.tar.gz\nçöp satır\n"
    sums = fn.parse_shasums(text)
    assert sums["node-v22.11.0-win-x64.zip"] == h and "node-v22.11.0-linux-x64.tar.gz" in sums
    assert len(sums) == 2


def _fake_world(version="v22.11.0", tamper=False):
    root = f"node-{version}-win-x64/"
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr(root + "node.exe", b"MZ-fake-node")
        zf.writestr(root + "LICENSE", b"MIT-like license")
    data = buf.getvalue()
    digest = hashlib.sha256(b"baska" if tamper else data).hexdigest()
    name = f"node-{version}-win-x64.zip"
    files = {
        "https://nodejs.org/dist/index.json": json.dumps(INDEX).encode(),
        f"https://nodejs.org/dist/{version}/SHASUMS256.txt": f"{digest}  {name}\n".encode(),
        f"https://nodejs.org/dist/{version}/{name}": data,
    }
    return lambda url, *a, **k: files[url]


def test_install_node_downloads_verifies_and_writes(fn, tmp_path):
    version, path = fn.install_node(tmp_path / "bin", get=_fake_world())
    assert version == "v22.11.0" and path.read_bytes() == b"MZ-fake-node"
    assert (tmp_path / "bin" / "LICENSE-node.txt").read_bytes() == b"MIT-like license"


def test_install_node_rejects_hash_mismatch_and_writes_nothing(fn, tmp_path):
    with pytest.raises(RuntimeError, match="SHA-256 uyusmuyor"):
        fn.install_node(tmp_path / "bin", get=_fake_world(tamper=True))
    assert not (tmp_path / "bin").exists()


def test_main_returns_error_code_instead_of_crashing(fn, tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(fn, "fetch", lambda *a, **k: (_ for _ in ()).throw(OSError("ag yok")))
    assert fn.main(["--dest", str(tmp_path / "b")]) == 1
    assert "HATA" in capsys.readouterr().err


def test_install_node_never_touches_network_when_get_is_mocked(fn, tmp_path, monkeypatch):
    """Varsayılan 'fetch' çağrı anında çözülmeli: bu test gerçek ağ erişimi olsa da geçmeli."""
    calls = []
    monkeypatch.setattr(fn, "fetch", lambda url, *a, **k: calls.append(url) or (_ for _ in ()).throw(OSError("yok")))
    with pytest.raises(OSError):
        fn.install_node(tmp_path / "bin")
    assert calls == ["https://nodejs.org/dist/index.json"]
