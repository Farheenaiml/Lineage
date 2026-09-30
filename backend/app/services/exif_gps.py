"""
Extract GPS coordinates from image EXIF metadata using Pillow only (free,
already a dependency). Returns None when the file carries no GPS block —
we never guess a location.
"""
from io import BytesIO

from PIL import Image

GPS_IFD = 0x8825


def _ratio(v) -> float:
    try:
        return float(v)
    except Exception:
        n, d = v
        return float(n) / float(d) if d else 0.0


def _dms_to_deg(dms, ref) -> float | None:
    try:
        d, m, s = (_ratio(x) for x in dms)
        deg = d + m / 60.0 + s / 3600.0
        if str(ref).upper() in ("S", "W"):
            deg = -deg
        return deg
    except Exception:
        return None


def extract_gps(raw: bytes) -> dict | None:
    try:
        img = Image.open(BytesIO(raw))
        exif = img.getexif()
        gps = exif.get_ifd(GPS_IFD) if exif else None
    except Exception:
        return None
    if not gps:
        return None
    # tags: 1 LatRef, 2 Lat, 3 LonRef, 4 Lon
    if 2 not in gps or 4 not in gps:
        return None
    lat = _dms_to_deg(gps[2], gps.get(1, "N"))
    lon = _dms_to_deg(gps[4], gps.get(3, "E"))
    if lat is None or lon is None or not (-90 <= lat <= 90 and -180 <= lon <= 180):
        return None
    if lat == 0 and lon == 0:  # null island = unset GPS, not a real fix
        return None
    return {"latitude": round(lat, 6), "longitude": round(lon, 6)}
