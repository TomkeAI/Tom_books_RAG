"""Pydantic 数据模型"""
from pydantic import BaseModel, Field
from typing import List, Optional


class Message(BaseModel):
    """单条对话消息"""
    role: str = Field(..., description="user 或 assistant")
    content: str = Field(..., description="消息内容")


class ChatRequest(BaseModel):
    """对话请求"""
    query: str = Field(..., description="用户提问", max_length=5000)
    conversation_id: Optional[str] = Field(None, description="对话 ID，留空创建新对话")
    top_k: Optional[int] = Field(None, description="检索文档数量", ge=1, le=20)


class ChatResponse(BaseModel):
    """对话响应"""
    answer: str = Field(..., description="LLM 回答")
    conversation_id: str = Field(..., description="对话 ID")
    sources: List[dict] = Field(default_factory=list, description="引用来源")


class Source(BaseModel):
    """检索到的来源文档"""
    book: str = Field(..., description="书名")
    chapter: str = Field(..., description="章节标题")
    content: str = Field(..., description="片段内容")
    score: float = Field(..., description="相似度分数")


class BookInfo(BaseModel):
    """书本信息"""
    id: str = Field(..., description="唯一标识")
    title: str = Field(..., description="书名")
    chapter_count: int = Field(..., description="章节数量")


class ConversationSummary(BaseModel):
    """对话概要"""
    conversation_id: str = Field(..., description="对话 ID")
    message_count: int = Field(..., description="消息数")
    last_query: str = Field(..., description="最后一条用户消息")
    created_at: str = Field(..., description="创建时间")


class FeedbackRequest(BaseModel):
    """点赞反馈请求"""
    question: str = Field(..., description="用户的问题")
    answer: str = Field(..., description="回答内容")
    source_books: List[str] = Field(default_factory=list, description="引用来源的书名")
    conversation_id: Optional[str] = Field(None, description="对话 ID")


class SearchRequest(BaseModel):
    """知识检索请求（独立于对话）"""
    query: str = Field(..., description="搜索关键词")
    top_k: Optional[int] = Field(5, description="返回结果数")


class SearchResponse(BaseModel):
    """知识检索响应"""
    results: List[Source] = Field(default_factory=list, description="检索结果")
    total: int = Field(0, description="结果总数")
