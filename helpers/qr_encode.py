"""
Hafif, sıfır dış bağımlılıklı QR Kod üretici (ISO/IEC 18004, Byte modu, ECC-L, Sürüm 1-6).
Audifly Connect'in yerel LAN adresini telefon kamerasının anında okuyabileceği
QPixmap olarak üretir.
"""
from __future__ import annotations

# Sürüm 1..6 (ECC-L) tablosu: (boyut, toplam_veri_baytı, ec_kod_sayısı, hizalama_merkezleri)
# Not: Sürüm 1..6 ECC-L tek bloktur (interleaving gerekmez).
_VERSION_TABLE = {
    1: (21, 19, 7, []),
    2: (25, 34, 10, [6, 18]),
    3: (29, 55, 15, [6, 22]),
    4: (33, 80, 20, [6, 26]),
    5: (37, 108, 26, [6, 30]),
    6: (41, 136, 18, [6, 34]),  # Sürüm 6 ECC-L 2 bloktur; 1..5 tek blok (108 bayt, ~106 karakter)
}

# Tek bloklu Sürüm 1..5: 106 bayta kadar tüm LAN URL'lerini rahatlıkla taşır.
_SINGLE_BLOCK_VERSIONS = (1, 2, 3, 4, 5)

# GF(256) log/antilog tabloları (ilkel polinom 0x11d)
_EXP = [0] * 512
_LOG = [0] * 256
_x = 1
for _i in range(255):
    _EXP[_i] = _x
    _LOG[_x] = _i
    _x <<= 1
    if _x & 0x100:
        _x ^= 0x11D
for _i in range(255, 512):
    _EXP[_i] = _EXP[_i - 255]


def _gf_mul(a: int, b: int) -> int:
    if a == 0 or b == 0:
        return 0
    return _EXP[_LOG[a] + _LOG[b]]


def _rs_generator(degree: int) -> list[int]:
    poly = [1]
    for i in range(degree):
        next_poly = [0] * (len(poly) + 1)
        root = _EXP[i]
        for j, coef in enumerate(poly):
            next_poly[j] ^= coef
            next_poly[j + 1] ^= _gf_mul(coef, root)
        poly = next_poly
    return poly


def _rs_encode(data: list[int], ec_count: int) -> list[int]:
    gen = _rs_generator(ec_count)
    rem = list(data) + [0] * ec_count
    for i in range(len(data)):
        factor = rem[i]
        if factor != 0:
            for j in range(1, len(gen)):
                rem[i + j] ^= _gf_mul(gen[j], factor)
    return rem[len(data):]


def _format_bits(ec_bits: int, mask_id: int) -> int:
    """BCH(15,5) format bilgisi + 0x5412 XOR maskesi (ECC-L için ec_bits=0b01)."""
    data = (ec_bits << 3) | mask_id
    rem = data << 10
    for bit in range(14, 9, -1):
        if rem & (1 << bit):
            rem ^= 0x537 << (bit - 10)
    return ((data << 10) | rem) ^ 0x5412


def _mask_fn(mask_id: int, r: int, c: int) -> bool:
    if mask_id == 0:
        return (r + c) % 2 == 0
    if mask_id == 1:
        return r % 2 == 0
    if mask_id == 2:
        return c % 3 == 0
    if mask_id == 3:
        return (r + c) % 3 == 0
    if mask_id == 4:
        return ((r // 2) + (c // 3)) % 2 == 0
    if mask_id == 5:
        return ((r * c) % 2 + (r * c) % 3) == 0
    if mask_id == 6:
        return (((r * c) % 2 + (r * c) % 3) % 2) == 0
    return (((r + c) % 2 + (r * c) % 3) % 2) == 0


def _penalty(mat: list[list[int]]) -> int:
    """ISO/IEC 18004 maske ceza skoru (daha düşük = kamera için daha okunaklı)."""
    n = len(mat)
    score = 0
    # Satır/sütun ardışık aynı renk modüller
    for r in range(n):
        run_r = 1
        run_c = 1
        for c in range(1, n):
            if mat[r][c] == mat[r][c - 1]:
                run_r += 1
            else:
                if run_r >= 5:
                    score += 3 + (run_r - 5)
                run_r = 1
            if mat[c][r] == mat[c - 1][r]:
                run_c += 1
            else:
                if run_c >= 5:
                    score += 3 + (run_c - 5)
                run_c = 1
        if run_r >= 5:
            score += 3 + (run_r - 5)
        if run_c >= 5:
            score += 3 + (run_c - 5)
    # 2x2 tek renk bloklar
    for r in range(n - 1):
        for c in range(n - 1):
            v = mat[r][c]
            if v == mat[r][c + 1] == mat[r + 1][c] == mat[r + 1][c + 1]:
                score += 3
    return score


def encode_qr(text: str) -> list[list[bool]]:
    """Verilen metni QR matrisine (True=siyah, False=beyaz) kodlar."""
    raw = text.encode("utf-8")
    version = None
    for v in _SINGLE_BLOCK_VERSIONS:
        _, data_cap, _, _ = _VERSION_TABLE[v]
        # Byte modu: 4 bit mod + 8 bit uzunluk + 8*len + 4 bit sonlandırıcı
        if len(raw) + 2 <= data_cap:
            version = v
            break
    if version is None:
        raise ValueError(f"QR metni çok uzun ({len(raw)} bayt, maks 106 bayt).")

    size, data_cap, ec_count, align_centers = _VERSION_TABLE[version]

    # 1) Bit akışı (Byte modu = 0100)
    bits: list[int] = [0, 1, 0, 0]
    for i in range(7, -1, -1):
        bits.append((len(raw) >> i) & 1)
    for b in raw:
        for i in range(7, -1, -1):
            bits.append((b >> i) & 1)

    max_data_bits = data_cap * 8
    # Sonlandırıcı (en fazla 4 sıfır biti)
    bits.extend([0] * min(4, max_data_bits - len(bits)))
    # Bayt sınırına hizala
    while len(bits) % 8 != 0:
        bits.append(0)

    data_bytes = []
    for i in range(0, len(bits), 8):
        val = 0
        for b in bits[i:i + 8]:
            val = (val << 1) | b
        data_bytes.append(val)

    pad_bytes = (0xEC, 0x11)
    pad_idx = 0
    while len(data_bytes) < data_cap:
        data_bytes.append(pad_bytes[pad_idx % 2])
        pad_idx += 1

    ec_bytes = _rs_encode(data_bytes, ec_count)
    codewords = data_bytes + ec_bytes

    # 2) Fonksiyon desenleri ve rezervasyon matrisi
    mat = [[0] * size for _ in range(size)]
    is_func = [[False] * size for _ in range(size)]

    def set_func(r: int, c: int, val: int):
        if 0 <= r < size and 0 <= c < size:
            mat[r][c] = val
            is_func[r][c] = True

    def draw_finder(top: int, left: int):
        for dr in range(-1, 8):
            for dc in range(-1, 8):
                r, c = top + dr, left + dc
                if not (0 <= r < size and 0 <= c < size):
                    continue
                if dr in (-1, 7) or dc in (-1, 7):
                    set_func(r, c, 0)
                elif dr in (0, 6) or dc in (0, 6) or (2 <= dr <= 4 and 2 <= dc <= 4):
                    set_func(r, c, 1)
                else:
                    set_func(r, c, 0)

    draw_finder(0, 0)
    draw_finder(0, size - 7)
    draw_finder(size - 7, 0)

    # Hizalama desenleri (Sürüm 2+)
    for r_c in align_centers:
        for c_c in align_centers:
            if is_func[r_c][c_c]:
                continue
            for dr in range(-2, 3):
                for dc in range(-2, 3):
                    val = 1 if (max(abs(dr), abs(dc)) in (0, 2)) else 0
                    set_func(r_c + dr, c_c + dc, val)

    # Zamanlama desenleri
    for i in range(8, size - 8):
        if not is_func[6][i]:
            set_func(6, i, 1 if i % 2 == 0 else 0)
        if not is_func[i][6]:
            set_func(i, 6, 1 if i % 2 == 0 else 0)

    # Karanlık modül + format bilgi alanlarını rezerve et
    set_func(size - 8, 8, 1)
    for i in range(9):
        if i != 6:
            is_func[8][i] = True
            is_func[i][8] = True
    for i in range(8):
        is_func[8][size - 1 - i] = True
        is_func[size - 1 - i][8] = True

    # 3) Veri bitlerini zikzak yerleştir
    all_bits = []
    for cw in codewords:
        for i in range(7, -1, -1):
            all_bits.append((cw >> i) & 1)

    bit_idx = 0
    col = size - 1
    upward = True
    while col > 0:
        if col == 6:
            col -= 1
        rows = range(size - 1, -1, -1) if upward else range(size)
        for r in rows:
            for dc in (0, -1):
                c = col + dc
                if not is_func[r][c]:
                    mat[r][c] = all_bits[bit_idx] if bit_idx < len(all_bits) else 0
                    bit_idx += 1
        col -= 2
        upward = not upward

    # 4) En düşük cezalı maskeyi seç ve format bilgisini yaz
    best_mat = None
    best_score = 10**9
    for mask_id in range(8):
        cand = [row[:] for row in mat]
        for r in range(size):
            for c in range(size):
                if not is_func[r][c] and _mask_fn(mask_id, r, c):
                    cand[r][c] ^= 1

        fmt = _format_bits(0b01, mask_id)  # 0b01 = ECC Level L
        # Format bitleri (MSB=bit 14 -> LSB=bit 0)
        for i in range(6):
            bit = (fmt >> (14 - i)) & 1
            cand[8][i] = bit
            cand[size - 1 - i][8] = bit
        cand[8][7] = (fmt >> 8) & 1
        cand[8][8] = (fmt >> 7) & 1
        cand[7][8] = (fmt >> 6) & 1
        cand[size - 7][8] = (fmt >> 8) & 1
        cand[8][size - 8] = (fmt >> 7) & 1
        cand[8][size - 7] = (fmt >> 6) & 1
        for i in range(6):
            bit = (fmt >> (5 - i)) & 1
            cand[5 - i][8] = bit
            cand[8][size - 6 + i] = bit

        sc = _penalty(cand)
        if sc < best_score:
            best_score = sc
            best_mat = cand

    return [[bool(cell) for cell in row] for row in best_mat]


def qr_to_qpixmap(text: str, box_size: int = 7, border: int = 4,
                  fg: str = "#0b0d14", bg: str = "#ffffff"):
    """Metni yüksek kontrastlı QPixmap QR koduna çevirir."""
    from PySide6.QtGui import QColor, QPainter, QPixmap

    matrix = encode_qr(text)
    n = len(matrix)
    img_px = (n + 2 * border) * box_size
    pm = QPixmap(img_px, img_px)
    pm.fill(QColor(bg))
    p = QPainter(pm)
    fg_col = QColor(fg)
    for r, row in enumerate(matrix):
        y = (r + border) * box_size
        for c, dark in enumerate(row):
            if dark:
                p.fillRect((c + border) * box_size, y, box_size, box_size, fg_col)
    p.end()
    return pm
