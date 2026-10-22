"""Координаты города и сетка точек поиска."""
import math

from . import state
from .browser_search import city_center

_geocode_cache: dict[str, tuple[float, float, tuple[float, float, float, float] | None] | None] = {}


def geocode_city(city: str) -> tuple[float, float, tuple[float, float, float, float] | None] | None:
    """Return (lat, lon, envelope) for *city*. envelope — рамка города (юг, север, запад, восток) из офлайн-таблицы city_coords: сетка точек обрезается по ней, чтобы круг радиусом 20 км не захватывал пригороды и соседние районы."""
    key = city.strip().lower()
    if key in _geocode_cache:
        return _geocode_cache[key]

    result = None
    center = city_center(city)
    if center:
        try:
            from .city_coords import lookup_bbox
            envelope = lookup_bbox(city)
        except Exception:
            envelope = None
        result = (center[0], center[1], envelope)

    _geocode_cache[key] = result
    return result


def build_grid(
    clat: float,
    clon: float,
    envelope: tuple[float, float, float, float] | None = None,
) -> list[tuple[float, float]]:
    """Return a list of (lat, lon) points covering a circle of state.GRID_RADIUS_KM around (clat, clon) with state.GRID_STEP_KM spacing."""
    lat_step = state.GRID_STEP_KM / 111.32
    lon_step = state.GRID_STEP_KM / (111.32 * math.cos(math.radians(clat)))
    r_lat = state.GRID_RADIUS_KM / 111.32
    r_lon = state.GRID_RADIUS_KM / (111.32 * math.cos(math.radians(clat)))

    lat0, lat1 = clat - r_lat, clat + r_lat
    lon0, lon1 = clon - r_lon, clon + r_lon

    # Рамка города только ОТБРАСЫВАЕТ точки, но не сдвигает саму сетку.
    env = envelope if envelope else None

    pts: list[tuple[float, float]] = []
    lat = lat0
    while lat <= lat1 + 1e-9:
        lon = lon0
        while lon <= lon1 + 1e-9:
            dlat = (lat - clat) * 111.32
            dlon = (lon - clon) * 111.32 * math.cos(math.radians(clat))
            inside = dlat ** 2 + dlon ** 2 <= state.GRID_RADIUS_KM ** 2
            if inside and env:
                south, north, west, east = env
                inside = south <= lat <= north and west <= lon <= east
            if inside:
                pts.append((round(lat, 6), round(lon, 6)))
            lon += lon_step
        lat += lat_step

    # Grid alignment can skip the exact center; always include it.
    if not any(abs(a - clat) < 1e-6 and abs(b - clon) < 1e-6 for a, b in pts):
        pts.append((round(clat, 6), round(clon, 6)))
    return pts


def build_grid_index(points: list[tuple[float, float]]) -> dict[tuple[float, float], dict]:
    """Map every grid point to its up / left / up-left neighbours (or None), assuming row-major order (same latitude = one row)."""
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
