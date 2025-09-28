# app/services/datastore.py
from __future__ import annotations

import json
import os
from typing import List, Dict, Any, Optional

from utils.logger import get_logger

log = get_logger("datastore")

# 서울시 야경명소 API 출력 필드(17개)
FIELDS = [
    "NUM", "SUBJECT_CD", "TITLE", "ADDR", "LA", "LO",
    "TEL_NO", "URL", "OPERATING_TIME", "FREE_YN", "ENTR_FEE",
    "CONTENTS", "SUBWAY", "BUS", "PARKING_INFO", "REG_DATE", "MOD_DATE",
]


def _normalize_value(key: str, value: Optional[str]) -> Optional[Any]:
    """
    필드별 정규화 규칙:
      - 좌표(LA, LO): float 변환, 0.0 또는 변환 불가 → None
      - 문자열: strip(), 빈 문자열 → None
    """
    if value is None:
        return None

    value = value.strip()
    if value == "":
        return None

    if key in ("LA", "LO"):
        try:
            fval = float(value)
            return None if fval == 0.0 else fval
        except ValueError:
            return None

    return value


def normalize_row(row: Dict[str, Any]) -> Dict[str, Any]:
    """단일 row(dict)를 17개 표준 스키마로 정규화"""
    out: Dict[str, Any] = {}
    for key in FIELDS:
        out[key] = _normalize_value(key, row.get(key))
    return out


def normalize_rows(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """여러 row 정규화"""
    return [normalize_row(r) for r in rows]


def save_to_json(rows: List[Dict[str, Any]], path: str) -> None:
    """정규화 데이터 JSON 저장"""
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
    except Exception:
        # dirname이 없을 수도 있음(현재 경로 저장)
        pass
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(rows, f, ensure_ascii=False, indent=2)
        log.info(f"JSON 저장 완료: {path} (rows={len(rows)})")
    except Exception as e:
        log.error(f"JSON 저장 실패: {e}")


def load_from_json(path: str) -> List[Dict[str, Any]]:
    """JSON 파일 불러오기 (리스트 예상)"""
    if not os.path.exists(path):
        log.warning(f"파일 없음: {path}")
        return []
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, list):
            return data
        log.error("JSON 최상위가 list가 아닙니다.")
        return []
    except Exception as e:
        log.error(f"JSON 불러오기 실패: {e}")
        return []


# 단독 실행 테스트
if __name__ == "__main__":
    sample = {
        "NUM": " 1 ", "SUBJECT_CD": "A01", "TITLE": " 남산타워 ",
        "ADDR": " 서울시 용산구 ", "LA": "37.551169", "LO": "126.988227",
        "TEL_NO": " 02-123-4567 ", "URL": " http://namsan.com ",
        "OPERATING_TIME": "10:00~22:00 ", "FREE_YN": "N ",
        "ENTR_FEE": "10000 ", "CONTENTS": " 서울의 대표 야경 명소 ",
        "SUBWAY": " 명동역 ", "BUS": " 02,03 ",
        "PARKING_INFO": " 유료주차 ", "REG_DATE": "20250101", "MOD_DATE": "20250927",
    }
    norm = normalize_row(sample)
    print("정규화:", norm)
    save_to_json([norm], "data/nightspots.json")
    print("로드:", load_from_json("data/nightspots.json"))
