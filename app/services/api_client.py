# app/services/api_client.py
from __future__ import annotations

import requests
import xml.etree.ElementTree as ET
from typing import List, Dict, Optional, Tuple

from utils.config import settings
from utils.logger import get_logger

log = get_logger("api_client")

BASE_URL = "http://openapi.seoul.go.kr:8088"
SERVICE_NAME = "viewNightSpot"


def build_url(start: int, end: int, typ: str = "xml") -> str:
    """
    서울시 야경명소 OpenAPI URL 생성
    :param start: 시작 인덱스 (정수)
    :param end: 종료 인덱스 (정수)
    :param typ: 응답 타입 (xml | json) - 본 프로젝트는 xml 기준
    """
    key = settings.SEOUL_OPENAPI_KEY
    return f"{BASE_URL}/{key}/{typ}/{SERVICE_NAME}/{start}/{end}/"


def _parse_xml_to_rows(xml_content: bytes) -> Tuple[List[Dict[str, str]], Optional[str]]:
    """
    XML 응답을 row dict 리스트로 파싱
    :return: (rows, error_message)
    """
    try:
        root = ET.fromstring(xml_content)
    except Exception as e:
        return [], f"XML 파싱 오류: {e}"

    # 에러 메시지 노드(RESULT/MESSAGE) 감지
    # 응답 스키마에 따라 <RESULT><CODE/MSG> 또는 <MESSAGE> 형태가 있을 수 있음
    result_node = root.find(".//RESULT") or root.find(".//result")
    if result_node is not None:
        msg_node = result_node.find("MESSAGE") or result_node.find("message") or result_node.find("MSG")
        if msg_node is not None and msg_node.text:
            # INFO-000 외 메시지는 사용자에게 그대로 전달
            msg = msg_node.text.strip()
            if "INFO-000" not in msg:
                return [], f"API 응답 메시지: {msg}"

    rows: List[Dict[str, str]] = []
    for item in root.iter("row"):
        row_dict = {child.tag: (child.text or "").strip() for child in item}
        rows.append(row_dict)

    # 데이터 없음 처리
    if not rows:
        # 데이터가 없거나 샘플키 제한 등
        msg_node = root.find(".//MESSAGE") or root.find(".//message")
        if msg_node is not None and msg_node.text:
            return [], f"API 응답 메시지: {msg_node.text.strip()}"
    return rows, None


def fetch_page(start: int = 1, end: int = 5) -> Dict[str, object]:
    """
    OpenAPI를 호출해 XML을 받아 dict 리스트로 반환
    예외 처리: 환경변수 없음, 네트워크/타임아웃, 4xx/5xx, XML 파싱 오류
    :return: {"ok": bool, "data": List[dict] | None, "error": str | None, "url": str}
    """
    if settings.SEOUL_OPENAPI_KEY == "환경변수 없음":
        return {
            "ok": False,
            "data": None,
            "error": "SEOUL_OPENAPI_KEY가 설정되지 않았습니다(.env 또는 환경변수 확인).",
            "url": "",
        }

    url = build_url(start, end, typ="xml")
    try:
        resp = requests.get(url, timeout=8)
        resp.raise_for_status()  # 4xx/5xx 발생 시 예외
    except requests.exceptions.Timeout:
        log.error("API 요청 타임아웃")
        return {"ok": False, "data": None, "error": "API 요청 타임아웃", "url": url}
    except requests.RequestException as e:
        log.error(f"API 요청 실패: {e}")
        return {"ok": False, "data": None, "error": f"API 요청 실패: {e}", "url": url}

    rows, parse_err = _parse_xml_to_rows(resp.content)
    if parse_err:
        log.error(parse_err)
        return {"ok": False, "data": None, "error": parse_err, "url": url}

    return {"ok": True, "data": rows, "error": None, "url": url}


# 모듈 단독 실행 테스트
if __name__ == "__main__":
    result = fetch_page(1, 5)
    print(result["ok"], result["url"])
    if result["ok"]:
        print(f"rows: {len(result['data'])}")
        print(result["data"][:2])
    else:
        print("error:", result["error"])
