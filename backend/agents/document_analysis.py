"""Document analysis agent - deep analysis of a specific paper."""

import asyncio

from agents.base import BaseAgent, AgentContext, AgentResponse


class DocumentAnalysisAgent(BaseAgent):
    async def process(self, context: AgentContext, where_filter: dict = None) -> AgentResponse:
        paper_id = context.paper_id

        qf = where_filter or {}
        if paper_id:
            qf = {**qf, "paper_id": paper_id}
            chunks = await asyncio.to_thread(self.vector_store.query, context.query, 20, qf)
        else:
            chunks = await asyncio.to_thread(self.vector_store.query, context.query, 15, qf)

        if not chunks:
            return AgentResponse(
                content="No document content found. Please specify a paper or upload one first.",
                agent_type="document_analysis",
            )

        answer = await self.llm.generate_with_context_async(
            query=context.query,
            context_chunks=chunks,
            system="""You are an expert scientific paper analyst specializing in single-cell 3D genomics.
Provide a deep, structured analysis of the paper content. Include:
1. Key findings and contributions
2. Methodology assessment
3. Strengths and limitations
4. Relationship to the broader field
Cite sources using [Source N] notation.""",
        )

        citations = self._build_citations(chunks)
        return AgentResponse(content=answer, citations=citations, agent_type="document_analysis")
