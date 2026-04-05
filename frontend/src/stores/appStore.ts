import { create } from 'zustand';
import type { ChatMessage, Paper } from '../types';

interface AppState {
  // Chat
  sessionId: string | null;
  messages: ChatMessage[];
  setSessionId: (id: string | null) => void;
  addMessage: (msg: ChatMessage) => void;
  clearMessages: () => void;

  // Papers
  papers: Paper[];
  setPapers: (papers: Paper[]) => void;
  selectedPaperId: string | null;
  setSelectedPaperId: (id: string | null) => void;

  // UI
  sidebarCollapsed: boolean;
  toggleSidebar: () => void;
  activeTab: string;
  setActiveTab: (tab: string) => void;
}

export const useAppStore = create<AppState>((set) => ({
  sessionId: null,
  messages: [],
  setSessionId: (id) => set({ sessionId: id }),
  addMessage: (msg) => set((s) => ({ messages: [...s.messages, msg] })),
  clearMessages: () => set({ messages: [], sessionId: null }),

  papers: [],
  setPapers: (papers) => set({ papers }),
  selectedPaperId: null,
  setSelectedPaperId: (id) => set({ selectedPaperId: id }),

  sidebarCollapsed: false,
  toggleSidebar: () => set((s) => ({ sidebarCollapsed: !s.sidebarCollapsed })),
  activeTab: 'chat',
  setActiveTab: (tab) => set({ activeTab: tab }),
}));
