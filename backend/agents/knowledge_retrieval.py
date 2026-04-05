"""Knowledge retrieval agent - hierarchical RAG with citation tracking."""

from agents.base import BaseAgent, AgentContext, AgentResponse


class KnowledgeRetrievalAgent(BaseAgent):
    async def process(self, context: AgentContext) -> AgentResponse:
        # Retrieve relevant chunks from vector store
        chunks = self.vector_store.query(context.query, n_results=10)

        if not chunks:
            return AgentResponse(
                content="I couldn't find relevant information in the knowledge base. "
                "Please try rephrasing your question or upload relevant papers first.",
                agent_type="knowledge_retrieval",
            )

        # Generate answer with citations
        answer = self.llm.generate_with_context(
            query=context.query,
            context_chunks=chunks,
            system="""You are a domain expert in single-cell 3D genomics.
Answer the question based on the provided research paper excerpts.
Always cite your sources using [Source N] notation corresponding to the provided context.
Be precise, scientific, and thorough. If the context doesn't fully answer the question, say so.""",
        )

        citations = self._build_citations(chunks)
        return AgentResponse(content=answer, citations=citations, agent_type="knowledge_retrieval")
