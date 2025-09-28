from typing import List, Dict, Optional
import html
import uuid

def _filter_points(spots: List[Dict]):
    pts = []
    for s in spots:
        la, lo = s.get("LA"), s.get("LO")
        if isinstance(la, (int, float)) and isinstance(lo, (int, float)):
            pts.append({
                "title": s.get("TITLE") or "(제목 없음)",
                "addr": s.get("ADDR") or "-",
                "lat": float(la),
                "lon": float(lo),
            })
    return pts

def render_leaflet_map(
    spots: List[Dict],
    center: Optional[tuple] = None,   # (lat, lon)
    height: int = 500,
    zoom: int = 13,
) -> str:
    """
    Streamlit iframe(srcdoc)에서도 잘 뜨는 Leaflet 지도 HTML 반환
    - 외부 도메인 화이트리스트 불필요
    - 마커 팝업: TITLE / 주소
    """
    points = _filter_points(spots)
    if not points:
        return "<p style='color:gray'>좌표가 있는 명소가 없습니다.</p>"

    # 중심 좌표: 전달받은 center 우선, 없으면 첫 포인트
    if center and isinstance(center[0], (int, float)) and isinstance(center[1], (int, float)):
        center_lat, center_lon = float(center[0]), float(center[1])
    else:
        center_lat, center_lon = points[0]["lat"], points[0]["lon"]

    # 고유 map div id (같은 페이지에서 여러 번 렌더링 시 충돌 방지)
    map_id = f"leaflet_{uuid.uuid4().hex}"

    markers_js = []
    bounds_js = []
    for p in points:
        title = html.escape(p["title"])
        addr = html.escape(p["addr"])
        markers_js.append(
            f"L.marker([{p['lat']}, {p['lon']}]).addTo(map)"
            f".bindPopup('<b>{title}</b><br/>{addr}');"
        )
        bounds_js.append(f"[{p['lat']}, {p['lon']}]")

    markers_code = "\n".join(markers_js)
    bounds_code = ",".join(bounds_js)

    return f"""
<link
  rel="stylesheet"
  href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"
  integrity="sha256-p4NxAoJBhIIN+hmNHrzRCf9tD/miZyoHS5obTRR9BMY="
  crossorigin=""
/>
<div id="{map_id}" style="width:100%;height:{height}px;"></div>
<script
  src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"
  integrity="sha256-20nQCchB9co0qIjJZRGuk2/Z9VM+kNiyxNV1lvTlZBo="
  crossorigin=""
></script>
<script>
  var map = L.map('{map_id}', {{zoomControl: true}}).setView([{center_lat}, {center_lon}], {zoom});
  L.tileLayer('https://{{s}}.tile.openstreetmap.org/{{z}}/{{x}}/{{y}}.png', {{
    maxZoom: 19,
    attribution: '&copy; OpenStreetMap contributors'
  }}).addTo(map);

  {markers_code}

  try {{
    var bounds = L.latLngBounds([{bounds_code}]);
    map.fitBounds(bounds, {{ padding: [20, 20] }});
  }} catch (e) {{
    // bounds 계산 실패 시 기본 중심/줌 유지
  }}
</script>
"""


def render_map(spots: List[Dict], api_key: str) -> str:
    if not api_key or api_key == "환경변수 없음":
        return "<p style='color:red;'>[ERROR] KAKAO_API_KEY가 설정되지 않았습니다.</p>"
    if not spots:
        return "<p style='color:gray;'>표시할 명소가 없습니다.</p>"

    # 유효 좌표만 필터링
    points = [
        {"title": s.get("TITLE", "알 수 없음"),
         "lat": s.get("LA"), "lon": s.get("LO")}
        for s in spots
        if isinstance(s.get("LA"), (int, float)) and isinstance(s.get("LO"), (int, float))
    ]
    if not points:
        return "<p style='color:gray;'>좌표가 있는 명소가 없습니다.</p>"

    center_lat = points[0]["lat"]
    center_lon = points[0]["lon"]

    # 안전한 로딩(https + autoload=false + kakao.maps.load)
    # kakao 객체가 안 뜨는 경우 사용자에게 보이는 에러 박스도 함께 넣습니다.
    markers_js = "\n".join([
        f"""
        (function() {{
          var marker = new kakao.maps.Marker({{
            position: new kakao.maps.LatLng({p['lat']}, {p['lon']})
          }});
          marker.setMap(map);
          var iw = new kakao.maps.InfoWindow({{
            content: '<div style="padding:5px;font-size:12px;">{p['title']}</div>'
          }});
          kakao.maps.event.addListener(marker, 'click', function() {{
            iw.open(map, marker);
          }});
        }})();
        """
        for p in points
    ])

    html = f"""
    <div id="map_wrap" style="width:100%;height:500px;position:relative;">
      <div id="map" style="width:100%;height:100%;"></div>
      <div id="map_error" style="display:none;position:absolute;left:8px;top:8px;
           background:#fff3cd;border:1px solid #ffeeba;color:#856404;
           padding:6px 8px;border-radius:6px;font-size:12px;">
        지도를 불러오지 못했습니다. (도메인 등록/네트워크/키 확인)
      </div>
    </div>

    <script src="https://dapi.kakao.com/v2/maps/sdk.js?appkey={api_key}&autoload=false"></script>
    <script>
      (function () {{
        function init() {{
          try {{
            var container = document.getElementById('map');
            var options = {{
              center: new kakao.maps.LatLng({center_lat}, {center_lon}),
              level: 6
            }};
            window.map = new kakao.maps.Map(container, options);
            {markers_js}
          }} catch (e) {{
            document.getElementById('map_error').style.display = 'block';
          }}
        }}

        // kakao 객체가 준비된 뒤 초기화
        if (window.kakao && window.kakao.maps && window.kakao.maps.load) {{
          kakao.maps.load(init);
        }} else {{
          // SDK 스크립트 로딩이 늦을 수 있으므로 약간 기다렸다가 재시도
          var tries = 0;
          var timer = setInterval(function() {{
            tries += 1;
            if (window.kakao && window.kakao.maps && window.kakao.maps.load) {{
              clearInterval(timer);
              kakao.maps.load(init);
            }} else if (tries > 20) {{
              clearInterval(timer);
              document.getElementById('map_error').style.display = 'block';
            }}
          }}, 150);
        }}
      }})();
    </script>
    """
    return html
