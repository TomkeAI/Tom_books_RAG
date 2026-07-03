"""混合搜索 — BM25 关键词 + 向量语义 双通道融合"""
import logging
import re
from typing import List

logger = logging.getLogger(__name__)

try:
    from rank_bm25 import BM25Okapi
    _bm25_available = True
except ImportError:
    _bm25_available = False
    logger.warning("rank_bm25 未安装，回退到纯向量搜索")


def _tokenize(text: str) -> List[str]:
    """中英文分词（简单方案）"""
    # 英文按空格分，中文按单字+常见词
    tokens = []
    for part in re.findall(r"[a-zA-Z0-9]+|[^\s]", text):
        if re.match(r"[a-zA-Z0-9]+", part):
            tokens.append(part.lower())
        else:
            # 中文：双字词
            for i in range(len(part) - 1):
                tokens.append(part[i : i + 2])
            tokens.append(part)
    return tokens


def hybrid_search(
    query: str,
    vector_search_fn,
    corpus: List[str] = None,
    corpus_ids: List[str] = None,
    top_k: int = 5,
    alpha: float = 0.5,
) -> List[dict]:
    """混合搜索：BM25 + 向量，RRF 融合"""
    # 1. 向量搜索
    vector_results = vector_search_fn(query, top_k=top_k * 2)
    vector_map = {r.get("chapter", ""): r for r in vector_results}

    # 2. BM25 搜索
    bm25_results = []
    if _bm25_available and corpus and corpus_ids:
        tokenized_corpus = [_tokenize(doc) for doc in corpus]
        bm25 = BM25Okapi(tokenized_corpus)
        query_tokens = _tokenize(query)
        scores = bm25.get_scores(query_tokens)
        ranked = sorted(
            zip(corpus_ids, scores), key=lambda x: -x[1]
        )[:top_k]
        for cid, score in ranked:
            if score > 0:
                for r in vector_results:
                    if r.get("chapter") == cid:
                        bm25_results.append(r)
                        break

    # 3. RRF 融合
    seen = set()
    fused = []
    rank = 1
    for r in vector_results + bm25_results:
        key = r.get("chapter", "") + r.get("book", "")
        if key in seen:
            continue
        seen.add(key)
        r["_rrf_score"] = 1.0 / (rank + 60)
        fused.append(r)
        rank += 1
        if len(fused) >= top_k:
            break

    fused.sort(key=lambda x: -x.get("_rrf_score", 0))
    return fused[:top_k]
