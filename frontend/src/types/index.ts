export interface Paper {
  id: string;
  title: string;
  authors: string[];
  year: number;
  filename: string;
  status: 'pending' | 'processing' | 'completed' | 'failed';
  chunks_count: number;
  abstract: string;
  created_at: string;
}

export interface Citation {
  paper_id: string;
  title: string;
  authors: string;
  year: number;
  page_start: number;
  page_end: number;
  excerpt: string;
}

export interface ChatMessage {
  role: 'user' | 'assistant';
  content: string;
  citations?: Citation[];
  agent_type?: string;
}

export interface QueryResponse {
  content: string;
  agent_type: string;
  citations: Citation[];
}

export interface ChatResponse extends QueryResponse {
  session_id: string;
}

export interface TimelineEvent {
  year: number;
  title: string;
  description: string;
  methods?: string[];
  papers?: string[];
}

export interface Stats {
  papers: { total: number; completed: number };
  vector_store: { total_chunks: number };
}

// Research types (NEW)
export interface ResearchJob {
  job_id: string;
  status: 'pending' | 'running' | 'completed' | 'failed';
  topic: string;
  query: string;
  max_papers: number;
  total_papers: number;
  processed_papers: number;
  analyzed_papers: number;
  current_stage: string;
  created_at: string;
  completed_at?: string;
  error_message: string;
  result_path: string;  // local path to Markdown report
  warnings: string[];   // partial failure messages (S2/LLM issues)
  // Checkpoint/resume fields
  stage_completed?: {
    searching?: boolean;
    enriching?: boolean;
    analyzing?: boolean;
    converting?: boolean;
  };
  last_successful_stage?: string;
  stage_retry_count?: number;
}

export interface AuthorInfo {
  name: string;
  first_name: string;
  last_name: string;
  affiliation: string;
  email: string;
  is_first_author: boolean;
  is_corresponding_author: boolean;
}

export interface ResearchPaper {
  pmid?: string;
  doi?: string;
  title: string;
  abstract: string;
  journal: string;
  year: number;
  authors: AuthorInfo[];
  first_author?: string;
  corresponding_authors?: string[];
  affiliations?: string[];
}

export interface CompletedResearch {
  job_id: string;
  topic: string;
  paper_count: number;
  completed_at?: string;
}

// Hypergraph types
export interface HypergraphNode {
  id: string;
  name?: string;
  type: 'author' | 'paper' | 'institution' | 'time_period' | 'concept';
  [key: string]: any;
}

export interface HypergraphEdge {
  type: string;
  nodes: string[];
  weight: number;
  paper?: string;
}

export interface HypergraphData {
  nodes: {
    authors: HypergraphNode[];
    papers: HypergraphNode[];
    institutions: HypergraphNode[];
    time_periods: HypergraphNode[];
    concepts: HypergraphNode[];
  };
  hyperedges: HypergraphEdge[];
}

export interface KeyFigure {
  name: string;
  role: string;
  influence_score: number;
  institution: string;
}

export interface CollaborationCluster {
  id: string;
  members: string[];
  institution: string;
  paper_count: number;
}

export interface Milestone {
  year: number;
  event: string;
  significance: string;
  key_papers: string[];
}

export interface Debate {
  topic: string;
  sides: string[];
  status: 'ongoing' | 'resolved';
}

export interface HypergraphAnalysis {
  summary: string;
  key_figures: KeyFigure[];
  collaboration_clusters: CollaborationCluster[];
  milestones: Milestone[];
  debates: Debate[];
  consensus_areas: string[];
  temporal_patterns: string;
}

export interface HypergraphTimelineResponse {
  job_id: string;
  topic: string;
  hypergraph: HypergraphData;
  analysis: HypergraphAnalysis;
  statistics: {
    total_papers: number;
    total_authors: number;
    total_institutions: number;
    time_range: { start: number; end: number };
  };
}
