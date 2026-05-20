import { useEffect, useState } from 'react';
import { Input, Card, List, Tag, Typography, Space, Spin, Empty } from 'antd';
import { SearchOutlined, BookOutlined } from '@ant-design/icons';
import ReactMarkdown from 'react-markdown';
import { queryKnowledge } from '../utils/api';
import {
  useClearQueuedKnowledgeQuery,
  useKnowledgeInitialQuery,
  useKnowledgeInitialTopic,
  useKnowledgeQueryNonce,
  useSelectedWikiKbId,
} from '../stores/appStore';
import type { Citation, QueryResponse } from '../types';

const { Text, Paragraph } = Typography;
const { Search } = Input;

export default function KnowledgeExplorer() {
  const [query, setQuery] = useState('');
  const [result, setResult] = useState<QueryResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const knowledgeInitialQuery = useKnowledgeInitialQuery();
  const knowledgeInitialTopic = useKnowledgeInitialTopic();
  const knowledgeQueryNonce = useKnowledgeQueryNonce();
  const clearQueuedKnowledgeQuery = useClearQueuedKnowledgeQuery();
  const selectedWikiKbId = useSelectedWikiKbId();

  const runSearch = async (value: string, topic?: string | null) => {
    if (!value.trim()) return;
    setLoading(true);
    setQuery(value.trim());
    try {
      const data = await queryKnowledge(value.trim(), undefined, topic || undefined, selectedWikiKbId || undefined);
      setResult(data);
    } catch (err: any) {
      setResult({
        content: `Error: ${err.response?.data?.detail || err.message}`,
        agent_type: 'error',
        citations: [],
      });
    } finally {
      setLoading(false);
    }
  };

  const handleSearch = async (value: string) => {
    await runSearch(value);
  };

  useEffect(() => {
    if (!knowledgeInitialQuery) return;
    runSearch(knowledgeInitialQuery, knowledgeInitialTopic);
    clearQueuedKnowledgeQuery();
  }, [knowledgeInitialQuery, knowledgeInitialTopic, knowledgeQueryNonce, clearQueuedKnowledgeQuery]);

  const isWikiTrace = (citation: Citation) => citation.title?.startsWith('Wiki:');

  return (
    <div>
      <Search
        placeholder="Search the knowledge base..."
        enterButton={<><SearchOutlined /> Search</>}
        size="large"
        value={query}
        onChange={(event) => setQuery(event.target.value)}
        onSearch={handleSearch}
        loading={loading}
        style={{ marginBottom: 24 }}
      />

      {loading && (
        <div style={{ textAlign: 'center', padding: 40 }}>
          <Spin size="large" />
          <br />
          <Text type="secondary">Searching wiki pages and source documents...</Text>
        </div>
      )}

      {!loading && result && (
        <Space direction="vertical" style={{ width: '100%' }} size="large">
          <Card title={<><Tag color="green">{result.agent_type}</Tag> Answer</>}>
            <ReactMarkdown>{result.content}</ReactMarkdown>
          </Card>

          {result.citations.length > 0 && (
            <Card
              title={
                <Space>
                  <Text strong>Sources & Traces</Text>
                  <Tag>{result.citations.length} items</Tag>
                </Space>
              }
            >
              <List
                dataSource={result.citations}
                renderItem={(citation: Citation, index: number) => (
                  <List.Item>
                    <List.Item.Meta
                      title={
                        <Space>
                          <Tag color={isWikiTrace(citation) ? 'purple' : 'blue'}>
                            [{index + 1}]
                          </Tag>
                          <Text strong>{citation.title || 'Unknown paper'}</Text>
                          {(citation.year ?? 0) > 0 && <Tag>{citation.year}</Tag>}
                          {isWikiTrace(citation) && (
                            <Tag color="purple" icon={<BookOutlined />}>Wiki Trace</Tag>
                          )}
                        </Space>
                      }
                      description={
                        <div>
                          {!isWikiTrace(citation) && (
                            <>
                              <Text type="secondary">{citation.authors}</Text>
                              <br />
                              <Text type="secondary">
                                Page {citation.page_start}
                                {citation.page_end !== citation.page_start ? `-${citation.page_end}` : ''}
                              </Text>
                            </>
                          )}
                          <Paragraph
                            type={isWikiTrace(citation) ? 'success' : 'secondary'}
                            ellipsis={{ rows: 3, expandable: true, symbol: 'expand source' }}
                            style={isWikiTrace(citation) ? {
                              borderLeft: '3px solid #d3adf7',
                              paddingLeft: 8,
                              background: '#f9f0ff',
                              borderRadius: 4,
                              padding: '4px 8px',
                              marginTop: 8,
                            } : undefined}
                          >
                            {citation.excerpt}
                          </Paragraph>
                        </div>
                      }
                    />
                  </List.Item>
                )}
              />
            </Card>
          )}
        </Space>
      )}

      {!loading && !result && (
        <Empty description="Search for topics like 'scHi-C methodology' or 'chromatin organization'" />
      )}
    </div>
  );
}
