"""FastAPI 入口"""
import logging
import os
import threading
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from config import settings
from models import ChatRequest, ChatResponse, SearchRequest, SearchResponse, BookInfo, FeedbackRequest

# 设置 API Key（当 .env 加载失败时兜底）
if not settings.llm_api_key:
    settings.llm_api_key = "sk-f961a2f189a041aea517db9b006a0c42"
if not settings.longcat_api_key:
    settings.longcat_api_key = "ak_2Nh1rC0R63rr6Co2YH9ye28r7pE2H"
from chat_memory import chat_memory
from rag_engine import rag_engine
from db import ingest_books
from frameworks_index import build_framework_index

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

DATA_DIR = os.path.dirname(os.path.abspath(__file__))
STATIC_DIR = os.path.join(DATA_DIR, "static")

_ingest_done = False


@asynccontextmanager
async def lifespan(app: FastAPI):
    def _bg_ingest():
        global _ingest_done
        logger.info("后台导入书本知识到向量数据库...")
        ingest_books(force_reindex=False)
        build_framework_index()
        logger.info(f"导入完成 | 模式: {rag_engine.mode}")

    t = threading.Thread(target=_bg_ingest, daemon=True)
    t.start()
    logger.info("服务已就绪（首次启动后台正在导入数据）")
    yield
    logger.info("服务关闭")


app = FastAPI(
    title="Books RAG 读书助手",
    description="基于 8 本经典书籍的 RAG 问答系统",
    version="1.0.0",
    lifespan=lifespan,
)

os.makedirs(STATIC_DIR, exist_ok=True)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/", response_class=HTMLResponse)
async def index():
    index_path = os.path.join(STATIC_DIR, "index.html")
    if os.path.exists(index_path):
        with open(index_path, "r", encoding="utf-8") as f:
            content = f.read()
        from fastapi.responses import Response
        return Response(
            content=content,
            media_type="text/html",
            headers={"Cache-Control": "no-store, must-revalidate", "Pragma": "no-cache"},
        )
    return HTMLResponse("<h1>Books RAG</h1>")


@app.get("/api/health")
async def health():
    return {
        "status": "ok",
        "mode": rag_engine.mode,
        "books_count": len(settings.books),
        "has_llm": settings.has_llm,
        "model": settings.llm_model,
        "provider": settings._current_provider,
    }


@app.post("/api/model/switch")
async def switch_model(req: Request):
    body = await req.json()
    provider = body.get("provider", "deepseek")
    result = settings.switch_model(provider)
    if "error" in result:
        from fastapi.responses import JSONResponse
        return JSONResponse(status_code=400, content=result)
    # 热更新 RAG 引擎的客户端配置（不需要重建，引用仍有效）
    from rag_engine import rag_engine as re
    re._init_client()
    logger.info(f"已切换模型: {result}")
    return result


@app.get("/api/books", response_model=list[BookInfo])
async def list_books():
    import glob
    books = []
    for skill_dir, title in settings.books:
        pattern = os.path.join(settings.books_base, skill_dir, "chapters", "*.md")
        files = glob.glob(pattern)
        books.append(BookInfo(
            id=skill_dir,
            title=title,
            chapter_count=len(files),
        ))
    return books


@app.post("/api/chat/stream")
async def chat_stream(req: ChatRequest):
    """流式对话接口 — threading 生产 + asyncio 消费（彻底分离）"""
    import asyncio, json, threading
    from queue import Queue, Empty
    from rag_engine import rag_engine

    conv_id = req.conversation_id
    if not conv_id or conv_id not in chat_memory._sessions:
        conv_id = chat_memory.create_conversation()

    history = chat_memory.get_history_for_llm(conv_id)
    q = Queue()
    done = threading.Event()

    # 获取当前对话的"目标书"上下文
    conv_ctx = chat_memory._sessions.get(conv_id, None)
    current_book = getattr(conv_ctx, '_current_book', None) if conv_ctx else None

    full_answer = []
    _last_sources_list = []

    def _produce():
        nonlocal _last_sources_list
        try:
            q.put(json.dumps({"type": "conv", "id": conv_id}))
            for evt in rag_engine.query_stream(
                query=req.query, history=history, top_k=req.top_k,
                current_book_id=current_book,
            ):
                parsed = json.loads(evt)
                if parsed.get("type") == "sources":
                    _last_sources_list = [s for s in parsed.get("sources", [])]
                q.put(evt)
        finally:
            q.put(None)
            done.set()

    threading.Thread(target=_produce, daemon=True).start()

    async def event_stream():
        nonlocal full_answer
        while True:
            # 批量取数据，最多等 0.05 秒
            try:
                evt = q.get(timeout=0.05)
            except Empty:
                if done.is_set():
                    break
                continue

            if evt is None:
                # 生产者已结束，清空剩余
                break

            parsed = json.loads(evt)
            if parsed["type"] == "token":
                full_answer.append(parsed["text"])
            yield f"data: {evt}\n\n"

        chat_memory.add_message(conv_id, "user", req.query)
        # 保存来源信息用于历史点赞
        source_books_meta = list(set(
            s.get("book", "") for s in _last_sources_list if s.get("book")
        ))
        answer_text = "".join(full_answer)
        chat_memory.add_message(conv_id, "assistant", answer_text,
                                source_books=source_books_meta, question=req.query)

        # 更新用户兴趣画像（轻量级，不改变检索）
        try:
            from user_profile import update_profile
            update_profile(req.query, conv_id)
        except Exception:
            pass

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.post("/api/chat", response_model=ChatResponse)
async def chat(req: ChatRequest):
    conv_id = req.conversation_id
    if not conv_id or conv_id not in chat_memory._sessions:
        conv_id = chat_memory.create_conversation()

    history = chat_memory.get_history_for_llm(conv_id)
    answer, sources = rag_engine.query(
        query=req.query,
        history=history,
        top_k=req.top_k,
    )

    chat_memory.add_message(conv_id, "user", req.query)
    chat_memory.add_message(conv_id, "assistant", answer)

    return ChatResponse(
        answer=answer,
        conversation_id=conv_id,
        sources=sources,
    )


@app.get("/api/conversations")
async def list_conversations():
    return chat_memory.list_conversations()


@app.get("/api/conversations/{conversation_id}")
async def get_conversation(conversation_id: str):
    """获取指定对话的完整消息"""
    return chat_memory.get_history_messages(conversation_id)


@app.delete("/api/conversations/{conversation_id}")
async def delete_conversation(conversation_id: str):
    chat_memory.delete_conversation(conversation_id)
    return {"status": "deleted", "conversation_id": conversation_id}


@app.delete("/api/conversations")
async def clear_conversations():
    chat_memory.clear_all()
    return {"status": "cleared"}


@app.post("/api/search", response_model=SearchResponse)
async def search(req: SearchRequest):
    from db import search_books
    results = search_books(req.query, top_k=req.top_k)
    return SearchResponse(
        results=[{
            "book": r["book"],
            "chapter": r["chapter"],
            "content": r["content"],
            "score": round(r["score"], 4),
        } for r in results],
        total=len(results),
    )


@app.post("/api/reindex")
async def reindex():
    ingest_books(force_reindex=True)
    from epub_ingest import ingest_epubs
    ingest_epubs(force_reindex=True)
    from pdf_ingest import ingest_pdfs
    ingest_pdfs(force_reindex=True)
    build_framework_index(force_reindex=True)
    return {"status": "ok", "message": "全部重新索引完成"}


@app.post("/api/reindex/epub")
async def reindex_epub():
    from epub_ingest import ingest_epubs
    from pdf_ingest import ingest_pdfs
    ingest_epubs(force_reindex=True)
    ingest_pdfs(force_reindex=True)
    return {"status": "ok", "message": "EPUB + PDF 重新索引完成"}


@app.post("/api/feedback")
async def feedback(req: FeedbackRequest):
    """保存点赞的问答对"""
    from feedback_store import save_feedback, count_feedback
    result = save_feedback(
        question=req.question,
        answer=req.answer,
        source_books=req.source_books,
    )
    return {"status": "ok", **result}


@app.post("/api/feedback/toggle")
async def toggle_feedback(req: FeedbackRequest):
    """切换点赞/取消状态"""
    from feedback_store import is_liked, save_feedback, remove_feedback, count_feedback
    liked_before = is_liked(question=req.question, answer=req.answer)
    logger.info(f"TOGGLE: q={req.question[:60]}... a={req.answer[:60]}... is_liked_before={liked_before}")
    if liked_before:
        removed = remove_feedback(question=req.question, answer=req.answer)
        action = "unliked"
        logger.info(f"TOGGLE: remove_feedback returned {removed}, action={action}")
    else:
        r = save_feedback(question=req.question, answer=req.answer, source_books=req.source_books)
        action = "liked"
        logger.info(f"TOGGLE: save_feedback returned {r}, action={action}")
    total = count_feedback()
    logger.info(f"TOGGLE: total after={total}")
    return {"status": action, "total": total, "action": action}


@app.post("/api/feedback/dislike")
async def dislike_feedback(req: FeedbackRequest):
    """差评"""
    from feedback_store import dislike_feedback, count_feedback
    count = dislike_feedback(
        question=req.question, answer=req.answer,
        source_books=req.source_books,
    )
    return {"status": "ok", "disliked_count": count}


@app.post("/api/feedback/check")
async def feedback_check(req: FeedbackRequest):
    """检查某条问答是否已点赞（使用统一的 is_liked）"""
    from feedback_store import is_liked
    return {"liked": is_liked(question=req.question, answer=req.answer)}


@app.get("/api/feedback/count")
async def feedback_count():
    """获取精选问答总数"""
    from feedback_store import count_feedback
    return {"count": count_feedback()}
