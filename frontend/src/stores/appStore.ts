import { create } from 'zustand';
import type { ChatMessage, Paper } from '../types';

export interface WikiKb {
  id: string;
  name: string;
  description: string;
  created_at: string;
}

export interface AppState {
  // Chat state
  sessionId: string | null;
  messages: ChatMessage[];
  setSessionId: (id: string) => void;
  addMessage: (msg: ChatMessage) => void;
  clearMessages: () => void;

  // Papers state
  papers: Paper[];
  selectedPaperId: string | null;
  setPapers: (papers: Paper[]) => void;
  setSelectedPaperId: (id: string | null) => void;

  // Wiki KB state
  wikiKbs: WikiKb[];
  selectedWikiKbId: string | null;
  setWikiKbs: (kbs: WikiKb[]) => void;
  setSelectedWikiKbId: (id: string | null) => void;

  // Knowledge query queue
  knowledgeInitialQuery: string | null;
  knowledgeInitialTopic: string | null;
  knowledgeQueryNonce: number;
  queueKnowledgeQuery: (query: string, topic?: string | null) => void;
  clearQueuedKnowledgeQuery: () => void;

  // UI
  sidebarCollapsed: boolean;
  activeTab: string;
  toggleSidebar: () => void;
  setActiveTab: (tab: string) => void;
}

export const useAppStore = create<AppState>((set) => ({
  // Chat
  sessionId: null,
  messages: [],
  setSessionId: (id) => set({ sessionId: id }),
  addMessage: (msg) => set((s) => ({ messages: [...s.messages, msg] })),
  clearMessages: () => set({ sessionId: null, messages: [] }),

  // Papers
  papers: [],
  selectedPaperId: null,
  setPapers: (papers) => set({ papers }),
  setSelectedPaperId: (id) => set({ selectedPaperId: id }),

  // Wiki KB
  wikiKbs: [],
  selectedWikiKbId: null,
  setWikiKbs: (kbs) => set({ wikiKbs: kbs }),
  setSelectedWikiKbId: (id) => set({ selectedWikiKbId: id }),

  // Knowledge query queue
  knowledgeInitialQuery: null,
  knowledgeInitialTopic: null,
  knowledgeQueryNonce: 0,
  queueKnowledgeQuery: (query, topic) =>
    set((s) => ({
      knowledgeInitialQuery: query,
      knowledgeInitialTopic: topic ?? null,
      knowledgeQueryNonce: s.knowledgeQueryNonce + 1,
    })),
  clearQueuedKnowledgeQuery: () =>
    set({ knowledgeInitialQuery: null, knowledgeInitialTopic: null }),

  // UI
  sidebarCollapsed: false,
  activeTab: 'research',
  toggleSidebar: () => set((s) => ({ sidebarCollapsed: !s.sidebarCollapsed })),
  setActiveTab: (tab) => set({ activeTab: tab }),
}));

export const useSessionId = () => useAppStore((state) => state.sessionId);
export const useMessages = () => useAppStore((state) => state.messages);
export const useSetSessionId = () => useAppStore((state) => state.setSessionId);
export const useAddMessage = () => useAppStore((state) => state.addMessage);
export const useClearMessages = () => useAppStore((state) => state.clearMessages);

export const usePapers = () => useAppStore((state) => state.papers);
export const useSelectedPaperId = () => useAppStore((state) => state.selectedPaperId);
export const useSetPapers = () => useAppStore((state) => state.setPapers);
export const useSetSelectedPaperId = () => useAppStore((state) => state.setSelectedPaperId);

export const useWikiKbs = () => useAppStore((state) => state.wikiKbs);
export const useSelectedWikiKbId = () => useAppStore((state) => state.selectedWikiKbId);
export const useSetWikiKbs = () => useAppStore((state) => state.setWikiKbs);
export const useSetSelectedWikiKbId = () => useAppStore((state) => state.setSelectedWikiKbId);

export const useKnowledgeInitialQuery = () => useAppStore((state) => state.knowledgeInitialQuery);
export const useKnowledgeInitialTopic = () => useAppStore((state) => state.knowledgeInitialTopic);
export const useKnowledgeQueryNonce = () => useAppStore((state) => state.knowledgeQueryNonce);
export const useQueueKnowledgeQuery = () => useAppStore((state) => state.queueKnowledgeQuery);
export const useClearQueuedKnowledgeQuery = () => useAppStore((state) => state.clearQueuedKnowledgeQuery);

export const useSidebarCollapsed = () => useAppStore((state) => state.sidebarCollapsed);
export const useActiveTab = () => useAppStore((state) => state.activeTab);
export const useToggleSidebar = () => useAppStore((state) => state.toggleSidebar);
export const useSetActiveTab = () => useAppStore((state) => state.setActiveTab);
