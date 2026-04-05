"""Agent coordinator - routes queries to appropriate specialized agents."""

import logging

from agents.base import AgentContext, AgentResponse
from app.services.llm_service import LLMService
from app.services.vector_store import VectorStoreService

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

    async def route_and_process(
        self,
        context: AgentContext,
        where_filter: dict = None,
    ) -> AgentResponse:
        agent_type = self.llm.classify_query(context.query)
        logger.info(f"Query classified as: {agent_type}")

        agent = self._agents.get(agent_type)
        if agent is None:
            agent = self._agents["knowledge_retrieval"]
            agent_type = "knowledge_retrieval"

        # Pass where_filter to agent if supported
        try:
            response = await agent.process(context, where_filter=where_filter)
        except TypeError:
            # Agent doesn't support where_filter — fall back
            response = await agent.process(context)
        response.agent_type = agent_type
        return response
