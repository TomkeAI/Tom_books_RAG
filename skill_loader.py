"""SKILL.md 框架加载器 — 自动发现并缓存"""
import os
import re
import logging
from typing import Optional

logger = logging.getLogger(__name__)

SKILL_DIR = os.path.expanduser("~/.codebuddy/skills")
_cache: dict[str, str] = {}


def _list_skill_books() -> list[str]:
    """自动列出所有有 SKILL.md + chapters 的技能目录"""
    books = []
    for entry in os.listdir(SKILL_DIR):
        skill_md = os.path.join(SKILL_DIR, entry, "SKILL.md")
        chapters = os.path.join(SKILL_DIR, entry, "chapters")
        if os.path.isfile(skill_md) and os.path.isdir(chapters):
            books.append(entry)
    return books


def load_book_framework(book_id: str) -> Optional[str]:
    """加载指定书的 SKILL.md 框架摘要（缓存）"""
    if book_id in _cache:
        return _cache[book_id]

    skill_file = os.path.join(SKILL_DIR, book_id, "SKILL.md")
    if not os.path.exists(skill_file):
        return None

    with open(skill_file, "r", encoding="utf-8") as f:
        content = f.read()

    body = re.sub(r"^---\n.*?\n---\n", "", content, flags=re.DOTALL)

    sections = []
    for pat, label in [
        (r"#+?\s*(?:Core Frameworks|Frameworks Introduced)", "核心框架"),
        (r"#+?\s*Mental Models", "思维模型"),
        (r"#+?\s*Key Concepts", "关键概念"),
        (r"#+?\s*Key Takeaways", "核心要点"),
    ]:
        m = re.search(
            pat + r"(.*?)(?=#+?\s*(?:Anti-patterns|Worked Example|Chapter Index|Connects To|Scope|Supporting Files|如何|$))",
            body,
            re.DOTALL | re.IGNORECASE,
        )
        if m:
            text = m.group(1).strip()
            if text and len(text) > 50:
                sections.append(f"## {label}\n{text[:3000]}")

    # 附加 cheatsheet
    cs_path = os.path.join(SKILL_DIR, book_id, "cheatsheet.md")
    if os.path.exists(cs_path):
        with open(cs_path, "r", encoding="utf-8") as f:
            cs = f.read()
        sections.append("## 速查表\n" + cs[:2000])

    result = "\n\n".join(sections) if sections else body[:3000]
    _cache[book_id] = result
    return result


def get_framework_prompt(book_id: str) -> Optional[str]:
    """获取可直接插入系统提示词的框架文本"""
    fw = load_book_framework(book_id)
    if not fw:
        return None
    # 从 config 找中文名
    from config import settings
    title = book_id
    for bid, bt in settings.books:
        if bid == book_id:
            title = bt
            break
    return f"以下是《{title}》的框架摘要，请优先以此作为回答的知识骨架：\n\n{fw}"


def load_all_frameworks() -> dict[str, str]:
    """预加载所有书的框架摘要"""
    result = {}
    for book_id in _list_skill_books():
        fw = load_book_framework(book_id)
        if fw:
            result[book_id] = fw
    logger.info(f"已预加载 {len(result)} 本书的框架摘要")
    return result
