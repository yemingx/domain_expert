import { useState, useEffect, useRef, useMemo, useCallback } from 'react';
import {
  Card,
  Button,
  Select,
  Space,
  message,
  Typography,
  Tabs,
  List,
  Tag,
  Badge,
  Slider,
  Checkbox,
  Empty,
  Spin,
  Divider,
} from 'antd';
import {
  ReloadOutlined,
  ShareAltOutlined,
  TeamOutlined,
  TrophyOutlined,
  BookOutlined,
  BulbOutlined,
  GlobalOutlined,
  ClockCircleOutlined,
} from '@ant-design/icons';
import { useQuery } from '@tanstack/react-query';
import * as d3 from 'd3';
import { getCompletedResearch, getHypergraphTimeline } from '../utils/api';
import { useQueueKnowledgeQuery, useSetActiveTab } from '../stores/appStore';
import type {
  CompletedResearch,
  KeyFigure,
  CollaborationCluster,
  Milestone,
  Debate,
} from '../types';

const { Text, Title, Paragraph, Link } = Typography;
const { Option } = Select;

type AnalysisTabKey = 'overview' | 'figures' | 'collaboration' | 'milestones' | 'debates';

interface GraphData {
  nodes: GraphNode[];
  links: GraphLink[];
  neighbors: Map<string, Set<string>>;
}

interface GraphNode extends d3.SimulationNodeDatum {
  id: string;
  rawId: string;
  name: string;
  type: 'author' | 'paper' | 'institution' | 'time_period';
  radius: number;
  color: string;
  data: any;
  rank: number;
  emphasis: number;
  anchorX?: number;
  anchorY?: number;
  year?: number;
  clusterKey?: string;
}

interface GraphLink extends d3.SimulationLinkDatum<GraphNode> {
  source: string | GraphNode;
  target: string | GraphNode;
  weight: number;
  type: 'authorship' | 'temporal' | 'collaboration' | 'affiliation' | 'citation';
  opacity: number;
}

interface AuthorMatch {
  authorId: string;
  authorName: string;
  confidence: number;
}

const NODE_COLORS: Record<GraphNode['type'], string> = {
  author: '#1677ff',
  paper: '#52c41a',
  institution: '#fa8c16',
  time_period: '#722ed1',
};

interface Author {
  id: string;
  name: string;
  affiliation?: string;
  papers?: string[];
  total_citations?: number;
  is_first_author_count?: number;
  is_corresponding_author_count?: number;
  coauthors?: string[];
}

interface Paper {
  id: string;
  title: string;
  year?: number;
  journal?: string;
  doi?: string;
  citation_count?: number;
}

interface Institution {
  id: string;
  name: string;
  authors?: string[];
  papers?: string[];
}

interface TimePeriod {
  id: string;
  year: number;
  papers?: string[];
}

interface Hyperedge {
  type: string;
  nodes: string[];
  paper?: string;
}

interface CollaborationLink {
  source: string;
  target: string;
  weight: number;
}

interface ActiveNodes {
  authorIds: Set<string>;
  institutionIds: Set<string>;
  timeIds: Set<string>;
  paperIds: Set<string>;
}

const ANALYSIS_METHODS: Record<AnalysisTabKey, string> = {
  overview: '基于超图中的作者、论文、机构与时间节点结构，并结合模型摘要，提炼当前研究主题的整体格局。',
  figures: '通过作者连接度、发文活跃度、第一/通讯作者信号与论文影响力，识别关键人物。',
  collaboration: '根据重复共著关系与机构分布，提炼稳定合作簇和主要协作网络。',
  milestones: '结合时间分布、关键论文与影响力变化，提炼研究发展的重要阶段与转折点。',
  debates: '从分析结果中归纳持续出现的争议点、不同立场与逐步形成的共识。',
};

const clamp = (value: number, min: number, max: number) => Math.max(min, Math.min(max, value));

const normalizeEdgeId = (value: string, prefix: string) => value.startsWith(prefix) ? value.slice(prefix.length) : value;

const normalizeText = (value?: string | null) => (value || '')
  .trim()
  .toLowerCase()
  .replace(/\s+/g, ' ')
  .replace(/[.,;:()\[\]{}'"`’]/g, '');

const buildNeighborMap = (links: GraphLink[]) => {
  const neighbors = new Map<string, Set<string>>();

  links.forEach((link) => {
    const source = typeof link.source === 'string' ? link.source : link.source.id;
    const target = typeof link.target === 'string' ? link.target : link.target.id;

    if (!neighbors.has(source)) neighbors.set(source, new Set());
    if (!neighbors.has(target)) neighbors.set(target, new Set());

    neighbors.get(source)!.add(target);
    neighbors.get(target)!.add(source);
  });

  return neighbors;
};

function filterPapersByYear(papers: Paper[], yearRange: [number, number]): Set<string> {
  return new Set(
    papers
      .filter((paper) => !paper.year || (paper.year >= yearRange[0] && paper.year <= yearRange[1]))
      .map((paper) => paper.id),
  );
}

function buildAuthorshipIndex(
  edges: Hyperedge[],
  authorMap: Map<string, Author>,
  paperMap: Map<string, Paper>,
  filteredPaperIds: Set<string>,
): Map<string, Set<string>> {
  const paperIdsByAuthor = new Map<string, Set<string>>();

  edges.forEach((edge) => {
    const authorId = edge.nodes.find((nodeId) => authorMap.has(normalizeEdgeId(nodeId, 'author_')));
    const paperId = edge.nodes.find((nodeId) => paperMap.has(normalizeEdgeId(nodeId, 'paper_')));
    if (!authorId || !paperId) return;

    const normalizedAuthorId = normalizeEdgeId(authorId, 'author_');
    const normalizedPaperId = normalizeEdgeId(paperId, 'paper_');
    if (!filteredPaperIds.has(normalizedPaperId)) return;

    if (!paperIdsByAuthor.has(normalizedAuthorId)) {
      paperIdsByAuthor.set(normalizedAuthorId, new Set());
    }
    paperIdsByAuthor.get(normalizedAuthorId)!.add(normalizedPaperId);
  });

  return paperIdsByAuthor;
}

function buildTemporalIndex(
  edges: Hyperedge[],
  paperMap: Map<string, Paper>,
  timeMap: Map<string, TimePeriod>,
  filteredPaperIds: Set<string>,
): Map<string, Set<string>> {
  const paperIdsByTime = new Map<string, Set<string>>();

  edges.forEach((edge) => {
    const paperId = edge.nodes.find((nodeId) => paperMap.has(normalizeEdgeId(nodeId, 'paper_')));
    const timeId = edge.nodes.find((nodeId) => timeMap.has(normalizeEdgeId(nodeId, 'time_')) || timeMap.has(nodeId));
    if (!paperId || !timeId) return;

    const normalizedPaperId = normalizeEdgeId(paperId, 'paper_');
    const normalizedTimeId = normalizeEdgeId(timeId, 'time_');
    if (!filteredPaperIds.has(normalizedPaperId) || !timeMap.has(normalizedTimeId)) return;

    if (!paperIdsByTime.has(normalizedTimeId)) {
      paperIdsByTime.set(normalizedTimeId, new Set());
    }
    paperIdsByTime.get(normalizedTimeId)!.add(normalizedPaperId);
  });

  return paperIdsByTime;
}

function buildCollaborationLinks(
  edges: Hyperedge[],
  authorMap: Map<string, Author>,
  filteredPaperIds: Set<string>,
  includeCollaboration: boolean,
): CollaborationLink[] {
  if (!includeCollaboration) return [];

  const collaborationWeights = new Map<string, CollaborationLink>();

  edges.forEach((edge) => {
    if (edge.paper && !filteredPaperIds.has(edge.paper)) return;

    const authorIds = edge.nodes
      .map((nodeId) => normalizeEdgeId(nodeId, 'author_'))
      .filter((nodeId) => authorMap.has(nodeId));

    for (let i = 0; i < authorIds.length; i += 1) {
      for (let j = i + 1; j < authorIds.length; j += 1) {
        const [source, target] = [authorIds[i], authorIds[j]].sort();
        const key = `${source}|${target}`;
        const current = collaborationWeights.get(key);
        collaborationWeights.set(key, {
          source,
          target,
          weight: (current?.weight ?? 0) + 1,
        });
      }
    }
  });

  const sortedLinks = [...collaborationWeights.values()].sort((a, b) => b.weight - a.weight);
  const hasStrongLinks = sortedLinks.some((link) => link.weight >= 2);
  const filteredLinks = sortedLinks.filter((link) => link.weight >= (hasStrongLinks ? 2 : 1));

  const cappedLinks: CollaborationLink[] = [];
  const degreeMap = new Map<string, number>();

  filteredLinks.forEach((link) => {
    const sourceDegree = degreeMap.get(link.source) ?? 0;
    const targetDegree = degreeMap.get(link.target) ?? 0;
    if (sourceDegree >= 4 || targetDegree >= 4) return;

    cappedLinks.push(link);
    degreeMap.set(link.source, sourceDegree + 1);
    degreeMap.set(link.target, targetDegree + 1);
  });

  return cappedLinks;
}

function determineActiveNodes(
  viewMode: 'full' | 'collaboration' | 'temporal',
  paperIdsByAuthor: Map<string, Set<string>>,
  paperIdsByTime: Map<string, Set<string>>,
  collaborationLinks: CollaborationLink[],
  authorMap: Map<string, Author>,
  institutionMap: Map<string, Institution>,
  filteredPaperIds: Set<string>,
): ActiveNodes {
  const activeAuthorIds = new Set<string>();
  const activeInstitutionIds = new Set<string>();
  const activeTimeIds = new Set<string>();
  const activePaperIds = new Set(filteredPaperIds);

  if (viewMode === 'collaboration') {
    collaborationLinks.forEach((link) => {
      activeAuthorIds.add(link.source);
      activeAuthorIds.add(link.target);
    });

    if (activeAuthorIds.size === 0) {
      [...paperIdsByAuthor.entries()]
        .sort((a, b) => b[1].size - a[1].size)
        .slice(0, 20)
        .forEach(([authorId]) => activeAuthorIds.add(authorId));
    }
  } else if (viewMode === 'temporal') {
    paperIdsByTime.forEach((paperIds, timeId) => {
      if (paperIds.size > 0) activeTimeIds.add(timeId);
    });

    [...paperIdsByAuthor.entries()].forEach(([authorId, paperIds]) => {
      const author = authorMap.get(authorId);
      if (!author) return;
      const shouldKeep = paperIds.size >= 2 || (author.is_first_author_count ?? 0) > 0 || (author.is_corresponding_author_count ?? 0) > 0;
      if (shouldKeep) activeAuthorIds.add(authorId);
    });
  } else {
    [...paperIdsByAuthor.keys()].forEach((authorId) => activeAuthorIds.add(authorId));
    paperIdsByTime.forEach((paperIds, timeId) => {
      if (paperIds.size > 0) activeTimeIds.add(timeId);
    });
  }

  institutionMap.forEach((institution, institutionId) => {
    const paperOverlap = (institution.papers ?? []).filter((paperId) => activePaperIds.has(paperId)).length;
    const authorOverlap = (institution.authors ?? []).filter((authorId) => activeAuthorIds.has(authorId)).length;
    const shouldKeep = viewMode === 'collaboration' ? authorOverlap >= 2 : paperOverlap > 0 || authorOverlap > 0;
    if (shouldKeep) activeInstitutionIds.add(institutionId);
  });

  return {
    authorIds: activeAuthorIds,
    institutionIds: activeInstitutionIds,
    timeIds: activeTimeIds,
    paperIds: activePaperIds,
  };
}

function buildGraphNodes(
  activeNodes: ActiveNodes,
  authorMap: Map<string, Author>,
  paperMap: Map<string, Paper>,
  institutionMap: Map<string, Institution>,
  timeMap: Map<string, TimePeriod>,
  paperIdsByAuthor: Map<string, Set<string>>,
  viewMode: string,
): { nodes: GraphNode[]; nodeByGraphId: Map<string, GraphNode> } {
  const nodes: GraphNode[] = [];
  const nodeByGraphId = new Map<string, GraphNode>();

  const addNode = (node: GraphNode) => {
    nodes.push(node);
    nodeByGraphId.set(node.id, node);
  };

  const getAverageYear = (paperIds: Iterable<string>) => {
    const years = [...paperIds]
      .map((paperId) => paperMap.get(paperId)?.year)
      .filter((year): year is number => Boolean(year));
    return years.length > 0 ? years.reduce((sum, year) => sum + year, 0) / years.length : undefined;
  };

  if (viewMode !== 'collaboration') {
    [...activeNodes.paperIds]
      .map((paperId) => paperMap.get(paperId))
      .filter((paper): paper is Paper => paper !== undefined)
      .forEach((paper) => {
        const citationCount = paper.citation_count ?? 0;
        addNode({
          id: `paper:${paper.id}`,
          rawId: paper.id,
          name: paper.title || paper.id,
          type: 'paper',
          radius: clamp(6 + Math.sqrt(citationCount + 1) * 1.7, 6, 16),
          color: NODE_COLORS.paper,
          data: paper,
          rank: citationCount + 1,
          emphasis: citationCount,
          year: paper.year,
        });
      });
  }

  [...activeNodes.authorIds]
    .map((authorId) => authorMap.get(authorId))
    .filter((author): author is Author => author !== undefined)
    .forEach((author) => {
      const relatedPaperIds = paperIdsByAuthor.get(author.id) ?? new Set();
      addNode({
        id: `author:${author.id}`,
        rawId: author.id,
        name: author.name,
        type: 'author',
        radius: clamp(8 + Math.sqrt(relatedPaperIds.size || 1) * 2.4, 8, 18),
        color: NODE_COLORS.author,
        data: author,
        rank: relatedPaperIds.size + (author.total_citations ?? 0) / 25,
        emphasis: relatedPaperIds.size,
        year: getAverageYear(relatedPaperIds),
        clusterKey: author.affiliation || 'Independent',
      });
    });

  [...activeNodes.institutionIds]
    .map((institutionId) => institutionMap.get(institutionId))
    .filter((institution): institution is Institution => institution !== undefined)
    .forEach((institution) => {
      const relevantPaperIds = (institution.papers ?? []).filter((paperId) => activeNodes.paperIds.has(paperId));
      addNode({
        id: `institution:${institution.id}`,
        rawId: institution.id,
        name: institution.name,
        type: 'institution',
        radius: clamp(10 + Math.sqrt(relevantPaperIds.length || 1) * 2.6, 10, 20),
        color: NODE_COLORS.institution,
        data: institution,
        rank: relevantPaperIds.length,
        emphasis: relevantPaperIds.length,
        year: getAverageYear(relevantPaperIds),
        clusterKey: institution.name,
      });
    });

  if (viewMode !== 'collaboration') {
    [...activeNodes.timeIds]
      .map((timeId) => timeMap.get(timeId))
      .filter((period): period is TimePeriod => period !== undefined)
      .forEach((period) => {
        addNode({
          id: `time:${period.id}`,
          rawId: period.id,
          name: String(period.year),
          type: 'time_period',
          radius: 14,
          color: NODE_COLORS.time_period,
          data: period,
          rank: (period.papers ?? []).length,
          emphasis: (period.papers ?? []).length,
          year: period.year,
        });
      });
  }

  return { nodes, nodeByGraphId };
}

function buildGraphLinks(
  activeNodes: ActiveNodes,
  authorshipEdges: Hyperedge[],
  temporalEdges: Hyperedge[],
  citationEdges: any[],
  collaborationLinks: CollaborationLink[],
  authorMap: Map<string, Author>,
  institutionMap: Map<string, Institution>,
  paperMap: Map<string, Paper>,
  timeMap: Map<string, TimePeriod>,
  viewMode: string,
  includeOptions: { collaboration: boolean; influence: boolean },
): GraphLink[] {
  const links: GraphLink[] = [];
  const seenEdges = new Set<string>();

  if (viewMode !== 'collaboration') {
    authorshipEdges.forEach((edge) => {
      const authorId = edge.nodes.find((nodeId) => authorMap.has(normalizeEdgeId(nodeId, 'author_')));
      const paperId = edge.nodes.find((nodeId) => paperMap.has(normalizeEdgeId(nodeId, 'paper_')));
      if (!authorId || !paperId) return;

      const normalizedAuthorId = normalizeEdgeId(authorId, 'author_');
      const normalizedPaperId = normalizeEdgeId(paperId, 'paper_');
      const source = `author:${normalizedAuthorId}`;
      const target = `paper:${normalizedPaperId}`;

      if (!activeNodes.authorIds.has(normalizedAuthorId) || !activeNodes.paperIds.has(normalizedPaperId)) return;
      addEdge(links, seenEdges, {
        source,
        target,
        weight: 1,
        type: 'authorship',
        opacity: viewMode === 'temporal' ? 0.25 : 0.3,
      });
    });

    temporalEdges.forEach((edge) => {
      const paperId = edge.nodes.find((nodeId) => paperMap.has(normalizeEdgeId(nodeId, 'paper_')));
      const timeId = edge.nodes.find((nodeId) => timeMap.has(normalizeEdgeId(nodeId, 'time_')) || timeMap.has(nodeId));
      if (!paperId || !timeId) return;

      const normalizedPaperId = normalizeEdgeId(paperId, 'paper_');
      const normalizedTimeId = normalizeEdgeId(timeId, 'time_');
      const source = `paper:${normalizedPaperId}`;
      const target = `time:${normalizedTimeId}`;

      if (!activeNodes.paperIds.has(normalizedPaperId) || !activeNodes.timeIds.has(normalizedTimeId)) return;
      addEdge(links, seenEdges, {
        source,
        target,
        weight: 1,
        type: 'temporal',
        opacity: viewMode === 'temporal' ? 0.55 : 0.22,
      });
    });

    if (includeOptions.influence) {
      citationEdges
        .filter((edge) => activeNodes.paperIds.has(edge.source) && activeNodes.paperIds.has(edge.target))
        .sort((a, b) => b.weight - a.weight)
        .slice(0, 60)
        .forEach((edge) => {
          const source = `paper:${edge.source}`;
          const target = `paper:${edge.target}`;
          addEdge(links, seenEdges, {
            source,
            target,
            weight: edge.weight ?? 1,
            type: 'citation',
            opacity: 0.12,
          });
        });
    }
  }

  [...activeNodes.authorIds].forEach((authorId) => {
    const author = authorMap.get(authorId);
    if (!author?.affiliation) return;

    const institutionEntry = [...activeNodes.institutionIds]
      .map((institutionId) => institutionMap.get(institutionId))
      .find((institution) => institution?.name === author.affiliation);

    if (!institutionEntry) return;

    const source = `author:${authorId}`;
    const target = `institution:${institutionEntry.id}`;
    addEdge(links, seenEdges, {
      source,
      target,
      weight: 1,
      type: 'affiliation',
      opacity: viewMode === 'collaboration' ? 0.32 : 0.16,
    });
  });

  if (viewMode === 'collaboration') {
    collaborationLinks.forEach((edge) => {
      const source = `author:${edge.source}`;
      const target = `author:${edge.target}`;
      addEdge(links, seenEdges, {
        source,
        target,
        weight: edge.weight,
        type: 'collaboration',
        opacity: 0.2 + Math.min(edge.weight, 4) * 0.15,
      });
    });
  }

  return links;
}

function pruneIsolatedNodes(nodes: GraphNode[], links: GraphLink[]): { nodes: GraphNode[]; links: GraphLink[] } {
  const degreeMap = new Map<string, number>();
  links.forEach((link) => {
    const source = typeof link.source === 'string' ? link.source : link.source.id;
    const target = typeof link.target === 'string' ? link.target : link.target.id;
    degreeMap.set(source, (degreeMap.get(source) ?? 0) + 1);
    degreeMap.set(target, (degreeMap.get(target) ?? 0) + 1);
  });

  const prunedNodes = nodes.filter((node) => (degreeMap.get(node.id) ?? 0) > 0);
  const prunedNodeIds = new Set(prunedNodes.map((node) => node.id));
  const prunedLinks = links.filter((link) => {
    const source = typeof link.source === 'string' ? link.source : link.source.id;
    const target = typeof link.target === 'string' ? link.target : link.target.id;
    return prunedNodeIds.has(source) && prunedNodeIds.has(target);
  });

  return { nodes: prunedNodes, links: prunedLinks };
}

const addEdge = (links: GraphLink[], seen: Set<string>, edge: GraphLink) => {
  const source = typeof edge.source === 'string' ? edge.source : edge.source.id;
  const target = typeof edge.target === 'string' ? edge.target : edge.target.id;
  const key = [edge.type, source, target].sort().join('|');

  if (seen.has(key)) return;
  seen.add(key);
  links.push(edge);
};

const buildAuthorQuery = (authorName: string) => `列出 ${authorName} 已发表的论文，并说明其在每篇论文中的作者位置（第一作者/通讯作者/其他）。`;

export default function HypergraphTimeline() {
  const svgRef = useRef<SVGSVGElement>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  const [dimensions, setDimensions] = useState({ width: 800, height: 680 });

  const [selectedJobId, setSelectedJobId] = useState<string | null>(null);
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null);
  const [activeAnalysisTab, setActiveAnalysisTab] = useState<AnalysisTabKey>('overview');
  const [yearFilter, setYearFilter] = useState<[number, number]>([2000, 2025]);
  const [viewMode, setViewMode] = useState<'full' | 'collaboration' | 'temporal'>('full');
  const [includeOptions, setIncludeOptions] = useState({
    collaboration: true,
    influence: true,
    milestones: true,
  });
  const setActiveTab = useSetActiveTab();
  const queueKnowledgeQuery = useQueueKnowledgeQuery();

  const { data: completedResearch = [], isLoading: researchLoading } = useQuery({
    queryKey: ['completed-research'],
    queryFn: getCompletedResearch,
  });

  const {
    data: hypergraphData,
    isLoading: hypergraphLoading,
    isFetching: hypergraphFetching,
    error: hypergraphError,
    refetch: refetchHypergraph,
  } = useQuery({
    queryKey: [
      'hypergraph-timeline',
      selectedJobId,
      includeOptions.collaboration,
      includeOptions.influence,
      includeOptions.milestones,
    ],
    queryFn: () =>
      getHypergraphTimeline(
        selectedJobId!,
        'full',
        includeOptions.collaboration,
        includeOptions.influence,
        includeOptions.milestones,
      ),
    enabled: !!selectedJobId,
    staleTime: 5 * 60_000,
  });

  useEffect(() => {
    if (!hypergraphError) return;
    message.error(`Failed to load hypergraph: ${(hypergraphError as Error).message}`);
  }, [hypergraphError]);

  useEffect(() => {
    const updateDimensions = () => {
      if (!containerRef.current) return;
      const { width } = containerRef.current.getBoundingClientRect();
      setDimensions({
        width: Math.max(width - 32, 720),
        height: 680,
      });
    };

    updateDimensions();
    window.addEventListener('resize', updateDimensions);
    return () => window.removeEventListener('resize', updateDimensions);
  }, []);


  useEffect(() => {
    if (!hypergraphData?.statistics.time_range.start || !hypergraphData?.statistics.time_range.end) return;
    setYearFilter([
      hypergraphData.statistics.time_range.start,
      hypergraphData.statistics.time_range.end,
    ]);
  }, [hypergraphData?.job_id]);

  const analysis = hypergraphData?.analysis;

  const keyFigureMatches = useMemo(() => {
    if (!analysis?.key_figures?.length || !hypergraphData?.hypergraph.nodes.authors?.length) return [];

    const authors = hypergraphData.hypergraph.nodes.authors as any[];
    const authorById = new Map(authors.map((author) => [author.id, author]));
    const authorsByName = new Map<string, any[]>();

    authors.forEach((author) => {
      const normalizedName = normalizeText(author.name);
      if (!normalizedName) return;
      if (!authorsByName.has(normalizedName)) authorsByName.set(normalizedName, []);
      authorsByName.get(normalizedName)!.push(author);
    });

    return analysis.key_figures.map((figure: KeyFigure) => {
      const normalizedName = normalizeText(figure.name);
      const normalizedInstitution = normalizeText(figure.institution);

      if (figure.author_id && authorById.has(figure.author_id)) {
        const author = authorById.get(figure.author_id)!;
        return {
          authorId: author.id,
          authorName: author.name,
          confidence: figure.match_confidence ?? 1,
        } satisfies AuthorMatch;
      }

      const candidates = authorsByName.get(normalizedName) ?? [];
      if (candidates.length === 0) return null;

      const scored = candidates
        .map((author) => {
          let score = 0;
          if (normalizeText(author.name) === normalizedName) score += 3;
          if (normalizedInstitution && normalizeText(author.affiliation).includes(normalizedInstitution)) score += 2;
          score += Math.min((author.total_citations ?? 0) / 100, 1.5);
          score += Math.min((author.papers?.length ?? 0) / 10, 1);
          score += Math.min((author.is_first_author_count ?? 0) / 5, 0.75);
          score += Math.min((author.is_corresponding_author_count ?? 0) / 5, 0.75);
          return { author, score };
        })
        .sort((left, right) => right.score - left.score);

      const [best, runnerUp] = scored;
      if (!best || best.score < 3) return null;
      if (runnerUp && best.score - runnerUp.score < 0.5) return null;

      return {
        authorId: best.author.id,
        authorName: best.author.name,
        confidence: Math.min(best.score / 6, 1),
      } satisfies AuthorMatch;
    });
  }, [analysis?.key_figures, hypergraphData?.hypergraph.nodes.authors]);

  const keyFigureAuthorIds = useMemo(
    () => new Set(keyFigureMatches.filter(Boolean).map((match) => `author:${match!.authorId}`)),
    [keyFigureMatches],
  );

  const analysisShortcuts = useMemo(() => ([
    { key: 'overview' as const, label: 'Overview', count: undefined },
    { key: 'figures' as const, label: 'Key Figures', count: analysis?.key_figures?.length || 0 },
    { key: 'collaboration' as const, label: 'Clusters', count: analysis?.collaboration_clusters?.length || 0 },
    { key: 'milestones' as const, label: 'Milestones', count: analysis?.milestones?.length || 0 },
    { key: 'debates' as const, label: 'Debates', count: analysis?.debates?.length || 0 },
  ]), [analysis]);

  const openKnowledgeForAuthor = useCallback((authorName: string) => {
    if (!hypergraphData?.topic) return;
    queueKnowledgeQuery(buildAuthorQuery(authorName), hypergraphData.topic);
    setActiveTab('knowledge');
  }, [hypergraphData?.topic, queueKnowledgeQuery, setActiveTab]);

  const focusAuthorInGraph = useCallback((authorId: string, panelKey: AnalysisTabKey = 'figures') => {
    setActiveAnalysisTab(panelKey);
    setSelectedNodeId(`author:${authorId}`);
  }, []);

  const convertToGraphData = useCallback((): GraphData => {
    if (!hypergraphData) {
      return { nodes: [], links: [], neighbors: new Map() };
    }

    const { authors, papers, institutions, time_periods } = hypergraphData.hypergraph.nodes;
    const authorMap = new Map(authors.map((author: any) => [author.id, author]));
    const paperMap = new Map(papers.map((paper: any) => [paper.id, paper]));
    const institutionMap = new Map(institutions.map((institution: any) => [institution.id, institution]));
    const timeMap = new Map(time_periods.map((period: any) => [period.id, period]));

    const filteredPaperIds = filterPapersByYear([...paperMap.values()], yearFilter);

    const edges = hypergraphData.hypergraph.hyperedges;
    const authorshipEdges = edges.filter((edge: any) => edge.type === 'authorship');
    const temporalEdges = edges.filter((edge: any) => edge.type === 'temporal');
    const coauthorshipEdges = edges.filter((edge: any) => edge.type === 'coauthorship');
    const citationEdges = (hypergraphData.hypergraph as any).citation_edges ?? [];

    const paperIdsByAuthor = buildAuthorshipIndex(authorshipEdges, authorMap, paperMap, filteredPaperIds);
    const paperIdsByTime = buildTemporalIndex(temporalEdges, paperMap, timeMap, filteredPaperIds);

    const collaborationLinks = buildCollaborationLinks(coauthorshipEdges, authorMap, filteredPaperIds, includeOptions.collaboration);

    const activeNodes = determineActiveNodes(
      viewMode,
      paperIdsByAuthor,
      paperIdsByTime,
      collaborationLinks,
      authorMap,
      institutionMap,
      filteredPaperIds,
    );

    const { nodes: graphNodes } = buildGraphNodes(
      activeNodes,
      authorMap,
      paperMap,
      institutionMap,
      timeMap,
      paperIdsByAuthor,
      viewMode,
    );

    const graphLinks = buildGraphLinks(
      activeNodes,
      authorshipEdges,
      temporalEdges,
      citationEdges,
      collaborationLinks,
      authorMap,
      institutionMap,
      paperMap,
      timeMap,
      viewMode,
      includeOptions,
    );

    const { nodes: prunedNodes, links: prunedLinks } = pruneIsolatedNodes(graphNodes, graphLinks);

    return {
      nodes: prunedNodes,
      links: prunedLinks,
      neighbors: buildNeighborMap(prunedLinks),
    };
  }, [hypergraphData, includeOptions, viewMode, yearFilter]);

  const graphData = useMemo(() => convertToGraphData(), [convertToGraphData]);

  const visibleStats = useMemo(() => (
    graphData.nodes.reduce(
      (stats, node) => {
        if (node.type === 'paper') stats.papers += 1;
        if (node.type === 'author') stats.authors += 1;
        return stats;
      },
      { papers: 0, authors: 0 },
    )
  ), [graphData.nodes]);

  const selectedNode = useMemo(
    () => graphData.nodes.find((node) => node.id === selectedNodeId) ?? null,
    [graphData.nodes, selectedNodeId],
  );

  useEffect(() => {
    if (selectedNodeId && !graphData.nodes.some((node) => node.id === selectedNodeId)) {
      setSelectedNodeId(null);
    }
  }, [graphData.nodes, selectedNodeId]);

  useEffect(() => {
    if (!svgRef.current || !hypergraphData || graphData.nodes.length === 0) return;

    const { width, height } = dimensions;
    const nodes = graphData.nodes.map((node) => ({ ...node }));
    const links = graphData.links.map((link) => ({ ...link }));
    const highlightedNodeIds = new Set<string>();

    if (selectedNodeId) {
      highlightedNodeIds.add(selectedNodeId);
      graphData.neighbors.get(selectedNodeId)?.forEach((nodeId) => highlightedNodeIds.add(nodeId));
    }

    const svg = d3.select(svgRef.current);
    svg.selectAll('*').remove();
    svg.attr('width', width).attr('height', height);

    const inner = svg.append('g');

    const yearValues = [...new Set(nodes.map((node) => node.year).filter((year): year is number => Boolean(year)))].sort((a, b) => a - b);
    const yearScale = d3.scalePoint<number>()
      .domain(yearValues.length > 0 ? yearValues : [yearFilter[0], yearFilter[1]])
      .range([80, Math.max(160, width - 80)]);

    const institutionNames = [...new Set(
      nodes
        .filter((node) => node.type === 'institution')
        .map((node) => node.clusterKey || node.name),
    )];

    const institutionScale = d3.scalePoint<string>()
      .domain(institutionNames.length > 0 ? institutionNames : ['Independent'])
      .range([100, Math.max(160, width - 100)]);

    nodes.forEach((node) => {
      if (viewMode === 'temporal') {
        if (node.type === 'time_period') {
          node.anchorX = yearScale(node.year ?? yearFilter[0]);
          node.anchorY = 120;
        } else if (node.type === 'paper') {
          node.anchorX = yearScale(node.year ?? yearFilter[0]);
          node.anchorY = height * 0.48;
        } else {
          node.anchorX = yearScale(node.year ?? yearFilter[0]);
          node.anchorY = 250;
        }
      } else if (viewMode === 'collaboration') {
        const cluster = node.type === 'institution' ? (node.clusterKey || node.name) : (node.clusterKey || 'Independent');
        node.anchorX = institutionScale(cluster);
        node.anchorY = node.type === 'institution' ? 160 : 420;
      } else {
        const laneY = {
          author: 130,
          paper: 320,
          institution: 520,
          time_period: 620,
        }[node.type];
        node.anchorY = laneY;
        node.anchorX = node.year ? yearScale(node.year) : width / 2;
      }
    });

    const zoom = d3.zoom<SVGSVGElement, unknown>()
      .scaleExtent([0.5, 3])
      .on('zoom', (event) => {
        inner.attr('transform', event.transform);
      });

    svg.call(zoom);

    const simulation = d3.forceSimulation<GraphNode>(nodes)
      .force('link', d3.forceLink<GraphNode, GraphLink>(links)
        .id((node) => node.id)
        .distance((link) => {
          if (link.type === 'temporal') return viewMode === 'temporal' ? 55 : 90;
          if (link.type === 'authorship') return 70;
          if (link.type === 'affiliation') return viewMode === 'collaboration' ? 60 : 90;
          if (link.type === 'citation') return 120;
          return 80;
        })
        .strength((link) => {
          if (link.type === 'collaboration') return 0.45;
          if (link.type === 'temporal') return viewMode === 'temporal' ? 0.7 : 0.35;
          if (link.type === 'affiliation') return 0.28;
          if (link.type === 'citation') return 0.1;
          return 0.3;
        }))
      .force('charge', d3.forceManyBody().strength(viewMode === 'collaboration' ? -180 : -140))
      .force('collide', d3.forceCollide<GraphNode>().radius((node) => node.radius + 8).strength(0.9))
      .force('x', d3.forceX<GraphNode>((node) => node.anchorX ?? width / 2).strength(viewMode === 'collaboration' ? 0.28 : 0.22))
      .force('y', d3.forceY<GraphNode>((node) => node.anchorY ?? height / 2).strength(viewMode === 'temporal' ? 0.3 : 0.24))
      .force('center', d3.forceCenter(width / 2, height / 2).strength(0.05));

    const link = inner.append('g')
      .selectAll('line')
      .data(links)
      .enter()
      .append('line')
      .attr('stroke', (datum) => {
        if (datum.type === 'temporal') return '#722ed1';
        if (datum.type === 'authorship') return '#52c41a';
        if (datum.type === 'collaboration') return '#1677ff';
        if (datum.type === 'affiliation') return '#fa8c16';
        return '#8c8c8c';
      })
      .attr('stroke-width', (datum) => clamp(1 + Math.sqrt(datum.weight), 1, 4))
      .attr('stroke-opacity', (datum) => {
        if (!selectedNodeId) return datum.opacity;
        const source = typeof datum.source === 'string' ? datum.source : datum.source.id;
        const target = typeof datum.target === 'string' ? datum.target : datum.target.id;
        return highlightedNodeIds.has(source) && highlightedNodeIds.has(target) ? Math.max(datum.opacity, 0.45) : 0.04;
      })
      .attr('stroke-dasharray', (datum) => datum.type === 'citation' ? '5 4' : null);

    const keyFigureRings = inner.append('g')
      .selectAll('circle')
      .data(nodes.filter((datum) => keyFigureAuthorIds.has(datum.id)))
      .enter()
      .append('circle')
      .attr('r', (datum) => datum.radius + 5)
      .attr('fill', 'none')
      .attr('stroke', '#faad14')
      .attr('stroke-width', (datum) => datum.id === selectedNodeId ? 4 : 2.5)
      .attr('stroke-opacity', (datum) => {
        if (!selectedNodeId) return 0.95;
        return highlightedNodeIds.has(datum.id) ? 1 : 0.3;
      })
      .style('pointer-events', 'none');

    const node = inner.append('g')
      .selectAll('circle')
      .data(nodes)
      .enter()
      .append('circle')
      .attr('r', (datum) => datum.radius)
      .attr('fill', (datum) => datum.color)
      .attr('stroke', (datum) => {
        if (datum.id === selectedNodeId) return '#111111';
        if (highlightedNodeIds.has(datum.id)) return '#111111';
        if (keyFigureAuthorIds.has(datum.id)) return '#faad14';
        return '#ffffff';
      })
      .attr('stroke-width', (datum) => {
        if (datum.id === selectedNodeId) return 3;
        if (highlightedNodeIds.has(datum.id)) return 2;
        if (keyFigureAuthorIds.has(datum.id)) return 2.5;
        return 1.5;
      })
      .attr('fill-opacity', (datum) => {
        if (!selectedNodeId) return 0.94;
        return highlightedNodeIds.has(datum.id) ? 0.98 : 0.14;
      })
      .style('cursor', 'pointer')
      .call(d3.drag<SVGCircleElement, GraphNode>()
        .on('start', (event, datum) => {
          if (!event.active) simulation.alphaTarget(0.25).restart();
          datum.fx = datum.x;
          datum.fy = datum.y;
        })
        .on('drag', (event, datum) => {
          datum.fx = event.x;
          datum.fy = event.y;
        })
        .on('end', (event, datum) => {
          if (!event.active) simulation.alphaTarget(0);
          datum.fx = null;
          datum.fy = null;
        }))
      .on('click', (_, datum) => {
        setSelectedNodeId((current) => current === datum.id ? null : datum.id);
      });

    node.append('title').text((datum) => datum.name);

    const labeledNodes = nodes.filter((datum) => {
      if (datum.id === selectedNodeId) return true;
      if (highlightedNodeIds.has(datum.id)) return true;
      if (keyFigureAuthorIds.has(datum.id)) return true;
      if (datum.type === 'time_period') return true;
      if (datum.type === 'author') return true;
      if (viewMode === 'collaboration') {
        return datum.type === 'institution';
      }
      if (viewMode === 'temporal') {
        return datum.type === 'paper' && datum.rank >= 15;
      }
      return datum.type === 'institution' && datum.rank >= 3;
    }).slice(0, 60);

    const labels = inner.append('g')
      .selectAll('text')
      .data(labeledNodes)
      .enter()
      .append('text')
      .text((datum) => {
        const baseName = datum.type === 'paper'
          ? `${datum.name.slice(0, 28)}${datum.name.length > 28 ? '…' : ''}`
          : datum.name;
        return keyFigureAuthorIds.has(datum.id) ? `★ ${baseName}` : baseName;
      })
      .attr('font-size', (datum) => datum.id === selectedNodeId ? '12px' : datum.type === 'author' ? '11px' : '10px')
      .attr('font-weight', (datum) => {
        if (datum.id === selectedNodeId || highlightedNodeIds.has(datum.id) || keyFigureAuthorIds.has(datum.id)) return 700;
        return datum.type === 'author' ? 600 : 500;
      })
      .attr('text-anchor', 'middle')
      .attr('fill', (datum) => keyFigureAuthorIds.has(datum.id) ? '#ad6800' : '#262626')
      .style('pointer-events', 'none')
      .style('paint-order', 'stroke')
      .style('stroke', '#ffffff')
      .style('stroke-width', 3)
      .style('stroke-linejoin', 'round')
      .style('opacity', (datum) => {
        if (!selectedNodeId) return 0.88;
        return highlightedNodeIds.has(datum.id) || keyFigureAuthorIds.has(datum.id) ? 1 : 0.2;
      });

    simulation.on('tick', () => {
      link
        .attr('x1', (datum) => (datum.source as GraphNode).x ?? 0)
        .attr('y1', (datum) => (datum.source as GraphNode).y ?? 0)
        .attr('x2', (datum) => (datum.target as GraphNode).x ?? 0)
        .attr('y2', (datum) => (datum.target as GraphNode).y ?? 0);

      keyFigureRings
        .attr('cx', (datum) => datum.x ?? 0)
        .attr('cy', (datum) => datum.y ?? 0);

      node
        .attr('cx', (datum) => datum.x ?? 0)
        .attr('cy', (datum) => datum.y ?? 0);

      labels
        .attr('x', (datum) => datum.x ?? 0)
        .attr('y', (datum) => (datum.y ?? 0) + datum.radius + 14);
    });

    return () => {
      simulation.stop();
    };
  }, [dimensions, graphData, hypergraphData, selectedNodeId, viewMode, yearFilter, keyFigureAuthorIds]);

  const renderMethodHint = (tabKey: AnalysisTabKey) => (
    <Paragraph type="secondary" style={{ marginBottom: 12 }}>
      分析方法：{ANALYSIS_METHODS[tabKey]}
    </Paragraph>
  );

  const renderAuthorAction = (authorName: string) => (
    <Link onClick={(event) => {
      event.stopPropagation();
      openKnowledgeForAuthor(authorName);
    }}>
      {authorName}
    </Link>
  );

  const renderNodeDetails = () => {
    if (!selectedNode) return null;

    const { type, data, name } = selectedNode;

    if (type === 'author') {
      return (
        <Card title="Author Details" size="small">
          <Space direction="vertical" style={{ width: '100%' }}>
            <Title level={5} style={{ marginBottom: 0 }}>{name}</Title>
            <Text type="secondary">{data.affiliation || 'No affiliation'}</Text>
            <Link onClick={() => openKnowledgeForAuthor(name)}>查询该作者的论文与作者位置</Link>
            <Divider />
            <Text>Papers: {data.papers?.length || 0}</Text>
            <Text>First author: {data.is_first_author_count || 0} papers</Text>
            <Text>Corresponding author: {data.is_corresponding_author_count || 0} papers</Text>
            <Text>Coauthors: {data.coauthors?.length || 0}</Text>
            <Text>Total citations: {data.total_citations || 0}</Text>
          </Space>
        </Card>
      );
    }

    if (type === 'paper') {
      return (
        <Card title="Paper Details" size="small">
          <Space direction="vertical" style={{ width: '100%' }}>
            <Text strong>{data.title}</Text>
            <Text type="secondary">{data.journal || 'Unknown journal'}</Text>
            <Divider />
            <Text>Year: {data.year || 'Unknown'}</Text>
            <Text>Citations: {data.citation_count || 0}</Text>
            {data.doi ? <Text copyable={{ text: data.doi }}>DOI: {data.doi}</Text> : null}
          </Space>
        </Card>
      );
    }

    if (type === 'institution') {
      return (
        <Card title="Institution Details" size="small">
          <Space direction="vertical" style={{ width: '100%' }}>
            <Title level={5}>{name}</Title>
            <Text>Authors: {data.authors?.length || 0}</Text>
            <Text>Papers: {data.papers?.length || 0}</Text>
          </Space>
        </Card>
      );
    }

    return (
      <Card title="Time Period Details" size="small">
        <Space direction="vertical" style={{ width: '100%' }}>
          <Title level={5}>{name}</Title>
          <Text>Papers: {data.papers?.length || 0}</Text>
        </Space>
      </Card>
    );
  };

  return (
    <Space direction="vertical" style={{ width: '100%' }} size="large">
      <Card>
        <Title level={4}>
          <ShareAltOutlined /> Hypergraph Timeline Analysis
        </Title>
        <Paragraph type="secondary">
          Explore collaboration, evolution over time, and institution structure without collapsing everything into a single dense blob.
        </Paragraph>

        <Space style={{ width: '100%', marginBottom: 16 }} wrap>
          <Text strong>Select Research Results:</Text>
          <Select
            style={{ width: 400 }}
            placeholder="Choose completed research..."
            loading={researchLoading}
            onChange={(value) => {
              setSelectedJobId(value);
              setSelectedNodeId(null);
              setActiveAnalysisTab('overview');
            }}
            value={selectedJobId}
          >
            {completedResearch.map((research: CompletedResearch) => (
              <Option key={research.job_id} value={research.job_id}>
                {research.topic} ({research.paper_count} papers)
              </Option>
            ))}
          </Select>
          <Button
            icon={<ReloadOutlined />}
            onClick={() => selectedJobId && refetchHypergraph()}
            loading={hypergraphFetching}
          >
            Refresh
          </Button>
        </Space>

        {hypergraphData && (
          <Space style={{ width: '100%' }} wrap>
            <Text>Year Range:</Text>
            <Slider
              range
              min={hypergraphData.statistics.time_range.start}
              max={hypergraphData.statistics.time_range.end}
              value={yearFilter}
              onChange={(value) => {
                setSelectedNodeId(null);
                setYearFilter(value as [number, number]);
              }}
              style={{ width: 240 }}
            />
            <Select value={viewMode} onChange={(value) => {
              setSelectedNodeId(null);
              setViewMode(value);
            }} style={{ width: 170 }}>
              <Option value="full">Layered View</Option>
              <Option value="collaboration">Collaboration</Option>
              <Option value="temporal">Temporal</Option>
            </Select>
            <Checkbox
              checked={includeOptions.collaboration}
              onChange={(event) => setIncludeOptions({ ...includeOptions, collaboration: event.target.checked })}
            >
              Collaboration
            </Checkbox>
            <Checkbox
              checked={includeOptions.influence}
              onChange={(event) => setIncludeOptions({ ...includeOptions, influence: event.target.checked })}
            >
              Influence
            </Checkbox>
            <Checkbox
              checked={includeOptions.milestones}
              onChange={(event) => setIncludeOptions({ ...includeOptions, milestones: event.target.checked })}
            >
              Milestones
            </Checkbox>
          </Space>
        )}
      </Card>

      {hypergraphLoading ? (
        <Card>
          <Spin size="large" tip="Building hypergraph...">
            <div style={{ height: 680 }} />
          </Spin>
        </Card>
      ) : hypergraphData ? (
        <Card
          title={
            <Space wrap>
              <Space>
                <GlobalOutlined />
                <span>Hypergraph Visualization</span>
              </Space>
              <Badge count={visibleStats.papers} showZero color="#52c41a" />
              <Text type="secondary">visible papers</Text>
              <Badge count={visibleStats.authors} showZero color="#1677ff" />
              <Text type="secondary">visible authors</Text>
              <Badge count={graphData.links.length} showZero color="#8c8c8c" />
              <Text type="secondary">visible links</Text>
            </Space>
          }
        >
          <div ref={containerRef} style={{ width: '100%' }}>
            <svg
              ref={svgRef}
              style={{
                border: '1px solid #d9d9d9',
                borderRadius: 8,
                background: 'linear-gradient(180deg, #fafafa 0%, #f5f5f5 100%)',
                cursor: 'grab',
                width: '100%',
              }}
            />
          </div>

          <div style={{ marginTop: 16 }}>
            <Space wrap>
              <Tag color="#1677ff">Author</Tag>
              <Tag color="#52c41a">Paper</Tag>
              <Tag color="#fa8c16">Institution</Tag>
              <Tag color="#722ed1">Time Period</Tag>
              <Tag color="#faad14">Key Figure</Tag>
              <Text type="secondary">Click a node to highlight its neighborhood. Drag to reposition. Scroll to zoom.</Text>
            </Space>
          </div>
        </Card>
      ) : selectedJobId ? (
        <Empty description="Failed to load hypergraph data" />
      ) : (
        <Empty description="Select a research result to visualize" />
      )}

      {analysis && (
        <Card>
          <Space wrap style={{ marginBottom: 16 }}>
            {analysisShortcuts.map((item) => (
              <Button
                key={item.key}
                type={activeAnalysisTab === item.key ? 'primary' : 'default'}
                onClick={() => setActiveAnalysisTab(item.key)}
              >
                {item.label}
                {typeof item.count === 'number' ? ` (${item.count})` : ''}
              </Button>
            ))}
          </Space>

          <Tabs
            activeKey={activeAnalysisTab}
            onChange={(key) => setActiveAnalysisTab(key as AnalysisTabKey)}
            items={[
              {
                key: 'overview',
                label: (
                  <Space>
                    <BookOutlined /> Overview
                  </Space>
                ),
                children: (
                  <Space direction="vertical" style={{ width: '100%' }}>
                    {renderMethodHint('overview')}
                    <Paragraph>{analysis.summary}</Paragraph>
                    <Title level={5}>Consensus Areas</Title>
                    <Space wrap>
                      {analysis.consensus_areas?.map((area: string) => (
                        <Tag key={area} color="green">{area}</Tag>
                      ))}
                    </Space>
                    <Title level={5}>Temporal Patterns</Title>
                    <Paragraph>{analysis.temporal_patterns}</Paragraph>
                  </Space>
                ),
              },
              {
                key: 'figures',
                label: (
                  <Space>
                    <TrophyOutlined /> Key Figures ({analysis.key_figures?.length || 0})
                  </Space>
                ),
                children: (
                  <Space direction="vertical" style={{ width: '100%' }}>
                    {renderMethodHint('figures')}
                    <List
                      dataSource={analysis.key_figures}
                      renderItem={(figure: KeyFigure, index: number) => {
                        const match = keyFigureMatches[index];
                        return (
                          <List.Item
                            style={{ cursor: match ? 'pointer' : 'default' }}
                            onClick={() => match && focusAuthorInGraph(match.authorId, 'figures')}
                            actions={match ? [
                              <Button key="locate" type="link" onClick={(event) => {
                                event.stopPropagation();
                                focusAuthorInGraph(match.authorId, 'figures');
                              }}>
                                在图中定位
                              </Button>,
                            ] : undefined}
                          >
                            <List.Item.Meta
                              title={(
                                <Space wrap>
                                  <Text strong>{renderAuthorAction(figure.name)}</Text>
                                  <Tag color="gold">Score: {figure.influence_score.toFixed(1)}</Tag>
                                  {match ? <Tag color="blue">图中已标注</Tag> : null}
                                </Space>
                              )}
                              description={(
                                <Space direction="vertical" size={0}>
                                  <Text type="secondary">{figure.institution}</Text>
                                  <Text>{figure.role}</Text>
                                </Space>
                              )}
                            />
                          </List.Item>
                        );
                      }}
                    />
                  </Space>
                ),
              },
              {
                key: 'collaboration',
                label: (
                  <Space>
                    <TeamOutlined /> Clusters ({analysis.collaboration_clusters?.length || 0})
                  </Space>
                ),
                children: (
                  <Space direction="vertical" style={{ width: '100%' }}>
                    {renderMethodHint('collaboration')}
                    <List
                      dataSource={analysis.collaboration_clusters}
                      renderItem={(cluster: CollaborationCluster) => (
                        <List.Item>
                          <List.Item.Meta
                            title={cluster.institution || `Cluster ${cluster.id}`}
                            description={(
                              <Space direction="vertical" size={8} style={{ width: '100%' }}>
                                <Text>{cluster.members?.length || 0} members</Text>
                                <Text>{cluster.paper_count} papers</Text>
                                <Space wrap>
                                  {cluster.members?.map((member) => (
                                    <Tag
                                      key={`${cluster.id}-${member}`}
                                      color="processing"
                                      style={{ cursor: 'pointer' }}
                                      onClick={(event) => {
                                        event.stopPropagation();
                                        openKnowledgeForAuthor(member);
                                      }}
                                    >
                                      {member}
                                    </Tag>
                                  ))}
                                </Space>
                              </Space>
                            )}
                          />
                        </List.Item>
                      )}
                    />
                  </Space>
                ),
              },
              {
                key: 'milestones',
                label: (
                  <Space>
                    <ClockCircleOutlined /> Milestones ({analysis.milestones?.length || 0})
                  </Space>
                ),
                children: (
                  <Space direction="vertical" style={{ width: '100%' }}>
                    {renderMethodHint('milestones')}
                    <List
                      dataSource={analysis.milestones}
                      renderItem={(milestone: Milestone) => (
                        <List.Item>
                          <List.Item.Meta
                            title={(
                              <Space>
                                <Tag color="blue">{milestone.year}</Tag>
                                <Text strong>{milestone.event}</Text>
                              </Space>
                            )}
                            description={(
                              <Space direction="vertical" size={0}>
                                <Text>{milestone.significance}</Text>
                                <Text type="secondary">Key papers: {milestone.key_papers?.length || 0}</Text>
                              </Space>
                            )}
                          />
                        </List.Item>
                      )}
                    />
                  </Space>
                ),
              },
              {
                key: 'debates',
                label: (
                  <Space>
                    <BulbOutlined /> Debates ({analysis.debates?.length || 0})
                  </Space>
                ),
                children: (
                  <Space direction="vertical" style={{ width: '100%' }}>
                    {renderMethodHint('debates')}
                    <List
                      dataSource={analysis.debates}
                      renderItem={(debate: Debate) => (
                        <List.Item>
                          <List.Item.Meta
                            title={(
                              <Space>
                                <Text strong>{debate.topic}</Text>
                                <Tag color={debate.status === 'ongoing' ? 'orange' : 'green'}>
                                  {debate.status}
                                </Tag>
                              </Space>
                            )}
                            description={<Text type="secondary">Sides: {debate.sides?.join(' vs ')}</Text>}
                          />
                        </List.Item>
                      )}
                    />
                  </Space>
                ),
              },
            ]}
          />
        </Card>
      )}

      {selectedNode && (
        <div style={{ position: 'fixed', right: 24, bottom: 24, width: 320, zIndex: 1000 }}>
          {renderNodeDetails()}
        </div>
      )}
    </Space>
  );
}
