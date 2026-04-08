import axios from 'axios';
import type {
  Paper,
  ChatResponse,
  QueryResponse,
  Stats,
  ResearchJob,
  CompletedResearch,
  ReportInfo,
  ReportHypergraphResponse,
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

export async function listPapers(): Promise<Paper[]> {
  const { data } = await api.get('/papers');
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

export async function deleteResearchJob(jobId: string, force: boolean = false): Promise<{ job_id: string; deleted: boolean }> {
  const { data } = await api.delete(`/research/jobs/${jobId}`, { params: { force } });
  return data;
}

export function getResearchDownloadUrl(jobId: string): string {
  return `/api/v1/research/download/${jobId}`;
}

export async function getCompletedResearch(): Promise<CompletedResearch[]> {
  const { data } = await api.get('/research/completed');
  return data;
}

// === Hypergraph Timeline (Report-based) ===

export async function getAvailableReports(): Promise<ReportInfo[]> {
  const { data } = await api.get('/knowledge/reports');
  return data;
}

export async function getHypergraphFromReport(
  filePath: string,
  minImpactFactor: number = 2.0,
  dateStart?: string,
  dateEnd?: string,
): Promise<ReportHypergraphResponse> {
  const { data } = await api.post('/knowledge/hypergraph-from-report', {
    file_path: filePath,
    min_impact_factor: minImpactFactor,
    date_start: dateStart || null,
    date_end: dateEnd || null,
  });
  return data;
}

// === Knowledge ===

export async function queryKnowledge(query: string, paperId?: string): Promise<QueryResponse> {
  const { data } = await api.post('/knowledge/query', { query, paper_id: paperId });
  return data;
}

export async function chat(message: string, sessionId?: string, paperId?: string): Promise<ChatResponse> {
  const { data } = await api.post('/knowledge/chat', {
    message,
    session_id: sessionId,
    paper_id: paperId,
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

// === Writing ===

export async function draftReview(topic: string, userPerspective: string = '', sectionType: string = 'introduction') {
  const { data } = await api.post('/writing/draft-review', {
    topic,
    user_perspective: userPerspective,
    section_type: sectionType,
  });
  return data;
}

export async function suggestCitations(text: string, nResults: number = 10) {
  const { data } = await api.post('/writing/suggest-citations', { text, n_results: nResults });
  return data;
}

// === Review ===

export async function evaluatePaper(paperId: string, focusAreas: string[] = []) {
  const { data } = await api.post('/review/evaluate', { paper_id: paperId, focus_areas: focusAreas });
  return data;
}

// === Stats ===

export async function getStats(): Promise<Stats> {
  const { data } = await api.get('/stats');
  return data;
}

export default api;
