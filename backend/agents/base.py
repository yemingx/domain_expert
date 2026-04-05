"""Base agent class and shared context."""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class Citation:
    paper_id: str = ""
    title: str = ""
    authors: str = ""
    year: int = 0
    page_start: int = 0
    page_end: int = 0
    excerpt: str = ""


@dataclass
class AgentResponse:
    content: str = ""
    citations: list[Citation] = field(default_factory=list)
    agent_type: str = ""
    metadata: dict = field(default_factory=dict)


@dataclass
class AgentContext:
    query: str = ""
    chat_history: list[dict] = field(default_factory=list)
    paper_id: Optional[str] = None
    user_perspective: str = ""
    extra: dict = field(default_factory=dict)


class BaseAgent(ABC):
    def __init__(self, llm_service, vector_store):
        self.llm = llm_service
        self.vector_store = vector_store

    @abstractmethod
    async def process(self, context: AgentContext) -> AgentResponse:
        pass

    def _build_citations(self, chunks: list[dict]) -> list[Citation]:
        citations = []
        seen = set()
        for chunk in chunks:
            key = (chunk.get("paper_id", ""), chunk.get("page_start", 0))
            if key in seen:
                continue
            seen.add(key)
            citations.append(Citation(
                paper_id=chunk.get("paper_id", ""),
                title=chunk.get("title", ""),
                authors=chunk.get("authors", ""),
                year=chunk.get("year", 0),
                page_start=chunk.get("page_start", 0),
                page_end=chunk.get("page_end", 0),
                excerpt=chunk.get("content", "")[:200],
            ))
        return citations
