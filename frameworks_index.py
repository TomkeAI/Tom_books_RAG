"""框架摘要索引 — 自动从 SKILL.md 和 EPUB 元数据构建"""
import os
import re
import logging
from typing import List, Optional

from config import settings
from db import _get_embed_fn, get_chroma_client

logger = logging.getLogger(__name__)


def _auto_discover_frameworks() -> dict:
    """自动扫描 skills 目录，从 SKILL.md 提取框架"""

    # 从 skill 目录发现的框架
    frameworks = {}

    for entry in os.listdir(settings.books_base):
        skill_dir = os.path.join(settings.books_base, entry)
        skill_md = os.path.join(skill_dir, "SKILL.md")
        chapters = os.path.join(skill_dir, "chapters")
        if not (os.path.isdir(skill_dir) and os.path.isfile(skill_md) and os.path.isdir(chapters)):
            continue

        with open(skill_md, "r", encoding="utf-8") as f:
            content = f.read()

        # 去掉 YAML 头部
        body = re.sub(r"^---\n.*?\n---\n", "", content, flags=re.DOTALL)

        # 提取框架部分
        sections = []
        for pat in [
            r"(?:#+?\s*(?:Core Frameworks|Frameworks Introduced|Mental Models))",
            r"(?:#+?\s*(?:Key Concepts))",
            r"(?:#+?\s*(?:Key Takeaways))",
        ]:
            m = re.search(
                pat + r"(.*?)(?=#+?\s*(?:Anti-patterns|Worked Example|Chapter Index|Connects To|Scope|Supporting Files|如何|$))",
                body,
                re.DOTALL | re.IGNORECASE,
            )
            if m:
                sections.append(m.group(1).strip())

        # 提取关键词（从 SKILL.md 的 description 和框架文本）
        name_match = re.search(r'description:\s*"(.+?)"', content)
        desc = name_match.group(1) if name_match else entry

        framework_text = "\n".join(sections) if sections else body[:1500]
        keywords = desc.split("，")[0] if "，" in desc else entry

        frameworks[entry] = {
            "title": entry,  # 用 skill 目录名，config.py 会提供中文名
            "framework": framework_text[:2000],
            "keywords": desc[:300],
        }

    return frameworks


def _build_framework_docs() -> List[dict]:
    """构建框架搜索索引文档，从每本书的 config 名称和框架摘要合成"""
    fws = _auto_discover_frameworks()
    docs = []

    for book_id, _ in settings.books:
        info = fws.get(book_id, {})
        title = info.get("title", book_id)

        # 从 settings 拿更好的中文名
        for bid, bt in settings.books:
            if bid == book_id:
                title = bt
                break

        framework = info.get("framework", "")
        keywords = info.get("keywords", "")

        text = f"书名：{title}\n{framework}\n关键词：{keywords}"
        docs.append({"id": book_id, "title": title, "text": text})

    return docs


def build_framework_index(force_reindex: bool = False):
    """构建/更新框架索引"""
    embed_fn = _get_embed_fn()
    client = get_chroma_client()

    col_name = settings.collection_name + "_frameworks"

    if force_reindex:
        try:
            client.delete_collection(col_name)
        except Exception:
            pass

    collection = client.get_or_create_collection(
        name=col_name,
        embedding_function=embed_fn,
        metadata={"hnsw:space": "cosine"},
    )

    if collection.count() > 0 and not force_reindex:
        return

    docs = _build_framework_docs()
    if not docs:
        logger.warning("未发现任何书籍框架")
        return

    collection.add(
        ids=[d["id"] for d in docs],
        documents=[d["text"] for d in docs],
        metadatas=[{"title": d["title"]} for d in docs],
    )
    logger.info(f"框架索引构建完成: {len(docs)} 本书")


def identify_book(query: str) -> List[dict]:
    """判断问题最相关的书籍"""
    embed_fn = _get_embed_fn()
    client = get_chroma_client()

    col_name = settings.collection_name + "_frameworks"
    try:
        collection = client.get_collection(col_name, embedding_function=embed_fn)
    except Exception:
        return []

    results = collection.query(
        query_texts=[query],
        n_results=1,
    )

    matches = []
    if results["ids"] and results["ids"][0]:
        for i in range(len(results["ids"][0])):
            matches.append({
                "book_id": results["ids"][0][i],
                "title": results["metadatas"][0][i]["title"],
                "score": results["distances"][0][i],
            })
    return matches
