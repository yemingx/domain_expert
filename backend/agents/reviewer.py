"""Reviewer agent - paper evaluation with scoring rubric."""

import asyncio

from agents.base import BaseAgent, AgentContext, AgentResponse


class ReviewerAgent(BaseAgent):
    RUBRIC_CATEGORIES = [
        "Novelty",
        "Technical Soundness",
        "Clarity of Writing",
        "Experimental Design",
        "Data Analysis",
        "Significance to Field",
        "Reproducibility",
        "Literature Coverage",
    ]

    async def process(self, context: AgentContext, where_filter: dict = None) -> AgentResponse:
        paper_id = context.paper_id

        qf = where_filter or {}
        if paper_id:
            qf = {**qf, "paper_id": paper_id}
            chunks = await asyncio.to_thread(self.vector_store.query, context.query, 25, qf)
        else:
            chunks = await asyncio.to_thread(self.vector_store.query, context.query, 20, qf)

        if not chunks:
            return AgentResponse(
                content="No paper content found to review. Please specify a paper.",
                agent_type="reviewer",
            )

        categories_str = "\n".join(f"- {category}" for category in self.RUBRIC_CATEGORIES)

        answer = await self.llm.generate_with_context_async(
            query=context.query,
            context_chunks=chunks,
            system=f"""You are an expert peer reviewer for single-cell 3D genomics papers.
Evaluate the paper content and provide:

1. **Overall Assessment**: A summary of the paper's strengths and weaknesses

2. **Scoring** (rate each 1-10 with justification):
{categories_str}

3. **Detailed Comments**:
   - Major issues that must be addressed
   - Minor suggestions for improvement
   - Questions for the authors

4. **Recommendation**: Accept / Minor Revision / Major Revision / Reject

Cite specific parts of the paper using [Source N] notation to support your assessment.""",
        )

        citations = self._build_citations(chunks)
        return AgentResponse(
            content=answer,
            citations=citations,
            agent_type="reviewer",
            metadata={"rubric_categories": self.RUBRIC_CATEGORIES},
        )
