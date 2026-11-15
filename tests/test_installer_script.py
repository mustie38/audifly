"""audifly.iss'i Inno Setup olmadan da denetler (CI'da Inno derlemesi ancak etiket atınca çalışır;
bu testler aynı sınıf hataları push anında yakalar)."""
import importlib.util
import re
from pathlib import Path

import pytest

PACKAGING = Path(__file__).resolve().parent.parent / "packaging"
ISS = PACKAGING / "audifly.iss"
ALLOWED_DIRECTIVES = ("define", "undef", "if", "ifdef", "ifndef", "else", "elif", "endif",
                      "include", "emit", "pragma", "error", "sub", "endsub")


@pytest.fixture(scope="module")
def iss_text():
    return ISS.read_text(encoding="utf-8-sig")


def test_iss_has_utf8_bom_so_turkish_text_is_not_garbled():
    assert ISS.read_bytes()[:3] == b"\xef\xbb\xbf"


def test_iss_has_no_stray_preprocessor_lines(iss_text):
    """'#13#10' gibi Pascal karakter kodları satır başındaysa ISPP bunu komut sanıp derlemeyi
    'Unknown preprocessor directive' ile durdurur (v0.4.3 release'i bu yüzden kırıldı)."""
    for number, line in enumerate(iss_text.splitlines(), 1):
        stripped = line.strip()
        if stripped.startswith("#"):
            name = re.match(r"#\s*(\w+)", stripped)
            assert name and name.group(1).lower() in ALLOWED_DIRECTIVES, f"{number}. satır: {stripped!r}"


def test_iss_setup_section_has_no_trailing_comments(iss_text):
    section = None
    for number, line in enumerate(iss_text.splitlines(), 1):
        header = re.match(r"\[(\w+)\]", line.strip())
        if header:
            section = header.group(1)
            continue
        if section == "Setup" and re.match(r"\w+=", line) and re.search(r"\s;", line):
            pytest.fail(f"[Setup] satır sonu yorumu geçersiz (satır {number}): {line!r}")


def test_iss_version_matches_pyproject(iss_text):
    import tomllib
    version = tomllib.loads((PACKAGING.parent / "pyproject.toml").read_text(encoding="utf-8"))["project"]["version"]
    assert re.search(rf'(?m)^#define MyAppVersion "{re.escape(version)}"$', iss_text)


@pytest.fixture(scope="module")
def setter():
    spec = importlib.util.spec_from_file_location("set_iss_version", PACKAGING / "set_iss_version.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_set_version_rewrites_only_the_define(setter, iss_text):
    new = setter.set_version(iss_text, "9.8.7")
    assert '#define MyAppVersion "9.8.7"' in new and new.count("#define MyAppVersion") == 1
    assert new.replace("9.8.7", "X") != iss_text            # gerçekten değişti
    assert new.replace('"9.8.7"', '"0"') .splitlines()[0] == iss_text.splitlines()[0]


def test_set_version_validates_input_and_keeps_bom(setter, iss_text, tmp_path):
    for bad in ("v1.2.3", "1.2", "x", ""):
        with pytest.raises(ValueError):
            setter.set_version(iss_text, bad)
    with pytest.raises(ValueError):
        setter.set_version("hiç define yok", "1.2.3")
    copy = tmp_path / "t.iss"
    copy.write_bytes(ISS.read_bytes())
    assert setter.main(["2.0.0", str(copy)]) == 0
    raw = copy.read_bytes()
    assert raw[:3] == b"\xef\xbb\xbf" and b'#define MyAppVersion "2.0.0"' in raw
    assert setter.main(["bozuk", str(copy)]) == 1
