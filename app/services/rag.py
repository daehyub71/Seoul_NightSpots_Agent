# app/services/rag.py
from __future__ import annotations

import numpy as np
from typing import List, Dict, Any, Tuple, Optional

from utils.logger import get_logger
from .embeddings import get_embedder  # 상대 임포트
# ↑ scripts에서 import 시 오류 나면: from services.embeddings import get_embedder 로 변경

log = get_logger("rag")

# 인덱스(프로세스 메모리 상주)
_INDEX: Dict[str, Any] = {
    "docs": [],           # [{id, title, url, text, meta}]
    "embeddings": None,   # np.ndarray [N, D]
    "embedder": None,     # 임베더 객체
}


def _concat_fields(row: Dict[str, Any]) -> str:
    """
    검색에 사용할 통합 텍스트 만들기
    (TITLE, CONTENTS, OPERATING_TIME, ENTR_FEE, SUBWAY, BUS, PARKING_INFO, ADDR, URL)
    """
    parts = []
    for k in ("TITLE", "CONTENTS", "OPERATING_TIME", "ENTR_FEE", "SUBWAY", "BUS", "PARKING_INFO", "ADDR", "URL"):
        v = row.get(k)
        if v:
            parts.append(str(v))
    return " | ".join(parts)


def _make_snippet(text: str, length: int = 160) -> str:
    s = (text or "").replace("\n", " ").strip()
    return s[:length] + ("…" if len(s) > length else "")


def build_index(rows: List[Dict[str, Any]], rebuild: bool = False) -> None:
    """
    문서 목록(rows)을 받아 인덱스를 빌드하여 메모리에 적재.
    """
    if not rows:
        log.warning("build_index: 입력 rows가 비어 있습니다.")
        _INDEX["docs"] = []
        _INDEX["embeddings"] = None
        _INDEX["embedder"] = None
        return

    docs: List[Dict[str, Any]] = []
    corpus: List[str] = []
    for i, r in enumerate(rows):
        title = (r.get("TITLE") or "").strip()
        url = (r.get("URL") or "").strip()
        text = _concat_fields(r)
        docs.append({
            "id": i,
            "title": title,
            "url": url,
            "text": text,
            "meta": {
                "addr": r.get("ADDR"),
                "operating": r.get("OPERATING_TIME"),
                "fee": r.get("ENTR_FEE"),
            }
        })
        corpus.append(text)

    # 임베딩 선택/계산
    embedder, doc_vecs = get_embedder(corpus)
    # numpy 배열로 캐스팅 (길이가 다른 경우는 AOAI/TFIDF에서는 발생하지 않음)
    embeddings = np.array(doc_vecs, dtype=float)

    _INDEX["docs"] = docs
    _INDEX["embeddings"] = embeddings
    _INDEX["embedder"] = embedder

    log.info(f"인덱스 빌드 완료: docs={len(docs)}, embedder={getattr(embedder, 'name', 'unknown')}")


def search(query: str, k: int = 5) -> List[Dict[str, Any]]:
    """
    질의어로 인덱스를 검색하여 Top-k 문서 반환.
    반환 항목: TITLE, URL, SNIPPET, SCORE
    """
    if not query or not _INDEX["docs"] or _INDEX["embeddings"] is None or _INDEX["embedder"] is None:
        return []

    embedder = _INDEX["embedder"]
    doc_mat: np.ndarray = _INDEX["embeddings"]  # [N, D]
    q_vec = np.array(embedder.encode_query(query), dtype=float)

    # 코사인 유사도 계산
    # 각 행과 q_vec의 코사인
    # 정규화
    doc_norms = np.linalg.norm(doc_mat, axis=1)
    q_norm = np.linalg.norm(q_vec)
    if q_norm == 0.0:
        scores = np.zeros(len(doc_mat))
    else:
        dots = doc_mat @ q_vec
        with np.errstate(divide="ignore", invalid="ignore"):
            scores = np.where(doc_norms > 0, dots / (doc_norms * q_norm), 0.0)

    # Top-k
    idxs = np.argsort(-scores)[:k]
    out: List[Dict[str, Any]] = []
    for idx in idxs:
        d = _INDEX["docs"][int(idx)]
        out.append({
            "TITLE": d["title"],
            "URL": d["url"],
            "SNIPPET": _make_snippet(d["text"]),
            "SCORE": float(scores[int(idx)]),
        })
    return out


# 모듈 단독 테스트
if __name__ == "__main__":
    rows = [
        {"TITLE": "남산타워", "CONTENTS": "서울의 대표 야경", "ADDR": "용산구", "URL": "https://n"},
        {"TITLE": "여의도 한강공원", "CONTENTS": "강변 산책과 야간조명", "ADDR": "영등포구", "URL": "https://y"},
        {"TITLE": "서울로7017", "CONTENTS": "고가 보행로의 도시 야경", "ADDR": "중구", "URL": "https://s"},
    ]
    build_index(rows, rebuild=True)
    print(search("한강 야경", k=2))
