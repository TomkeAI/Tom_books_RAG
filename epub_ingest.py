"""EPUB 整书导入模块 — 按章节导入，保留完整上下文"""
import os
import glob
import logging
import re
from typing import List, Optional

from ebooklib import epub
from bs4 import BeautifulSoup

from config import settings

logger = logging.getLogger(__name__)


def extract_epub_chapters(epub_path: str) -> List[dict]:
    """解析 EPUB 文件，按章节提取纯文本（每章作为一个大块）"""
    book = epub.read_epub(epub_path)
    chapters = []
    title = book.get_metadata("DC", "title")
    book_title = title[0][0] if title else os.path.splitext(os.path.basename(epub_path))[0]

    for item in book.get_items():
        if item.get_type() != 9:  # 9 = document type
            continue

        # 提取目录层级做章节标题
        html = item.get_content().decode("utf-8", errors="replace")
        soup = BeautifulSoup(html, "html.parser")

        # 移除 script / style
        for tag in soup(["script", "style", "nav"]):
            tag.decompose()

        text = soup.get_text(separator="\n", strip=True)
        if not text or len(text) < 100:
            continue  # 跳过短无意义页

        # 用 h1/h2 提取章节标题
        chapter_title = None
        for tag in soup.find_all(["h1", "h2", "h3"]):
            t = tag.get_text(strip=True)
            if t and len(t) < 200:
                chapter_title = t
                break

        if not chapter_title:
            chapter_title = f"章节 {len(chapters) + 1}"

        chapters.append({
            "title": chapter_title,
            "content": text,
            "book": book_title,
        })

    return chapters


def _resolve_book_id(filename: str) -> Optional[str]:
    """根据文件名匹配 config 中定义的 book_id"""
    fname_lower = filename.lower()
    from config import settings
    for skill_id, keywords in settings._skill_epub_map.items():
        if any(kw.lower() in fname_lower for kw in keywords):
            return skill_id
    return None


def ingest_epubs(force_reindex: bool = False):
    """将所有 EPUB 文件导入 Chroma（含 book_id 元数据用于按书过滤）"""
    from db import _get_embed_fn, get_chroma_client

    embed_fn = _get_embed_fn()
    client = get_chroma_client()

    if force_reindex:
        try:
            client.delete_collection(settings.collection_name + "_epub")
        except Exception:
            pass

    collection = client.get_or_create_collection(
        name=settings.collection_name + "_epub",
        embedding_function=embed_fn,
        metadata={"hnsw:space": "cosine"},
    )

    epub_pattern = os.path.join(settings.epub_dir, "*.epub")
    files = sorted(glob.glob(epub_pattern))

    if not files:
        return

    all_docs = []
    all_ids = []
    all_metas = []
    idx = 0

    for fpath in files:
        fname = os.path.splitext(os.path.basename(fpath))[0]
        logger.info(f"解析: {fname}.epub")

        try:
            chapters = extract_epub_chapters(fpath)
        except Exception as e:
            logger.error(f"  解析失败: {e}")
            continue

        book_id = _resolve_book_id(fname) or f"epub_{idx}"
        logger.info(f"  共 {len(chapters)} 章, book_id={book_id}")

        for ch in chapters:
            all_docs.append(ch["content"])
            all_ids.append(f"epub_{idx}")
            all_metas.append({
                "book": ch["book"],
                "chapter": ch["title"],
                "source": "epub",
                "book_id": book_id,
            })
            idx += 1

    if not all_docs:
        return

    total = len(all_docs)
    logger.info(f"共 {total} 章，写入 Chroma...")

    batch_size = 16
    for i in range(0, total, batch_size):
        end = min(i + batch_size, total)
        collection.add(
            ids=all_ids[i:end],
            documents=all_docs[i:end],
            metadatas=all_metas[i:end],
        )

    logger.info(f"EPUB 导入完成！{total} 章")


def search_epub(query: str, top_k: int = 3, filter_book_id: Optional[str] = None) -> List[dict]:
    """检索 EPUB 整书知识（可指定书）"""
    from db import _get_embed_fn, get_chroma_client

    embed_fn = _get_embed_fn()
    client = get_chroma_client()

    try:
        collection = client.get_collection(
            settings.collection_name + "_epub",
            embedding_function=embed_fn,
        )
    except Exception:
        return []

    where_filter = None
    if filter_book_id:
        where_filter = {"book_id": filter_book_id}

    results = collection.query(
        query_texts=[query],
        n_results=min(top_k, collection.count()),
        where=where_filter,
    )

    sources = []
    if results["ids"] and results["ids"][0]:
        for i in range(len(results["ids"][0])):
            sources.append({
                "book": results["metadatas"][0][i]["book"],
                "chapter": results["metadatas"][0][i]["chapter"],
                "content": results["documents"][0][i],
                "score": results["distances"][0][i] if results.get("distances") else 0,
                "source": "epub",
            })
    return sources
