"""Agent coordinator - routes queries to appropriate specialized agents."""

import logging
from typing import Optional

from agents.base import AgentContext, AgentResponse
from app.services.llm_service import LLMService, get_llm_service
from app.services.vector_store import VectorStoreService, get_vector_store

logger = logging.getLogger(__name__)


class AgentCoordinator:
    def __init__(self, llm_service: LLMService, vector_store: VectorStoreService):
        self.llm = llm_service
        self.vector_store = vector_store
        self._agents = {}
        self._init_agents()

    def _init_agents(self):
        from agents.knowledge_retrieval import KnowledgeRetrievalAgent
        from agents.document_analysis import DocumentAnalysisAgent
        from agents.timeline_synthesis import TimelineSynthesisAgent
        from agents.writing_assistant import WritingAssistantAgent
        from agents.reviewer import ReviewerAgent

        self._agents = {
            "knowledge_retrieval": KnowledgeRetrievalAgent(self.llm, self.vector_store),
            "document_analysis": DocumentAnalysisAgent(self.llm, self.vector_store),
            "timeline_synthesis": TimelineSynthesisAgent(self.llm, self.vector_store),
            "writing_assistant": WritingAssistantAgent(self.llm, self.vector_store),
            "reviewer": ReviewerAgent(self.llm, self.vector_store),
        }

    @staticmethod
    def _heuristic_route(context: AgentContext) -> Optional[str]:
        query = (context.query or "").lower()

        if any(token in query for token in ["evaluate", "score", "review this paper", "peer review", "major revision", "minor revision", "accept", "reject"]):
            return "reviewer"

        if any(token in query for token in ["draft", "write", "rewrite", "edit this", "introduction", "discussion", "conclusion", "suggest citations"]):
            return "writing_assistant"

        if any(token in query for token in ["timeline", "history", "evolution", "trend", "milestone", "over time", "paradigm shift"]):
            return "timeline_synthesis"

        if context.paper_id and any(token in query for token in ["analyze", "analysis", "summarize this paper", "strength", "weakness", "limitation", "methodology"]):
            return "document_analysis"

        return None

    async def route_and_process(
        self,
        context: AgentContext,
        where_filter: dict = None,
    ) -> AgentResponse:
        agent_type = self._heuristic_route(context)
        if agent_type is None:
            agent_type = await self.llm.classify_query_async(context.query)
        logger.info("Query classified as: %s", agent_type)

        agent = self._agents.get(agent_type)
        if agent is None:
            agent = self._agents["knowledge_retrieval"]
            agent_type = "knowledge_retrieval"

        try:
            response = await agent.process(context, where_filter=where_filter)
        except TypeError:
            response = await agent.process(context)
        response.agent_type = agent_type
        return response


_coordinator: Optional[AgentCoordinator] = None


def get_agent_coordinator() -> AgentCoordinator:
    global _coordinator
    if _coordinator is None:
        _coordinator = AgentCoordinator(get_llm_service(), get_vector_store())
    return _coordinator
