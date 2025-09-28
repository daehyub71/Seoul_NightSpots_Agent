# app/services/geo.py
from __future__ import annotations

import math
from typing import List, Dict, Any, Optional, Tuple

EARTH_RADIUS_KM = 6371.0088  # 평균 지구 반경(km)

def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """
    두 위경도 좌표 간 대권거리(km)를 반환합니다.
    입력과 출력:
        - 입력: 위도/경도(십진수, degrees)
        - 출력: 거리(km, float)
    순수 함수이며 I/O가 없습니다.
    """
    # 라디안 변환
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = phi2 - phi1
    dlambda = math.radians(lon2 - lon1)

    a = math.sin(dphi / 2.0) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2.0) ** 2
    c = 2.0 * math.atan2(math.sqrt(a), math.sqrt(1.0 - a))
    return EARTH_RADIUS_KM * c


def _safe_float(x: Any) -> Optional[float]:
    """
    내부용: 숫자 변환 시도. None/변환 실패 시 None 반환.
    0.0 좌표(유효하지 않은 데이터로 간주)도 None 처리합니다.
    """
    try:
        if x is None:
            return None
        f = float(x)
        return None if f == 0.0 else f
    except Exception:
        return None


def nearest(
    rows: List[Dict[str, Any]],
    lat: float,
    lon: float,
    topn: int = 5,
    radius_km: Optional[float] = None,
) -> List[Dict[str, Any]]:
    """
    정규화된 rows(LA/LO 포함)에서 (lat, lon)과 가까운 순서대로 상위 N개를 반환합니다.

    동작 규칙
      - LA/LO가 None이거나 0인 데이터는 제외
      - radius_km 지정 시 그 반경 이내만 반환
      - 반환 필드: TITLE, ADDR, OPERATING_TIME, URL, LA, LO, DIST_KM

    순수 함수이며 I/O가 없습니다.
    """
    lat = float(lat)
    lon = float(lon)

    candidates: List[Dict[str, Any]] = []
    for r in rows:
        la = _safe_float(r.get("LA"))
        lo = _safe_float(r.get("LO"))
        if la is None or lo is None:
            continue
        d = haversine_km(lat, lon, la, lo)
        if (radius_km is not None) and (d > radius_km):
            continue
        candidates.append({
            "TITLE": (r.get("TITLE") or "").strip(),
            "ADDR": (r.get("ADDR") or "").strip(),
            "OPERATING_TIME": (r.get("OPERATING_TIME") or "").strip(),
            "URL": (r.get("URL") or "").strip(),
            "LA": la,
            "LO": lo,
            "DIST_KM": round(d, 3),
        })

    # 거리 오름차순 정렬
    candidates.sort(key=lambda x: x["DIST_KM"])
    return candidates[: max(1, int(topn))]


# ---------------------------------------------------------------------------
# [Agent O] geo helpers
# ---------------------------------------------------------------------------

def validate_coords(lat: float, lon: float) -> bool:
    """
    위도/경도의 유효 범위를 검증합니다.
    - 위도(lat):  -90.0 <= lat <= 90.0
    - 경도(lon): -180.0 <= lon <= 180.0
    - NaN/Inf/None/변환불가는 False
    순수 함수.
    """
    try:
        lat_f = float(lat)
        lon_f = float(lon)
    except Exception:
        return False

    # 유한 값 검증
    if not (math.isfinite(lat_f) and math.isfinite(lon_f)):
        return False

    return (-90.0 <= lat_f <= 90.0) and (-180.0 <= lon_f <= 180.0)


# 서울 주요 프리셋 좌표(간단한 기준점). 필요 시 자유롭게 보정하세요.
PRESET_COORDS: Dict[str, Tuple[float, float]] = {
    # 중심 업무/관광 거점
    "시청":   (37.5663, 126.9779),  # 서울시청
    "광화문": (37.5759, 126.9768),  # 광화문광장 인근
    "남산":   (37.5512, 126.9882),  # N서울타워
    # 동남/서남 축
    "잠실":   (37.5130, 127.1028),  # 롯데월드타워 인근
    "강남":   (37.4979, 127.0276),  # 강남역 사거리
    "여의도": (37.5219, 126.9244),  # 여의도역/공원 일대
}

# alias 테이블(대소문자/공백/영문 표기 등 보완)
_PRESET_ALIASES: Dict[str, str] = {
    "seoul city hall": "시청",
    "city hall": "시청",
    "gwanghwamun": "광화문",
    "namsan": "남산",
    "jamsil": "잠실",
    "gangnam": "강남",
    "yeouido": "여의도",
}


def _normalize_label(label: str) -> str:
    """프리셋 라벨을 소문자/트림으로 정규화합니다."""
    return (label or "").strip().lower()


def get_preset_coord(label: str) -> Optional[Tuple[float, float]]:
    """
    프리셋 라벨로 좌표를 반환합니다.
    - 정확 일치(한글 키) 우선
    - alias(영문/공백/소문자 등) 매핑 보조
    - 존재하지 않으면 None
    순수 함수.
    """
    if not label:
        return None

    # 1) 정확 일치(한글 키)
    if label in PRESET_COORDS:
        return PRESET_COORDS[label]

    # 2) 정규화 + alias 매핑
    key = _normalize_label(label)
    mapped = _PRESET_ALIASES.get(key)
    if mapped and mapped in PRESET_COORDS:
        return PRESET_COORDS[mapped]

    # 3) 공백 제거/한글 키 소문자 비교 등 관대한 매칭(선택)
    #    예: "  강남 " -> "강남"
    trimmed = label.strip()
    if trimmed in PRESET_COORDS:
        return PRESET_COORDS[trimmed]

    return None


__all__ = [
    "EARTH_RADIUS_KM",
    "haversine_km",
    "nearest",
    "validate_coords",          # [Agent O]
    "PRESET_COORDS",            # [Agent O]
    "get_preset_coord",         # [Agent O]
]
# EOF
