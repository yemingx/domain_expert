"""Document analysis agent - deep analysis of a specific paper."""

from agents.base import BaseAgent, AgentContext, AgentResponse


class DocumentAnalysisAgent(BaseAgent):
    async def process(self, context: AgentContext) -> AgentResponse:
        paper_id = context.paper_id

        if paper_id:
            chunks = self.vector_store.query(
                context.query, n_results=20, where_filter={"paper_id": paper_id}
            )
        else:
            chunks = self.vector_store.query(context.query, n_results=15)

        if not chunks:
            return AgentResponse(
                content="No document content found. Please specify a paper or upload one first.",
                agent_type="document_analysis",
            )

        answer = self.llm.generate_with_context(
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
