# app/services/embeddings.py
from __future__ import annotations

import math
import os
from typing import List, Dict, Any, Optional, Iterable, Tuple

from utils.logger import get_logger
from utils.config import settings

log = get_logger("embeddings")

# ===== 공통 유틸 =====
def _cosine(a: Iterable[float], b: Iterable[float]) -> float:
    num = 0.0
    da = 0.0
    db = 0.0
    for x, y in zip(a, b):
        num += x * y
        da += x * x
        db += y * y
    if da == 0.0 or db == 0.0:
        return 0.0
    return num / (math.sqrt(da) * math.sqrt(db))


def _simple_tokenize(text: str) -> List[str]:
    # 매우 단순 토크나이저: 영문/숫자/한글 분리 없이 공백 기준
    return [t for t in (text or "").lower().split() if t]


# ===== 임베더 베이스 =====
class BaseEmbedder:
    name: str = "base"

    def encode_texts(self, texts: List[str]) -> List[List[float]]:
        raise NotImplementedError

    def encode_query(self, text: str) -> List[float]:
        return self.encode_texts([text])[0]

    def similarity(self, doc_vecs: List[List[float]], query_vec: List[float]) -> List[float]:
        return [_cosine(v, query_vec) for v in doc_vecs]


# ===== 1) Azure OpenAI 임베딩 (우선) =====
class AOAIEmbedder(BaseEmbedder):
    name = "aoai"

    def __init__(self, endpoint: str, api_key: str, deployment: str, api_version: str = "2024-02-15-preview"):
        self.endpoint = endpoint.rstrip("/")
        self.api_key = api_key
        self.deployment = deployment
        self.api_version = api_version

    def _embed_batch(self, batch: List[str]) -> List[List[float]]:
        import requests  # 지연 임포트
        url = f"{self.endpoint}/openai/deployments/{self.deployment}/embeddings?api-version={self.api_version}"
        headers = {
            "Content-Type": "application/json",
            "api-key": self.api_key,
        }
        payload = {"input": batch}
        resp = requests.post(url, headers=headers, json=payload, timeout=20)
        resp.raise_for_status()
        data = resp.json()
        # OpenAI 형식 가정: {"data":[{"embedding":[...]}]}
        return [item["embedding"] for item in data.get("data", [])]

    def encode_texts(self, texts: List[str]) -> List[List[float]]:
        out: List[List[float]] = []
        B = 64
        for i in range(0, len(texts), B):
            out.extend(self._embed_batch(texts[i:i + B]))
        return out


# ===== 2) TF-IDF (scikit-learn) =====
class TfidfEmbedder(BaseEmbedder):
    name = "tfidf"

    def __init__(self, corpus: List[str]):
        from sklearn.feature_extraction.text import TfidfVectorizer  # 지연 임포트
        self.vectorizer = TfidfVectorizer(
            max_features=20000,
            ngram_range=(1, 2),
            token_pattern=r"(?u)\b\w+\b",
        )
        self.doc_mat = self.vectorizer.fit_transform(corpus)  # fit은 build_index에서 호출됨 컨텍스트로 수행

    def encode_texts(self, texts: List[str]) -> List[List[float]]:
        mat = self.vectorizer.transform(texts)
        return [row.toarray().ravel().tolist() for row in mat]

    # TF-IDF는 내적이 코사인과 동일하게 동작(정규화된 경우) → 그대로 사용 가능
    def similarity(self, doc_vecs: List[List[float]], query_vec: List[float]) -> List[float]:
        # 메모리 절약을 위해 벡터를 다시 만들지 않고 간단 코사인
        return super().similarity(doc_vecs, query_vec)


# ===== 3) 키워드 코사인 (순수 파이썬 최종 폴백) =====
class KeywordEmbedder(BaseEmbedder):
    name = "keyword"

    def __init__(self, corpus: List[str]):
        # 단어 사전 구성
        vocab_set = set()
        tokenized_docs = []
        for t in corpus:
            toks = _simple_tokenize(t)
            tokenized_docs.append(toks)
            vocab_set.update(toks)
        self.vocab = {w: i for i, w in enumerate(sorted(vocab_set))}
        self.doc_vecs = [self._to_vec(toks) for toks in tokenized_docs]

    def _to_vec(self, toks: List[str]) -> List[float]:
        vec = [0.0] * len(self.vocab)
        for tok in toks:
            idx = self.vocab.get(tok)
            if idx is not None:
                vec[idx] += 1.0
        return vec

    def encode_texts(self, texts: List[str]) -> List[List[float]]:
        return [self._to_vec(_simple_tokenize(t)) for t in texts]


def get_embedder(corpus_texts: List[str]) -> Tuple[BaseEmbedder, List[List[float]]]:
    """
    임베더 선택 (우선순위):
      1) AOAI (환경변수 모두 설정 시)
      2) TF-IDF (scikit-learn 사용 가능 시)
      3) 키워드 코사인 (순수 파이썬)
    반환: (embedder, doc_vectors)
    """
    # 1) AOAI
    if all([
        settings.AOAI_ENDPOINT != "환경변수 없음",
        settings.AOAI_API_KEY != "환경변수 없음",
        settings.AOAI_DEPLOYMENT != "환경변수 없음",
    ]):
        try:
            emb = AOAIEmbedder(
                endpoint=settings.AOAI_ENDPOINT,
                api_key=settings.AOAI_API_KEY,
                deployment=settings.AOAI_DEPLOYMENT,
            )
            log.info("임베딩: AOAI 사용")
            doc_vecs = emb.encode_texts(corpus_texts)
            return emb, doc_vecs
        except Exception as e:
            log.warning(f"AOAI 임베딩 실패 → 폴백 TF-IDF: {e}")

    # 2) TF-IDF
    try:
        emb = TfidfEmbedder(corpus_texts)
        log.info("임베딩: TF-IDF 사용")
        # 이미 fit에서 문서행렬 보유하지만, 일관성 위해 리스트 벡터로 변환
        doc_vecs = emb.encode_texts(corpus_texts)
        return emb, doc_vecs
    except Exception as e:
        log.warning(f"TF-IDF 임베딩 실패 → 폴백 키워드 코사인: {e}")

    # 3) 키워드
    emb = KeywordEmbedder(corpus_texts)
    log.info("임베딩: 키워드 코사인 사용")
    doc_vecs = emb.encode_texts(corpus_texts)
    return emb, doc_vecs
