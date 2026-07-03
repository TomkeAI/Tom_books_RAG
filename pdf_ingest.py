"""PDF 导入模块 — 按章节分割文字型 PDF"""
import os
import glob
import re
import logging
from typing import List, Optional

from config import settings

logger = logging.getLogger(__name__)


def extract_pdf_chapters(pdf_path: str) -> List[dict]:
    """从 PDF 提取文本并按章节分割"""
    try:
        from pypdf import PdfReader
    except ImportError:
        logger.error("请先安装 pypdf: pip install pypdf")
        return []

    try:
        reader = PdfReader(pdf_path)
    except Exception as e:
        logger.error(f"  无法读取 PDF: {e}")
        return []

    book_title = os.path.splitext(os.path.basename(pdf_path))[0]
    chapters = []
    current_title = "前言"
    current_pages = []
    chapter_num = 0

    # 常见章节标题模式
    chapter_patterns = [
        re.compile(r"^(?:第\s*[一二三四五六七八九十百千\d]+\s*(?:章|节|部分|篇|卷))", re.UNICODE),
        re.compile(r"^(?:Chapter|CHAPTER|Section)\s+\d+", re.UNICODE),
        re.compile(r"^(?:Part|PART)\s+[IVXLCDM\d]+", re.UNICODE),
    ]

    for page_num, page in enumerate(reader.pages):
        text = page.extract_text()
        if not text or len(text.strip()) < 20:
            continue

        lines = text.split("\n")
        first_line = lines[0].strip() if lines else ""

        # 判断是否为新章节
        is_new_chapter = False
        for pat in chapter_patterns:
            if pat.match(first_line) and len(first_line) < 100:
                is_new_chapter = True
                break

        # 全大写短标题也可能是章节
        if first_line and first_line == first_line.upper() and 5 < len(first_line) < 80:
            is_new_chapter = True

        if is_new_chapter and current_pages:
            # 保存上一章
            content = "\n\n".join(current_pages).strip()
            if len(content) > 200:
                chapters.append({
                    "title": current_title,
                    "content": content,
                })
                chapter_num += 1
            current_pages = []
            current_title = first_line[:80]

        current_pages.append(text)

    # 最后一章
    if current_pages:
        content = "\n\n".join(current_pages).strip()
        if len(content) > 200:
            chapters.append({
                "title": current_title,
                "content": content,
            })

    if not chapters:
        # 按页分割作为后备
        for i, page in enumerate(reader.pages):
            text = page.extract_text()
            if text and len(text.strip()) > 200:
                chapters.append({
                    "title": f"第 {i+1} 页",
                    "content": text,
                })

    return chapters


def _resolve_book_id(filename: str) -> Optional[str]:
    """根据文件名匹配 config 中定义的 book_id"""
    fname_lower = filename.lower()
    for skill_id, keywords in settings._skill_epub_map.items():
        if any(kw.lower() in fname_lower for kw in keywords):
            return skill_id
    return None


def ingest_pdfs(force_reindex: bool = False):
    """将所有 PDF 文件导入 Chroma"""
    from db import _get_embed_fn, get_chroma_client

    embed_fn = _get_embed_fn()
    client = get_chroma_client()

    if force_reindex:
        try:
            client.delete_collection(settings.collection_name + "_epub")
        except Exception:
            pass

    col_name = settings.collection_name + "_epub"  # 和 EPUB 用同一个集合
    collection = client.get_or_create_collection(
        name=col_name,
        embedding_function=embed_fn,
        metadata={"hnsw:space": "cosine"},
    )

    pdf_pattern = os.path.join(settings.epub_dir, "*.pdf")
    files = sorted(glob.glob(pdf_pattern))
    if not files:
        return

    # 检查哪些 PDF 已导入（按文件名去重）
    existing = set()
    try:
        existing_meta = collection.get(include=["metadatas"])
        if existing_meta and existing_meta["metadatas"]:
            for m in existing_meta["metadatas"]:
                if m and m.get("source_file"):
                    existing.add(m["source_file"])
    except Exception:
        pass

    new_chapters = []
    for fpath in files:
        fname = os.path.basename(fpath)
        if fname in existing and not force_reindex:
            logger.info(f"  {fname} 已存在，跳过")
            continue

        logger.info(f"解析 PDF: {fname}")
        chapters = extract_pdf_chapters(fpath)
        logger.info(f"  共 {len(chapters)} 章")

        fname_stem = os.path.splitext(fname)[0]
        book_id = _resolve_book_id(fname_stem) or f"pdf_{hash(fname_stem) % 10**8}"

        for ch in chapters:
            new_chapters.append({
                "content": ch["content"],
                "book": fname_stem,
                "chapter": ch["title"],
                "source": "pdf",
                "source_file": fname,
                "book_id": book_id,
            })

    if not new_chapters:
        return

    total = len(new_chapters)
    logger.info(f"写入 {total} 个 PDF 章节...")

    batch_size = 10
    for i in range(0, total, batch_size):
        batch = new_chapters[i : i + batch_size]
        collection.add(
            ids=[f"pdf_{hash(b['content']) % 10**8}" for b in batch],
            documents=[b["content"] for b in batch],
            metadatas=[{
                "book": b["book"],
                "chapter": b["chapter"],
                "source": "pdf",
                "source_file": b["source_file"],
                "book_id": b["book_id"],
            } for b in batch],
        )

    logger.info(f"PDF 导入完成: {total} 章节")
