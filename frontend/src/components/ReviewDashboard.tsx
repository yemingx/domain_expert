import { useState } from 'react';
import { Card, Select, Button, Typography, Space, Spin, Empty, Tag } from 'antd';
import ReactMarkdown from 'react-markdown';
import { useQuery } from '@tanstack/react-query';
import { listPapers, evaluatePaper } from '../utils/api';
import type { Paper } from '../types';

const { Text } = Typography;

export default function ReviewDashboard() {
  const [selectedPaper, setSelectedPaper] = useState<string | null>(null);
  const [evaluation, setEvaluation] = useState<any>(null);
  const [loading, setLoading] = useState(false);

  const { data: papers = [] } = useQuery({
    queryKey: ['papers'],
    queryFn: listPapers,
  });

  const completedPapers = papers.filter((p: Paper) => p.status === 'completed');

  const handleEvaluate = async () => {
    if (!selectedPaper) return;
    setLoading(true);
    try {
      const result = await evaluatePaper(selectedPaper);
      setEvaluation(result);
    } catch (err: any) {
      setEvaluation({ evaluation: `Error: ${err.response?.data?.detail || err.message}` });
    } finally {
      setLoading(false);
    }
  };

  return (
    <Space direction="vertical" style={{ width: '100%' }} size="large">
      <Card title="Paper Review & Evaluation">
        <Space>
          <Select
            placeholder="Select a paper to review"
            style={{ width: 400 }}
            value={selectedPaper}
            onChange={setSelectedPaper}
            options={completedPapers.map((p: Paper) => ({
              value: p.id,
              label: `${p.title || p.filename} (${p.year || 'N/A'})`,
            }))}
          />
          <Button type="primary" onClick={handleEvaluate} loading={loading} disabled={!selectedPaper}>
            Evaluate
          </Button>
        </Space>
        {completedPapers.length === 0 && (
          <div style={{ marginTop: 12 }}>
            <Text type="secondary">Upload and process papers first to enable review.</Text>
          </div>
        )}
      </Card>

      {loading && (
        <Card>
          <div style={{ textAlign: 'center', padding: 40 }}>
            <Spin size="large" />
            <br />
            <Text type="secondary">Evaluating paper...</Text>
          </div>
        </Card>
      )}

      {!loading && evaluation && (
        <Card title="Evaluation Results">
          <ReactMarkdown>{evaluation.evaluation}</ReactMarkdown>
          {evaluation.rubric_categories?.length > 0 && (
            <div style={{ marginTop: 16 }}>
              <Text strong>Rubric Categories: </Text>
              {evaluation.rubric_categories.map((cat: string, i: number) => (
                <Tag key={i} color="blue">{cat}</Tag>
              ))}
            </div>
          )}
        </Card>
      )}

      {!loading && !evaluation && completedPapers.length > 0 && (
        <Empty description="Select a paper and click Evaluate to get a review" />
      )}
    </Space>
  );
}
