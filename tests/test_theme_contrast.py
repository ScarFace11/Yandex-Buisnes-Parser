"""Светлая и тёмная темы опираются на ОДИН набор токенов и проходят WCAG AA.

Тема — это не «список hex-ов», а роли: `--txt`, `--card`, `--sub`… Если правило
читает `var(--…)`, обе темы получают согласованный результат, а контраст можно
посчитать заранее — без браузера. Проверяем ровно это:

1. `:root` и `[data-theme="dark"]` объявляют одни и те же имена токенов
   (иначе правило, добавленное в одну тему, «теряет» цвет в другой).
2. Ни одно правило вне блоков токенов не содержит hex-литерал: цвет, забытый
   в правиле, не переключается вместе с темой.
3. Контраст пар «текст на фоне» — не ниже 4.5:1 в обеих темах.
"""
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
STYLE = (ROOT / "static" / "css" / "style.css").read_text(encoding="utf-8")

DARK = '[data-theme="dark"]'


# ── Разбор токенов ──────────────────────────────────────────────
def token_block(selector: str) -> dict[str, str]:
    """Все `--token:value` из блока `selector{…}` (первого по файлу)."""
    start = STYLE.index(selector + "{")
    end = STYLE.index("\n}", start)
    block = STYLE[start:end]
    out = {}
    for m in re.finditer(r"(--[a-z0-9-]+)\s*:\s*([^;]+);", block):
        out[m.group(1)] = m.group(2).strip()
    return out


def resolve(tokens: dict[str, str], value: str, depth: int = 0) -> str:
    """Разворачивает var(--…) до конкретного цвета."""
    value = value.strip()
    m = re.fullmatch(r"var\((--[a-z0-9-]+)\)", value)
    if m and depth < 8:
        return resolve(tokens, tokens[m.group(1)], depth + 1)
    return value


def to_rgb(value: str):
    """hex/rgb(a) → (r, g, b, a) или None."""
    value = value.strip()
    m = re.fullmatch(r"#([0-9a-fA-F]{3,8})", value)
    if m:
        h = m.group(1)
        if len(h) == 3:
            h = "".join(c * 2 for c in h)
        if len(h) == 8:
            h = h[:6]
        return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16), 1.0)
    m = re.fullmatch(r"rgba?\(([^)]+)\)", value)
    if m:
        parts = [float(p.strip()) for p in m.group(1).split(",")]
        if len(parts) >= 3:
            return (parts[0], parts[1], parts[2], parts[3] if len(parts) > 3 else 1.0)
    return None


def over(fg, bg):
    """Накладывает полупрозрачный слой fg на непрозрачный bg."""
    if fg is None or bg is None:
        raise AssertionError("не разобран цвет")
    a = fg[3]
    return (fg[0] * a + bg[0] * (1 - a),
            fg[1] * a + bg[1] * (1 - a),
            fg[2] * a + bg[2] * (1 - a), 1.0)


def luminance(rgb) -> float:
    def chan(v):
        v /= 255.0
        return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4
    r, g, b = chan(rgb[0]), chan(rgb[1]), chan(rgb[2])
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast(a, b) -> float:
    la, lb = luminance(a), luminance(b)
    hi, lo = max(la, lb), min(la, lb)
    return (hi + 0.05) / (lo + 0.05)


LIGHT = token_block(":root")
DARK_TOKENS = token_block(DARK)

# Пары «текст на фоне», которые обязаны читаться в любой теме.
# Полупрозрачный фон проверяется поверх каждой базовой поверхности (карточка,
# фон страницы, шапка) — берём худший случай.
PAIRS = [
    ("--txt", "--bg"), ("--txt", "--card"), ("--txt", "--panel"),
    ("--txt", "--field"), ("--txt", "--term"), ("--txt", "--bdr"),
    ("--sub", "--bg"), ("--sub", "--card"), ("--sub", "--panel"),
    ("--muted", "--bg"), ("--muted", "--card"), ("--muted", "--panel"),
    ("--c", "--bg"), ("--c", "--card"), ("--c", "--cl"), ("--c", "--panel"),
    ("--on-accent", "--brand"), ("--on-accent", "--hdr"),
    ("--on-accent", "--red-btn"), ("--on-accent", "--red-btn-2"),
    ("--on-accent", "--vk"), ("--on-accent", "--ig"),
    ("--on-accent", "--tg"), ("--on-accent", "--wa"),
    ("--pause-txt", "--pause-from"), ("--pause-txt", "--pause-to"),
    ("--tip-txt", "--tip-bg"), ("--tip-ok", "--tip-bg"),
    ("--ok-txt", "--ok-bg"), ("--ok-strong", "--ok-bg"),
    ("--warn-txt", "--warn-bg"), ("--warn-strong", "--warn-bg"),
    ("--err-txt", "--err-bg"), ("--err-strong", "--err-bg"),
]
SURFACES = ("--card", "--bg", "--hdr")


def worst_contrast(tokens: dict[str, str], fg_tok: str, bg_tok: str) -> float:
    fg = to_rgb(resolve(tokens, tokens[fg_tok]))
    bg = to_rgb(resolve(tokens, tokens[bg_tok]))
    assert fg and bg, f"{fg_tok} / {bg_tok} не разобраны"
    if fg[3] < 1.0:                       # полупрозрачный текст — поверх фона
        fg = over(fg, to_rgb(resolve(tokens, tokens[bg_tok])))
    if bg[3] < 1.0:                       # полупрозрачный фон — поверх поверхностей
        return min(contrast(fg, over(bg, to_rgb(resolve(tokens, tokens[s]))))
                   for s in SURFACES)
    return contrast(fg, bg)


class TestOneTokenSet:
    def test_both_themes_define_the_same_tokens(self):
        missing_in_dark = sorted(set(LIGHT) - set(DARK_TOKENS))
        missing_in_light = sorted(set(DARK_TOKENS) - set(LIGHT))
        assert not missing_in_dark, f"нет в тёмной теме: {missing_in_dark}"
        assert not missing_in_light, f"нет в светлой теме: {missing_in_light}"

    def test_no_undefined_token_is_used(self):
        """Иначе объявление молча теряется (border:1px solid var(--нет) → нет рамки).

        Токен без fallback обязан быть в теме. `var(--tile,var(--bdr))` — это
        значение, которое страница может подставить инлайном (карточка
        соцсети, слайдер), и без подстановки берётся fallback — такие можно.
        """
        defined = set(LIGHT)
        bare = set()
        for m in re.finditer(r"var\((\s*--[a-z0-9-]+)\s*\)", STYLE):
            bare.add(m.group(1).strip())
        assert not (bare - defined), (
            f"правила читают несуществующие токены без fallback: {sorted(bare - defined)}")
        app_js = (ROOT / "static" / "js" / "app.js").read_text(encoding="utf-8")
        assert "--tile:" in app_js, "карточки соцсетей должны нести свой цвет в --tile"

    def test_rules_do_not_hardcode_colours(self):
        """Цвет вне блоков токенов не переключается вместе с темой."""
        css = re.sub(r"/\*.*?\*/", "", STYLE, flags=re.S)
        light_block = css[css.index(":root{"):css.index("\n}")]
        dark_block = css[css.index(DARK + "{"):css.index("\n}", css.index(DARK + "{"))]
        rest = css.replace(light_block, "").replace(dark_block, "")
        literals = []
        for line in rest.split("\n"):
            decls = line.split(":")[1:] if "{" in line else [line]
            for chunk in decls:
                for hexv in re.findall(r"#[0-9a-fA-F]{3,8}\b", chunk):
                    literals.append(hexv)
        assert not literals, f"hex-литералы вместо токенов: {sorted(set(literals))}"


class TestContrast:
    @pytest.mark.parametrize("fg,bg", PAIRS, ids=lambda p: p.lstrip("-"))
    def test_light_theme_meets_wcag_aa(self, fg, bg):
        ratio = worst_contrast(LIGHT, fg, bg)
        assert ratio >= 4.5, f"светлая тема: {fg} на {bg} = {ratio:.2f}:1 < 4.5:1"

    @pytest.mark.parametrize("fg,bg", PAIRS, ids=lambda p: p.lstrip("-"))
    def test_dark_theme_meets_wcag_aa(self, fg, bg):
        ratio = worst_contrast(DARK_TOKENS, fg, bg)
        assert ratio >= 4.5, f"тёмная тема: {fg} на {bg} = {ratio:.2f}:1 < 4.5:1"

    def test_dark_theme_is_soft_not_black_and_white(self):
        assert DARK_TOKENS["--bg"] == "#191C22"
        assert DARK_TOKENS["--txt"] == "#E3E7EE"

    def test_pause_is_orange_in_both_themes(self):
        """⏸ Пауза — оранжевая; красный остаётся за ⏹ «Остановить»."""
        for tokens in (LIGHT, DARK_TOKENS):
            assert to_rgb(tokens["--pause-from"])[0] > 200      # много красного
            assert 120 < to_rgb(tokens["--pause-from"])[1] < 190  # …и зелёного
            assert to_rgb(tokens["--pause-from"])[2] < 90        # почти без синего
