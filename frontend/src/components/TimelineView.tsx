import { useState, useEffect } from 'react';
import { Card, Typography, Spin, Empty, Tag, Space } from 'antd';
import ReactMarkdown from 'react-markdown';
import { getTimeline } from '../utils/api';

const { Title, Text } = Typography;

interface TimelineEvent {
  year: number;
  title: string;
  description: string;
  methods?: string[];
}

export default function TimelineView() {
  const [events, setEvents] = useState<TimelineEvent[]>([]);
  const [summary, setSummary] = useState('');
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    loadTimeline();
  }, []);

  const loadTimeline = async () => {
    setLoading(true);
    try {
      const data = await getTimeline();
      setEvents(data.timeline || []);
      setSummary(data.summary || '');
    } catch {
      setSummary('Failed to load timeline. Make sure papers are uploaded to the knowledge base.');
    } finally {
      setLoading(false);
    }
  };

  if (loading) {
    return (
      <div style={{ textAlign: 'center', padding: 60 }}>
        <Spin size="large" />
        <br />
        <Text type="secondary">Generating domain timeline...</Text>
      </div>
    );
  }

  return (
    <Space direction="vertical" style={{ width: '100%' }} size="large">
      {events.length > 0 ? (
        <div>
          <Title level={4}>Domain Timeline</Title>
          {events
            .sort((a, b) => a.year - b.year)
            .map((event, i) => (
              <Card key={i} size="small" style={{ marginBottom: 12, borderLeft: '4px solid #1677ff' }}>
                <Space>
                  <Tag color="blue" style={{ fontSize: 16, padding: '4px 12px' }}>
                    {event.year}
                  </Tag>
                  <div>
                    <Text strong>{event.title}</Text>
                    <br />
                    <Text type="secondary">{event.description}</Text>
                    {event.methods && event.methods.length > 0 && (
                      <div style={{ marginTop: 4 }}>
                        {event.methods.map((m, j) => (
                          <Tag key={j} color="green">{m}</Tag>
                        ))}
                      </div>
                    )}
                  </div>
                </Space>
              </Card>
            ))}
        </div>
      ) : null}

      {summary && (
        <Card title="Summary">
          <ReactMarkdown>{summary}</ReactMarkdown>
        </Card>
      )}

      {!events.length && !summary && (
        <Empty description="Upload papers to generate a domain timeline" />
      )}
    </Space>
  );
}
