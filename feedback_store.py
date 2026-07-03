"""优秀问答回灌 — 点赞的问答存入 Chroma，后续检索可复用"""
import os
import json
import time
import logging
from typing import List, Optional

from db import _get_embed_fn, get_chroma_client
from config import settings

logger = logging.getLogger(__name__)

FEEDBACK_FILE = os.path.join(os.path.dirname(__file__), "data", "curated_qa.json")
COLLECTION_SUFFIX = "_curated"


def _get_collection():
    """获取或创建"精选问答"集合"""
    embed_fn = _get_embed_fn()
    client = get_chroma_client()
    col_name = settings.collection_name + COLLECTION_SUFFIX
    try:
        return client.get_collection(name=col_name, embedding_function=embed_fn)
    except Exception:
        collection = client.create_collection(
            name=col_name,
            embedding_function=embed_fn,
            metadata={"hnsw:space": "cosine"},
        )
        logger.info("已创建精选问答集合")
        return collection


def save_feedback(question: str, answer: str, source_books: List[str]) -> dict:
    """保存点赞的问答对到 Chroma + JSON 日志"""
    collection = _get_collection()
    timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
    qa_id = f"qa_{hash(question + answer) % 10**8}"

    # 组合检索文本
    doc_text = f"问题：{question}\n\n回答：{answer}"

    metadata = {
        "question": question[:200],
        "source_books": ",".join(source_books)[:500],
        "created_at": timestamp,
        "type": "curated_qa",
    }

    # 写入 Chroma
    collection.add(
        ids=[qa_id],
        documents=[doc_text],
        metadatas=[metadata],
    )

    # 同时追加到 JSON 日志（备查 + 人工质检）
    os.makedirs(os.path.dirname(FEEDBACK_FILE), exist_ok=True)
    record = {
        "id": qa_id,
        "question": question,
        "answer": answer,
        "source_books": source_books,
        "created_at": timestamp,
    }
    existing = []
    if os.path.exists(FEEDBACK_FILE):
        try:
            with open(FEEDBACK_FILE, "r", encoding="utf-8") as f:
                existing = json.load(f)
        except Exception:
            pass
    existing.append(record)
    with open(FEEDBACK_FILE, "w", encoding="utf-8") as f:
        json.dump(existing, f, ensure_ascii=False, indent=2)

    count = collection.count()
    logger.info(f"已保存精选问答 (#{count}): {question[:50]}...")
    return {"id": qa_id, "total": count}


def search_curated(query: str, top_k: int = 2) -> List[dict]:
    """检索最相关的精选问答（自动过滤差评条目）"""
    try:
        collection = _get_collection()
    except Exception:
        return []

    if collection.count() == 0:
        return []

    results = collection.query(
        query_texts=[query],
        n_results=min(top_k + 3, collection.count()),  # 多搜几条留余地
    )

    sources = []
    if results["ids"] and results["ids"][0]:
        for i in range(len(results["ids"][0])):
            m = results["metadatas"][0][i]
            q = m.get("question", "")
            content = results["documents"][0][i]
            # 过滤已被差评的条目
            if is_disliked(q, content):
                continue
            sources.append({
                "book": "⭐ 精选回答",
                "chapter": q[:60],
                "content": content,
                "score": results["distances"][0][i] if results.get("distances") else 0,
                "source": "curated",
                "question": q,
            })
            if len(sources) >= top_k:
                break
    return sources


def is_liked(question: str, answer: str) -> bool:
    """检查某条问答是否已被点赞 — 用 JSON 文件做精确匹配，比 Chroma 语义搜索更可靠"""
    import os as _os
    if not _os.path.exists(FEEDBACK_FILE):
        return False
    try:
        with open(FEEDBACK_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        for d in data:
            if d.get("question") == question and d.get("answer") == answer:
                return True
        return False
    except Exception:
        return False


# check_kept 是 is_liked 的别名，保持向后兼容
check_liked = is_liked


def count_feedback() -> int:
    """当前精选问答总数"""
    try:
        return _get_collection().count()
    except Exception:
        return 0


def remove_feedback(question: str, answer: str) -> bool:
    """取消点赞，删除指定问答"""
    try:
        collection = _get_collection()
        # 找到匹配的问答
        results = collection.query(
            query_texts=[question[:200]],
            n_results=3,
        )
        removed = False
        if results["ids"] and results["ids"][0]:
            for i, qa_id in enumerate(results["ids"][0]):
                doc = results["documents"][0][i]
                if answer[:100] in doc or question[:100] in doc:
                    collection.delete(ids=[qa_id])
                    removed = True
        # 同步更新 JSON 日志
        _sync_json_after_remove(question, answer)
        return removed
    except Exception:
        return False


def _sync_json_after_remove(question: str, answer: str):
    """从 JSON 日志中移除匹配的条目"""
    import os as _os
    if not _os.path.exists(FEEDBACK_FILE):
        return
    try:
        with open(FEEDBACK_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        data = [d for d in data if not (
            (question[:50] in d.get("question", "")) and
            (answer[:50] in d.get("answer", ""))
        )]
        with open(FEEDBACK_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


# --- 差评管理 ---

def _get_disliked_collection():
    """获取或创建差评集合"""
    embed_fn = _get_embed_fn()
    client = get_chroma_client()
    col_name = settings.collection_name + "_disliked"
    try:
        return client.get_collection(name=col_name, embedding_function=embed_fn)
    except Exception:
        return client.create_collection(
            name=col_name, embedding_function=embed_fn,
            metadata={"hnsw:space": "cosine"},
        )


def dislike_feedback(question: str, answer: str, source_books: list = None) -> int:
    """记录差评并关联到来源"""
    collection = _get_disliked_collection()
    qa_id = f"dislike_{hash(question + answer) % 10**8}"
    meta = {
        "question": question[:200],
        "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
    }
    if source_books:
        meta["source_books"] = ",".join(source_books)[:500]
    try:
        collection.upsert(
            ids=[qa_id],
            documents=[f"问题：{question}\n\n回答：{answer}"],
            metadatas=[meta],
        )
    except Exception:
        pass
    return collection.count()


def get_disliked_patterns(query: str) -> str:
    """检索与当前问题相关的差评记录，提取警示信息"""
    try:
        collection = _get_disliked_collection()
        if collection.count() == 0:
            return ""
        results = collection.query(query_texts=[query[:200]], n_results=3)
        if not results["ids"] or not results["ids"][0]:
            return ""
        patterns = []
        for i in range(min(3, len(results["ids"][0]))):
            m = results["metadatas"][0][i]
            q = m.get("question", "")[:60]
            sb = m.get("source_books", "")
            parts = [f"此前「{q}」被标记为差评回答"]
            if sb:
                parts.append(f"（涉及来源：{sb}）")
            patterns.append("".join(parts))
        if patterns:
            return "\n".join(patterns) + "\n请特别注意，不要重复类似偏差，如果涉及以上来源请格外谨慎使用。"
    except Exception:
        pass
    return ""


def is_disliked(question: str, answer: str = "") -> bool:
    """检查某条问答是否被差评"""
    try:
        collection = _get_disliked_collection()
        # 按问题文本搜索
        results = collection.query(
            query_texts=[question[:200]],
            n_results=2,
        )
        if not results["ids"] or not results["ids"][0]:
            return False
        for doc in results["documents"][0]:
            if answer[:80] in doc or question[:80] in doc:
                return True
        return False
    except Exception:
        return False



