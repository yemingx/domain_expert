"""Knowledge retrieval agent - hierarchical RAG with citation tracking and wiki source tracing."""

import asyncio
import logging

from agents.base import BaseAgent, AgentContext, AgentResponse, Citation

logger = logging.getLogger(__name__)


class KnowledgeRetrievalAgent(BaseAgent):
    async def process(self, context: AgentContext, where_filter: dict = None) -> AgentResponse:
        chunks = await asyncio.to_thread(
            self.vector_store.query,
            context.query,
            10,
            where_filter,
        )

        if not chunks:
            return AgentResponse(
                content="I couldn't find relevant information in the knowledge base. "
                "Please try rephrasing your question or upload relevant papers first.",
                agent_type="knowledge_retrieval",
            )

        answer = await self.llm.generate_with_context_async(
            query=context.query,
            context_chunks=chunks,
            system="""You are a domain expert in single-cell 3D genomics.
Answer the question based on the provided research paper excerpts.
Always cite your sources using [Source N] notation corresponding to the provided context.
Be precise, scientific, and thorough. If the context doesn't fully answer the question, say so.""",
        )

        citations = self._build_citations(chunks)
        wiki_traces = await asyncio.to_thread(self._get_wiki_traces, chunks)
        citations.extend(wiki_traces)

        return AgentResponse(
            content=answer,
            citations=citations[:15],
            agent_type="knowledge_retrieval",
        )

    def _get_wiki_traces(self, chunks: list[dict]) -> list[Citation]:
        """Find related wiki pages that reference the source papers."""
        try:
            from app.services.wiki_service import get_wiki_service

            wiki = get_wiki_service()
            paper_ids = {chunk.get("paper_id", "") for chunk in chunks if chunk.get("paper_id")}

            traces = []
            for page in wiki.list_pages():
                for pid in paper_ids:
                    if pid in page.get("source_paper_ids", []):
                        full_page = wiki.get_page(page["slug"])
                        if full_page:
                            traces.append(Citation(
                                paper_id=pid,
                                title=f"Wiki: {page['title']}",
                                authors=[],
                                year=None,
                                page_start=0,
                                page_end=0,
                                excerpt=full_page.content[:300],
                            ))
            return traces
        except Exception as exc:
            logger.warning("Wiki traces skipped: %s", exc)
            return []
