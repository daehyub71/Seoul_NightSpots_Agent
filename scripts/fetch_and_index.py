# scripts/fetch_and_index.py
from __future__ import annotations

import sys
import argparse
from pathlib import Path
from typing import List, Dict, Any, Tuple

# --- 프로젝트 루트 경로 등록 (scripts/에서 app/* 임포트용) ---
ROOT_DIR = Path(__file__).resolve().parents[1]
APP_DIR = ROOT_DIR / "app"
if str(APP_DIR) not in sys.path:
    sys.path.append(str(APP_DIR))

from utils.logger import get_logger
from utils.config import settings
from services.api_client import fetch_page
from services.datastore import normalize_rows, load_from_json, save_to_json

log = get_logger("fetch_and_index")

DEFAULT_OUTPUT = ROOT_DIR / "data" / "nightspots.json"

# 1페이지당 건수(서울 OpenAPI는 요청당 최대 1000건 가능, 환경에 맞게 조절)
PAGE_SIZE = 200


def parse_pages(pages_arg: str) -> List[int]:
    """--pages '1-5' 또는 '3' 형태 파싱 → [1,2,3,4,5] / [3]"""
    pages_arg = pages_arg.strip()
    if "-" in pages_arg:
        s, e = pages_arg.split("-", 1)
        start, end = int(s), int(e)
        if start <= 0 or end < start:
            raise ValueError("--pages 범위를 확인하세요 (예: 1-5)")
        return list(range(start, end + 1))
    # 단일 페이지
    val = int(pages_arg)
    if val <= 0:
        raise ValueError("--pages는 1 이상의 정수여야 합니다.")
    return [val]


def page_to_index_range(page: int, page_size: int = PAGE_SIZE) -> Tuple[int, int]:
    """페이지 → OpenAPI start/end 인덱스 (1-base, end 포함)"""
    start = (page - 1) * page_size + 1
    end = page * page_size
    return start, end


def dedupe_rows(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    중복 제거:
    1) NUM 우선
    2) 없으면 (TITLE, ADDR, LA, LO) 조합 키
    """
    seen = set()
    out = []
    for r in rows:
        key = None
        if r.get("NUM"):
            key = ("NUM", str(r.get("NUM")))
        else:
            key = (
                "TALALOKEY",
                str(r.get("TITLE") or "").strip(),
                str(r.get("ADDR") or "").strip(),
                str(r.get("LA") or ""),
                str(r.get("LO") or ""),
            )
        if key not in seen:
            seen.add(key)
            out.append(r)
    return out


def main():
    parser = argparse.ArgumentParser(description="Fetch → Normalize → Index → Save")
    parser.add_argument("--pages", required=True, help="가져올 페이지 범위 (예: 1-5 또는 3)")
    parser.add_argument("--rebuild", action="store_true", help="기존 JSON 무시하고 재구성")
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT), help="저장 경로 (기본: data/nightspots.json)")
    parser.add_argument("--page-size", type=int, default=PAGE_SIZE, help=f"페이지당 건수 (기본 {PAGE_SIZE})")
    args = parser.parse_args()

    if settings.SEOUL_OPENAPI_KEY == "환경변수 없음":
        log.error("SEOUL_OPENAPI_KEY가 설정되지 않았습니다(.env 또는 환경변수 확인).")
        sys.exit(1)

    try:
        pages = parse_pages(args.pages)
    except Exception as e:
        log.error(f"--pages 파싱 오류: {e}")
        sys.exit(1)

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    # 기존 데이터 로드 (rebuild가 아니라면 병합)
    if args.rebuild:
        all_rows: List[Dict[str, Any]] = []
        log.info("--rebuild 지정: 기존 JSON을 무시합니다.")
    else:
        all_rows = load_from_json(str(output_path)) or []
        log.info(f"기존 JSON 로드: {len(all_rows)} rows")

    # 수집 → 정규화 누적
    fetched_total = 0
    for p in pages:
        start, end = page_to_index_range(p, args.page_size)
        log.info(f"[수집] page={p} → start={start}, end={end}")
        res = fetch_page(start, end)
        if not res["ok"]:
            log.warning(f"페이지 {p} 수집 실패: {res['error']}")
            continue
        raw_rows = res["data"] or []
        fetched_total += len(raw_rows)
        norm = normalize_rows(raw_rows)
        all_rows.extend(norm)
        log.info(f"[정규화] page={p}: {len(raw_rows)} → {len(norm)} rows")

    # 중복 제거
    before = len(all_rows)
    all_rows = dedupe_rows(all_rows)
    after = len(all_rows)
    if before != after:
        log.info(f"[중복제거] {before} → {after}")

    # (선택) RAG 인덱싱 호출
    # services/rag.py에 build_index(rows, rebuild: bool=False) 가 있다고 가정.
    try:
        from services import rag  # 지연 임포트
        if hasattr(rag, "build_index"):
            log.info("[RAG] 인덱싱 시작")
            try:
                # 함수 시그니처 유연 대응
                rag.build_index(all_rows, rebuild=args.rebuild)  # type: ignore
            except TypeError:
                rag.build_index(all_rows)  # type: ignore
            log.info("[RAG] 인덱싱 완료")
        else:
            log.warning("[RAG] build_index 함수가 없습니다. 인덱싱을 건너뜁니다.")
    except Exception as e:
        log.warning(f"[RAG] 인덱싱 단계에서 오류(건너뜀): {e}")

    # 저장
    save_to_json(all_rows, str(output_path))

    log.info("=== 실행 요약 ===")
    log.info(f"수집 페이지: {pages} (page_size={args.page_size})")
    log.info(f"수집 건수(raw): {fetched_total}")
    log.info(f"최종 건수(normalized & dedup): {len(all_rows)}")
    log.info(f"저장 경로: {output_path}")


if __name__ == "__main__":
    main()
