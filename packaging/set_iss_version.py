"""packaging/audifly.iss icindeki '#define MyAppVersion "x.y.z"' satirini gunceller.

Kullanim:  python packaging/set_iss_version.py 0.4.5 [iss_yolu]
Dosya UTF-8 BOM ile yazilir (Inno Setup Turkce karakterleri ancak boyle dogru okur).
Cikti mesajlari ASCII (Windows konsolu cp1252).
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

PATTERN = re.compile(r'(?m)^(#define MyAppVersion )"[^"\r\n]*"')


def set_version(text: str, version: str) -> str:
    if not re.fullmatch(r"\d+\.\d+\.\d+", version):
        raise ValueError(f"gecersiz surum: {version!r}")
    new, count = PATTERN.subn(lambda m: f'{m.group(1)}"{version}"', text)
    if count != 1:
        raise ValueError("audifly.iss icinde tek bir '#define MyAppVersion' satiri bulunamadi")
    return new


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if not argv:
        print("kullanim: set_iss_version.py <surum> [iss_yolu]", file=sys.stderr)
        return 2
    path = Path(argv[1]) if len(argv) > 1 else Path(__file__).resolve().parent / "audifly.iss"
    try:
        text = path.read_text(encoding="utf-8-sig")
        path.write_text(set_version(text, argv[0]), encoding="utf-8-sig", newline="")
    except Exception as e:
        print(f"HATA: {e}", file=sys.stderr)
        return 1
    print(f"{path.name}: MyAppVersion = {argv[0]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
