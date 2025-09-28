# app/ui/app_view.py
from __future__ import annotations

import sys
from pathlib import Path
from typing import Dict, Any, List, Tuple

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
from services.geo import nearest
from services.vis import make_ascii_minimap, normalize_points_for_scatter
from services.rag import build_index as rag_build_index, search as rag_search
from services.map_renderer import render_leaflet_map  # ✅ Leaflet 전용

log = get_logger("ui.app_view")

# 프로젝트 루트 기준 데이터 경로(절대경로 고정: 경로 불일치 방지)
DATA_PATH = APP_DIR.parent / "data" / "nightspots.json"

# 프리셋 좌표 (테스트 편의)
PRESETS: Dict[str, Tuple[float, float]] = {
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
# 탭 구성
# =========================
tab1, tab2 = st.tabs(["📍 가까운 명소 추천", "💬 질문하기"])

# ------------------------------------
# 탭1: 가까운 명소 추천
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

            # 3) 산점도 + ASCII 대안 시각화
            #render_scatter_and_ascii(results, lat=lat, lon=lon)

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

# 푸터
st.caption("Leaflet 기반 지도와 대안 시각화(산점도·ASCII)를 제공합니다.")
