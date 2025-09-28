# app/agents/graph.py
from __future__ import annotations

from typing import Any, Dict, List, Optional, TypedDict
from utils.logger import get_logger

# LangGraph
from langgraph.graph import StateGraph, END

# 우리 에이전트
from .nodes import agent_c, agent_d, agent_e
# [Agent O] 신규 노드
from .nodes import origin_resolver_node

log = get_logger("agents.graph")


class GraphState(TypedDict, total=False):
    # 입력
    rows: List[Dict[str, Any]]
    lat: float                      # Agent C가 사용하는 기준 좌표(lat)
    lon: float                      # Agent C가 사용하는 기준 좌표(lon)
    topn: int
    radius_km: Optional[float]
    question: str

    # 지도 옵션
    center: Optional[tuple]         # (lat, lon) - 없으면 C 입력 좌표 사용
    map_provider: str               # "leaflet"(기본) | "kakao"(선택)

    # 중간/출력
    recommendations: List[Dict[str, Any]]
    map_html: str
    answer: str
    sources: List[Dict[str, Any]]

    # ----------------------------- #
    # [Agent O] OriginResolver 전용 상태
    # ----------------------------- #
    origin_mode: str                # "device" | "manual"
    origin_label: str               # "내 위치" 또는 프리셋/사용자 지정 명칭
    origin_lat: float               # O에서 확정한 기준 위도
    origin_lon: float               # O에서 확정한 기준 경도
    error: Optional[str]            # O 단계에서의 오류 메시지(없으면 None)


# ----------------------------- #
# [Agent O] 유효성 검사 함수
# ----------------------------- #
def ensure_origin_valid(state: Dict[str, Any]) -> None:
    """
    Agent O(OriginResolver)가 채운 상태값을 검증한다.
    - 필수: origin_mode("device"|"manual"), origin_lat, origin_lon
    - 좌표 범위: lat ∈ [-90, 90], lon ∈ [-180, 180]
    - radius_km: None 또는 0 이상
    - topn: 1 이상 정수
    실패 시 ValueError를 던진다.
    """
    mode = (state.get("origin_mode") or "").strip().lower()
    if mode not in ("device", "manual"):
        raise ValueError("[Agent O] origin_mode는 'device' 또는 'manual'이어야 합니다.")

    try:
        lat = float(state.get("origin_lat"))
        lon = float(state.get("origin_lon"))
    except Exception:
        raise ValueError("[Agent O] origin_lat / origin_lon이 유효한 숫자가 아닙니다.")

    if not (-90.0 <= lat <= 90.0 and -180.0 <= lon <= 180.0):
        raise ValueError("[Agent O] 좌표 범위를 벗어났습니다 (lat[-90,90], lon[-180,180]).")

    # radius_km 검증 (옵션)
    rk = state.get("radius_km", None)
    if rk is not None and rk != "":
        try:
            rk_val = float(rk)
        except Exception:
            raise ValueError("[Agent O] radius_km은 숫자여야 합니다.")
        if rk_val < 0:
            raise ValueError("[Agent O] radius_km은 0 이상이어야 합니다.")

    # topn 검증
    try:
        topn = int(state.get("topn", 5))
    except Exception:
        raise ValueError("[Agent O] topn은 정수여야 합니다.")
    if topn < 1:
        raise ValueError("[Agent O] topn은 1 이상이어야 합니다.")


# ----------------------------- #
# 그래프 빌더들
# ----------------------------- #
def build_graph_ced() -> Any:
    """
    (레거시) C → E → D 경로의 LangGraph 생성
    - C: Geo Recommender
    - E: Map Renderer
    - D: Answer Synthesizer
    """
    builder = StateGraph(GraphState)

    builder.add_node("AgentC_Recommender", agent_c)
    builder.add_node("AgentE_Map", agent_e)
    builder.add_node("AgentD_Answer", agent_d)

    builder.set_entry_point("AgentC_Recommender")
    builder.add_edge("AgentC_Recommender", "AgentE_Map")
    builder.add_edge("AgentE_Map", "AgentD_Answer")
    builder.add_edge("AgentD_Answer", END)

    graph = builder.compile()
    log.info("LangGraph 컴파일 완료 (레거시): C → E → D")
    return graph


def build_graph_full() -> Any:
    """
    (표준) O → C → E → D 경로의 LangGraph 생성
    - O: OriginResolver (기준 좌표 확정 및 C가 쓰는 lat/lon 주입)
    - C: Geo Recommender
    - E: Map Renderer
    - D: Answer Synthesizer
    """
    builder = StateGraph(GraphState)

    builder.add_node("AgentO_OriginResolver", origin_resolver_node)  # [Agent O]
    builder.add_node("AgentC_Recommender", agent_c)
    builder.add_node("AgentE_Map", agent_e)
    builder.add_node("AgentD_Answer", agent_d)

    builder.set_entry_point("AgentO_OriginResolver")                 # [Agent O] START → O
    builder.add_edge("AgentO_OriginResolver", "AgentC_Recommender")  # O → C
    builder.add_edge("AgentC_Recommender", "AgentE_Map")             # C → E
    builder.add_edge("AgentE_Map", "AgentD_Answer")                  # E → D
    builder.add_edge("AgentD_Answer", END)                           # D → END

    graph = builder.compile()
    log.info("LangGraph 컴파일 완료: O → C → E → D")
    return graph


# 기본 build_graph는 신규 표준(START→O→C→E→D)을 반환
def build_graph() -> Any:
    return build_graph_full()


# ----------------------------- #
# 다이어그램 (DOT / Mermaid)
# ----------------------------- #
def get_graph_dot() -> str:
    """O→C→E→D 경로를 DOT(Graphviz) 포맷으로 반환"""
    return r"""
digraph G {
  rankdir=LR;
  node [shape=box, style="rounded,filled", color="#4F46E5", fillcolor="#EEF2FF"];

  O [label="Agent O\n(OriginResolver)"];
  C [label="Agent C\n(Geo Recommender)"];
  E [label="Agent E\n(Map Renderer)"];
  D [label="Agent D\n(Answer Synthesizer)"];
  End [label="END", shape=doublecircle, color="#10B981", fillcolor="#ECFDF5"];

  O -> C [label="origin_* → lat/lon 확정"];
  C -> E [label="recommendations"];
  E -> D [label="map_html (state)"];
  D -> End;
}
""".strip()


def get_graph_mermaid() -> str:
    """O→C→E→D 경로를 Mermaid 포맷으로 반환 (옵션)"""
    return r"""
flowchart LR
  O["Agent O<br/>(OriginResolver)"] -->|origin_* → lat/lon| C["Agent C<br/>(Geo Recommender)"]
  C -->|recommendations| E["Agent E<br/>(Map Renderer)"]
  E -->|map_html (state)| D["Agent D<br/>(Answer Synthesizer)"]
  D --> End(("END"))
""".strip()


# ----------------------------- #
# 편의 실행 함수들
# ----------------------------- #
def run_o_to_d(
    *,
    rows: List[Dict[str, Any]],
    origin_mode: str,
    origin_lat: float,
    origin_lon: float,
    origin_label: str = "내 위치",
    question: str = "",
    topn: int = 5,
    radius_km: Optional[float] = 3.0,
    map_provider: Optional[str] = None,
) -> GraphState:
    """
    (표준) START→O→C→E→D 경로 실행 편의 함수.
    O가 lat/lon을 확정하여 C로 넘긴다.
    """
    state: GraphState = {
        "rows": rows,
        "origin_mode": origin_mode,
        "origin_lat": float(origin_lat),
        "origin_lon": float(origin_lon),
        "origin_label": origin_label,
        "topn": int(topn),
        "radius_km": radius_km,
        "question": question or "",
    }
    if map_provider:
        state["map_provider"] = map_provider

    # O 단계 입력 검증 (실패 시 예외)
    ensure_origin_valid(state)

    graph = build_graph_full()
    final_state: GraphState = graph.invoke(state)  # LangGraph 0.2+
    return final_state


def run_c_to_d(
    rows: List[Dict[str, Any]],
    lat: float,
    lon: float,
    question: str,
    topn: int = 5,
    radius_km: Optional[float] = None,
    *,
    map_provider: Optional[str] = None,   # "leaflet"(기본) | "kakao"
    center: Optional[tuple] = None,       # (lat, lon) 지정 시 지도 중심 강제
) -> GraphState:
    """
    (레거시) 입력을 받아 C→E→D 경로를 한번에 실행
    - map_provider 미지정 시 'leaflet' 기본
    """
    state: GraphState = {
        "rows": rows,
        "lat": float(lat),
        "lon": float(lon),
        "topn": int(topn),
        "radius_km": radius_km,
        "question": question or "",
    }
    if map_provider:
        state["map_provider"] = map_provider
    if center:
        state["center"] = center

    graph = build_graph_ced()
    final_state: GraphState = graph.invoke(state)  # LangGraph 0.2+
    return final_state


# 모듈 단독 테스트 (임시)
if __name__ == "__main__":
    dummy_rows = [
        {"TITLE": "남산타워", "ADDR": "용산구", "LA": 37.5512, "LO": 126.9882, "OPERATING_TIME": "10~22", "URL": "https://n"},
        {"TITLE": "서울로7017", "ADDR": "중구", "LA": 37.5563, "LO": 126.9723, "OPERATING_TIME": "상시", "URL": "https://s"},
    ]

    print("=== DOT ===")
    print(get_graph_dot())
    print("\n=== Mermaid ===")
    print(get_graph_mermaid())

    print("\n=== run_o_to_d (device) ===")
    res_o = run_o_to_d(
        rows=dummy_rows,
        origin_mode="device",
        origin_lat=37.5512,
        origin_lon=126.9882,
        origin_label="내 위치",
        question="남산 근처 야경 추천 2곳",
        topn=2,
        map_provider="leaflet",
    )
    print("answer:\n", res_o.get("answer"))
    print("map_html length:", len(res_o.get("map_html","")))

    print("\n=== run_c_to_d (legacy) ===")
    res_c = run_c_to_d(
        dummy_rows,
        37.5512, 126.9882,
        "남산 근처 야경 추천 2곳",
        topn=2,
        map_provider="leaflet"
    )
    print("answer:\n", res_c.get("answer"))
    print("map_html length:", len(res_c.get("map_html","")))
# EOF
