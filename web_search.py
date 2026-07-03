"""联网搜索模块 — 博查 AI 搜索（国内网络优化）"""
import logging
import os
from typing import List
import requests

logger = logging.getLogger(__name__)

API_KEY = os.getenv("BOCHA_API_KEY", "")
# 如果 config 里有，优先用 config 的
try:
    from config import settings
    if settings.bocha_api_key:
        API_KEY = settings.bocha_api_key
except ImportError:
    pass
API_URL = "https://api.bochaai.com/v1/web-search"


def search_web(query: str, max_results: int = 3) -> List[dict]:
    """博查搜索——国内专为 AI 设计的搜索 API"""
    if not API_KEY:
        logger.warning("未配置 BOCHA_API_KEY，联网搜索不可用")
        return []

    try:
        resp = requests.post(
            API_URL,
            headers={
                "Authorization": f"Bearer {API_KEY}",
                "Content-Type": "application/json",
            },
            json={
                "query": query,
                "freshness": "noLimit",
                "summary": True,
                "count": max_results,
            },
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()

        # 解析返回结果
        results = []
        webpages = (
            data.get("data", {})
            .get("webPages", {})
            .get("value", [])
        )
        for item in webpages[:max_results]:
            results.append({
                "title": item.get("name", ""),
                "body": item.get("summary", item.get("snippet", "")),
                "href": item.get("url", ""),
            })

        if results:
            logger.info(f"博查搜索到 {len(results)} 条结果")
        return results

    except Exception as e:
        logger.warning(f"博查搜索失败: {e}")
        return []
