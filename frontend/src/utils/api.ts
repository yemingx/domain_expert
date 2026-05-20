import axios from 'axios';
import type {
  Paper,
  ChatResponse,
  QueryResponse,
  Stats,
  ResearchJob,
  CompletedResearch,
  HypergraphTimelineResponse,
} from '../types';

const api = axios.create({
  baseURL: '/api/v1',
  headers: { 'Content-Type': 'application/json' },
});

// === Papers ===

export async function uploadPaper(file: File): Promise<{ paper_id: string; status: string }> {
  const formData = new FormData();
  formData.append('file', file);
  const { data } = await api.post('/papers/upload', formData, {
    headers: { 'Content-Type': 'multipart/form-data' },
  });
  return data;
}

export async function uploadPaperWithMineru(file: File): Promise<{
  paper_id: string;
  filename: string;
  status: string;
  markdown_status: string;
}> {
  const formData = new FormData();
  formData.append('file', file);
  const { data } = await api.post('/papers/upload-with-mineru', formData, {
    headers: { 'Content-Type': 'multipart/form-data' },
  });
  return data;
}

export async function listPapers(wikiKbId?: string | null): Promise<Paper[]> {
  const { data } = await api.get('/papers', { params: wikiKbId ? { wiki_kb_id: wikiKbId } : {} });
  return data;
}

export async function getPaper(id: string): Promise<Paper> {
  const { data } = await api.get(`/papers/${id}`);
  return data;
}

// === Research (NEW) ===

export async function runResearch(
  topic: string,
  query: string,
  max_papers: number = 50,
): Promise<ResearchJob> {
  const { data } = await api.post('/research/run', {
    topic,
    query,
    max_papers,
  });
  return data;
}

export async function listResearchJobs(): Promise<ResearchJob[]> {
  const { data } = await api.get('/research/jobs');
  return data;
}

export async function getResearchJob(jobId: string): Promise<ResearchJob> {
  const { data } = await api.get(`/research/jobs/${jobId}`);
  return data;
}

export async function retryResearchJob(jobId: string): Promise<ResearchJob> {
  const { data } = await api.post(`/research/retry/${jobId}`);
  return data;
}

export async function resetResearchJob(jobId: string): Promise<ResearchJob> {
  const { data } = await api.post(`/research/reset/${jobId}`);
  return data;
}

export async function importResearchToKB(jobId: string): Promise<{ job_id: string; chunks_added: number }> {
  const { data } = await api.post(`/research/import/${jobId}`);
  return data;
}

export async function deleteResearchJob(jobId: string): Promise<{ job_id: string; deleted: boolean }> {
  const { data } = await api.delete(`/research/jobs/${jobId}`);
  return data;
}

export function getResearchDownloadUrl(jobId: string): string {
  return `/api/v1/research/download/${jobId}`;
}

export async function getCompletedResearch(): Promise<CompletedResearch[]> {
  const { data } = await api.get('/research/completed');
  return data;
}

// === Hypergraph Timeline (NEW) ===

export async function getHypergraphTimeline(
  jobId: string,
  analysisDepth: string = 'full',
  includeCollaboration: boolean = true,
  includeInfluence: boolean = true,
  includeMilestones: boolean = true,
): Promise<HypergraphTimelineResponse> {
  const { data } = await api.post('/knowledge/hypergraph-timeline', {
    job_id: jobId,
    analysis_depth: analysisDepth,
    include_collaboration: includeCollaboration,
    include_influence: includeInfluence,
    include_milestones: includeMilestones,
  });
  return data;
}

// === Knowledge ===

export async function queryKnowledge(
  query: string,
  paperId?: string,
  topic?: string,
  wikiKbId?: string,
): Promise<QueryResponse> {
  const { data } = await api.post('/knowledge/query', {
    query,
    paper_id: paperId,
    topic,
    wiki_kb_id: wikiKbId,
  });
  return data;
}

export async function chat(message: string, sessionId?: string, paperId?: string, wikiKbId?: string): Promise<ChatResponse> {
  const { data } = await api.post('/knowledge/chat', {
    message,
    session_id: sessionId,
    paper_id: paperId,
    wiki_kb_id: wikiKbId,
  });
  return data;
}

export async function getTimeline(): Promise<{ timeline: any[]; summary: string }> {
  const { data } = await api.get('/knowledge/timeline');
  return data;
}

export async function compareMethods(methods: string[], aspects?: string[]): Promise<{ comparison: string }> {
  const { data } = await api.post('/knowledge/compare', { methods, aspects });
  return data;
}

// === Wiki KB Management ===

export interface WikiKbData {
  id: string;
  name: string;
  description: string;
  created_at: string;
}

export async function listWikiKbs(): Promise<WikiKbData[]> {
  const { data } = await api.get('/wiki/kbs');
  return data;
}

export async function createWikiKb(name: string, description: string = ''): Promise<WikiKbData> {
  const { data } = await api.post('/wiki/kbs', { name, description });
  return data;
}

export async function deleteWikiKb(kbId: string): Promise<void> {
  await api.delete(`/wiki/kbs/${kbId}`);
}

export async function importResearchToWiki(kbId: string, jobId: string): Promise<{ status: string; chunks: number }> {
  const { data } = await api.post('/wiki/import-research', { kb_id: kbId, job_id: jobId });
  return data;
}

export async function importPaperToWikiKB(kbId: string, paperId: string): Promise<{ status: string; chunks: number }> {
  const { data } = await api.post('/wiki/import-paper', { kb_id: kbId, paper_id: paperId });
  return data;
}

// === Wiki Pages (scoped by KB) ===

export interface WikiPageListItem {
  slug: string;
  title: string;
  page_type: string;
  source_paper_ids: string[];
  updated_at: string;
}

export interface WikiPageData {
  slug: string;
  title: string;
  content: string;
  page_type: string;
  source_paper_ids: string[];
  cross_refs: string[];
  created_at: string;
  updated_at: string;
}

export interface WikiSearchResult {
  type: 'wiki_page' | 'raw_source';
  slug?: string;
  paper_id?: string;
  title: string;
  snippet: string;
  score: number;
}

export async function listWikiPages(kbId?: string | null): Promise<WikiPageListItem[]> {
  const { data } = await api.get('/wiki/pages', { params: kbId ? { kb_id: kbId } : {} });
  return data;
}

export async function getWikiPage(slug: string, kbId?: string | null): Promise<WikiPageData> {
  const { data } = await api.get(`/wiki/pages/${slug}`, { params: kbId ? { kb_id: kbId } : {} });
  return data;
}

export async function wikiSearch(q: string, kbId?: string | null): Promise<WikiSearchResult[]> {
  const { data } = await api.get('/wiki/search', { params: { q, ...(kbId ? { kb_id: kbId } : {}) } });
  return data;
}

export async function wikiIngest(paperId: string, kbId?: string | null): Promise<{ status: string; pages_created: any[] }> {
  const { data } = await api.post('/wiki/ingest', { paper_id: paperId, kb_id: kbId || '' });
  return data;
}

export async function uploadPaperWithMineruToKB(file: File, wikiKbId: string): Promise<{
  paper_id: string;
  filename: string;
  status: string;
  markdown_status: string;
  wiki_kb_id: string;
}> {
  const formData = new FormData();
  formData.append('file', file);
  formData.append('wiki_kb_id', wikiKbId);
  const { data } = await api.post('/papers/upload-with-mineru', formData, {
    headers: { 'Content-Type': 'multipart/form-data' },
  });
  return data;
}

export async function getPaperMarkdown(paperId: string, kbId?: string | null): Promise<{ paper_id: string; markdown: string }> {
  const { data } = await api.get(`/papers/${paperId}/markdown`, { params: kbId ? { kb_id: kbId } : {} });
  return data;
}

// === Writing ===

export async function draftReview(topic: string, userPerspective: string = '', sectionType: string = 'introduction', wikiKbId?: string | null) {
  const { data } = await api.post('/writing/draft-review', {
    topic,
    user_perspective: userPerspective,
    section_type: sectionType,
    wiki_kb_id: wikiKbId || undefined,
  });
  return data;
}

export async function suggestCitations(text: string, nResults: number = 10, wikiKbId?: string | null) {
  const { data } = await api.post('/writing/suggest-citations', { text, n_results: nResults, wiki_kb_id: wikiKbId || undefined });
  return data;
}

// === Review ===

export async function evaluatePaper(paperId: string, focusAreas: string[] = [], wikiKbId?: string | null) {
  const { data } = await api.post('/review/evaluate', { paper_id: paperId, focus_areas: focusAreas, wiki_kb_id: wikiKbId || undefined });
  return data;
}

// === Stats ===

export async function getStats(): Promise<Stats> {
  const { data } = await api.get('/stats');
  return data;
}

export default api;
