# -*- coding: utf-8 -*-
"""Фирменная иконка приложения: static/icon.icns (+ static/icon.png).

Рисуем «пин» на синем градиенте (цвета — из палитры интерфейса) и собираем
из рендеров стандартный .icns-контейнер без сторонних утилит: каждая
лекция — PNG (ic07…ic10, ic11…ic14, включая Retina-варианты). Так иконку
можно перерисовать одной командой, а не искать исходник:

    pip install pillow          # dev-зависимость, в requirements не входит
    python scripts/gen_icon.py

parser-mac.spec берёт static/icon.icns по умолчанию (YP_ICON — переопределение),
поэтому после запуска скрипта сборка `./build-mac.sh` уже подхватывает её.
"""
import io
import math
import struct
from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parent.parent
ICNS_PATH = ROOT / "static" / "icon.icns"
PNG_PATH = ROOT / "static" / "icon.png"

SS = 4              # суперсэмплинг: рисуем в 4x и ужимаем — без лесенок
BASE = 1024         # базовый размер, из него рендерятся все лекции

TOP = (59, 130, 246)        # градиент — синий интерфейса, светлый сверху
BOTTOM = (29, 78, 216)
WHITE = (255, 255, 255, 255)


def _rounded_mask(size: int, radius: int) -> Image.Image:
    """Маска скруглённого квадрата — форма «иконки приложения» на macOS."""
    mask = Image.new("L", (size, size), 0)
    ImageDraw.Draw(mask).rounded_rectangle(
        [0, 0, size - 1, size - 1], radius=radius, fill=255)
    return mask


def _gradient(size: int) -> Image.Image:
    """Вертикальный градиент, нарисованный по строке и растянутый."""
    strip = Image.new("RGB", (1, size))
    px = strip.load()
    for y in range(size):
        t = y / (size - 1)
        px[0, y] = tuple(int(a + (b - a) * t) for a, b in zip(TOP, BOTTOM))
    return strip.resize((size, size))


def _pin_mask(size: int) -> Image.Image:
    """Маска булавки карты: круглая голова + остриё, внутри вырез-«ухо»."""
    s = size * SS
    mask = Image.new("L", (s, s), 0)
    d = ImageDraw.Draw(mask)
    cx, cy, r = s // 2, int(s * 0.42), int(s * 0.19)
    d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=255)
    # Вершины острия лежат ТОЧНО на окружности (x = √(r² − 0.35r²)):
    # шире круга — на стыке вылезает уступ, уже — заметная выемка.
    joint = int(r * math.sqrt(1 - 0.35 * 0.35))
    d.polygon([(cx - joint, cy + int(r * 0.35)),
               (cx + joint, cy + int(r * 0.35)),
               (cx, int(s * 0.79))], fill=255)
    hole = int(r * 0.42)
    d.ellipse([cx - hole, cy - hole, cx + hole, cy + hole], fill=0)
    return mask.resize((size, size), Image.LANCZOS)


def render(size: int) -> Image.Image:
    icon = _gradient(size).convert("RGBA")
    icon.putalpha(_rounded_mask(size, int(size * 0.225)))
    icon.paste(Image.new("RGBA", (size, size), WHITE), (0, 0), _pin_mask(size))
    return icon


def _icns_entry(kind: str, size: int) -> bytes:
    """Лекция .icns: тип + длина + PNG-данные (PNG уже сжат, кодировать заново не нужно)."""
    buf = io.BytesIO()
    render(size).save(buf, "PNG")
    data = buf.getvalue()
    return kind.encode("ascii") + struct.pack(">I", len(data) + 8) + data


def main() -> None:
    ICNS_PATH.parent.mkdir(parents=True, exist_ok=True)
    render(BASE).save(PNG_PATH)          # исходник для фавикона и документации
    # ic07…ic10 — обычные размеры, ic11…ic14 — их Retina-двойки (16@2x … 256@2x).
    entries = [_icns_entry(k, s) for k, s in (
        ("ic07", 128), ("ic08", 256), ("ic09", 512), ("ic10", 1024),
        ("ic11", 32), ("ic12", 64), ("ic13", 256), ("ic14", 512),
    )]
    body = b"".join(entries)
    ICNS_PATH.write_bytes(b"icns" + struct.pack(">I", len(body) + 8) + body)
    print(f"[ok] {ICNS_PATH.relative_to(ROOT)} — {ICNS_PATH.stat().st_size} Б; "
          f"{PNG_PATH.relative_to(ROOT)} — {PNG_PATH.stat().st_size} Б")


if __name__ == "__main__":
    main()
