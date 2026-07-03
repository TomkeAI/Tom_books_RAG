"""Chroma 数据库操作 — 使用 ONNX 嵌入，无需额外模型下载"""
import os
import glob
import logging
import time
import threading
from typing import List, Optional

import chromadb
from chromadb.config import Settings as ChromaSettings
from chromadb.utils.embedding_functions import ONNXMiniLM_L6_V2

from config import settings

logger = logging.getLogger(__name__)

# 全局缓存嵌入函数（ONNX 轻量级，首次加载快，后续秒级）
_embed_fn: Optional[ONNXMiniLM_L6_V2] = None
_embed_lock = threading.Lock()


def _get_embed_fn():
    """获取 ONNX MiniLM 嵌入函数（全局缓存 + 线程安全）"""
    global _embed_fn
    if _embed_fn is not None:
        return _embed_fn
    with _embed_lock:
        if _embed_fn is not None:
            return _embed_fn
        logger.info("初始化 ONNX 嵌入模型 (all-MiniLM-L6-v2)")
        t0 = time.time()
        _embed_fn = ONNXMiniLM_L6_V2(preferred_providers=["CPUExecutionProvider"])
        logger.info(f"嵌入模型就绪（耗时 {time.time()-t0:.1f}s）")
    return _embed_fn


def get_chroma_client():
    os.makedirs(settings.chroma_persist_dir, exist_ok=True)
    return chromadb.PersistentClient(
        path=settings.chroma_persist_dir,
        settings=ChromaSettings(anonymized_telemetry=False),
    )


def _read_chunks(filepath: str) -> List[dict]:
    """把一章读成较大的文本块"""
    with open(filepath, "r", encoding="utf-8") as f:
        text = f.read()

    lines = text.split("\n")
    chunks = []
    current = []
    current_h = ""
    size = 0
    max_size = settings.chunk_size

    for line in lines:
        if line.startswith("# "):
            current_h = line.strip("# ").strip()
        elif line.startswith("## "):
            sub = line.strip("## ").strip()
            current_h = f"{current_h} > {sub}" if current_h else sub

        if line.strip() == "" and size >= max_size * 0.8 and current:
            chunks.append({"content": "\n".join(current).strip(), "heading": current_h})
            current = []
            size = 0
            continue

        current.append(line)
        size += len(line) + 1

        if size >= max_size:
            chunks.append({"content": "\n".join(current).strip(), "heading": current_h})
            current = []
            size = 0

    if current:
        chunks.append({"content": "\n".join(current).strip(), "heading": current_h})

    return chunks


def ingest_books(force_reindex: bool = False):
    """将书本技能章节导入 Chroma"""
    embed_fn = _get_embed_fn()
    client = get_chroma_client()

    if force_reindex:
        try:
            client.delete_collection(settings.collection_name)
        except Exception:
            pass

    # 直接传嵌入函数给 Chroma 集合，由 Chroma 自动管理嵌入
    collection = client.get_or_create_collection(
        name=settings.collection_name,
        embedding_function=embed_fn,
        metadata={"hnsw:space": "cosine"},
    )

    if collection.count() > 0 and not force_reindex:
        logger.info(f"向量库已有 {collection.count()} 条数据，跳过导入")
        return

    chunks_all = []
    ids_all = []
    metas_all = []
    idx = 0

    for bi, (skill_dir, book_title) in enumerate(settings.books, 1):
        pattern = os.path.join(settings.books_base, skill_dir, "chapters", "*.md")
        files = sorted(glob.glob(pattern))
        if not files:
            logger.warning(f"  未找到 {skill_dir} 章节")
            continue

        for fpath in files:
            fname = os.path.splitext(os.path.basename(fpath))[0]
            chapter = fname.split("-", 1)[-1] if "-" in fname else fname
            fchunks = _read_chunks(fpath)

            for c in fchunks:
                chunks_all.append(c["content"])
                ids_all.append(f"{skill_dir}_{idx}")
                metas_all.append({
                    "book": book_title,
                    "chapter": chapter,
                    "section": c["heading"],
                })
                idx += 1

            logger.info(f"  [{bi}/{len(settings.books)}] {chapter}: {len(fchunks)} 块")

    if not chunks_all:
        logger.warning("没有找章节数据")
        return

    total = len(chunks_all)
    logger.info(f"共 {total} 块，写入 Chroma（自动嵌入）...")

    t0 = time.time()
    batch_size = 128
    for i in range(0, total, batch_size):
        end = min(i + batch_size, total)
        collection.add(
            ids=ids_all[i:end],
            documents=chunks_all[i:end],
            metadatas=metas_all[i:end],
        )

    logger.info(f"导入完成！{total} 块，耗时 {time.time()-t0:.1f}s")


def search_books(query: str, top_k: int = 5) -> List[dict]:
    """检索最相关的书本知识"""
    embed_fn = _get_embed_fn()
    client = get_chroma_client()

    try:
        collection = client.get_collection(
            settings.collection_name,
            embedding_function=embed_fn,
        )
    except Exception:
        return []

    t0 = time.time()
    results = collection.query(
        query_texts=[query],
        n_results=min(top_k, collection.count()),
    )
    elapsed = time.time() - t0

    sources = []
    if results["ids"] and results["ids"][0]:
        for i in range(len(results["ids"][0])):
            sources.append({
                "book": results["metadatas"][0][i]["book"],
                "chapter": results["metadatas"][0][i]["chapter"],
                "section": results["metadatas"][0][i].get("section", ""),
                "content": results["documents"][0][i],
                "score": results["distances"][0][i] if results.get("distances") else 0,
            })
    logger.info(f"检索: {len(sources)} 条, {elapsed:.2f}s")
    return sources
