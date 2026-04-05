"""Writing assistant agent - review drafting and citation suggestions."""

from agents.base import BaseAgent, AgentContext, AgentResponse


class WritingAssistantAgent(BaseAgent):
    async def process(self, context: AgentContext) -> AgentResponse:
        chunks = self.vector_store.query(context.query, n_results=15)

        user_perspective = ""
        if context.user_perspective:
            user_perspective = f"\n\nThe user's perspective/notes:\n{context.user_perspective}"

        answer = self.llm.generate_with_context(
            query=context.query + user_perspective,
            context_chunks=chunks,
            system="""You are a scientific writing assistant for single-cell 3D genomics research.
Help the user draft, revise, or improve review sections, paper text, or responses to reviewers.
When drafting:
1. Use academic scientific writing style
2. Integrate evidence from the provided sources
3. Maintain logical flow and argumentation
4. Include proper citations using [Source N] notation
5. If the user provided their perspective, integrate it naturally into the writing
When suggesting citations, explain why each reference is relevant.""",
        )

        citations = self._build_citations(chunks)
        return AgentResponse(content=answer, citations=citations, agent_type="writing_assistant")

    async def suggest_citations(self, query: str, n_results: int = 10) -> AgentResponse:
        chunks = self.vector_store.query(query, n_results=n_results)

        if not chunks:
            return AgentResponse(content="No relevant citations found.", agent_type="writing_assistant")

        suggestions = []
        for i, chunk in enumerate(chunks, 1):
            title = chunk.get("title", "Unknown")
            authors = chunk.get("authors", "Unknown")
            year = chunk.get("year", "")
            excerpt = chunk["content"][:200]
            suggestions.append(
                f"{i}. **{title}** ({authors}, {year})\n   Relevant excerpt: \"{excerpt}...\"\n"
            )

        content = "## Suggested Citations\n\n" + "\n".join(suggestions)
        citations = self._build_citations(chunks)
        return AgentResponse(content=content, citations=citations, agent_type="writing_assistant")
