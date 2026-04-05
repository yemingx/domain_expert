import { useState, useRef } from 'react';
import { Button, Card, List, Tag, Typography, Space, message, Progress, Table } from 'antd';
import {
  UploadOutlined, FileTextOutlined, ReloadOutlined,
  FolderOpenOutlined, CheckCircleOutlined, CloseCircleOutlined, LoadingOutlined,
} from '@ant-design/icons';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { uploadPaper, listPapers } from '../utils/api';
import type { Paper } from '../types';

const { Text } = Typography;

const statusColors: Record<string, string> = {
  pending: 'default',
  processing: 'processing',
  completed: 'success',
  failed: 'error',
};

interface QueueItem {
  name: string;
  file: File;
  status: 'pending' | 'uploading' | 'done' | 'error';
  error?: string;
}

export default function PaperUpload() {
  const queryClient = useQueryClient();
  const [queue, setQueue] = useState<QueueItem[]>([]);
  const [running, setRunning] = useState(false);

  const fileInputRef = useRef<HTMLInputElement>(null);
  const folderInputRef = useRef<HTMLInputElement>(null);
  const dropRef = useRef<HTMLDivElement>(null);
  const [dragOver, setDragOver] = useState(false);

  const { data: papers = [], isLoading, refetch } = useQuery({
    queryKey: ['papers'],
    queryFn: listPapers,
    refetchInterval: 5000,
  });

  // ── helpers ────────────────────────────────────────────────────────────────

  const updateItem = (idx: number, patch: Partial<QueueItem>) =>
    setQueue(q => q.map((item, i) => (i === idx ? { ...item, ...patch } : item)));

  const enqueue = (files: FileList | File[]) => {
    const pdfs = Array.from(files).filter(f => f.name.toLowerCase().endsWith('.pdf'));
    if (!pdfs.length) { message.warning('No PDF files found in selection'); return; }

    const newItems: QueueItem[] = pdfs.map(f => ({ name: f.name, file: f, status: 'pending' }));
    setQueue(q => [...q, ...newItems]);
    message.success(`Added ${pdfs.length} PDF${pdfs.length > 1 ? 's' : ''} to queue`);
  };

  // ── sequential upload runner ───────────────────────────────────────────────

  const runQueue = async (currentQueue: QueueItem[]) => {
    if (running) return;
    setRunning(true);

    for (let i = 0; i < currentQueue.length; i++) {
      if (currentQueue[i].status !== 'pending') continue;

      updateItem(i, { status: 'uploading' });
      try {
        await uploadPaper(currentQueue[i].file);
        updateItem(i, { status: 'done' });
        queryClient.invalidateQueries({ queryKey: ['papers'] });
      } catch (err: any) {
        updateItem(i, {
          status: 'error',
          error: err.response?.data?.detail || err.message,
        });
      }
    }

    setRunning(false);
  };

  const handleStartUpload = () => {
    // snapshot current queue to iterate correctly
    setQueue(q => {
      runQueue(q);
      return q;
    });
  };

  const clearCompleted = () =>
    setQueue(q => q.filter(item => item.status === 'pending' || item.status === 'uploading'));

  // ── drag-and-drop ──────────────────────────────────────────────────────────

  const onDrop = (e: React.DragEvent) => {
    e.preventDefault();
    setDragOver(false);
    enqueue(e.dataTransfer.files);
  };

  // ── derived state ──────────────────────────────────────────────────────────

  const pendingCount = queue.filter(i => i.status === 'pending').length;
  const doneCount = queue.filter(i => i.status === 'done').length;
  const errorCount = queue.filter(i => i.status === 'error').length;
  const uploadingNow = queue.find(i => i.status === 'uploading');
  const overallProgress = queue.length
    ? Math.round(((doneCount + errorCount) / queue.length) * 100)
    : 0;

  // ── queue status icon ──────────────────────────────────────────────────────

  const statusIcon = (item: QueueItem) => {
    if (item.status === 'uploading') return <LoadingOutlined style={{ color: '#1677ff' }} />;
    if (item.status === 'done') return <CheckCircleOutlined style={{ color: '#52c41a' }} />;
    if (item.status === 'error') return <CloseCircleOutlined style={{ color: '#ff4d4f' }} />;
    return <span style={{ color: '#999' }}>—</span>;
  };

  return (
    <Space direction="vertical" style={{ width: '100%' }} size="large">
      {/* ── Upload zone ──────────────────────────────────────────────────── */}
      <Card title="Upload Research Papers">
        {/* drop zone */}
        <div
          ref={dropRef}
          onDrop={onDrop}
          onDragOver={e => { e.preventDefault(); setDragOver(true); }}
          onDragLeave={() => setDragOver(false)}
          style={{
            border: `2px dashed ${dragOver ? '#1677ff' : '#d9d9d9'}`,
            borderRadius: 8,
            background: dragOver ? '#e6f4ff' : '#fafafa',
            padding: '32px 16px',
            textAlign: 'center',
            cursor: 'pointer',
            transition: 'all 0.2s',
            marginBottom: 16,
          }}
          onClick={() => fileInputRef.current?.click()}
        >
          <UploadOutlined style={{ fontSize: 48, color: '#1677ff' }} />
          <p style={{ margin: '12px 0 4px', fontSize: 16 }}>
            Drop PDFs here, or click to select files
          </p>
          <p style={{ color: '#999', margin: 0 }}>
            Multiple files supported
          </p>
        </div>

        {/* hidden inputs */}
        <input
          ref={fileInputRef}
          type="file"
          accept=".pdf"
          multiple
          style={{ display: 'none' }}
          onChange={e => { if (e.target.files) enqueue(e.target.files); e.target.value = ''; }}
        />
        <input
          ref={folderInputRef}
          type="file"
          // @ts-ignore – non-standard but supported in all major browsers
          webkitdirectory=""
          multiple
          style={{ display: 'none' }}
          onChange={e => { if (e.target.files) enqueue(e.target.files); e.target.value = ''; }}
        />

        {/* action buttons */}
        <Space wrap>
          <Button icon={<UploadOutlined />} onClick={() => fileInputRef.current?.click()}>
            Select PDFs
          </Button>
          <Button icon={<FolderOpenOutlined />} onClick={() => folderInputRef.current?.click()}>
            Select Folder
          </Button>
          {queue.length > 0 && (
            <>
              <Button
                type="primary"
                icon={<UploadOutlined />}
                disabled={running || pendingCount === 0}
                onClick={handleStartUpload}
              >
                Upload {pendingCount > 0 ? `${pendingCount} PDF${pendingCount > 1 ? 's' : ''}` : ''}
              </Button>
              <Button onClick={clearCompleted} disabled={running}>
                Clear Done / Errors
              </Button>
            </>
          )}
        </Space>

        {/* overall progress */}
        {queue.length > 0 && (
          <div style={{ marginTop: 16 }}>
            <Space style={{ marginBottom: 4 }}>
              <Text type="secondary">
                {doneCount}/{queue.length} uploaded
                {errorCount > 0 && <>, <Text type="danger">{errorCount} failed</Text></>}
                {uploadingNow && <> — uploading <b>{uploadingNow.name}</b></>}
              </Text>
            </Space>
            <Progress percent={overallProgress} status={errorCount > 0 ? 'exception' : running ? 'active' : 'normal'} />
          </div>
        )}

        {/* per-file queue table */}
        {queue.length > 0 && (
          <Table
            size="small"
            style={{ marginTop: 12 }}
            dataSource={queue}
            rowKey="name"
            pagination={false}
            scroll={{ y: 260 }}
            columns={[
              {
                title: 'File',
                dataIndex: 'name',
                ellipsis: true,
              },
              {
                title: 'Size',
                dataIndex: 'file',
                width: 80,
                render: (f: File) => `${(f.size / 1024).toFixed(0)} KB`,
              },
              {
                title: 'Status',
                dataIndex: 'status',
                width: 100,
                render: (status: string, item: QueueItem) => (
                  <Space size={4}>
                    {statusIcon(item)}
                    <span style={{ textTransform: 'capitalize' }}>
                      {status === 'error' ? <Text type="danger" title={item.error}>error</Text> : status}
                    </span>
                  </Space>
                ),
              },
            ]}
          />
        )}
      </Card>

      {/* ── Papers in knowledge base ─────────────────────────────────────── */}
      <Card
        title="Papers in Knowledge Base"
        extra={<Button icon={<ReloadOutlined />} onClick={() => refetch()}>Refresh</Button>}
      >
        <List
          loading={isLoading}
          dataSource={papers}
          locale={{ emptyText: 'No papers uploaded yet' }}
          renderItem={(paper: Paper) => (
            <List.Item>
              <List.Item.Meta
                avatar={<FileTextOutlined style={{ fontSize: 24 }} />}
                title={
                  <Space>
                    <Text strong>{paper.title || paper.filename}</Text>
                    <Tag color={statusColors[paper.status]}>{paper.status}</Tag>
                  </Space>
                }
                description={
                  <Space direction="vertical" size={0}>
                    {paper.authors?.length > 0 && (
                      <Text type="secondary">{paper.authors.join(', ')}</Text>
                    )}
                    <Space>
                      {paper.year > 0 && <Tag>{paper.year}</Tag>}
                      {paper.chunks_count > 0 && <Tag color="blue">{paper.chunks_count} chunks</Tag>}
                    </Space>
                  </Space>
                }
              />
            </List.Item>
          )}
        />
      </Card>
    </Space>
  );
}
