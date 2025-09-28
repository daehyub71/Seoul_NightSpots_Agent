# app/agents/nodes.py
from __future__ import annotations

from typing import Any, Dict, List, Optional
from utils.logger import get_logger
from services.geo import nearest
from utils.config import settings
from services.geo import validate_coords, get_preset_coord
# 지도 렌더러 (Leaflet 기본)
from services.map_renderer import render_leaflet_map
try:
    # 선택: 카카오 렌더러가 있으면 사용
    from services.map_renderer import render_map as render_kakao_map  # type: ignore
except Exception:  # noqa: E722
    render_kakao_map = None  # 카카오 미존재 시 안전 폴백

log = get_logger("agents.nodes")


def _format_sources(recs: List[Dict[str, Any]], limit: int = 5) -> str:
    lines = []
    for r in recs[:limit]:
        title = r.get("TITLE") or "(제목 없음)"
        url = r.get("URL") or ""
        lines.append(f"- {title} {f'({url})' if url else ''}".strip())
    return "\n".join(lines)


def _llm_answer_azure(question: str, recs: List[Dict[str, Any]]) -> Optional[str]:
    """
    Azure OpenAI가 설정된 경우 Chat Completions 호출.
    설정이 없거나 실패하면 None 반환 → 상위에서 폴백 사용.
    """
    # AOAI_ENDPOINT / AOAI_API_KEY / AOAI_DEPLOYMENT 모두 필요
    if any(v == "환경변수 없음" for v in [
        settings.AOAI_ENDPOINT, settings.AOAI_API_KEY, settings.AOAI_DEPLOYMENT
    ]):
        return None

    try:
        import requests  # 지연 임포트
        url = (
            f"{settings.AOAI_ENDPOINT.rstrip('/')}"
            f"/openai/deployments/{settings.AOAI_DEPLOYMENT}/chat/completions?api-version=2024-02-15-preview"
        )
        headers = {
            "Content-Type": "application/json",
            "api-key": settings.AOAI_API_KEY,
        }

        context_lines = []
        for r in recs:
            context_lines.append(
                f"* {r.get('TITLE','')} | 거리 {r.get('DIST_KM','-')}km | "
                f"{r.get('ADDR','-')} | 운영시간 {r.get('OPERATING_TIME','-')} | {r.get('URL','')}"
            )

        system_prompt = (
            "너는 '서울 야경 명소' 안내원이다. 제공된 컨텍스트만 사용해 간결히 답하고, "
            "마지막에 참고한 명소명과 URL을 목록으로 덧붙여라. 확실하지 않은 내용은 모른다고 말해라."
        )
        user_prompt = (
            f"[질문]\n{question}\n\n"
            f"[컨텍스트]\n" + "\n".join(context_lines)
        )

        payload = {
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": 0.3,
            "max_tokens": 512,
        }
        resp = requests.post(url, headers=headers, json=payload, timeout=20)
        resp.raise_for_status()
        data = resp.json()
        content = data["choices"][0]["message"]["content"]
        return content
    except Exception as e:
        log.warning(f"AOAI 응답 생성 실패 → 규칙 기반 폴백 사용: {e}")
        return None


# ========== Agent C ==========
def agent_c(state: Dict[str, Any]) -> Dict[str, Any]:
    """
    입력(state):
      - rows: 정규화된 전체 데이터(List[dict])  (LA/LO 포함)
      - lat, lon: 기준 좌표 (float)
      - topn: 추천 개수 (int, 기본 5)
      - radius_km: 반경 필터 (Optional[float])
    출력(state 업데이트):
      - recommendations: 거리순 추천 리스트(List[dict])
    """
    rows = state.get("rows") or []
    lat = float(state.get("lat"))
    lon = float(state.get("lon"))
    topn = int(state.get("topn", 5))
    radius_km = state.get("radius_km", None)
    if isinstance(radius_km, str) and radius_km.strip() == "":
        radius_km = None

    log.info(f"[C] 좌표(lat={lat}, lon={lon}), topn={topn}, radius={radius_km}")
    recs = nearest(rows, lat, lon, topn=topn, radius_km=radius_km)
    log.info(f"[C] 추천 결과 {len(recs)}건")

    out = dict(state)
    out["recommendations"] = recs
    # E에서 사용할 중심 좌표도 함께 저장(없으면 C의 입력 좌표 사용)
    out.setdefault("center", (lat, lon))
    return out


# ========== Agent E ==========
def agent_e(state: Dict[str, Any]) -> Dict[str, Any]:
    """
    Agent E (MapRenderer)
    - 역할: Agent C의 추천 리스트를 받아 지도 HTML 생성
    - 입력(state):
        - recommendations: List[dict] (Agent C 출력)
        - center: (lat, lon) 지도 중심(옵션, 없으면 첫 추천 or C입력 좌표)
        - map_provider: "leaflet"(기본) | "kakao"(선택)
    - 출력(state 업데이트):
        - map_html: str (iframe(srcdoc)로 바로 렌더 가능한 HTML)
    """
    recs: List[Dict[str, Any]] = state.get("recommendations") or []
    provider: str = (state.get("map_provider") or "leaflet").lower()

    # 중심 좌표 계산
    center: Optional[tuple] = state.get("center")
    if not center and ("lat" in state and "lon" in state):
        try:
            center = (float(state["lat"]), float(state["lon"]))
        except Exception:
            center = None

    if not recs:
        log.info("[E] recommendations 없음 → 빈 지도 안내 반환")
        out = dict(state)
        out["map_html"] = "<p style='color:gray'>표시할 추천 결과가 없습니다.</p>"
        return out

    try:
        if provider == "kakao" and render_kakao_map:
            kakao_key = settings.KAKAO_API_KEY
            if not kakao_key or kakao_key == "환경변수 없음":
                log.warning("[E] KAKAO_API_KEY 미설정 → Leaflet로 폴백")
                html = render_leaflet_map(recs, center=center, height=520, zoom=13)
            else:
                # (주의) Streamlit srcdoc 환경에선 카카오 JS SDK가 도메인 화이트리스트 문제로 실패할 수 있음
                html = render_kakao_map(recs, kakao_key)
        else:
            # 기본: Leaflet (Streamlit에서 안정적으로 동작)
            html = render_leaflet_map(recs, center=center, height=520, zoom=13)
    except Exception as e:
        log.exception("[E] 지도 렌더링 실패")
        html = f"<p style='color:red'>지도 렌더링 실패: {e}</p>"

    out = dict(state)
    out["map_html"] = html
    return out


# ========== Agent D ==========
def agent_d(state: Dict[str, Any]) -> Dict[str, Any]:
    """
    입력(state):
      - question: 사용자 질문 (str)
      - recommendations: Agent C의 추천 결과(List[dict])
    출력(state 업데이트):
      - answer: 최종 답변(str)
    """
    question = state.get("question") or ""
    recs: List[Dict[str, Any]] = state.get("recommendations") or []

    if not recs:
        answer = "추천 결과가 없어 답변을 생성할 수 없습니다. 기준 좌표 또는 반경 조건을 확인해 주세요."
    else:
        # 1) AOAI가 있으면 우선 사용
        answer = _llm_answer_azure(question, recs) or ""

        # 2) 규칙 기반 폴백 (AOAI 미설정/실패 시)
        if not answer:
            lines = []
            lines.append("아래 추천 결과를 참고해 주세요:")
            for r in recs:
                t = r.get("TITLE") or "(제목 없음)"
                d = r.get("DIST_KM", "-")
                addr = r.get("ADDR") or "-"
                op = r.get("OPERATING_TIME") or "-"
                url = r.get("URL") or ""
                line = f"- {t} · {d}km · {addr} · 운영시간 {op}" + (f" · {url}" if url else "")
                lines.append(line)
            lines.append("\n참고한 명소와 URL:")
            lines.append(_format_sources(recs))
            answer = "\n".join(lines)

    out = dict(state)
    out["answer"] = answer
    out["sources"] = [{"TITLE": r.get("TITLE"), "URL": r.get("URL")} for r in recs]
    return out

# [Agent O] origin_resolver_node
def _mask_coords(lat: float, lon: float) -> str:
    """좌표를 로그용으로 마스킹 (소수점 2자리까지만 표시)."""
    try:
        return f"({lat:.2f}, {lon:.2f})"
    except Exception:
        return "(invalid)"

def origin_resolver_node(state: Dict[str, Any]) -> Dict[str, Any]:
    """
    Agent O: OriginResolver
    - 역할: 기준 좌표(origin_lat, origin_lon)를 확정하고 state에 주입
    - 입력(state):
        - origin_mode: "device" | "manual"
        - origin_lat, origin_lon: (device 모드일 경우)
        - origin_label: str (옵션)
        - radius_km, topn (옵션)
    - 출력(state 업데이트):
        - lat, lon: Agent C가 사용할 좌표
        - radius_km, topn 기본값 주입
        - 오류 시 state["error"] 세팅 후 예외 발생
    """
    out = dict(state)
    mode = (out.get("origin_mode") or "").strip().lower()

    if mode not in ("device", "manual"):
        out["error"] = "[Agent O] origin_mode가 'device' 또는 'manual'이 아닙니다."
        raise ValueError(out["error"])

    if mode == "device":
        lat = out.get("origin_lat")
        lon = out.get("origin_lon")
        if lat is None or lon is None or not validate_coords(lat, lon):
            out["error"] = "[Agent O] device 모드에서 유효한 좌표를 가져오지 못했습니다."
            raise ValueError(out["error"])
        origin_label = out.get("origin_label") or "내 위치"

    elif mode == "manual":
        label = out.get("origin_label") or ""
        coords = get_preset_coord(label) if label else None
        if coords:
            lat, lon = coords
            origin_label = label
        else:
            lat = out.get("origin_lat")
            lon = out.get("origin_lon")
            if lat is None or lon is None or not validate_coords(lat, lon):
                out["error"] = "[Agent O] manual 모드에서 좌표가 없거나 잘못되었습니다."
                raise ValueError(out["error"])
            origin_label = label or "사용자 지정"

    # 기본값 주입
    radius_km = out.get("radius_km", 3.0)
    try:
        radius_km = float(radius_km) if radius_km is not None else None
    except Exception:
        radius_km = None

    topn = out.get("topn", 5)
    try:
        topn = int(topn)
    except Exception:
        topn = 5

    # Agent C용 좌표 키도 세팅
    out.update({
        "origin_mode": mode,
        "origin_label": origin_label,
        "origin_lat": float(lat),
        "origin_lon": float(lon),
        "lat": float(lat),
        "lon": float(lon),
        "radius_km": radius_km,
        "topn": topn,
    })

    log.info(f"[O] mode={mode}, label={origin_label}, coords={_mask_coords(lat, lon)}, "
             f"radius={radius_km}, topn={topn}")

    return out
