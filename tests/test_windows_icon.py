"""Фирменная иконка попадает в Windows-сборку, а не только в .app.

PyInstaller по умолчанию ставит на .exe свой значок, а окно консоли — значок
Python. Эти проверки дешёвые (файл + текст спеки), зато ловят регрессию, из-за
которой релиз уезжает без иконки.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ICON = ROOT / "static" / "icon.ico"


def test_ico_exists_and_carries_the_small_and_large_sizes():
    data = ICON.read_bytes()
    assert data[:4] == b"\x00\x00\x01\x00", "это не .ico"
    count = int.from_bytes(data[4:6], "little")
    assert count >= 5, f"в .ico всего {count} размеров"
    # В ICO 0 в поле ширины означает 256 px.
    widths = {data[6 + i * 16] or 256 for i in range(count)}
    assert {16, 32, 48, 256} <= widths, f"нет нужных размеров: {sorted(widths)}"


def test_windows_spec_passes_the_icon_to_the_exe():
    spec = (ROOT / "parser.spec").read_text(encoding="utf-8")
    assert 'ICON = os.path.join("static", "icon.ico")' in spec
    assert "icon=ICON" in spec


def test_console_window_gets_the_same_icon():
    app = (ROOT / "app.py").read_text(encoding="utf-8")
    assert "def _set_windows_console_icon()" in app
    assert "_set_windows_console_icon()" in app.split('if __name__ == "__main__":')[1]


def test_browser_tab_has_a_favicon():
    html = (ROOT / "templates" / "index.html").read_text(encoding="utf-8")
    assert '<link rel="icon"' in html
    assert "icon.png" in html
