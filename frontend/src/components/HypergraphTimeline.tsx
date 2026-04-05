import { useState, useEffect, useRef, useCallback } from 'react';
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
  Tooltip,
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
import { useQuery, useMutation } from '@tanstack/react-query';
import * as d3 from 'd3';
import {
  getCompletedResearch,
  getHypergraphTimeline,
} from '../utils/api';
import type {
  CompletedResearch,
  HypergraphTimelineResponse,
  HypergraphNode,
  KeyFigure,
  CollaborationCluster,
  Milestone,
  Debate,
} from '../types';

const { Text, Title, Paragraph } = Typography;
const { Option } = Select;

// D3 force-directed graph for hypergraph visualization
interface GraphData {
  nodes: GraphNode[];
  links: GraphLink[];
}

interface GraphNode extends d3.SimulationNodeDatum {
  id: string;
  name: string;
  type: 'author' | 'paper' | 'institution' | 'time_period';
  radius: number;
  color: string;
  data: any;
}

interface GraphLink extends d3.SimulationLinkDatum<GraphNode> {
  source: string | GraphNode;
  target: string | GraphNode;
  weight: number;
  type: string;
}

export default function HypergraphTimeline() {
  const svgRef = useRef<SVGSVGElement>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  const [dimensions, setDimensions] = useState({ width: 800, height: 600 });

  const [selectedJobId, setSelectedJobId] = useState<string | null>(null);
  const [selectedNode, setSelectedNode] = useState<GraphNode | null>(null);
  const [yearFilter, setYearFilter] = useState<[number, number]>([2000, 2025]);
  const [viewMode, setViewMode] = useState<'full' | 'collaboration' | 'temporal'>('full');
  const [includeOptions, setIncludeOptions] = useState({
    collaboration: true,
    influence: true,
    milestones: true,
  });

  // Get completed research
  const { data: completedResearch = [], isLoading: researchLoading } = useQuery({
    queryKey: ['completed-research'],
    queryFn: getCompletedResearch,
  });

  // Get hypergraph data
  const {
    data: hypergraphData,
    isPending: hypergraphLoading,
    mutate: fetchHypergraph,
  } = useMutation({
    mutationFn: () =>
      getHypergraphTimeline(
        selectedJobId!,
        'full',
        includeOptions.collaboration,
        includeOptions.influence,
        includeOptions.milestones,
      ),
    onError: (error: any) => {
      message.error(`Failed to load hypergraph: ${error.message}`);
    },
  });

  // Update dimensions on resize
  useEffect(() => {
    const updateDimensions = () => {
      if (containerRef.current) {
        const { width } = containerRef.current.getBoundingClientRect();
        setDimensions({
          width: Math.max(width - 32, 600),
          height: 600,
        });
      }
    };

    updateDimensions();
    window.addEventListener('resize', updateDimensions);
    return () => window.removeEventListener('resize', updateDimensions);
  }, []);

  // Fetch hypergraph when job is selected
  useEffect(() => {
    if (selectedJobId) {
      fetchHypergraph();
    }
  }, [selectedJobId]);

  // Convert hypergraph data to D3 format
  const convertToGraphData = useCallback((): GraphData => {
    if (!hypergraphData) return { nodes: [], links: [] };

    const nodes: GraphNode[] = [];
    const links: GraphLink[] = [];
    const nodeMap = new Map<string, GraphNode>();

    // Add author nodes
    hypergraphData.hypergraph.nodes.authors.forEach((author: any) => {
      const node: GraphNode = {
        id: `author_${author.id}`,
        name: author.name,
        type: 'author',
        radius: 8 + Math.sqrt(author.papers?.length || 1) * 3,
        color: '#1890ff',
        data: author,
      };
      nodes.push(node);
      nodeMap.set(node.id, node);
    });

    // Add paper nodes
    hypergraphData.hypergraph.nodes.papers.forEach((paper: any) => {
      // Filter by year
      if (paper.year && (paper.year < yearFilter[0] || paper.year > yearFilter[1])) {
        return;
      }

      const node: GraphNode = {
        id: `paper_${paper.id}`,
        name: paper.title?.substring(0, 30) + '...' || paper.id,
        type: 'paper',
        radius: 6 + (paper.citation_count || 0) * 0.5,
        color: '#52c41a',
        data: paper,
      };
      nodes.push(node);
      nodeMap.set(node.id, node);
    });

    // Add institution nodes
    hypergraphData.hypergraph.nodes.institutions.forEach((inst: any) => {
      const node: GraphNode = {
        id: `inst_${inst.id}`,
        name: inst.name?.substring(0, 30) || inst.id,
        type: 'institution',
        radius: 12 + (inst.papers?.length || 0) * 2,
        color: '#faad14',
        data: inst,
      };
      nodes.push(node);
      nodeMap.set(node.id, node);
    });

    // Add time period nodes
    hypergraphData.hypergraph.nodes.time_periods.forEach((period: any) => {
      const node: GraphNode = {
        id: `time_${period.id}`,
        name: String(period.year),
        type: 'time_period',
        radius: 15,
        color: '#722ed1',
        data: period,
      };
      nodes.push(node);
      nodeMap.set(node.id, node);
    });

    // Add links based on hyperedges
    hypergraphData.hypergraph.hyperedges.forEach((edge: any) => {
      if (edge.type === 'coauthorship' && viewMode !== 'temporal') {
        // Create pairwise links for co-authorship
        const authorNodes = edge.nodes
          .filter((id: string) => nodeMap.has(`author_${id}`))
          .map((id: string) => nodeMap.get(`author_${id}`)!);

        for (let i = 0; i < authorNodes.length; i++) {
          for (let j = i + 1; j < authorNodes.length; j++) {
            links.push({
              source: authorNodes[i].id,
              target: authorNodes[j].id,
              weight: edge.weight,
              type: 'coauthorship',
            });
          }
        }
      } else if (edge.type === 'authorship') {
        // Link author to paper
        const authorId = edge.nodes.find((n: string) => n.startsWith('author_') || nodeMap.has(`author_${n}`));
        const paperId = edge.nodes.find((n: string) => n.startsWith('paper_') || nodeMap.has(`paper_${n}`));

        if (authorId && paperId) {
          const authorKey = authorId.startsWith('author_') ? authorId : `author_${authorId}`;
          const paperKey = paperId.startsWith('paper_') ? paperId : `paper_${paperId}`;

          if (nodeMap.has(authorKey) && nodeMap.has(paperKey)) {
            links.push({
              source: authorKey,
              target: paperKey,
              weight: edge.weight,
              type: 'authorship',
            });
          }
        }
      } else if (edge.type === 'temporal' && viewMode !== 'collaboration') {
        // Link paper to time period
        const paperId = edge.nodes.find((n: string) => n.startsWith('paper_') || nodeMap.has(`paper_${n}`));
        const timeId = edge.nodes.find((n: string) => n.startsWith('time_') || nodeMap.has(`time_${n}`));

        if (paperId && timeId) {
          const paperKey = paperId.startsWith('paper_') ? paperId : `paper_${paperId}`;
          const timeKey = timeId.startsWith('time_') ? timeId : `time_${timeId}`;

          if (nodeMap.has(paperKey) && nodeMap.has(timeKey)) {
            links.push({
              source: paperKey,
              target: timeKey,
              weight: edge.weight,
              type: 'temporal',
            });
          }
        }
      }
    });

    return { nodes, links };
  }, [hypergraphData, yearFilter, viewMode]);

  // Render D3 graph
  useEffect(() => {
    if (!svgRef.current || !hypergraphData) return;

    const { width, height } = dimensions;
    const { nodes, links } = convertToGraphData();

    if (nodes.length === 0) return;

    // Clear previous content
    d3.select(svgRef.current).selectAll('*').remove();

    const svg = d3.select(svgRef.current)
      .attr('width', width)
      .attr('height', height);

    // Add zoom behavior
    const g = svg.append('g');

    const zoom = d3.zoom<SVGSVGElement, unknown>()
      .scaleExtent([0.1, 4])
      .on('zoom', (event) => {
        g.attr('transform', event.transform);
      });

    svg.call(zoom);

    // Create simulation
    const simulation = d3.forceSimulation<GraphNode>(nodes)
      .force('link', d3.forceLink<GraphNode, GraphLink>(links)
        .id(d => d.id)
        .distance(100)
        .strength(d => d.weight * 0.5))
      .force('charge', d3.forceManyBody().strength(-300))
      .force('center', d3.forceCenter(width / 2, height / 2))
      .force('collision', d3.forceCollide<GraphNode>().radius(d => d.radius + 5));

    // Create links
    const link = g.append('g')
      .attr('stroke', '#999')
      .attr('stroke-opacity', 0.6)
      .selectAll('line')
      .data(links)
      .enter()
      .append('line')
      .attr('stroke-width', d => Math.sqrt(d.weight))
      .attr('stroke', d => {
        if (d.type === 'coauthorship') return '#1890ff';
        if (d.type === 'authorship') return '#52c41a';
        if (d.type === 'temporal') return '#722ed1';
        return '#999';
      });

    // Create nodes
    const node = g.append('g')
      .selectAll('circle')
      .data(nodes)
      .enter()
      .append('circle')
      .attr('r', d => d.radius)
      .attr('fill', d => d.color)
      .attr('stroke', '#fff')
      .attr('stroke-width', 2)
      .style('cursor', 'pointer')
      .call(d3.drag<SVGCircleElement, GraphNode>()
        .on('start', (event, d) => {
          if (!event.active) simulation.alphaTarget(0.3).restart();
          d.fx = d.x;
          d.fy = d.y;
        })
        .on('drag', (event, d) => {
          d.fx = event.x;
          d.fy = event.y;
        })
        .on('end', (event, d) => {
          if (!event.active) simulation.alphaTarget(0);
          d.fx = null;
          d.fy = null;
        }))
      .on('click', (event, d) => {
        setSelectedNode(d);
      });

    // Add labels for important nodes
    const labels = g.append('g')
      .selectAll('text')
      .data(nodes.filter(d => d.type === 'author' || d.type === 'time_period'))
      .enter()
      .append('text')
      .attr('dy', d => d.radius + 12)
      .attr('text-anchor', 'middle')
      .text(d => d.name)
      .attr('font-size', '10px')
      .attr('fill', '#333')
      .style('pointer-events', 'none');

    // Update positions on tick
    simulation.on('tick', () => {
      link
        .attr('x1', d => (d.source as GraphNode).x!)
        .attr('y1', d => (d.source as GraphNode).y!)
        .attr('x2', d => (d.target as GraphNode).x!)
        .attr('y2', d => (d.target as GraphNode).y!);

      node
        .attr('cx', d => d.x!)
        .attr('cy', d => d.y!);

      labels
        .attr('x', d => d.x!)
        .attr('y', d => d.y!);
    });

    return () => {
      simulation.stop();
    };
  }, [hypergraphData, dimensions, convertToGraphData]);

  // Render node details
  const renderNodeDetails = () => {
    if (!selectedNode) return null;

    const { type, data, name } = selectedNode;

    if (type === 'author') {
      return (
        <Card title="Author Details" size="small">
          <Space direction="vertical" style={{ width: '100%' }}>
            <Title level={5}>{name}</Title>
            <Text type="secondary">{data.affiliation}</Text>
            <Divider />
            <Text>Papers: {data.papers?.length || 0}</Text>
            <Text>First author: {data.is_first_author_count || 0} papers</Text>
            <Text>Corresponding author: {data.is_corresponding_author_count || 0} papers</Text>
            <Text>Coauthors: {data.coauthors?.length || 0}</Text>
          </Space>
        </Card>
      );
    }

    if (type === 'paper') {
      return (
        <Card title="Paper Details" size="small">
          <Space direction="vertical" style={{ width: '100%' }}>
            <Text strong>{data.title}</Text>
            <Text type="secondary">{data.journal}</Text>
            <Divider />
            <Text>Year: {data.year}</Text>
            <Text>Citations: {data.citation_count}</Text>
            <Text ellipsis>{data.technical_route}</Text>
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

    return null;
  };

  const analysis = hypergraphData?.analysis;

  return (
    <Space direction="vertical" style={{ width: '100%' }} size="large">
      {/* Header */}
      <Card>
        <Title level={4}>
          <ShareAltOutlined /> Hypergraph Timeline Analysis
        </Title>
        <Paragraph type="secondary">
          Visualize research collaboration networks, track evolution over time, identify key figures,
          milestones, and academic debates using hypergraph analysis.
        </Paragraph>

        {/* Research Selection */}
        <Space style={{ width: '100%', marginBottom: 16 }} wrap>
          <Text strong>Select Research Results:</Text>
          <Select
            style={{ width: 400 }}
            placeholder="Choose completed research..."
            loading={researchLoading}
            onChange={setSelectedJobId}
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
            onClick={() => selectedJobId && fetchHypergraph()}
            loading={hypergraphLoading}
          >
            Refresh
          </Button>
        </Space>

        {/* Filters */}
        {hypergraphData && (
          <Space style={{ width: '100%' }} wrap>
            <Text>Year Range:</Text>
            <Slider
              range
              min={hypergraphData.statistics.time_range.start}
              max={hypergraphData.statistics.time_range.end}
              value={yearFilter}
              onChange={(value) => setYearFilter(value as [number, number])}
              style={{ width: 200 }}
            />
            <Select value={viewMode} onChange={setViewMode} style={{ width: 150 }}>
              <Option value="full">Full View</Option>
              <Option value="collaboration">Collaboration</Option>
              <Option value="temporal">Temporal</Option>
            </Select>
            <Checkbox
              checked={includeOptions.collaboration}
              onChange={(e) => setIncludeOptions({ ...includeOptions, collaboration: e.target.checked })}
            >
              Collaboration
            </Checkbox>
            <Checkbox
              checked={includeOptions.influence}
              onChange={(e) => setIncludeOptions({ ...includeOptions, influence: e.target.checked })}
            >
              Influence
            </Checkbox>
            <Checkbox
              checked={includeOptions.milestones}
              onChange={(e) => setIncludeOptions({ ...includeOptions, milestones: e.target.checked })}
            >
              Milestones
            </Checkbox>
          </Space>
        )}
      </Card>

      {/* Main Visualization */}
      {hypergraphLoading ? (
        <Card>
          <Spin size="large" tip="Building hypergraph...">
            <div style={{ height: 600 }} />
          </Spin>
        </Card>
      ) : hypergraphData ? (
        <Card
          title={
            <Space>
              <GlobalOutlined />
              <span>Hypergraph Visualization</span>
              <Badge count={hypergraphData.statistics.total_papers} showZero color="#52c41a" />
              <Text type="secondary">papers</Text>
              <Badge count={hypergraphData.statistics.total_authors} showZero color="#1890ff" />
              <Text type="secondary">authors</Text>
            </Space>
          }
        >
          <div ref={containerRef} style={{ width: '100%' }}>
            <svg
              ref={svgRef}
              style={{
                border: '1px solid #d9d9d9',
                borderRadius: 4,
                background: '#f5f5f5',
                cursor: 'grab',
              }}
            />
          </div>

          {/* Legend */}
          <div style={{ marginTop: 16 }}>
            <Space wrap>
              <Tag color="#1890ff">Author</Tag>
              <Tag color="#52c41a">Paper</Tag>
              <Tag color="#faad14">Institution</Tag>
              <Tag color="#722ed1">Time Period</Tag>
              <Text type="secondary">| Click nodes for details | Drag to pan | Scroll to zoom</Text>
            </Space>
          </div>
        </Card>
      ) : selectedJobId ? (
        <Empty description="Failed to load hypergraph data" />
      ) : (
        <Empty description="Select a research result to visualize" />
      )}

      {/* Analysis Tabs */}
      {analysis && (
        <Card>
          <Tabs
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
                  <List
                    dataSource={analysis.key_figures}
                    renderItem={(figure: KeyFigure) => (
                      <List.Item>
                        <List.Item.Meta
                          title={
                            <Space>
                              <Text strong>{figure.name}</Text>
                              <Tag color="gold">Score: {figure.influence_score.toFixed(1)}</Tag>
                            </Space>
                          }
                          description={
                            <Space direction="vertical" size={0}>
                              <Text type="secondary">{figure.institution}</Text>
                              <Text>{figure.role}</Text>
                            </Space>
                          }
                        />
                      </List.Item>
                    )}
                  />
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
                  <List
                    dataSource={analysis.collaboration_clusters}
                    renderItem={(cluster: CollaborationCluster) => (
                      <List.Item>
                        <List.Item.Meta
                          title={cluster.institution || `Cluster ${cluster.id}`}
                          description={
                            <Space direction="vertical" size={0}>
                              <Text>{cluster.members?.length || 0} members</Text>
                              <Text>{cluster.paper_count} papers</Text>
                              <Text type="secondary" ellipsis>
                                {cluster.members?.join(', ')}
                              </Text>
                            </Space>
                          }
                        />
                      </List.Item>
                    )}
                  />
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
                  <List
                    dataSource={analysis.milestones}
                    renderItem={(milestone: Milestone) => (
                      <List.Item>
                        <List.Item.Meta
                          title={
                            <Space>
                              <Tag color="blue">{milestone.year}</Tag>
                              <Text strong>{milestone.event}</Text>
                            </Space>
                          }
                          description={
                            <Space direction="vertical" size={0}>
                              <Text>{milestone.significance}</Text>
                              <Text type="secondary">Key papers: {milestone.key_papers?.length || 0}</Text>
                            </Space>
                          }
                        />
                      </List.Item>
                    )}
                  />
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
                  <List
                    dataSource={analysis.debates}
                    renderItem={(debate: Debate) => (
                      <List.Item>
                        <List.Item.Meta
                          title={
                            <Space>
                              <Text strong>{debate.topic}</Text>
                              <Tag color={debate.status === 'ongoing' ? 'orange' : 'green'}>
                                {debate.status}
                              </Tag>
                            </Space>
                          }
                          description={
                            <Text type="secondary">
                              Sides: {debate.sides?.join(' vs ')}
                            </Text>
                          }
                        />
                      </List.Item>
                    )}
                  />
                ),
              },
            ]}
          />
        </Card>
      )}

      {/* Node Detail Panel */}
      {selectedNode && (
        <div style={{ position: 'fixed', right: 24, bottom: 24, width: 300, zIndex: 1000 }}>
          {renderNodeDetails()}
        </div>
      )}
    </Space>
  );
}
