import { useState, useRef, useEffect } from 'react';
import { Input, Button, Card, Typography, Space, Tag, Tooltip, Spin, Empty } from 'antd';
import { SendOutlined, ClearOutlined } from '@ant-design/icons';
import ReactMarkdown from 'react-markdown';
import { useAppStore } from '../stores/appStore';
import { chat } from '../utils/api';
import type { Citation } from '../types';

const { Text, Paragraph } = Typography;
const { TextArea } = Input;

function CitationTag({ citation, index }: { citation: Citation; index: number }) {
  return (
    <Tooltip
      title={
        <div>
          <strong>{citation.title}</strong>
          <br />
          {citation.authors} ({citation.year})
          <br />
          Page {citation.page_start}
          {citation.page_end !== citation.page_start ? `-${citation.page_end}` : ''}
          <br />
          <em>"{citation.excerpt}"</em>
        </div>
      }
    >
      <Tag color="blue" style={{ cursor: 'pointer' }}>
        [{index + 1}]
      </Tag>
    </Tooltip>
  );
}

export default function ChatInterface() {
  const { messages, addMessage, sessionId, setSessionId, clearMessages, selectedPaperId } = useAppStore();
  const [input, setInput] = useState('');
  const [loading, setLoading] = useState(false);
  const messagesEndRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages]);

  const handleSend = async () => {
    const trimmed = input.trim();
    if (!trimmed || loading) return;

    addMessage({ role: 'user', content: trimmed });
    setInput('');
    setLoading(true);

    try {
      const response = await chat(trimmed, sessionId || undefined, selectedPaperId || undefined);
      setSessionId(response.session_id);
      addMessage({
        role: 'assistant',
        content: response.content,
        citations: response.citations,
        agent_type: response.agent_type,
      });
    } catch (err: any) {
      addMessage({
        role: 'assistant',
        content: `Error: ${err.response?.data?.detail || err.message || 'Request failed'}`,
      });
    } finally {
      setLoading(false);
    }
  };

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: 'calc(100vh - 130px)' }}>
      {/* Messages area */}
      <div style={{ flex: 1, overflow: 'auto', paddingBottom: 16 }}>
        {messages.length === 0 ? (
          <Empty description="Start a conversation about single-cell 3D genomics" style={{ marginTop: 100 }} />
        ) : (
          messages.map((msg, i) => (
            <Card
              key={i}
              size="small"
              style={{
                marginBottom: 12,
                background: msg.role === 'user' ? '#e6f4ff' : '#fff',
                borderColor: msg.role === 'user' ? '#91caff' : '#f0f0f0',
              }}
            >
              <Space direction="vertical" style={{ width: '100%' }}>
                <Space>
                  <Tag color={msg.role === 'user' ? 'blue' : 'green'}>
                    {msg.role === 'user' ? 'You' : 'Assistant'}
                  </Tag>
                  {msg.agent_type && <Tag>{msg.agent_type}</Tag>}
                </Space>
                <div className="markdown-content">
                  <ReactMarkdown>{msg.content}</ReactMarkdown>
                </div>
                {msg.citations && msg.citations.length > 0 && (
                  <div>
                    <Text type="secondary" strong>Sources: </Text>
                    {msg.citations.map((c, j) => (
                      <CitationTag key={j} citation={c} index={j} />
                    ))}
                  </div>
                )}
              </Space>
            </Card>
          ))
        )}
        {loading && (
          <Card size="small" style={{ marginBottom: 12 }}>
            <Spin size="small" /> <Text type="secondary">Thinking...</Text>
          </Card>
        )}
        <div ref={messagesEndRef} />
      </div>

      {/* Input area */}
      <div style={{ borderTop: '1px solid #f0f0f0', paddingTop: 12 }}>
        <Space.Compact style={{ width: '100%' }}>
          <TextArea
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onPressEnter={(e) => {
              if (!e.shiftKey) {
                e.preventDefault();
                handleSend();
              }
            }}
            placeholder="Ask about single-cell 3D genomics..."
            autoSize={{ minRows: 1, maxRows: 4 }}
            disabled={loading}
            style={{ flex: 1 }}
          />
          <Button type="primary" icon={<SendOutlined />} onClick={handleSend} loading={loading}>
            Send
          </Button>
          <Button icon={<ClearOutlined />} onClick={clearMessages} title="New chat">
            Clear
          </Button>
        </Space.Compact>
      </div>
    </div>
  );
}
