import { Children, memo, useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Input, Button, Card, Typography, Space, Tag, Spin, Empty } from 'antd';
import { SendOutlined, ClearOutlined, BookOutlined } from '@ant-design/icons';
import ReactMarkdown from 'react-markdown';
import {
  useAddMessage,
  useClearMessages,
  useMessages,
  useSelectedPaperId,
  useSelectedWikiKbId,
  useSessionId,
  useSetSessionId,
} from '../stores/appStore';
import { chat } from '../utils/api';
import type { ChatMessage, Citation } from '../types';

const { Text } = Typography;
const { TextArea } = Input;
const AUTO_SCROLL_THRESHOLD = 120;
const SOURCE_LINK_RE = /\[Source(?:s)?\s+([^\]]+)\]/gi;
const SOURCE_LINK_PROTOCOL = 'source://';

const isWikiCitation = (citation: Citation) => citation.title?.startsWith('Wiki:');
const formatAuthors = (authors: Citation['authors']) =>
  Array.isArray(authors) ? authors.filter(Boolean).join(', ') : authors;

const getCitationKey = (citation: Citation, index: number) =>
  `${citation.paper_id || 'citation'}-${citation.page_start}-${index}`;

const createMessageId = () =>
  globalThis.crypto?.randomUUID?.() ?? `msg-${Date.now()}-${Math.random().toString(36).slice(2, 10)}`;

const getMessageKey = (message: ChatMessage, index: number) =>
  message.id ?? `${message.role}-${index}-${message.content.slice(0, 32)}`;

function parseCitationSpec(spec: string, citations: Citation[]) {
  const indexes = new Set<number>();
  const parts = spec.split(',');

  for (const rawPart of parts) {
    const part = rawPart.trim();
    if (!part) continue;

    const rangeMatch = part.match(/^(\d+)\s*-\s*(\d+)$/);
    if (rangeMatch) {
      const start = Number(rangeMatch[1]);
      const end = Number(rangeMatch[2]);
      const rangeStart = Math.min(start, end);
      const rangeEnd = Math.max(start, end);
      for (let value = rangeStart; value <= rangeEnd; value += 1) {
        if (value >= 1 && value <= citations.length) indexes.add(value - 1);
      }
      continue;
    }

    const single = Number(part);
    if (!Number.isNaN(single) && single >= 1 && single <= citations.length) {
      indexes.add(single - 1);
    }
  }

  return Array.from(indexes)
    .sort((left, right) => left - right)
    .map((index) => ({ index, citation: citations[index] }));
}

function InlineCitationLink({
  label,
  spec,
  citations,
  onOpen,
}: {
  label: string;
  spec: string;
  citations: Citation[];
  onOpen: (indexes: number[]) => void;
}) {
  const matched = useMemo(() => parseCitationSpec(spec, citations), [spec, citations]);
  if (matched.length === 0) return <>{label}</>;

  return (
    <Button
      type="link"
      size="small"
      style={{ paddingInline: 4, height: 'auto', verticalAlign: 'baseline' }}
      onClick={() => onOpen(matched.map((item) => item.index))}
    >
      {label}
    </Button>
  );
}

function remarkSourceCitations() {
  const shouldSkip = new Set(['link', 'linkReference', 'definition', 'image', 'imageReference', 'inlineCode', 'code', 'html']);

  const splitTextNode = (value: string) => {
    const nodes: Array<Record<string, unknown>> = [];
    let lastIndex = 0;
    let match: RegExpExecArray | null;
    SOURCE_LINK_RE.lastIndex = 0;

    while ((match = SOURCE_LINK_RE.exec(value)) !== null) {
      const [label, spec] = match;
      const start = match.index;

      if (start > lastIndex) {
        nodes.push({ type: 'text', value: value.slice(lastIndex, start) });
      }

      nodes.push({
        type: 'link',
        url: `${SOURCE_LINK_PROTOCOL}${encodeURIComponent(spec)}`,
        children: [{ type: 'text', value: label }],
      });
      lastIndex = start + label.length;
    }

    if (lastIndex < value.length) {
      nodes.push({ type: 'text', value: value.slice(lastIndex) });
    }

    return nodes.length > 0 ? nodes : [{ type: 'text', value }];
  };

  const transformNode = (node: Record<string, any>) => {
    if (!node || !Array.isArray(node.children) || shouldSkip.has(node.type)) return;

    node.children = node.children.flatMap((child: Record<string, any>) => {
      if (child.type === 'text' && typeof child.value === 'string') {
        return splitTextNode(child.value);
      }
      transformNode(child);
      return [child];
    });
  };

  return (tree: Record<string, any>) => {
    transformNode(tree);
  };
}

function CitationTag({
  citation,
  index,
  onOpen,
}: {
  citation: Citation;
  index: number;
  onOpen: (indexes: number[]) => void;
}) {
  return (
    <Tag
      color={isWikiCitation(citation) ? 'purple' : 'blue'}
      style={{ cursor: 'pointer' }}
      icon={isWikiCitation(citation) ? <BookOutlined /> : undefined}
      onClick={() => onOpen([index])}
    >
      [Source {index + 1}]
    </Tag>
  );
}

const MessageCard = memo(function MessageCard({ message }: { message: ChatMessage }) {
  const sourceCitations = message.citations?.filter((citation) => !isWikiCitation(citation)) ?? [];
  const wikiCitations = message.citations?.filter((citation) => isWikiCitation(citation)) ?? [];
  const [openCitationIndexes, setOpenCitationIndexes] = useState<number[]>([]);
  const allCitations = message.citations ?? [];
  const markdownPlugins = useMemo(() => [remarkSourceCitations], []);
  const visibleCitations = openCitationIndexes
    .map((index) => ({ index, citation: allCitations[index] }))
    .filter((item): item is { index: number; citation: Citation } => Boolean(item.citation));

  const handleOpenCitations = useCallback((indexes: number[]) => {
    setOpenCitationIndexes((current) => {
      if (current.length === indexes.length && current.every((value, index) => value === indexes[index])) {
        return [];
      }
      return indexes;
    });
  }, []);

  return (
    <>
      <Card
        size="small"
        style={{
          marginBottom: 12,
          background: message.role === 'user' ? '#e6f4ff' : '#fff',
          borderColor: message.role === 'user' ? '#91caff' : '#f0f0f0',
        }}
      >
        <Space direction="vertical" style={{ width: '100%' }}>
          <Space>
            <Tag color={message.role === 'user' ? 'blue' : 'green'}>
              {message.role === 'user' ? 'You' : 'Assistant'}
            </Tag>
            {message.agent_type && <Tag>{message.agent_type}</Tag>}
          </Space>
          <div className="markdown-content">
            <ReactMarkdown
              remarkPlugins={markdownPlugins}
              components={{
                a: ({ href, children }) => {
                  if (href?.startsWith(SOURCE_LINK_PROTOCOL)) {
                    const spec = decodeURIComponent(href.slice(SOURCE_LINK_PROTOCOL.length));
                    const label = Children.toArray(children).map((child) => String(child)).join('') || `[Source ${spec}]`;
                    return (
                      <InlineCitationLink
                        label={label}
                        spec={spec}
                        citations={allCitations}
                        onOpen={handleOpenCitations}
                      />
                    );
                  }
                  return (
                    <a href={href} target="_blank" rel="noreferrer">
                      {children}
                    </a>
                  );
                },
              }}
            >
              {message.content}
            </ReactMarkdown>
          </div>
          {message.citations && message.citations.length > 0 && (
            <div>
              {sourceCitations.length > 0 && (
                <Space wrap style={{ marginBottom: 4 }}>
                  <Text type="secondary" strong>Sources: </Text>
                  {sourceCitations.map((citation, index) => (
                    <CitationTag
                      key={getCitationKey(citation, index)}
                      citation={citation}
                      index={index}
                      onOpen={handleOpenCitations}
                    />
                  ))}
                </Space>
              )}
              {wikiCitations.length > 0 && (
                <div style={{ marginTop: 8, padding: '8px 12px', background: '#f9f0ff', borderRadius: 6, borderLeft: '3px solid #d3adf7' }}>
                  <Text type="secondary" strong style={{ color: '#722ed1' }}>
                    <BookOutlined /> Wiki Traces:
                  </Text>
                  <Space wrap style={{ marginTop: 4 }}>
                    {wikiCitations.map((citation) => {
                      const globalIndex = allCitations.indexOf(citation);
                      return (
                        <CitationTag
                          key={getCitationKey(citation, globalIndex)}
                          citation={citation}
                          index={globalIndex}
                          onOpen={handleOpenCitations}
                        />
                      );
                    })}
                  </Space>
                </div>
              )}
            </div>
          )}
          {visibleCitations.length > 0 && (
            <div
              style={{
                marginTop: 8,
                padding: 12,
                background: '#fcfcfc',
                border: '1px solid #f0f0f0',
                borderRadius: 10,
              }}
            >
              <Space
                align="center"
                style={{ width: '100%', justifyContent: 'space-between', marginBottom: 12 }}
              >
                <Text strong>Source Excerpts</Text>
                <Button size="small" onClick={() => setOpenCitationIndexes([])}>
                  Close
                </Button>
              </Space>
              <Space direction="vertical" size="middle" style={{ width: '100%' }}>
                {visibleCitations.map(({ index, citation }) => (
                  <Card key={getCitationKey(citation, index)} size="small">
                    <Space direction="vertical" size="small" style={{ width: '100%' }}>
                      <Space wrap>
                        <Tag color={isWikiCitation(citation) ? 'purple' : 'blue'}>
                          Source {index + 1}
                        </Tag>
                        {citation.paper_id && <Tag>{citation.paper_id}</Tag>}
                      </Space>
                      <Text strong>{citation.title}</Text>
                      {formatAuthors(citation.authors) && (
                        <Text type="secondary">
                          {formatAuthors(citation.authors)}
                          {citation.year ? ` (${citation.year})` : ''}
                        </Text>
                      )}
                      {!isWikiCitation(citation) && (
                        <Text type="secondary">
                          Page {citation.page_start}
                          {citation.page_end !== citation.page_start ? `-${citation.page_end}` : ''}
                        </Text>
                      )}
                      <div
                        style={{
                          whiteSpace: 'pre-wrap',
                          lineHeight: 1.7,
                          background: '#fafafa',
                          border: '1px solid #f0f0f0',
                          borderRadius: 8,
                          padding: 12,
                        }}
                      >
                        {citation.excerpt || 'No excerpt available.'}
                      </div>
                    </Space>
                  </Card>
                ))}
              </Space>
            </div>
          )}
        </Space>
      </Card>
    </>
  );
});

export default function ChatInterface() {
  const sessionId = useSessionId();
  const setSessionId = useSetSessionId();
  const messages = useMessages();
  const addMessage = useAddMessage();
  const clearMessages = useClearMessages();
  const selectedPaperId = useSelectedPaperId();
  const selectedWikiKbId = useSelectedWikiKbId();
  const [input, setInput] = useState('');
  const [loading, setLoading] = useState(false);
  const scrollContainerRef = useRef<HTMLDivElement>(null);
  const shouldAutoScrollRef = useRef(true);

  useEffect(() => {
    const container = scrollContainerRef.current;
    if (!container) return;

    const updateScrollIntent = () => {
      const distanceToBottom = container.scrollHeight - container.scrollTop - container.clientHeight;
      shouldAutoScrollRef.current = distanceToBottom <= AUTO_SCROLL_THRESHOLD;
    };

    updateScrollIntent();
    container.addEventListener('scroll', updateScrollIntent);
    return () => container.removeEventListener('scroll', updateScrollIntent);
  }, []);

  useEffect(() => {
    const container = scrollContainerRef.current;
    if (!container || !shouldAutoScrollRef.current) return;
    container.scrollTo({ top: container.scrollHeight, behavior: 'smooth' });
  }, [messages.length, loading]);

  const appendMessage = useCallback((message: ChatMessage) => {
    addMessage({ ...message, id: message.id ?? createMessageId() });
  }, [addMessage]);

  const handleSend = useCallback(async () => {
    const trimmed = input.trim();
    if (!trimmed || loading) return;

    shouldAutoScrollRef.current = true;
    appendMessage({ role: 'user', content: trimmed });
    setInput('');
    setLoading(true);

    try {
      const response = await chat(
        trimmed,
        sessionId || undefined,
        selectedPaperId || undefined,
        selectedWikiKbId || undefined,
      );
      setSessionId(response.session_id);
      appendMessage({
        role: 'assistant',
        content: response.content,
        citations: response.citations,
        agent_type: response.agent_type,
      });
    } catch (err: any) {
      appendMessage({
        role: 'assistant',
        content: `Error: ${err.response?.data?.detail || err.message || 'Request failed'}`,
      });
    } finally {
      setLoading(false);
    }
  }, [appendMessage, input, loading, selectedPaperId, selectedWikiKbId, sessionId, setSessionId]);

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: 'calc(100vh - 130px)' }}>
      <div ref={scrollContainerRef} style={{ flex: 1, overflow: 'auto', paddingBottom: 16 }}>
        {messages.length === 0 ? (
          <Empty description="Start a conversation about single-cell 3D genomics" style={{ marginTop: 100 }} />
        ) : (
          messages.map((message, index) => (
            <MessageCard key={message.id ?? getMessageKey(message, index)} message={message} />
          ))
        )}
        {loading && (
          <Card size="small" style={{ marginBottom: 12 }}>
            <Spin size="small" /> <Text type="secondary">Thinking...</Text>
          </Card>
        )}
      </div>

      <div style={{ borderTop: '1px solid #f0f0f0', paddingTop: 12 }}>
        <Space.Compact style={{ width: '100%' }}>
          <TextArea
            value={input}
            onChange={(event) => setInput(event.target.value)}
            onPressEnter={(event) => {
              if (!event.shiftKey) {
                event.preventDefault();
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
