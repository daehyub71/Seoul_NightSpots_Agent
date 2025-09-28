# app/ui/components/location_picker.py
from __future__ import annotations

from typing import Dict, Optional, Tuple, Any

import streamlit as st

# 프로젝트 서비스 헬퍼
try:
    # 배치된 경로에 맞춰 조정하세요.
    from app.services.geo import validate_coords, get_preset_coord, PRESET_COORDS
except Exception:
    # 상대 임포트가 다르면 아래와 같이 바꾸세요.
    from services.geo import validate_coords, get_preset_coord, PRESET_COORDS


# ---------------------------------------------------------------------
# 내부 유틸
# ---------------------------------------------------------------------
def _get_query_params() -> Dict[str, Any]:
    """Streamlit 버전에 따라 query params 가져오기 (호환 래퍼)."""
    # Streamlit >= 1.30
    if hasattr(st, "query_params"):
        try:
            # st.query_params는 Mapping[str, str|list[str]] 형태
            qp = dict(st.query_params)  # type: ignore[attr-defined]
            # list[str]가 올 수 있어 첫 값만 취함
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
    """프리셋 드롭다운 및 좌표 추출."""
    labels = list(PRESET_COORDS.keys())
    if default_label not in labels:
        default_label = labels[0]
    label = st.selectbox("프리셋", labels, index=labels.index(default_label))
    latlon = get_preset_coord(label)
    lat, lon = (latlon[0], latlon[1]) if latlon else (None, None)
    return label, lat, lon


# ---------------------------------------------------------------------
# 공개 API
# ---------------------------------------------------------------------
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
        radius_km = st.number_input("반경 (km)", min_value=0.0, value=3.0, step=0.5, format="%.1f")
    with col1:
        topn = st.number_input("추천 개수 (Top-N)", min_value=1, value=5, step=1)

    # 모드 선택
    mode = st.radio("위치 기준 선택", ("현재 위치(모바일)", "원하는 장소 직접 지정"), horizontal=True)
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
        use_preset = st.checkbox(f"프리셋 좌표 사용({label})", value=True)

    with col_b:
        st.write("수동 좌표 입력")
        lat_in = st.text_input("위도(lat)", value=f"{p_lat:.6f}" if p_lat is not None else "")
        lon_in = st.text_input("경도(lon)", value=f"{p_lon:.6f}" if p_lon is not None else "")

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


# ---------------------------------------------------------------------
# 데모 실행 가드
# ---------------------------------------------------------------------
if __name__ == "__main__":
    st.set_page_config(page_title="Location Picker Demo", page_icon="🧭", layout="centered")

    st.title("🧭 Location Picker (Agent O)")
    st.write("이 페이지는 위치 기준 설정 컴포넌트를 단독으로 테스트하기 위한 데모입니다.")

    cfg = get_origin_config()
    st.divider()
    st.subheader("반환 값")
    st.write(cfg)
# EOF
