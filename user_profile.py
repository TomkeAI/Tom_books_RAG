"""用户兴趣画像 — 从对话历史提取偏好，注入后续问答上下文"""
import os
import json
import time
import logging
from typing import Optional

logger = logging.getLogger(__name__)

PROFILE_FILE = os.path.join(os.path.dirname(__file__), "data", "user_profile.json")

# 预定义的主题关键词，用于快速匹配兴趣
_TOPIC_KEYWORDS = {
    "投资理财": ["投资", "股票", "基金", "价值投资", "段永平", "芒格", "巴菲特", "仓位", "买入", "卖出",
                "估值", "财报", "企业", "商业模式", "护城河", "ROE", "现金流"],
    "心理学与认知": ["认知偏误", "系统1", "系统2", "卡尼曼", "损失厌恶", "锚定", "可得性启发",
                  "代表性启发", "前景理论", "框架效应"],
    "斯多葛哲学": ["斯多葛", "控制二分法", "沉思录", "奥勒留", "塞涅卡", "爱比克泰德", "memento mori",
                "amor fati", "负面可视化", "斯多葛挑战"],
    "人际关系": ["关系", "恋爱", "亲密关系", "沟通", "rapport", "影响力", "爱情", "婚姻"],
    "欲望与动机": ["欲望", "渴望", "动机", "on desire", "身份焦虑", "status anxiety"],
    "习惯与行动": ["习惯", "原子习惯", "自律", "意志力", "拖延", "执行", "行动"],
    "人生哲学": ["意义", "幸福", "die with zero", "flow", "心流", "美好生活", "guide to good life",
              "活出生命的意义", "弗兰克尔"],
    "进化与人性": ["自私的基因", "道金斯", "进化", "利他", "meme", "模因"],
}


def _load_profile() -> dict:
    """加载用户画像"""
    if not os.path.exists(PROFILE_FILE):
        return {
            "interests": [],
            "recent_topics": [],
            "conversation_count": 0,
            "last_updated": time.strftime("%Y-%m-%d %H:%M:%S"),
        }
    try:
        with open(PROFILE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _save_profile(profile: dict):
    """保存用户画像"""
    os.makedirs(os.path.dirname(PROFILE_FILE), exist_ok=True)
    with open(PROFILE_FILE, "w", encoding="utf-8") as f:
        json.dump(profile, f, ensure_ascii=False, indent=2)


def _detect_topics(text: str) -> list:
    """从文本中检测匹配的主题"""
    text_lower = text.lower()
    matched = []
    for topic, keywords in _TOPIC_KEYWORDS.items():
        for kw in keywords:
            if kw.lower() in text_lower:
                matched.append(topic)
                break
    return matched


def update_profile(query: str, conversation_id: Optional[str] = None):
    """根据用户的提问更新兴趣画像"""
    profile = _load_profile()
    profile["conversation_count"] = profile.get("conversation_count", 0) + 1
    profile["last_updated"] = time.strftime("%Y-%m-%d %H:%M:%S")

    # 检测本次问题的主题
    topics = _detect_topics(query)
    all_interests = profile.get("interests", [])
    for t in topics:
        if t not in all_interests:
            all_interests.append(t)

    # 按出现次数排序
    profile["interests"] = all_interests

    # 记录最近主题（最近 10 条）
    recent = profile.get("recent_topics", [])
    recent.append({
        "query": query[:100],
        "topics": topics,
        "time": time.strftime("%Y-%m-%d %H:%M"),
    })
    profile["recent_topics"] = recent[-10:]

    _save_profile(profile)

    if topics:
        logger.debug(f"兴趣检测: {topics}")


def get_profile_prompt() -> str:
    """获取用户画像的提示文本，注入系统提示词"""
    profile = _load_profile()
    interests = profile.get("interests", [])
    count = profile.get("conversation_count", 0)
    recent = profile.get("recent_topics", [])
    style = profile.get("user_style", "")

    if count < 3:
        return ""

    # 计算各兴趣的提及次数
    topic_count = {}
    for r in recent:
        for t in r.get("topics", []):
            topic_count[t] = topic_count.get(t, 0) + 1

    # 按热度排序
    hot_topics = sorted(topic_count.items(), key=lambda x: -x[1])

    parts = [f"## 用户背景（共 {count} 轮对话）"]
    if style:
        parts.append(f"用户风格偏好：{style}")
    if hot_topics:
        topics_desc = "、".join(f"{t}({n}次)" for t, n in hot_topics[:5])
        parts.append(f"近期关注领域：{topics_desc}")
    if recent:
        recent_queries = [r["query"][:60] for r in recent[-4:]]
        parts.append("最近提过的问题：")
        for q in recent_queries:
            parts.append(f"- {q}")

    parts.append("\n请记住这些背景信息，回答时体现出你认识这位用户——你了解他感兴趣的方向、偏好的分析风格。")
    return "\n".join(parts)


def update_user_style(style: str):
    """手动更新用户风格描述"""
    profile = _load_profile()
    profile["user_style"] = style
    _save_profile(profile)


def get_interests() -> list:
    """获取用户的兴趣列表"""
    return _load_profile().get("interests", [])
