# app/ui/app.py
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.append(str(ROOT_DIR))

import streamlit as st
import matplotlib.pyplot as plt
from services.vis import make_ascii_minimap, normalize_points_for_scatter
from utils.logger import get_logger
from utils.config import settings
from services.api_client import fetch_page  # ✅ API 호출 함수 추가
from services.rag import build_index, search as rag_search
from services.datastore import load_from_json
from services.geo import nearest
from agents.graph import run_c_to_d
from agents.graph import get_graph_dot
from services.map_renderer import render_map
from services.map_renderer import render_leaflet_map
from agents.graph import run_o_to_d, get_graph_mermaid
from ui.components.location_picker import get_origin_config

log = get_logger("ui")

st.set_page_config(page_title="서울 야경명소 테스트", layout="centered")
st.title("🌃 서울 야경명소 프로젝트 테스트")

def mask_secret(value: str, show: int = 4) -> str:
    if not value or value == "환경변수 없음":
        return value
    v = str(value)
    return v[:show] + "…" + f"(len={len(v)})"

def get_status_badge(value: str) -> str:
    return "✅ 설정됨" if value and value != "환경변수 없음" else "❌ 환경변수 없음"

# --- API 호출 테스트 ---
st.header("📡 API 호출 테스트")
start_end = st.slider("가져올 범위 (start ~ end)", min_value=1, max_value=5, value=(1, 5))
if st.button("서울시 야경명소 가져오기"):
    start, end = start_end
    if start > end:
        st.warning("시작 값이 종료 값보다 클 수 없습니다.")
    else:
        res = fetch_page(start, end)
        st.caption(f"요청 URL: {res.get('url','')}")
        if not res["ok"]:
            st.error(res["error"])
        else:
            data = res["data"] or []
            if not data:
                st.info("데이터가 없습니다.")
            else:
                st.success(f"{len(data)}건 불러옴 ✅")
                st.dataframe(data, use_container_width=True)

DATA_PATH = ROOT_DIR.parent / "data" / "nightspots.json"   # ✅ 프로젝트 루트 기준 절대경로

st.header("🧠 RAG 검색 테스트")

if st.button("인덱스 빌드 (nightspots.json)"):
    rows = load_from_json(str(DATA_PATH))  # ✅ 절대경로로 로드
    if not rows:
        st.error(f"{DATA_PATH} 에 데이터가 없습니다. 먼저 fetch_and_index.py를 실행하세요.")
    else:
        build_index(rows, rebuild=True)
        st.success(f"인덱스 빌드 완료: {len(rows)} rows")
        st.caption(f"로드 경로: {DATA_PATH}")

st.header("📍 가까운 야경 명소 찾기")

# 좌표 프리셋(선택): 사용자가 쉽게 테스트할 수 있도록 주요 지점 제공
PRESETS = {
    "— 직접 입력 —": None,
    "시청": (37.5663, 126.9779),
    "광화문": (37.5759, 126.9769),
    "남산": (37.5512, 126.9882),
    "잠실": (37.5133, 127.1025),
    "강남": (37.4979, 127.0276),
    "여의도": (37.5219, 126.9244),
}

c1, c2, c3 = st.columns([1,1,1])
with c1:
    preset = st.selectbox("기준 지점", list(PRESETS.keys()))
with c2:
    lat_in = st.text_input("위도(lat)", value="")
with c3:
    lon_in = st.text_input("경도(lon)", value="")

c4, c5 = st.columns([1,1])
with c4:
    topn = st.number_input("상위 N개", min_value=1, max_value=50, value=5, step=1, key="near_topn")
with c5:
    radius = st.number_input("반경 (km, 선택)", min_value=0.0, value=0.0, step=0.5, key="near_radius")
radius_km = None if radius == 0.0 else float(radius)

if st.button("가까운 명소 찾기"):
    # 좌표 결정: 프리셋 우선, 직접입력은 보조
    if preset != "— 직접 입력 —" and PRESETS[preset]:
        lat, lon = PRESETS[preset]
    else:
        try:
            lat = float(lat_in)
            lon = float(lon_in)
        except Exception:
            st.error("위도/경도를 올바르게 입력하세요. 예) 37.5512 / 126.9882")
            st.stop()

    rows = load_from_json(str(DATA_PATH))
    if not rows:
        st.error(f"데이터가 없습니다. 먼저 수집 스크립트를 실행하세요.\n경로: {DATA_PATH}")
    else:
        results = nearest(rows, lat, lon, topn=int(topn), radius_km=radius_km)
        if not results:
            st.info("해당 반경 내 결과가 없습니다.")
        else:
            st.success(f"{len(results)}개 결과")

            # 1) 카드 리스트
            for i, r in enumerate(results, start=1):
                st.markdown(
                    f"**{i}. {r['TITLE'] or '(제목 없음)'}**  \n"
                    f"📍 {r['ADDR'] or '-'}  \n"
                    f"🕒 {r['OPERATING_TIME'] or '-'}  \n"
                    f"🧭 거리: **{r['DIST_KM']} km**"
                )
                if r["URL"]:
                    st.markdown(f"[🔗 홈페이지]({r['URL']})")
                st.divider()

            # 2) 카카오맵 지도 embed
            st.subheader("🗺️ Leaflet 지도")
            leaf_html = render_leaflet_map(results, center=(lat, lon), height=520)
            st.components.v1.html(leaf_html, height=520)
            
            # 2) 산점도(지도 대안)
            st.subheader("🗺️ 간이 산점도")
            norm = normalize_points_for_scatter(results, center=(lat, lon))
            fig = plt.figure(figsize=(5, 5))
            ax = plt.gca()
            ax.scatter(norm["xs"], norm["ys"], s=60)         # 추천 포인트
            ax.scatter([norm["center_x"]], [norm["center_y"]], s=100, marker="*", label="기준점")  # 기준점
            # 라벨(상위 5개만 깔끔하게)
            for x, y, t in list(zip(norm["xs"], norm["ys"], norm["titles"]))[:5]:
                ax.text(x + 0.01, y + 0.01, t, fontsize=9)
            ax.set_xlim(-0.05, 1.05)
            ax.set_ylim(-0.05, 1.05)
            ax.set_xlabel("경도(상대)")
            ax.set_ylabel("위도(상대)")
            ax.grid(True, alpha=0.3)
            ax.legend(loc="lower right")
            st.pyplot(fig, clear_figure=True)

            # 3) ASCII 격자 미니맵
            st.subheader("🧭 ASCII 격자 미니맵")
            ascii_map = make_ascii_minimap(results, center=(lat, lon), grid=21)
            st.code(ascii_map, language="text")

# ================================
# 🧭 위치 기준 선택 → 추천/답변 (START→O→C→E→D)
# ================================
st.header("🧭 위치 기준 선택 → 추천/답변 (Agent O)")

# 1) 위치 기준 설정 UI (device/manual)
cfg = get_origin_config()

# 2) 실행 버튼
col_run1, col_run2 = st.columns([1, 3])
with col_run1:
    run_o = st.button("START→O→C→E→D 실행", use_container_width=True)
with col_run2:
    st.caption("버튼을 누르면 O에서 좌표 확정 → C(추천) → E(지도) → D(답변) 순으로 실행합니다.")

if run_o:
    # (a) 설정이 없거나 유효하지 않으면 UI가 이미 안내하고 None을 반환합니다.
    if not cfg:
        st.warning("위치 설정이 유효하지 않습니다. 위 UI에서 좌표를 확인해 주세요.")
        st.stop()

    # (b) 데이터 로드
    rows = load_from_json(str(DATA_PATH))
    if not rows:
        st.error(f"데이터가 없습니다. 먼저 수집 스크립트를 실행하세요.\n경로: {DATA_PATH}")
        st.stop()

    try:
        # (c) 그래프 실행 (START→O→C→E→D)
        res = run_o_to_d(
            rows=rows,
            origin_mode=cfg["origin_mode"],
            origin_lat=cfg["origin_lat"],
            origin_lon=cfg["origin_lon"],
            origin_label=cfg["origin_label"],
            question=st.text_input("질문(선택)", value="주변 야경 명소 3곳과 운영시간 알려줘", key="o2d_q"),
            topn=int(cfg["topn"]),
            radius_km=float(cfg["radius_km"]),
            map_provider="leaflet",  # 또는 "kakao"
        )
    except Exception as e:
        st.exception(e)
        st.stop()

    # (d) 결과 표시
    st.success("실행 완료 ✅")
    recs = res.get("recommendations", [])

    st.subheader("추천 결과 (거리순)")
    if not recs:
        st.info("추천 결과가 없습니다. 반경을 넓히거나 Top-N을 늘려보세요.")
    else:
        for i, r in enumerate(recs, start=1):
            st.markdown(
                f"**{i}. {r.get('TITLE','(제목 없음)')}**  \n"
                f"📍 {r.get('ADDR','-')}  \n"
                f"🕒 {r.get('OPERATING_TIME','-')}  \n"
                f"🧭 거리: **{r.get('DIST_KM','-')} km**"
            )
            if r.get("URL"):
                st.markdown(f"[🔗 홈페이지]({r['URL']})")
            st.divider()

        # 지도
        st.subheader("🗺️ 지도")
        st.components.v1.html(res.get("map_html", "<p>지도 없음</p>"), height=520)

    # 최종 답변
    st.subheader("최종 답변")
    st.write(res.get("answer", "(응답 없음)"))

    # 그래프 구조
    st.subheader("🗺️ LangGraph (O→C→E→D) 미니 뷰어")
    with st.expander("그래프 구조 보기", expanded=True):
        st.graphviz_chart(get_graph_dot(), use_container_width=True)
        st.caption("Agent O(OriginResolver) → Agent C(추천) → Agent E(지도) → Agent D(답변) → END")
        st.code(get_graph_mermaid(), language="mermaid")

    # 상태/디버그 탭
    st.subheader("🧩 GraphState 미리보기")
    t1, t2, t3, t4 = st.tabs(["State(JSON)", "Recommendations", "Sources", "Raw"])
    with t1:
        st.json(res, expanded=False)
    with t2:
        if recs:
            cols = ["TITLE", "DIST_KM", "ADDR", "OPERATING_TIME", "URL", "LA", "LO"]
            table = [{k: r.get(k) for k in cols} for r in recs]
            st.dataframe(table, use_container_width=True)
        else:
            st.info("추천 데이터가 없습니다.")
    with t3:
        sources = res.get("sources", [])
        if sources:
            st.dataframe(sources, use_container_width=True)
            for s in sources:
                title = s.get("TITLE") or "(제목 없음)"
                url = s.get("URL") or ""
                st.markdown(f"- [{title}]({url})" if url else f"- {title}")
        else:
            st.info("출처 정보가 없습니다.")
    with t4:
        st.code(repr(res))

    # 추가 디버그
    with st.expander("🔎 디버그: 입력 파라미터 / 기준 좌표", expanded=False):
        st.write({
            "origin_mode": cfg["origin_mode"],
            "origin_label": cfg["origin_label"],
            "origin_lat": cfg["origin_lat"],
            "origin_lon": cfg["origin_lon"],
            "radius_km": cfg["radius_km"],
            "topn": cfg["topn"],
        })

st.header("🧭 추천 → 🧠 답변 (LangGraph C→D)")

lat = st.text_input("위도", "37.5512")
lon = st.text_input("경도", "126.9882")
topn = st.number_input("추천 개수", min_value=1, max_value=20, value=5, key="graph_topn")
radius = st.number_input("반경 (km, 선택)", min_value=0.0, value=0.0, step=0.5, key="graph_radius")
radius_km = None if radius == 0.0 else float(radius)
question = st.text_input("질문", "여의도 근처 무료 야경 명소와 운영시간 알려줘")

if st.button("C→D 실행"):
    try:
        lat_f = float(lat); lon_f = float(lon)
    except Exception:
        st.error("위도/경도를 숫자로 입력하세요.")
        st.stop()

    rows = load_from_json(str(DATA_PATH))
    if not rows:
        st.error(f"데이터가 없습니다. 먼저 fetch_and_index.py 실행.\n경로: {DATA_PATH}")
    else:
        res = run_c_to_d(
            rows, lat_f, lon_f, question,
            topn=int(topn),
            radius_km=(None if radius == 0 else float(radius))
        )

        # ---- 기존 요약 뷰 ----
        st.subheader("추천 결과 (요약)")
        recs = res.get("recommendations", [])
        if recs:
            for r in recs:
                st.markdown(
                    f"- **{r.get('TITLE','(제목 없음)')}** · {r.get('DIST_KM','-')}km · "
                    f"{r.get('ADDR','-')} · 운영시간 {r.get('OPERATING_TIME','-')}"
                )
        else:
            st.info("추천 결과가 없습니다.")

        st.subheader("최종 답변")
        st.write(res.get("answer", "(응답 없음)"))

        st.subheader("🗺️ LangGraph (C→D) 미니 뷰어")
        with st.expander("그래프 구조 보기", expanded=True):
            dot = get_graph_dot()

            # 실행 파라미터를 간단히 에지/노드 툴팁에 덧붙이고 싶으면 아래처럼 주석 해제해 커스터마이즈 가능
            # dot += '\n// params: topn={}, radius_km={}\n'.format(int(topn), None if radius == 0 else float(radius))

            st.graphviz_chart(dot, use_container_width=True)
            st.caption("Agent C(거리 추천) → Agent D(답변 합성) → END")



        # ---- GraphState 디스플레이 (탭 구성) ----
        st.subheader("🧩 GraphState 미리보기")
        t1, t2, t3, t4 = st.tabs(["State(JSON)", "Recommendations", "Sources", "Raw"])

        with t1:
            # GraphState 전체를 JSON으로 보기 좋게
            st.json(res, expanded=False)

        with t2:
            if recs:
                # 표 형태로 빠르게 훑기
                cols = ["TITLE", "DIST_KM", "ADDR", "OPERATING_TIME", "URL", "LA", "LO"]
                table = [{k: r.get(k) for k in cols} for r in recs]
                st.dataframe(table, use_container_width=True)
            else:
                st.info("추천 데이터가 없습니다.")

        with t3:
            sources = res.get("sources", [])
            if sources:
                st.dataframe(sources, use_container_width=True)
                # 링크도 바로 눌러보게
                for s in sources:
                    title = s.get("TITLE") or "(제목 없음)"
                    url = s.get("URL") or ""
                    if url:
                        st.markdown(f"- [{title}]({url})")
                    else:
                        st.markdown(f"- {title}")
            else:
                st.info("출처 정보가 없습니다.")

        with t4:
            # 디버그용 원본 출력 (dict 그대로)
            st.code(repr(res))

        # ---- 추가 디버그(선택) ----
        with st.expander("🔎 디버그: 입력 파라미터 / 경로", expanded=False):
            from pathlib import Path
            st.write({
                "lat": lat_f,
                "lon": lon_f,
                "topn": int(topn),
                "radius_km": (None if radius == 0 else float(radius)),
                "DATA_PATH": str(DATA_PATH),
                "CWD": str(Path.cwd()),
            })


st.caption("※ .env에 SEOUL_OPENAPI_KEY 입력 후 실행하세요.")
