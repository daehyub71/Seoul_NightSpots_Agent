# app/services/vis.py
from __future__ import annotations
from typing import List, Dict, Any, Tuple
import math

def _bounds_from_points(
    points: List[Tuple[float, float]],
    padding_ratio: float = 0.15,
) -> Tuple[float, float, float, float]:
    """(lat, lon) 리스트에서 min/max 구해 패딩 적용한 경계 반환 (min_lat, max_lat, min_lon, max_lon)."""
    lats = [p[0] for p in points]
    lons = [p[1] for p in points]
    min_lat, max_lat = min(lats), max(lats)
    min_lon, max_lon = min(lons), max(lons)
    # 경계가 한 점에 몰려 있을 때를 대비
    if math.isclose(min_lat, max_lat):
        min_lat -= 0.001; max_lat += 0.001
    if math.isclose(min_lon, max_lon):
        min_lon -= 0.001; max_lon += 0.001
    # 패딩
    lat_pad = (max_lat - min_lat) * padding_ratio
    lon_pad = (max_lon - min_lon) * padding_ratio
    return (min_lat - lat_pad, max_lat + lat_pad, min_lon - lon_pad, max_lon + lon_pad)


def make_ascii_minimap(
    recs: List[Dict[str, Any]],
    center: Tuple[float, float],
    grid: int = 21,
) -> str:
    """
    추천 결과(recs: LA/LO 포함)를 ASCII 격자(grid x grid)에 투영해 문자열로 반환.
    중심점(center)은 '◎', 추천 포인트는 순위에 따라 '①②③④⑤…', 그 외는 '.' 으로 표기.
    """
    if not recs:
        return "(표시할 결과가 없습니다.)"
    lat0, lon0 = center

    pts = [(r["LA"], r["LO"]) for r in recs] + [center]
    min_lat, max_lat, min_lon, max_lon = _bounds_from_points(pts)

    # 위도가 위→아래로 감소하므로 행 좌표는 반대로 매핑
    def to_cell(lat: float, lon: float) -> Tuple[int, int]:
        row = int((max_lat - lat) / (max_lat - min_lat) * (grid - 1))
        col = int((lon - min_lon) / (max_lon - min_lon) * (grid - 1))
        # 가드
        row = max(0, min(grid - 1, row))
        col = max(0, min(grid - 1, col))
        return row, col

    canvas = [["." for _ in range(grid)] for _ in range(grid)]

    # 순위 라벨 (1~20까지만 특수문자, 이후 숫자)
    rank_symbols = list("①②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬⑭⑮⑯⑰⑱⑲⑳")

    # 추천 포인트 찍기
    for i, r in enumerate(recs):
        row, col = to_cell(r["LA"], r["LO"])
        sym = rank_symbols[i] if i < len(rank_symbols) else str((i + 1) % 10)
        canvas[row][col] = sym

    # 중심점 찍기 (덮어쓰기 우선순위 높게)
    r0, c0 = to_cell(lat0, lon0)
    canvas[r0][c0] = "◎"

    # 문자열 조립 (위쪽이 북쪽)
    lines = ["".join(line) for line in canvas]
    meta = f"범례: ◎=기준점, ①=1위, ②=2위 …   위쪽=북, 오른쪽=동"
    return "\n".join(lines + ["", meta])


def normalize_points_for_scatter(
    recs: List[Dict[str, Any]],
    center: Tuple[float, float],
) -> Dict[str, Any]:
    """
    산점도용 데이터 반환:
    - xs, ys: 정규화된 x/y(경도/위도) 좌표
    - titles: 라벨
    - center_x, center_y: 중심점 위치
    - bounds: (min_lat, max_lat, min_lon, max_lon)
    """
    if not recs:
        return {"xs": [], "ys": [], "titles": [], "center_x": 0, "center_y": 0, "bounds": None}

    lat0, lon0 = center
    pts = [(r["LA"], r["LO"]) for r in recs] + [center]
    min_lat, max_lat, min_lon, max_lon = _bounds_from_points(pts)

    def to_xy(lat: float, lon: float) -> Tuple[float, float]:
        x = (lon - min_lon) / (max_lon - min_lon)  # 0..1 (좌→우)
        y = (lat - min_lat) / (max_lat - min_lat)  # 0..1 (아래→위)
        return x, y

    xs, ys, titles = [], [], []
    for r in recs:
        x, y = to_xy(r["LA"], r["LO"])
        xs.append(x); ys.append(y); titles.append(r.get("TITLE") or "(제목 없음)")

    cx, cy = to_xy(lat0, lon0)
    return {"xs": xs, "ys": ys, "titles": titles, "center_x": cx, "center_y": cy,
            "bounds": (min_lat, max_lat, min_lon, max_lon)}
