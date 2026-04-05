import { useState } from 'react';
import { Card, Input, Select, Button, Typography, Space, Spin } from 'antd';
import ReactMarkdown from 'react-markdown';
import { draftReview, suggestCitations } from '../utils/api';

const { TextArea } = Input;
const { Text } = Typography;

export default function WritingAssistant() {
  const [topic, setTopic] = useState('');
  const [perspective, setPerspective] = useState('');
  const [sectionType, setSectionType] = useState('introduction');
  const [draft, setDraft] = useState<any>(null);
  const [citationText, setCitationText] = useState('');
  const [citationResult, setCitationResult] = useState<any>(null);
  const [loadingDraft, setLoadingDraft] = useState(false);
  const [loadingCitations, setLoadingCitations] = useState(false);

  const handleDraft = async () => {
    if (!topic.trim()) return;
    setLoadingDraft(true);
    try {
      const result = await draftReview(topic, perspective, sectionType);
      setDraft(result);
    } catch (err: any) {
      setDraft({ draft: `Error: ${err.response?.data?.detail || err.message}` });
    } finally {
      setLoadingDraft(false);
    }
  };

  const handleCitations = async () => {
    if (!citationText.trim()) return;
    setLoadingCitations(true);
    try {
      const result = await suggestCitations(citationText);
      setCitationResult(result);
    } catch (err: any) {
      setCitationResult({ suggestions: `Error: ${err.response?.data?.detail || err.message}` });
    } finally {
      setLoadingCitations(false);
    }
  };

  return (
    <Space direction="vertical" style={{ width: '100%' }} size="large">
      {/* Draft Review Section */}
      <Card title="Draft Review Section">
        <Space direction="vertical" style={{ width: '100%' }}>
          <Input
            placeholder="Topic (e.g., 'scHi-C methods for chromatin organization')"
            value={topic}
            onChange={(e) => setTopic(e.target.value)}
          />
          <Space>
            <Select
              value={sectionType}
              onChange={setSectionType}
              style={{ width: 200 }}
              options={[
                { value: 'introduction', label: 'Introduction' },
                { value: 'methods', label: 'Methods' },
                { value: 'results', label: 'Results' },
                { value: 'discussion', label: 'Discussion' },
                { value: 'conclusion', label: 'Conclusion' },
              ]}
            />
            <Button type="primary" onClick={handleDraft} loading={loadingDraft}>
              Generate Draft
            </Button>
          </Space>
          <TextArea
            placeholder="Your perspective or notes (optional - will be integrated into the draft)"
            value={perspective}
            onChange={(e) => setPerspective(e.target.value)}
            rows={3}
          />
        </Space>
      </Card>

      {loadingDraft && (
        <Card>
          <Spin /> <Text type="secondary">Generating draft...</Text>
        </Card>
      )}

      {!loadingDraft && draft && (
        <Card title="Generated Draft">
          <ReactMarkdown>{draft.draft}</ReactMarkdown>
        </Card>
      )}

      {/* Citation Suggestions */}
      <Card title="Suggest Citations">
        <Space direction="vertical" style={{ width: '100%' }}>
          <TextArea
            placeholder="Paste your text here to get citation suggestions..."
            value={citationText}
            onChange={(e) => setCitationText(e.target.value)}
            rows={4}
          />
          <Button type="primary" onClick={handleCitations} loading={loadingCitations}>
            Suggest Citations
          </Button>
        </Space>
      </Card>

      {loadingCitations && (
        <Card>
          <Spin /> <Text type="secondary">Finding relevant citations...</Text>
        </Card>
      )}

      {!loadingCitations && citationResult && (
        <Card title="Citation Suggestions">
          <ReactMarkdown>{citationResult.suggestions}</ReactMarkdown>
        </Card>
      )}
    </Space>
  );
}
