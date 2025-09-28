**목표**: 서울시 `viewNightSpot` Open API를 수집·정규화하고, RAG + 거리기반 추천 + LangGraph 멀티에이전트를 Streamlit UI로 제공

---

## 1) 환경 변수 설정 방법

프로젝트 루트에 `.env` 파일을 만듭니다. (이미 있다면 값만 채워주세요)

```bash
# .env (예시)
SEOUL_OPENAPI_KEY=발급_서울_오픈API키
AOAI_ENDPOINT=https://{your-resource}.openai.azure.com/
AOAI_API_KEY=xxxxxxxxxxxxxxxxxxxxxxxxxxxx
AOAI_DEPLOYMENT=text-embedding-3-large
```

* 키가 비어 있으면 앱 내에서 `"환경변수 없음"`으로 표시됩니다.
* AOAI(임베딩/LLM)는 **선택**입니다. 없으면 자동으로 TF-IDF → 키워드 코사인 순서로 폴백합니다.
* 키 로딩은 `app/utils/config.py`에서 수행합니다.

**환경 변수 점검 UI**

```bash
streamlit run app/ui/app.py
# "환경 변수 점검" 버튼 클릭 → 각 키의 상태 확인
```

---

## 2) 데이터 수집/정규화/인덱싱 (fetch_and_index.py)

서울시 Open API에서 데이터를 가져와 정규화 후 저장합니다. (필요하면 RAG 인덱싱까지 수행)

```bash
# 1~3페이지, 페이지당 기본 200건 수집 → data/nightspots.json 저장
python scripts/fetch_and_index.py --pages 1-3

# 기존 JSON 무시하고 재구축
python scripts/fetch_and_index.py --pages 1-3 --rebuild

# 페이지당 건수 조정 (예: 1000)
python scripts/fetch_and_index.py --pages 1-2 --page-size 1000
```

* 저장 경로: `data/nightspots.json` (스크립트 로그에 절대경로 출력)
* 정규화: `app/services/datastore.py`

  * 좌표 `LA/LO` → `float` 변환, `0.0`/변환실패는 `None`으로 제외
  * 문자열은 `strip()` 후 빈 값은 `None`
* 인덱싱: `app/services/rag.py::build_index()`
  AOAI 실패/미설정 시 TF-IDF/키워드 임베딩으로 자동 폴백

---

## 3) 앱 실행 (Streamlit)

메인 UI:

```bash
streamlit run app/ui/app_view.py
```

### 탭1: 📍 가까운 명소 추천

* 입력: 위도/경도 직접 입력 또는 드롭다운(시청/광화문/남산/잠실/강남/여의도)
* 출력: 거리순 **카드 리스트** + **matplotlib 산점도** + **ASCII 미니맵**
* 반경(km) 필터 옵션 제공

### 탭2: 💬 질문하기 (RAG)

* 입력: 자연어 질의 (예: “한강 근처 무료 야경명소 알려줘”)
* 출력: RAG 검색 결과 **요약+스니펫**, 각 항목의 **URL(출처)** 표기
* 최초 1회 인덱스 빌드 후 세션 캐시 사용

> 경로 불일치 방지: 앱은 `DATA_PATH = <프로젝트루트>/data/nightspots.json` 절대경로로 로드합니다.

---

## 4) 지도 API 대안 설명

사내/망 제한 등으로 외부 지도 API 사용이 어려운 환경을 고려해 다음 **대안 시각화**를 제공합니다.

* **matplotlib 산점도**: 추천 지점을 **상대 좌표**로 0~1 구간에 정규화해 배치 관계를 직관적으로 표시

  * 기준점(사용자 입력 좌표)은 별표(*)로 강조
  * 상위 5개 라벨 표시, 그리드/축 안내 제공
* **ASCII 격자 미니맵**: 21×21 문자 격자

  * `◎` = 기준점, `①②③…` = 1~N위 추천 지점
  * 위쪽=북, 오른쪽=동 방향 안내 문구 포함
* 구현 파일: `app/services/vis.py`
  UI 연동: `app/ui/app_view.py`

---

## 5) 오류 상황 FAQ

### Q1. `data/nightspots.json`을 못 찾습니다 / 결과가 비어 있어요

* **원인**: 경로 불일치 또는 수집 미실행
* **조치**

  1. `python scripts/fetch_and_index.py --pages 1-3` 실행
  2. 앱 상단 “ℹ️ 실행 환경/경로”에서 `DATA_PATH` 확인
  3. 권한/경로 문제 시 절대경로로 접근

### Q2. `SEOUL_OPENAPI_KEY`가 없다는 메시지가 떠요

* **원인**: `.env`에 키 미설정
* **조치**: `.env`에 `SEOUL_OPENAPI_KEY` 추가 후 재실행
  UI의 **환경 변수 점검** 페이지로 상태 확인

### Q3. AOAI 관련 네트워크/인증 에러

* **증상**: 임베딩/LLM 호출 실패, 타임아웃 등
* **조치**: AOAI 키/엔드포인트/디플로이먼트 값을 확인
  실패 시 자동으로 **TF-IDF → 키워드 코사인**으로 폴백되므로 기능 자체는 사용 가능

### Q4. `StreamlitDuplicateElementId` (중복 위젯 키 에러)

* **원인**: 동일한 레이블·파라미터 조합의 입력 위젯을 여러 번 사용
* **조치**: 모든 `st.number_input`/`st.text_input`/`st.selectbox` 등에 **고유한 `key=`**를 지정
  (예: `key="near_topn"`, `key="rag_topk"`)

### Q5. 그래프/시각화가 표시되지 않아요

* **원인**: 백엔드 환경에서 `matplotlib` 렌더링 이슈
* **조치**: 기본 백엔드 사용(코드에서 스타일 지정 없음), 가능한 최신 Streamlit 버전 사용
  앱을 재실행하거나 브라우저 새로고침

### Q6. LangGraph 이미지가 필요합니다

* **대안**: `st.graphviz_chart` 기반 **미니 뷰어** 제공 (`app/agents/graph.py::get_graph_dot`)
  별도 `graphviz` 패키지 설치 없이 브라우저에서 렌더링됨

### Q7. API 호출 실패/타임아웃

* **원인**: 네트워크, 샘플키 호출 제한, 잘못된 인덱스 범위
* **조치**: `app/services/api_client.py`는 4xx/5xx/타임아웃을 구분해 메시지 표시

  * 호출 범위를 1~5로 테스트 → 정상 동작 확인 후 범위 확장

---

## 빠른 스모크 테스트

1. **환경 변수 점검**

```bash
streamlit run app/ui/app.py
# 버튼: "환경 변수 점검" → 키 상태 확인
```

2. **데이터 수집**

```bash
python scripts/fetch_and_index.py --pages 1-3 --rebuild
```

3. **앱 실행**

```bash
streamlit run app/ui/app_view.py
# 탭1: "여의도" 프리셋 선택 → 추천 리스트 + 산점도 + ASCII 확인
# 탭2: "한강 근처 무료 야경명소 알려줘" → 결과 + 링크 확인
```

---

## 디렉토리 개요

```
app/
  utils/        ├─ config.py, logger.py
  services/     ├─ api_client.py, datastore.py, embeddings.py, rag.py, geo.py, vis.py
  agents/       ├─ nodes.py, graph.py
  ui/           ├─ app.py (환경변수/간이테스트), app_view.py (메인 UI)
data/
  └─ nightspots.json
scripts/
  └─ fetch_and_index.py
```

---

## 라이선스 / 기타

* 서울시 Open API 사용 정책을 준수하세요.
* 내부망/패키지 제약 환경을 고려해 모든 핵심 기능은 **폴백 경로**(AOAI 미사용 시 TF-IDF/키워드, 지도 대안 시각화)를 제공합니다.
* 이 README만 보고도 수집 → 인덱싱 → 실행까지 **바로 검증**할 수 있도록 구성했습니다.
