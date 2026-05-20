import React, { useState, useEffect } from 'react';
import {
  Card, Input, List, Tag, Spin, Empty, Button, Typography, Space,
  message, Modal, Select, Upload, Collapse,
} from 'antd';
import {
  SearchOutlined, BookOutlined, LinkOutlined, FileTextOutlined,
  ReloadOutlined, RightOutlined, HomeOutlined, PlusOutlined,
  DatabaseOutlined, DeleteOutlined, ImportOutlined, UploadOutlined,
  ExperimentOutlined, RobotOutlined, InboxOutlined,
} from '@ant-design/icons';
import ReactMarkdown from 'react-markdown';
import {
  listWikiKbs, createWikiKb, deleteWikiKb,
  listWikiPages, getWikiPage, wikiSearch, wikiIngest,
  getPaperMarkdown, importResearchToWiki, importPaperToWikiKB,
  uploadPaperWithMineruToKB, getCompletedResearch,
  WikiPageListItem, WikiPageData, WikiSearchResult,
} from '../utils/api';
import {
  useSelectedWikiKbId,
  useSetSelectedWikiKbId,
  useSetWikiKbs,
  useWikiKbs,
} from '../stores/appStore';
import { useQuery } from '@tanstack/react-query';

const { Text, Title, Paragraph } = Typography;
const { Dragger } = Upload;

const PAGE_TYPE_COLORS: Record<string, string> = {
  entity: '#1677ff',
  concept: '#52c41a',
  comparison: '#fa8c16',
  synthesis: '#722ed1',
  index: '#eb2f96',
};

interface Props {
  onKbChange?: () => void;
}

const WikiExplorer: React.FC<Props> = ({ onKbChange }) => {
  const wikiKbs = useWikiKbs();
  const setWikiKbs = useSetWikiKbs();
  const selectedWikiKbId = useSelectedWikiKbId();
  const setSelectedWikiKbId = useSetSelectedWikiKbId();

  const [searchQuery, setSearchQuery] = useState('');
  const [searchResults, setSearchResults] = useState<WikiSearchResult[]>([]);
  const [searching, setSearching] = useState(false);
  const [selectedPage, setSelectedPage] = useState<WikiPageData | null>(null);
  const [selectedRawMd, setSelectedRawMd] = useState('');
  const [ingesting, setIngesting] = useState(false);

  const [createModalOpen, setCreateModalOpen] = useState(false);
  const [newKbName, setNewKbName] = useState('');
  const [newKbDesc, setNewKbDesc] = useState('');

  const [importModalOpen, setImportModalOpen] = useState(false);
  const [importResearchJobId, setImportResearchJobId] = useState<string>('');
  const [importing, setImporting] = useState(false);
  const [uploading, setUploading] = useState(false);

  const [researchJobs, setResearchJobs] = useState<{ job_id: string; topic?: string; status?: string }[]>([]);

  const { data: pages, isLoading, refetch } = useQuery<WikiPageListItem[]>({
    queryKey: ['wikiPages', selectedWikiKbId],
    queryFn: () => listWikiPages(selectedWikiKbId),
    refetchInterval: false,
    enabled: !!selectedWikiKbId,
  });

  useEffect(() => {
    loadResearchJobs();
  }, []);

  const loadResearchJobs = async () => {
    try {
      const jobs = await getCompletedResearch();
      setResearchJobs(jobs.map(j => ({ job_id: j.job_id, topic: j.topic, status: 'completed' })));
    } catch { /* ignore */ }
  };

  useEffect(() => {
    if (searchQuery.trim().length < 2) { setSearchResults([]); return; }
    const timer = setTimeout(async () => {
      setSearching(true);
      try {
        setSearchResults(await wikiSearch(searchQuery.trim(), selectedWikiKbId));
      } catch { setSearchResults([]); } finally { setSearching(false); }
    }, 400);
    return () => clearTimeout(timer);
  }, [searchQuery, selectedWikiKbId]);

  const handlePageClick = async (slug: string) => {
    try {
      setSelectedPage(await getWikiPage(slug, selectedWikiKbId));
      setSelectedRawMd('');
    } catch { message.error('Failed to load wiki page'); }
  };

  const handleSourceClick = async (paperId: string) => {
    try {
      const { markdown } = await getPaperMarkdown(paperId, selectedWikiKbId);
      setSelectedRawMd(markdown);
    } catch { setSelectedRawMd('No raw markdown available.'); }
  };

  const handleIngest = async (paperId: string) => {
    setIngesting(true);
    try {
      const r = await wikiIngest(paperId, selectedWikiKbId);
      message.success(`Wiki compiled: ${r.pages_created.length} pages`);
      refetch();
    } catch { message.error('Ingestion failed'); } finally { setIngesting(false); }
  };

  const handleBack = () => { setSelectedPage(null); setSelectedRawMd(''); };

  const handleSearchResultClick = (r: WikiSearchResult) => {
    if (r.type === 'wiki_page' && r.slug) handlePageClick(r.slug);
    else if (r.type === 'raw_source' && r.paper_id) handleSourceClick(r.paper_id);
  };

  const handleCreateKb = async () => {
    if (!newKbName.trim()) return;
    try {
      await createWikiKb(newKbName.trim(), newKbDesc.trim());
      message.success('Knowledge base created');
      setCreateModalOpen(false);
      setNewKbName('');
      setNewKbDesc('');
      const kbs = await listWikiKbs();
      setWikiKbs(kbs);
      if (kbs.length > 0) setSelectedWikiKbId(kbs[0].id);
      onKbChange?.();
    } catch { message.error('Failed to create KB'); }
  };

  const handleDeleteKb = async (kbId: string) => {
    Modal.confirm({
      title: 'Delete this Knowledge Base?',
      content: 'All wiki pages and indexed data under this KB will be removed.',
      okText: 'Delete',
      okButtonProps: { danger: true },
      onOk: async () => {
        await deleteWikiKb(kbId);
        message.success('KB deleted');
        if (selectedWikiKbId === kbId) setSelectedWikiKbId(null);
        const kbs = await listWikiKbs();
        setWikiKbs(kbs);
        onKbChange?.();
      },
    });
  };

  const handleImportResearch = async () => {
    if (!importResearchJobId || !selectedWikiKbId) return;
    setImporting(true);
    try {
      const r = await importResearchToWiki(selectedWikiKbId, importResearchJobId);
      message.success(`Imported research: ${r.chunks} chunks indexed`);
      refetch();
      setImportModalOpen(false);
    } catch { message.error('Import failed'); } finally { setImporting(false); }
  };

  const handleUploadPdf = async (file: File) => {
    if (!selectedWikiKbId) { message.warning('Select a KB first'); return false; }
    setUploading(true);
    try {
      await uploadPaperWithMineruToKB(file, selectedWikiKbId);
      message.success(`${file.name} uploaded to KB`);
      refetch();
    } catch (err: any) {
      message.error(err.response?.data?.detail || err.message);
    } finally { setUploading(false); }
    return false;
  };

  // ---------- DETAIL VIEW (wiki page selected) ----------

  if (selectedPage) {
    return (
      <div style={{ height: 'calc(100vh - 120px)', display: 'flex', flexDirection: 'column', gap: 12 }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
          <Space>
            <Button type="link" icon={<HomeOutlined />} onClick={handleBack}>Wiki Home</Button>
            <Title level={5} style={{ margin: 0 }}>{selectedPage.title}</Title>
          </Space>
          <Button icon={<ReloadOutlined />} onClick={() => refetch()} size="small">Refresh</Button>
        </div>
        <Card size="small" style={{ borderRadius: 8, background: '#fafafa' }} styles={{ body: { padding: '8px 16px' } }}>
          <Space size="middle" wrap>
            <Tag color={PAGE_TYPE_COLORS[selectedPage.page_type] || '#999'}>{selectedPage.page_type}</Tag>
            {selectedPage.cross_refs.map(ref => (
              <Tag key={ref} style={{ cursor: 'pointer' }} color="blue" onClick={() => handlePageClick(ref)}>
                <LinkOutlined /> {ref}
              </Tag>
            ))}
          </Space>
          <div style={{ marginTop: 8 }}>
            {selectedPage.source_paper_ids.map(pid => (
              <Button key={pid} type="link" size="small" icon={<FileTextOutlined />} onClick={() => handleSourceClick(pid)}>
                Source: {pid.slice(0, 12)}...
              </Button>
            ))}
          </div>
        </Card>
        <div style={{ flex: 1, overflowY: 'auto' }}>
          <Card title={selectedPage.title} style={{ borderRadius: 8 }}
            styles={{ body: { maxHeight: 'calc(100vh - 350px)', overflowY: 'auto', padding: '16px 24px' } }}>
            <div className="wiki-markdown"><ReactMarkdown>{selectedPage.content}</ReactMarkdown></div>
          </Card>
        </div>
        {selectedRawMd && (
          <Collapse items={[{
            key: 'raw', label: 'Raw Source Markdown',
            children: <div style={{ maxHeight: '40vh', overflowY: 'auto' }}>
              <ReactMarkdown>{selectedRawMd.slice(0, 5000)}</ReactMarkdown>
            </div>,
          }]} style={{ borderRadius: 8 }} />
        )}
      </div>
    );
  }

  // ---------- MAIN VIEW ----------

  return (
    <div style={{ height: 'calc(100vh - 120px)', display: 'flex', flexDirection: 'column', gap: 16 }}>
      {/* KB Selector Bar */}
      <Card size="small" style={{ borderRadius: 8, background: '#f6f8fa' }}>
        <Space style={{ width: '100%', justifyContent: 'space-between' }}>
          <Space>
            <DatabaseOutlined style={{ color: '#1677ff' }} />
            <Text strong>Knowledge Base:</Text>
            <Select
              placeholder="Select or create a KB"
              value={selectedWikiKbId}
              onChange={setSelectedWikiKbId}
              style={{ minWidth: 220 }}
              options={wikiKbs.map(kb => ({ value: kb.id, label: kb.name }))}
              notFoundContent="No KBs yet"
            />
          </Space>
          <Space>
            <Button type="primary" icon={<PlusOutlined />} onClick={() => setCreateModalOpen(true)}>New KB</Button>
            {selectedWikiKbId && (
              <Button danger icon={<DeleteOutlined />} onClick={() => handleDeleteKb(selectedWikiKbId)}>Delete</Button>
            )}
            <Button icon={<ReloadOutlined />} onClick={() => { refetch(); onKbChange?.(); }} size="small" />
          </Space>
        </Space>
      </Card>

      {!selectedWikiKbId ? (
        <Empty description="Create a Knowledge Base to get started">
          <Button type="primary" icon={<PlusOutlined />} onClick={() => setCreateModalOpen(true)}>Create KB</Button>
        </Empty>
      ) : (
        <>
          {/* Import Sources Section */}
          <Card size="small" title={<><ImportOutlined /> Import Sources into KB</>} style={{ borderRadius: 8 }}>
            <Space wrap>
              <Button icon={<ExperimentOutlined />} onClick={() => { loadResearchJobs(); setImportModalOpen(true); }}>
                Import from Research
              </Button>
              <Upload
                accept=".pdf"
                showUploadList={false}
                beforeUpload={handleUploadPdf as any}
                disabled={uploading}
              >
                <Button icon={<UploadOutlined />} loading={uploading}>
                  Upload PDF (MinerU)
                </Button>
              </Upload>
            </Space>
          </Card>

          {/* Search */}
          <Input
            prefix={<SearchOutlined />}
            placeholder="Search wiki pages and source documents..."
            value={searchQuery}
            onChange={e => setSearchQuery(e.target.value)}
            allowClear
          />

          {searchQuery.trim().length >= 2 && (
            <Card size="small" title="Search Results" style={{ borderRadius: 8 }}>
              {searching ? <Spin /> : searchResults.length === 0 ? <Empty description="No results" /> : (
                <List size="small" dataSource={searchResults}
                  renderItem={item => (
                    <List.Item style={{ cursor: 'pointer', padding: '8px 12px' }} onClick={() => handleSearchResultClick(item)}>
                      <List.Item.Meta
                        title={<Space><Tag color={item.type === 'wiki_page' ? 'blue' : 'green'}>
                          {item.type === 'wiki_page' ? 'Wiki' : 'Source'}</Tag><Text strong>{item.title}</Text></Space>}
                        description={item.snippet.slice(0, 200)} />
                    </List.Item>
                  )} />
              )}
            </Card>
          )}

          {/* Wiki Pages */}
          {isLoading ? <Spin style={{ marginTop: 40 }} /> : (!pages || pages.length === 0) ? (
            <Empty description="No wiki pages yet. Import sources and run ingestion." style={{ marginTop: 40 }} />
          ) : (
            <List
              dataSource={pages}
              renderItem={page => (
                <Card hoverable size="small" style={{ marginBottom: 8, borderRadius: 8 }}
                  onClick={() => handlePageClick(page.slug)}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                    <Space>
                      <Tag color={PAGE_TYPE_COLORS[page.page_type] || '#999'}>{page.page_type}</Tag>
                      <Text strong>{page.title}</Text>
                    </Space>
                    <Space>
                      {page.source_paper_ids.map(pid => (
                        <Button key={pid} type="link" size="small" icon={<RobotOutlined />}
                          onClick={e => { e.stopPropagation(); handleIngest(pid); }} loading={ingesting}>
                          Ingest
                        </Button>
                      ))}
                      <RightOutlined style={{ color: '#bbb' }} />
                    </Space>
                  </div>
                </Card>
              )} />
          )}
        </>
      )}

      {/* Create KB Modal */}
      <Modal open={createModalOpen} title="Create Knowledge Base" onOk={handleCreateKb}
        onCancel={() => setCreateModalOpen(false)} okText="Create">
        <Space direction="vertical" style={{ width: '100%' }}>
          <Text strong>Name</Text>
          <Input placeholder="e.g., scHi-C Research" value={newKbName}
            onChange={e => setNewKbName(e.target.value)} onPressEnter={handleCreateKb} />
          <Text strong>Description (optional)</Text>
          <Input.TextArea placeholder="What's this KB about?" value={newKbDesc}
            onChange={e => setNewKbDesc(e.target.value)} rows={2} />
        </Space>
      </Modal>

      {/* Import Research Modal */}
      <Modal open={importModalOpen} title="Import Research into KB"
        onOk={handleImportResearch} onCancel={() => setImportModalOpen(false)}
        okText="Import" confirmLoading={importing}>
        <Space direction="vertical" style={{ width: '100%' }}>
          <Text>Select a completed research project:</Text>
          <Select
            placeholder="Choose research..."
            value={importResearchJobId || undefined}
            onChange={setImportResearchJobId}
            style={{ width: '100%' }}
            options={researchJobs.map(j => ({
              value: j.job_id,
              label: `${j.topic || j.job_id} (${j.status})`,
            }))}
          />
        </Space>
      </Modal>
    </div>
  );
};

export default WikiExplorer;