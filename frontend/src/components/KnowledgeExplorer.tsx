import { useState } from 'react';
import { Input, Card, List, Tag, Typography, Space, Spin, Empty, Tooltip } from 'antd';
import { SearchOutlined } from '@ant-design/icons';
import ReactMarkdown from 'react-markdown';
import { queryKnowledge } from '../utils/api';
import type { Citation, QueryResponse } from '../types';

const { Text, Paragraph } = Typography;
const { Search } = Input;

export default function KnowledgeExplorer() {
  const [query, setQuery] = useState('');
  const [result, setResult] = useState<QueryResponse | null>(null);
  const [loading, setLoading] = useState(false);

  const handleSearch = async (value: string) => {
    if (!value.trim()) return;
    setLoading(true);
    try {
      const data = await queryKnowledge(value.trim());
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

  return (
    <div>
      <Search
        placeholder="Search the knowledge base..."
        enterButton={<><SearchOutlined /> Search</>}
        size="large"
        onSearch={handleSearch}
        loading={loading}
        style={{ marginBottom: 24 }}
      />

      {loading && (
        <div style={{ textAlign: 'center', padding: 40 }}>
          <Spin size="large" />
          <br />
          <Text type="secondary">Searching knowledge base...</Text>
        </div>
      )}

      {!loading && result && (
        <Space direction="vertical" style={{ width: '100%' }} size="large">
          <Card title={<><Tag color="green">{result.agent_type}</Tag> Answer</>}>
            <ReactMarkdown>{result.content}</ReactMarkdown>
          </Card>

          {result.citations.length > 0 && (
            <Card title="Sources">
              <List
                dataSource={result.citations}
                renderItem={(citation: Citation, index: number) => (
                  <List.Item>
                    <List.Item.Meta
                      title={
                        <Space>
                          <Tag color="blue">[{index + 1}]</Tag>
                          <Text strong>{citation.title || 'Unknown paper'}</Text>
                          {citation.year > 0 && <Tag>{citation.year}</Tag>}
                        </Space>
                      }
                      description={
                        <div>
                          <Text type="secondary">{citation.authors}</Text>
                          <br />
                          <Text type="secondary">
                            Page {citation.page_start}
                            {citation.page_end !== citation.page_start ? `-${citation.page_end}` : ''}
                          </Text>
                          <Paragraph type="secondary" ellipsis={{ rows: 2, expandable: true }}>
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
