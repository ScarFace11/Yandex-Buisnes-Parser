"""
Координаты города и сетка точек поиска.

Геокодер-API Яндекс.Карт тоже платный (а бесплатная версия запрещает
сохранять данные), поэтому центр города берётся из карты: страница поиска
по названию города в реальном браузере сама проставляет центр в адресе
(ll/sll). Никаких HTTP-запросов с ключом приложение не делает.
"""
import math

from .browser_search import city_center

_geocode_cache: dict[str, tuple[float, float, tuple[float, float, float, float] | None] | None] = {}


def geocode_city(city: str) -> tuple[float, float, tuple[float, float, float, float] | None] | None:
    """
    Return (lat, lon, envelope) for *city*.

    envelope (рамка города) браузерная карта не отдаёт — возвращается None,
    и сетка строится по одному радиусу GRID_RADIUS_KM. Так честнее: раньше
    рамку давал геокодер-API, который мы больше не используем.
    """
    key = city.strip().lower()
    if key in _geocode_cache:
        return _geocode_cache[key]

    result = None
    center = city_center(city)
    if center:
        result = (center[0], center[1], None)

    _geocode_cache[key] = result
    return result


def build_grid(
    clat: float,
    clon: float,
    envelope: tuple[float, float, float, float] | None = None,
) -> list[tuple[float, float]]:
    """
    Return a list of (lat, lon) points covering a circle of
    state.GRID_RADIUS_KM around (clat, clon) with state.GRID_STEP_KM spacing.

    When *envelope* (the city's bounding box) is given, the search area is
    clipped to envelope ∩ circle, dropping points that fall outside the city
    (forests, fields, neighbouring districts) and saving Search API quota.
    """
    lat_step = state.GRID_STEP_KM / 111.32
    lon_step = state.GRID_STEP_KM / (111.32 * math.cos(math.radians(clat)))
    r_lat = state.GRID_RADIUS_KM / 111.32
    r_lon = state.GRID_RADIUS_KM / (111.32 * math.cos(math.radians(clat)))

    lat0, lat1 = clat - r_lat, clat + r_lat
    lon0, lon1 = clon - r_lon, clon + r_lon

    if envelope:
        elat_min, elat_max, elon_min, elon_max = envelope
        # Clip to the envelope (only ever shrinks the circle).
        lat0, lat1 = max(lat0, elat_min), min(lat1, elat_max)
        lon0, lon1 = max(lon0, elon_min), min(lon1, elon_max)

    pts: list[tuple[float, float]] = []
    lat = lat0
    while lat <= lat1 + 1e-9:
        lon = lon0
        while lon <= lon1 + 1e-9:
            dlat = (lat - clat) * 111.32
            dlon = (lon - clon) * 111.32 * math.cos(math.radians(clat))
            if dlat ** 2 + dlon ** 2 <= state.GRID_RADIUS_KM ** 2:
                pts.append((round(lat, 6), round(lon, 6)))
            lon += lon_step
        lat += lat_step

    # Grid alignment can skip the exact center; always include it.
    if not any(abs(a - clat) < 1e-6 and abs(b - clon) < 1e-6 for a, b in pts):
        pts.append((round(clat, 6), round(clon, 6)))
    return pts


def build_grid_index(points: list[tuple[float, float]]) -> dict[tuple[float, float], dict]:
    """
    Map every grid point to its up / left / up-left neighbours (or None),
    assuming row-major order (same latitude = one row). Used by the adaptive
    grid: a point whose known neighbours were all empty is skipped without a
    request.
    """
    by_lat: dict[float, list[float]] = {}
    for lat, lon in points:
        by_lat.setdefault(lat, []).append(lon)
    lats = sorted(by_lat)
    for lat in lats:
        by_lat[lat].sort()

    def find_lon(row_lons: list[float], target: float) -> float | None:
        for v in row_lons:
            if abs(v - target) < 1e-5:
                return v
        return None

    index: dict[tuple[float, float], dict] = {}
    for i, lat in enumerate(lats):
        lons = by_lat[lat]
        prev_lons = by_lat[lats[i - 1]] if i > 0 else []
        for j, lon in enumerate(lons):
            up = None
            if i > 0:
                ulon = find_lon(prev_lons, lon)
                if ulon is not None:
                    up = (lats[i - 1], ulon)
            left = (lat, lons[j - 1]) if j > 0 else None
            up_left = None
            if up is not None and j > 0:
                ulon2 = find_lon(prev_lons, lons[j - 1])
                if ulon2 is not None:
                    up_left = (lats[i - 1], ulon2)
            index[(lat, lon)] = {"up": up, "left": left, "up_left": up_left}
    return index
