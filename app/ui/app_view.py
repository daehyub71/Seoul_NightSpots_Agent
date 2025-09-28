# app/ui/app_view.py
from __future__ import annotations

import sys
from pathlib import Path
from typing import Dict, Any, List, Tuple, Optional

import streamlit as st
import matplotlib.pyplot as plt

# --- 앱 루트 경로 등록 (app/ui → app/* import) ---
APP_DIR = Path(__file__).resolve().parents[1]
if str(APP_DIR) not in sys.path:
    sys.path.append(str(APP_DIR))

# --- 내부 모듈 임포트 ---
from utils.logger import get_logger
from utils.config import settings
from services.datastore import load_from_json
from services.geo import nearest, validate_coords, get_preset_coord, PRESET_COORDS
from services.vis import make_ascii_minimap, normalize_points_for_scatter
from services.rag import build_index as rag_build_index, search as rag_search
from services.map_renderer import render_leaflet_map  # ✅ Leaflet 전용

# LangGraph 경로 (Agent O → C → E → D)
from agents.graph import run_o_to_d, get_graph_dot, get_graph_mermaid

log = get_logger("ui.app_view")

# 프로젝트 루트 기준 데이터 경로(절대경로 고정: 경로 불일치 방지)
DATA_PATH = APP_DIR.parent / "data" / "nightspots.json"

# (기존) 프리셋 좌표 (수동 추천 탭에서 사용)
PRESETS: Dict[str, Tuple[Optional[float], Optional[float]]] = {
    "— 직접 입력 —": (None, None),
    "시청": (37.5663, 126.9779),
    "광화문": (37.5759, 126.9769),
    "남산": (37.5512, 126.9882),
    "잠실": (37.5133, 127.1025),
    "강남": (37.4979, 127.0276),
    "여의도": (37.5219, 126.9244),
}

st.set_page_config(page_title="서울 야경명소 — 추천 & Q&A", layout="wide")
st.title("🌃 서울 야경명소 — 추천 & Q&A")

# 상단 상태/경로 안내
with st.expander("ℹ️ 실행 환경/경로", expanded=False):
    st.write({
        "DATA_PATH": str(DATA_PATH),
        "SEOUL_OPENAPI_KEY": "설정됨" if settings.SEOUL_OPENAPI_KEY != "환경변수 없음" else "환경변수 없음",
    })

# 세션 상태 초기화
if "rag_index_ready" not in st.session_state:
    st.session_state.rag_index_ready = False


# =========================
# 공용 렌더 유틸
# =========================
def render_cards(results: List[Dict[str, Any]]) -> None:
    """추천 결과를 카드 형태로 렌더링"""
    for i, r in enumerate(results, start=1):
        st.markdown(
            f"**{i}. {r.get('TITLE') or '(제목 없음)'}**  \n"
            f"📍 {r.get('ADDR') or '-'}  \n"
            f"🕒 {r.get('OPERATING_TIME') or '-'}  \n"
            f"🧭 거리: **{r.get('DIST_KM','-')} km**"
        )
        if r.get("URL"):
            st.markdown(f"[🔗 홈페이지]({r['URL']})")
        st.divider()


def render_scatter_and_ascii(results: List[Dict[str, Any]], lat: float, lon: float) -> None:
    """산점도 + ASCII 격자 미니맵"""
    st.subheader("🗺️ 간이 산점도")
    norm = normalize_points_for_scatter(results, center=(lat, lon))
    fig = plt.figure(figsize=(5, 5))
    ax = plt.gca()
    ax.scatter(norm["xs"], norm["ys"], s=60)                      # 추천 포인트
    ax.scatter([norm["center_x"]], [norm["center_y"]], s=100, marker="*", label="기준점")  # 기준점
    for x, y, t in list(zip(norm["xs"], norm["ys"], norm["titles"]))[:5]:
        ax.text(x + 0.01, y + 0.01, t, fontsize=9)
    ax.set_xlim(-0.05, 1.05); ax.set_ylim(-0.05, 1.05)
    ax.set_xlabel("경도(상대)"); ax.set_ylabel("위도(상대)")
    ax.grid(True, alpha=0.3); ax.legend(loc="lower right")
    st.pyplot(fig, clear_figure=True)

    st.subheader("🧭 ASCII 격자 미니맵")
    ascii_map = make_ascii_minimap(results, center=(lat, lon), grid=21)
    st.code(ascii_map, language="text")


# =========================
# Agent O용 위치 설정 유틸 (모바일/데스크톱 공용)
# =========================
def _get_query_params() -> Dict[str, str]:
    """Streamlit 버전에 따라 query params 가져오기 (호환 래퍼)."""
    # Streamlit >= 1.30
    if hasattr(st, "query_params"):
        try:
            qp = dict(st.query_params)  # type: ignore[attr-defined]
            return {k: (v[0] if isinstance(v, list) else v) for k, v in qp.items()}
        except Exception:
            pass
    # 구버전
    if hasattr(st, "experimental_get_query_params"):
        qp = st.experimental_get_query_params()  # type: ignore[attr-defined]
        return {k: (v[0] if isinstance(v, list) else v) for k, v in qp.items()}
    return {}


def _read_device_coords_from_query() -> Tuple[Optional[float], Optional[float]]:
    """URL 쿼리에서 디바이스 좌표를 읽어 float로 반환."""
    qp = _get_query_params()
    lat_s, lon_s = qp.get("device_lat"), qp.get("device_lon")
    try:
        lat = float(lat_s) if lat_s is not None else None
        lon = float(lon_s) if lon_s is not None else None
    except Exception:
        return None, None
    if lat is None or lon is None:
        return None, None
    if not validate_coords(lat, lon):
        return None, None
    return lat, lon


def _geolocation_html_button(button_label: str = "내 위치 가져오기") -> None:
    """
    지오로케이션을 요청하고 성공 시 부모 창 URL query에 좌표를 심는 버튼(HTML) 렌더.
    - 외부 패키지 없이 components.html만 사용
    - 성공: window.parent.location.search 에 device_lat, device_lon, device_ts 세팅
    """
    html = f"""
<div style="display:flex;gap:8px;align-items:center;">
  <button id="geo-btn" style="padding:8px 12px;cursor:pointer;">{button_label}</button>
  <span id="geo-msg" style="font-size:13px;color:#555;"></span>
</div>
<script>
  (function() {{
    const btn = document.getElementById("geo-btn");
    const msg = document.getElementById("geo-msg");

    function setMsg(text, color) {{
      msg.textContent = text;
      if (color) msg.style.color = color;
    }}

    function updateParentQuery(lat, lon) {{
      try {{
        const url = new URL(window.parent.location.href);
        url.searchParams.set("device_lat", String(lat));
        url.searchParams.set("device_lon", String(lon));
        url.searchParams.set("device_ts", String(Date.now())); // 캐시 방지
        window.parent.location.replace(url.toString());
      }} catch (e) {{
        setMsg("앱 URL 갱신 실패: " + e, "#b00020");
      }}
    }}

    btn.addEventListener("click", function() {{
      if (!navigator.geolocation) {{
        setMsg("이 브라우저에서는 위치 서비스를 지원하지 않습니다.", "#b00020");
        return;
      }}
      setMsg("현재 위치 확인 중...", "#555");
      navigator.geolocation.getCurrentPosition(
        function(pos) {{
          const lat = pos.coords.latitude;
          const lon = pos.coords.longitude;
          setMsg("위치 확인: " + lat.toFixed(5) + ", " + lon.toFixed(5), "#0a7");
          updateParentQuery(lat, lon);
        }},
        function(err) {{
          let m = "위치 권한이 거부되었거나 가져올 수 없습니다.";
          if (err && err.message) m += " (" + err.message + ")";
          setMsg(m, "#b00020");
        }},
        {{
          enableHighAccuracy: true,
          timeout: 10000,
          maximumAge: 0
        }}
      );
    }});
  }})();
</script>
"""
    st.components.v1.html(html, height=48)


def _preset_selector(default_label: str = "여의도") -> Tuple[str, Optional[float], Optional[float]]:
    """프리셋 드롭다운 및 좌표 추출 (services.geo의 PRESET_COORDS 사용)."""
    labels = list(PRESET_COORDS.keys())
    if default_label not in labels:
        default_label = labels[0]
    label = st.selectbox("프리셋", labels, index=labels.index(default_label), key="o_preset")
    latlon = get_preset_coord(label)
    lat, lon = (latlon[0], latlon[1]) if latlon else (None, None)
    return label, lat, lon


def get_origin_config() -> Optional[Dict[str, Any]]:
    """
    위치 기준 설정 UI를 렌더링하고, 사용자가 선택/입력한 설정을 반환합니다.

    반환값(dict) 스키마:
      {
        "origin_mode": "device" | "manual",
        "origin_label": str,
        "origin_lat": float,
        "origin_lon": float,
        "radius_km": float,
        "topn": int,
      }
    유효하지 않으면 None 반환(에러 메시지 출력).
    """
    st.subheader("기준 위치 선택")

    # 공통 옵션(반경, TopN)
    col0, col1 = st.columns(2)
    with col0:
        radius_km = st.number_input("반경 (km)", min_value=0.0, value=3.0, step=0.5, format="%.1f", key="o_radius")
    with col1:
        topn = st.number_input("추천 개수 (Top-N)", min_value=1, value=5, step=1, key="o_topn")

    # 모드 선택
    mode = st.radio("위치 기준 선택", ("현재 위치(모바일)", "원하는 장소 직접 지정"), horizontal=True, key="o_mode")
    if mode == "현재 위치(모바일)":
        st.caption("📍 브라우저/모바일에서 위치 권한을 허용해야 합니다. 좌표는 세션 내에서만 사용되며 저장되지 않습니다.")
        _geolocation_html_button("내 위치 가져오기")

        lat, lon = _read_device_coords_from_query()

        # 표시용/확인용
        with st.expander("가져온 좌표 확인", expanded=False):
            st.write("device_lat:", lat)
            st.write("device_lon:", lon)

        if lat is None or lon is None:
            st.info("상단 버튼을 눌러 위치를 허용하거나, 수동 입력 모드를 사용하세요.")
            return None

        if not validate_coords(lat, lon):
            st.error("가져온 좌표가 유효 범위를 벗어났습니다. 수동 입력을 사용하거나 다시 시도하세요.")
            return None

        return {
            "origin_mode": "device",
            "origin_label": "내 위치",
            "origin_lat": float(lat),
            "origin_lon": float(lon),
            "radius_km": float(radius_km),
            "topn": int(topn),
        }

    # manual 모드
    st.caption("🧭 프리셋을 고르거나 위도/경도를 직접 입력하세요.")
    col_a, col_b = st.columns([1, 1])

    with col_a:
        label, p_lat, p_lon = _preset_selector(default_label="여의도")
        use_preset = st.checkbox(f"프리셋 좌표 사용({label})", value=True, key="o_use_preset")

    with col_b:
        st.write("수동 좌표 입력")
        lat_in = st.text_input("위도(lat)", value=f"{p_lat:.6f}" if p_lat is not None else "", key="o_lat_in")
        lon_in = st.text_input("경도(lon)", value=f"{p_lon:.6f}" if p_lon is not None else "", key="o_lon_in")

    # 좌표 확정
    if use_preset and (p_lat is not None) and (p_lon is not None):
        lat, lon, origin_label = float(p_lat), float(p_lon), label
    else:
        # 수동 입력 우선
        try:
            lat = float(lat_in.strip())
            lon = float(lon_in.strip())
            origin_label = "사용자 지정"
        except Exception:
            st.error("위도/경도를 숫자로 입력해주세요. 예) 37.5665 / 126.9780")
            return None

    if not validate_coords(lat, lon):
        st.error("좌표 범위가 올바르지 않습니다. 위도[-90, 90], 경도[-180, 180].")
        return None

    return {
        "origin_mode": "manual",
        "origin_label": origin_label,
        "origin_lat": float(lat),
        "origin_lon": float(lon),
        "radius_km": float(radius_km),
        "topn": int(topn),
    }


# =========================
# 탭 구성
# =========================
tab1, tab2, tab3 = st.tabs(["📍 가까운 명소 추천", "💬 질문하기", "📱 Agent O (모바일/수동)"])

# ------------------------------------
# 탭1: 가까운 명소 추천 (기존 수동 + 즉시 거리계산)
# ------------------------------------
with tab1:
    st.markdown("기준 지점을 선택하거나, 위도/경도를 직접 입력하세요.")
    c1, c2, c3 = st.columns([1, 1, 1])
    with c1:
        preset = st.selectbox("기준 지점", list(PRESETS.keys()), key="near_preset")
    with c2:
        lat_in = st.text_input("위도(lat)", value="", key="near_lat")
    with c3:
        lon_in = st.text_input("경도(lon)", value="", key="near_lon")

    c4, c5 = st.columns([1, 1])
    with c4:
        topn = st.number_input("상위 N개", min_value=1, max_value=50, value=5, step=1, key="near_topn")
    with c5:
        radius = st.number_input("반경 (km, 선택)", min_value=0.0, value=0.0, step=0.5, key="near_radius")
    radius_km = None if radius == 0.0 else float(radius)

    if st.button("가까운 명소 찾기", key="near_search_btn"):
        # 기준 좌표 결정
        if preset != "— 직접 입력 —":
            lat_p, lon_p = PRESETS[preset]
            if lat_p is None or lon_p is None:
                st.error("프리셋 좌표를 확인할 수 없습니다.")
                st.stop()
            lat, lon = float(lat_p), float(lon_p)
        else:
            try:
                lat = float(lat_in); lon = float(lon_in)
            except Exception:
                st.error("위도/경도를 올바르게 입력하세요. 예) 37.5512 / 126.9882")
                st.stop()

        # 데이터 로드
        rows = load_from_json(str(DATA_PATH))
        if not rows:
            if settings.SEOUL_OPENAPI_KEY == "환경변수 없음":
                st.error("데이터가 없습니다. 그리고 SEOUL_OPENAPI_KEY도 설정되지 않았습니다. \n"
                         "1) .env에 키를 설정하고 수집 스크립트를 실행하거나,\n"
                         "2) data/nightspots.json을 미리 준비하세요.")
            else:
                st.error("데이터가 없습니다. 먼저 수집 스크립트(fetch_and_index.py)를 실행하여 캐시를 생성하세요.")
            st.stop()

        # 추천 계산
        try:
            results = nearest(rows, lat, lon, topn=int(topn), radius_km=radius_km)
        except Exception as e:
            st.error(f"거리 계산 중 오류가 발생했습니다: {e}")
            st.stop()

        if not results:
            st.info("해당 조건에서 추천 결과가 없습니다. 반경을 넓히거나 다른 지점으로 시도해보세요.")
        else:
            st.success(f"{len(results)}개 결과")
            # 1) 카드
            render_cards(results)

            # 2) Leaflet 지도 (항상 Leaflet)
            st.subheader("🗺️ 지도 보기 (Leaflet)")
            map_html = render_leaflet_map(results, center=(lat, lon), height=500, zoom=13)
            st.components.v1.html(map_html, height=500)

            # 3) 산점도 + ASCII 대안 시각화(원하면 해제)
            # render_scatter_and_ascii(results, lat=lat, lon=lon)

# ------------------------------------
# 탭2: 질문하기 (RAG)
# ------------------------------------
with tab2:
    st.markdown("자연어로 질문하면 관련 명소를 찾아 요약해 드립니다. (출처 포함)")

    c1, c2 = st.columns([3, 1])
    with c1:
        query = st.text_input("질문 입력", value="한강 근처 무료 야경명소 알려줘", key="rag_query")
    with c2:
        k = st.number_input("Top-K", min_value=1, max_value=20, value=5, step=1, key="rag_topk")

    if st.button("검색", key="rag_search_btn"):
        rows = load_from_json(str(DATA_PATH))
        if not rows:
            if settings.SEOUL_OPENAPI_KEY == "환경변수 없음":
                st.error("데이터가 없습니다. 그리고 SEOUL_OPENAPI_KEY도 설정되지 않았습니다. \n"
                         "1) .env에 키를 설정하고 수집 스크립트를 실행하거나,\n"
                         "2) data/nightspots.json을 미리 준비하세요.")
            else:
                st.error("데이터가 없습니다. 먼저 수집 스크립트(fetch_and_index.py)를 실행하세요.")
            st.stop()

        # 인덱스 준비 (세션 캐시)
        try:
            if not st.session_state.rag_index_ready:
                rag_build_index(rows, rebuild=True)
                st.session_state.rag_index_ready = True
        except Exception as e:
            st.error(f"인덱스 빌드 실패: {e}")
            st.stop()

        # 검색 실행
        try:
            results = rag_search(query, k=int(k))
        except Exception as e:
            st.error(f"검색 실패(네트워크/임베딩 오류 가능): {e}")
            st.stop()

        if not results:
            st.info("검색 결과가 없습니다. 다른 표현으로 질의해 보세요.")
        else:
            st.success(f"{len(results)}개 결과")
            for r in results:
                st.markdown(f"**{r['TITLE']}**  \n{r['SNIPPET']}")
                if r.get("URL"):
                    st.markdown(f"[🔗 바로가기]({r['URL']})")
                st.caption(f"score: {r['SCORE']:.3f}")
                st.divider()

            st.caption("※ 출처: 각 결과 하단의 링크 참고")

# ------------------------------------
# 탭3: 📱 Agent O (모바일/수동) — START→O→C→E→D
# ------------------------------------
with tab3:
    st.markdown("모바일에선 **내 위치 가져오기** 버튼으로 현재 위치를 사용하고, 데스크톱에선 프리셋/수동 좌표로 테스트하세요.")
    cfg = get_origin_config()

    # 실행 버튼
    col_run1, col_run2 = st.columns([1, 3])
    with col_run1:
        run_o = st.button("START→O→C→E→D 실행", use_container_width=True, key="o2d_run")
    with col_run2:
        st.caption("버튼을 누르면 O에서 좌표 확정 → C(추천) → E(지도) → D(답변) 순으로 실행합니다.")

    if run_o:
        if not cfg:
            st.warning("위치 설정이 유효하지 않습니다. 위 UI에서 좌표를 확인해 주세요.")
            st.stop()

        # 데이터 로드
        rows = load_from_json(str(DATA_PATH))
        if not rows:
            if settings.SEOUL_OPENAPI_KEY == "환경변수 없음":
                st.error("데이터가 없습니다. 그리고 SEOUL_OPENAPI_KEY도 설정되지 않았습니다. \n"
                         "1) .env에 키를 설정하고 수집 스크립트를 실행하거나,\n"
                         "2) data/nightspots.json을 미리 준비하세요.")
            else:
                st.error("데이터가 없습니다. 먼저 수집 스크립트(fetch_and_index.py)를 실행하여 캐시를 생성하세요.")
            st.stop()

        # 질문 입력
        question = st.text_input("질문(선택)", value="주변 야경 명소 3곳과 운영시간 알려줘", key="o2d_q")

        try:
            res = run_o_to_d(
                rows=rows,
                origin_mode=cfg["origin_mode"],
                origin_lat=cfg["origin_lat"],
                origin_lon=cfg["origin_lon"],
                origin_label=cfg["origin_label"],
                question=question,
                topn=int(cfg["topn"]),
                radius_km=float(cfg["radius_km"]),
                map_provider="leaflet",
            )
        except Exception as e:
            st.exception(e)
            st.stop()

        # 결과 표시
        st.success("Agent O 실행 완료 ✅")
        recs = res.get("recommendations", [])

        st.subheader("추천 결과 (거리순)")
        if not recs:
            st.info("추천 결과가 없습니다. 반경을 넓히거나 Top-N을 늘려보세요.")
        else:
            render_cards(recs)

            st.subheader("🗺️ 지도")
            st.components.v1.html(res.get("map_html", "<p>지도 없음</p>"), height=520)

        st.subheader("최종 답변")
        st.write(res.get("answer", "(응답 없음)"))

        # 그래프 구조/상태 디버그
        with st.expander("🗺️ LangGraph (O→C→E→D) 구조 보기", expanded=False):
            st.graphviz_chart(get_graph_dot(), use_container_width=True)
            st.caption("Agent O(OriginResolver) → Agent C(추천) → Agent E(지도) → Agent D(답변) → END")
            st.code(get_graph_mermaid(), language="mermaid")

        with st.expander("🧩 GraphState 미리보기", expanded=False):
            st.json(res, expanded=False)

        with st.expander("🔎 디버그: 입력 파라미터 / 기준 좌표", expanded=False):
            st.write({
                "origin_mode": cfg["origin_mode"],
                "origin_label": cfg["origin_label"],
                "origin_lat": cfg["origin_lat"],
                "origin_lon": cfg["origin_lon"],
                "radius_km": cfg["radius_km"],
                "topn": cfg["topn"],
            })

# 푸터
st.caption("Leaflet 지도 / RAG 검색 / Agent O(모바일/수동) 경로를 지원합니다. 좌표는 세션 내에서만 사용되며 저장하지 않습니다.")
# EOF
