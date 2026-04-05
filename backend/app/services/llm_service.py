"""LLM service using Anthropic SDK (compatible with DashScope and other providers)."""

import logging
from typing import Optional

from anthropic import Anthropic

from app.core.config import settings

logger = logging.getLogger(__name__)


class LLMService:
    def __init__(self):
        # DashScope proxy requires Authorization: Bearer <token> → use auth_token.
        # Standard Anthropic API uses x-api-key → use api_key.
        if settings.anthropic_auth_token:
            kwargs = {"auth_token": settings.anthropic_auth_token}
        else:
            kwargs = {"api_key": settings.anthropic_api_key}
        if settings.anthropic_base_url:
            kwargs["base_url"] = settings.anthropic_base_url
        self.client = Anthropic(**kwargs)
        self.model = settings.anthropic_model

    @staticmethod
    def _extract_text(response) -> str:
        """Extract text from response, skipping ThinkingBlock / other non-text blocks."""
        for block in response.content:
            if hasattr(block, "text"):
                return block.text
        return ""

    def chat(
        self,
        messages: list[dict],
        system: str = "",
        max_tokens: int = 4096,
        temperature: float = 0.7,
    ) -> str:
        try:
            kwargs = {
                "model": self.model,
                "max_tokens": max_tokens,
                "messages": messages,
            }
            if system:
                kwargs["system"] = system
            if temperature is not None:
                kwargs["temperature"] = temperature

            response = self.client.messages.create(**kwargs)
            return self._extract_text(response)
        except Exception as e:
            logger.error(f"LLM chat error: {e}")
            raise

    def classify_query(self, query: str) -> str:
        system = """You are a query classifier for a scientific research assistant.
Classify the user query into exactly one category:
- knowledge_retrieval: Questions about specific facts, methods, or findings from papers
- document_analysis: Requests to analyze a specific paper in depth
- timeline_synthesis: Questions about domain evolution, breakthroughs, or method comparisons over time
- writing_assistant: Requests to help write, draft, or edit review sections
- reviewer: Requests to evaluate or score a paper

Respond with ONLY the category name, nothing else."""

        messages = [{"role": "user", "content": query}]
        result = self.chat(messages, system=system, max_tokens=50, temperature=0.0)
        category = result.strip().lower()

        valid = {"knowledge_retrieval", "document_analysis", "timeline_synthesis", "writing_assistant", "reviewer"}
        if category not in valid:
            return "knowledge_retrieval"
        return category

    def generate_with_context(
        self,
        query: str,
        context_chunks: list[dict],
        system: str = "",
        max_tokens: int = 4096,
    ) -> str:
        context_text = ""
        for i, chunk in enumerate(context_chunks, 1):
            paper_id = chunk.get("paper_id", "unknown")
            page = chunk.get("page_start", "?")
            context_text += f"\n[Source {i}] (Paper: {paper_id}, Page: {page})\n{chunk['content']}\n"

        if not system:
            system = """You are a domain expert in single-cell 3D genomics.
Answer questions based on the provided research paper excerpts.
Always cite your sources using [Source N] notation.
Be precise and scientific in your responses."""

        messages = [
            {
                "role": "user",
                "content": f"Context from research papers:\n{context_text}\n\nQuestion: {query}",
            }
        ]
        return self.chat(messages, system=system, max_tokens=max_tokens)


# Singleton
_llm_service: Optional[LLMService] = None


def get_llm_service() -> LLMService:
    global _llm_service
    if _llm_service is None:
        _llm_service = LLMService()
    return _llm_service
