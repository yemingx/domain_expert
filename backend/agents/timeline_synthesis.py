"""Timeline synthesis agent - domain evolution and method comparison."""

from agents.base import BaseAgent, AgentContext, AgentResponse


class TimelineSynthesisAgent(BaseAgent):
    async def process(self, context: AgentContext) -> AgentResponse:
        chunks = self.vector_store.query(context.query, n_results=20)

        if not chunks:
            return AgentResponse(
                content="Insufficient data for timeline synthesis. Please upload more domain papers.",
                agent_type="timeline_synthesis",
            )

        answer = self.llm.generate_with_context(
            query=context.query,
            context_chunks=chunks,
            system="""You are a domain historian and methodologist for single-cell 3D genomics.
Synthesize the provided research excerpts to:
1. Construct a chronological timeline of key breakthroughs
2. Compare different technical approaches (e.g., scHi-C, Dip-C, SPRITE, GAM variants)
3. Identify paradigm shifts and emerging trends
4. Highlight core debates and unresolved questions in the field
Format the timeline with years and key events. Cite sources using [Source N] notation.""",
        )

        citations = self._build_citations(chunks)
        return AgentResponse(content=answer, citations=citations, agent_type="timeline_synthesis")
