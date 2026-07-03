"""对话状态管理 - JSON 持久化（重启不丢）"""
import json
import os
import uuid
import time
import threading
from typing import Dict, List, Optional
from models import Message

DATA_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(DATA_DIR, "data", "conversations.json")

_lock = threading.Lock()


def _load_db() -> dict:
    """从磁盘加载所有对话"""
    if not os.path.exists(DB_PATH):
        return {"sessions": {}, "created_at": {}, "last_query": {}}
    with _lock:
        try:
            with open(DB_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {"sessions": {}, "created_at": {}, "last_query": {}}


def _save_db(data: dict):
    """保存到磁盘"""
    with _lock:
        os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
        with open(DB_PATH, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=1)


class ChatMemory:
    def __init__(self, max_history: int = 20):
        self._max_history = max_history
        self._load()

    def _load(self):
        db = _load_db()
        self._sessions: Dict[str, list] = db.get("sessions", {})
        self._created_at: Dict[str, str] = db.get("created_at", {})
        self._last_query: Dict[str, str] = db.get("last_query", {})

    def _flush(self):
        _save_db({
            "sessions": self._sessions,
            "created_at": self._created_at,
            "last_query": self._last_query,
        })

    def create_conversation(self) -> str:
        cid = str(uuid.uuid4())[:8]
        self._sessions[cid] = []
        self._created_at[cid] = time.strftime("%Y-%m-%d %H:%M:%S")
        self._last_query[cid] = ""
        self._flush()
        return cid

    def add_message(self, conversation_id: str, role: str, content: str, **extras):
        if conversation_id not in self._sessions:
            raise ValueError(f"对话 {conversation_id} 不存在")
        msg = {"role": role, "content": content}
        # assistant 消息可以附带 source_books 和 question
        if extras:
            for key in ("source_books", "question"):
                if key in extras and extras[key]:
                    msg[key] = extras[key]
        self._sessions[conversation_id].append(msg)
        if role == "user":
            self._last_query[conversation_id] = content[:100]
        if len(self._sessions[conversation_id]) > self._max_history * 2:
            self._sessions[conversation_id] = self._sessions[conversation_id][-self._max_history * 2:]
        self._flush()

    def get_history(self, conversation_id: str) -> List[Message]:
        raw = self._sessions.get(conversation_id, [])
        return [Message(**m) for m in raw]

    def get_history_for_llm(self, conversation_id: str, max_pairs: int = 10) -> List[dict]:
        raw = self._sessions.get(conversation_id, [])
        recent = raw[-(max_pairs * 2):]
        return [{"role": m["role"], "content": m["content"]} for m in recent]

    def delete_conversation(self, conversation_id: str):
        self._sessions.pop(conversation_id, None)
        self._created_at.pop(conversation_id, None)
        self._last_query.pop(conversation_id, None)
        self._flush()

    def clear_all(self):
        self._sessions.clear()
        self._created_at.clear()
        self._last_query.clear()
        self._flush()

    def list_conversations(self) -> List[dict]:
        return [
            {
                "conversation_id": cid,
                "message_count": len(msgs),
                "last_query": self._last_query.get(cid, ""),
                "created_at": self._created_at.get(cid, ""),
            }
            for cid, msgs in self._sessions.items()
        ]

    def get_history_messages(self, conversation_id: str) -> List[dict]:
        """获取指定对话的所有消息（含元数据）"""
        msgs = self._sessions.get(conversation_id, [])
        result = []
        last_question = ""
        for m in msgs:
            item = {"role": m["role"], "content": m["content"]}
            if m["role"] == "user":
                last_question = m["content"]
            elif m["role"] == "assistant":
                # 如果没有保存 question（旧对话），从上下文推断
                item["question"] = m.get("question") or last_question
                item["source_books"] = m.get("source_books", [])
            result.append(item)
        return result


chat_memory = ChatMemory()
