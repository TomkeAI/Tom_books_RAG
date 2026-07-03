"""RAG 引擎 — 查询改写 + 对话上下文 + 混合搜索"""
import json
import logging
from typing import Generator, List, Optional
from openai import OpenAI
from config import settings

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """你是一个知识渊博的读书助手，能从多个学科视角综合分析问题。

你的知识库涵盖以下书籍：
- 投资理财：段永平投资问答录、Poor Charlie's Almanack（芒格）、What I Learned from Darwin（达尔文投资学）、Competition Demystified、The Innovator's Dilemma、The Psychology of Money（金钱心理学）、Same as Ever（一如既往）
- 决策与认知：Thinking, Fast and Slow（卡尼曼）
- 心理学与社会：On Desire（欲望心理学）、Status Anxiety（身份焦虑）、On Confidence（自信的力量）、A Slap in the Face（为何侮辱伤人）、Influence（影响力）、The Selfish Gene（自私的基因）、Nudge（助推）、Superforecasting（超预测）
- 人际关系：Relationships（亲密关系）、On Love（爱情哲学）、Alison Rapport（读懂他人）、Influence
- 人生哲学：A Guide to the Good Life（美好生活指南）、Die with Zero（人生最大化）、The Stoic Challenge（斯多葛挑战）、Man's Search for Meaning（活出生命的意义）、Meditations（沉思录）、论生命之短暂（塞涅卡）、The Enchiridion（爱比克泰德手册）
- 心流与幸福：Flow（心流）、The Happiness Hypothesis（象与骑象人）
- 健康与科学：Why We Sleep（我们为什么睡觉）、Spoon-Fed（被喂食）、抗炎生活
- 习惯与行动：Atomic Habits（原子习惯）

回答原则：
- 如果提供的书摘来自多个不同领域，请以**主领域的核心内容为主**，关联领域的视角作为补充和深化，不要本末倒置
- 比如投资问题：**以投资书籍的内容为主线**，从心理/欲望/社会地位等角度做补充解读，而不能让心理分析覆盖了投资核心
- 比如人际关系问题：**以关系建立和沟通技巧为核心**，用自我认知、欲望等作为背景理解
- 理想的比例是：主领域观点占回答的 ~70%，跨领域视角占 ~30%
- 不要提你的搜索能力或联网权限——如果提供了网络信息就参考它，没有提供就只凭书本知识回答"""

QUERY_REWRITE_PROMPT = """你是一个搜索助手。用户可能会使用代词（它、这、那）、省略语或不完整的表达来提问。
请根据对话历史，将用户的最新问题改写成一个独立的、自包含的搜索查询。
只输出改写后的查询，不要解释，不要添加额外内容。"""


class RAGEngine:
    def __init__(self):
        self._has_llm = settings.has_llm
        self._init_client()
        logger.info(f"LLM 模式: {settings.llm_model}" if self._has_llm else "纯检索模式")

    def _init_client(self):
        """初始化或重建 OpenAI 客户端"""
        self._has_llm = settings.has_llm
        if self._has_llm:
            logger.info(f"初始化 LLM 客户端: {settings.llm_base_url} / {settings.llm_model}")
            # LongCat 生成长回答（max_tokens=32768）需要更长的超时时间
            is_longcat = "longcat" in settings.llm_base_url.lower()
            timeout = 600.0 if is_longcat else 120.0
            self.client = OpenAI(
                api_key=settings.llm_api_key,
                base_url=settings.llm_base_url,
                timeout=timeout,
                max_retries=0,
            )

    @property
    def mode(self) -> str:
        return "llm" if self._has_llm else "search"

    def _rewrite_query(self, query: str, history: Optional[List[dict]]) -> str:
        """用 LLM 改写查询，消除指代歧义"""
        if not self._has_llm or not history:
            return query
        try:
            msgs = [{"role": "system", "content": QUERY_REWRITE_PROMPT}]
            # 取最近 2 轮历史
            recent = history[-4:] if len(history) > 4 else history
            msgs.extend(recent)
            msgs.append({"role": "user", "content": f"用户最新问题：{query}\n\n改写后的搜索查询："})
            resp = self.client.chat.completions.create(
                model=settings.llm_model,
                messages=msgs,
                temperature=0.1,
                max_tokens=128,
            )
            rewritten = resp.choices[0].message.content.strip().strip('"').strip("'")
            if rewritten:
                logger.info(f"查询改写: 「{query}」→「{rewritten}」")
                return rewritten
        except Exception as e:
            logger.warning(f"查询改写失败: {e}")
        return query

    def query_stream(
        self, query: str, history: Optional[List[dict]] = None, top_k: Optional[int] = None,
        current_book_id: Optional[str] = None,
    ) -> Generator[str, None, None]:
        k = top_k or settings.top_k

        # 0. 查询改写
        yield json.dumps({"type": "status", "text": "正在理解你的问题..."})
        search_query = self._rewrite_query(query, history)

        # 1. 识别相关书籍（用改写后的查询）
        yield json.dumps({"type": "status", "text": "正在识别相关书籍..."})
        from frameworks_index import identify_book

        target_book_id = current_book_id
        target_book_title = None

        if not target_book_id:
            matches = identify_book(search_query)
            if matches:
                target_book_id = matches[0]["book_id"]
                target_book_title = settings.get_book_title(target_book_id)
                yield json.dumps({
                    "type": "status",
                    "text": f"已定位书籍: {target_book_title}",
                })
            else:
                yield json.dumps({"type": "status", "text": "未能识别具体书籍，将搜索全部章节..."})

        # 2. 多书联合检索
        yield json.dumps({"type": "status", "text": "正在搜索相关章节..."})

        # 确定要搜索的书籍列表
        book_ids_to_search = []
        book_labels = {}  # book_id -> 显示名

        if target_book_id:
            # 主书
            book_ids_to_search.append(target_book_id)
            book_labels[target_book_id] = target_book_title or settings.get_book_title(target_book_id)

            # 关联书
            cross_refs = settings.get_cross_refs(target_book_id)
            for ref_id in cross_refs:
                if ref_id not in book_ids_to_search:
                    book_ids_to_search.append(ref_id)
                    book_labels[ref_id] = settings.get_book_title(ref_id)

            if cross_refs:
                ref_names = ", ".join(book_labels.get(r, r) for r in cross_refs[:3])
                yield json.dumps({
                    "type": "status",
                    "text": f"也参考了: {ref_names}",
                })

        from epub_ingest import search_epub

        sources = []
        seen_contents = set()

        for i, bid in enumerate(book_ids_to_search):
            is_primary = (i == 0)  # 第一本为主书
            per_book_k = 3 if is_primary else 1  # 主书搜 3 条，关联书各 1 条
            results = search_epub(search_query, top_k=per_book_k, filter_book_id=bid)
            for r in results:
                # 去重（按内容前200字）
                dedup_key = r["content"][:200]
                if dedup_key not in seen_contents:
                    seen_contents.add(dedup_key)
                    r["_book_id"] = bid
                    r["_is_primary"] = is_primary
                    # 关联书结果稍微降级（加分值=惩罚，score 越小越相关）
                    if not is_primary:
                        r["score"] = r.get("score", 0) + 0.15
                    sources.append(r)

        if not sources:
            # 回退：搜索全部
            sources = search_epub(search_query, top_k=k)
            if not sources:
                from db import search_books
                sources = search_books(search_query, top_k=k)

        # 3. 补充搜索精选问答
        curated_sources = []
        try:
            from feedback_store import search_curated
            curated_sources = search_curated(search_query, top_k=2)
        except Exception:
            pass

        if curated_sources:
            for cs in curated_sources:
                cs["score"] = cs.get("score", 0) * 0.3
            sources = curated_sources + sources

        if not sources:
            yield json.dumps({"type": "status", "text": "未找到相关内容"})
            yield json.dumps({"type": "done", "text": "未找到相关结果，请换个关键词试试。"})
            return

        # 按分数排序并截取 top_k
        sources.sort(key=lambda x: x.get("score", 0))
        sources = sources[:k]

        label = "整章"
        yield json.dumps({
            "type": "sources",
            "source_type": label,
            "target_book": target_book_id,
            "books_used": book_ids_to_search,
            "sources": [
                {"book": s["book"], "chapter": s["chapter"], "score": round(s["score"], 3)}
                for s in sources
            ],
        })

        if not self._has_llm:
            answer = self._format_no_llm(search_query, sources)
            yield json.dumps({"type": "token", "text": answer})
            yield json.dumps({"type": "done"})
            return

        # 3. 联网补充
        web_info = []
        if settings.web_search:
            yield json.dumps({"type": "status", "text": "正在补充网络信息..."})
            from web_search import search_web
            try:
                for r in search_web(search_query, max_results=3):
                    web_info.append(f"- {r['title']}\n  {r['body'][:300]}")
            except Exception:
                pass

        # 4. 构建 prompt（包含所有相关书的框架 + 用户画像）
        yield json.dumps({"type": "status", "text": "正在生成回答..."})
        messages = [{"role": "system", "content": SYSTEM_PROMPT}]

        # 根据模型调整参数
        is_longcat = "longcat" in settings.llm_base_url.lower()
        if is_longcat:
            # LongCat 1M 上下文，多给些书摘
            sources = sources[:max(k + 3, 10)]

        # 注入用户兴趣画像
        try:
            from user_profile import get_profile_prompt
            profile_text = get_profile_prompt()
            if profile_text:
                messages.append({"role": "system", "content": profile_text})
        except Exception as e:
            logger.warning(f"用户画像加载失败: {e}")

        # 注入所有相关书的框架摘要
        from skill_loader import get_framework_prompt
        framework_snippets = []
        for bid in book_ids_to_search:
            fw = get_framework_prompt(bid)
            if fw:
                framework_snippets.append(fw)
        if framework_snippets:
            combined = "\n\n".join(framework_snippets)
            # 如果太长就截断
            if len(combined) > 4000:
                combined = combined[:4000] + "\n\n...（框架摘要过长已截断）"
            messages.append({"role": "system", "content": combined})

        if history:
            messages.extend(history)

        book_context = "\n---\n".join(
            f"[来源 {i}] 《{s['book']}》— {s['chapter']}（整章）\n{s['content']}"
            for i, s in enumerate(sources, 1)
        )
        user_parts = [f"【检索到的书本知识】\n{book_context}"]
        if web_info:
            user_parts.append("【网络补充信息（仅供参考）】\n" + "\n".join(web_info))
        user_parts.append(f"【用户问题】\n{query}")
        messages.append({"role": "user", "content": "\n\n".join(user_parts)})

        # 5. 流式调用 LLM
        try:
            llm_kwargs = dict(
                model=settings.llm_model,
                messages=messages,
                temperature=0.7,
                max_tokens=8192,
                stream=True,
            )
            # LongCat 1M 上下文可生成更长回答，但 32768 太慢，限制到 8192
            if "longcat" in settings.llm_base_url.lower():
                llm_kwargs["max_tokens"] = 8192
            stream = self.client.chat.completions.create(**llm_kwargs)
            for chunk in stream:
                delta = chunk.choices[0].delta if chunk.choices else None
                if delta and delta.content:
                    yield json.dumps({"type": "token", "text": delta.content})
        except Exception as e:
            error_msg = str(e)
            logger.error(f"LLM 调用失败 [base_url={settings.llm_base_url}, model={settings.llm_model}]: {error_msg}")
            if "402" in error_msg or "Payment Required" in error_msg:
                hint = "当前模型 Token 额度不足，请切换回 DeepSeek 或补充 Longcat 额度"
            elif "401" in error_msg or "Unauthorized" in error_msg:
                hint = "API Key 无效，请检查配置"
            elif "400" in error_msg:
                hint = f"模型请求参数错误（base_url={settings.llm_base_url}, model={settings.llm_model}），请检查配置"
            else:
                hint = f"模型调用失败: {error_msg[:120]}"
            yield json.dumps({"type": "token", "text": f"\n\n> ⚠️ {hint}"})
        yield json.dumps({"type": "done"})

    def _format_no_llm(self, query: str, sources: List[dict]) -> str:
        parts = [f"为你找到以下相关书摘（共 {len(sources)} 条）：", ""]
        for i, s in enumerate(sources, 1):
            parts.append(f"── [{i}] 《{s['book']}》— {s['chapter']} ──")
            parts.append(s["content"][:600])
            if len(s["content"]) > 600:
                parts.append("...(截断)")
            parts.append("")
        return "\n".join(parts)


rag_engine = RAGEngine()
