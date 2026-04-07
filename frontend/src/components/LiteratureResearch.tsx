import { useState } from 'react';
import {
  Card,
  Button,
  Input,
  InputNumber,
  Form,
  Space,
  message,
  Table,
  Tag,
  Typography,
  Progress,
  Descriptions,
  Modal,
  Popconfirm,
  Alert,
  List,
} from 'antd';
import {
  SearchOutlined,
  ReloadOutlined,
  ImportOutlined,
  ExperimentOutlined,
  CheckCircleOutlined,
  CloseCircleOutlined,
  LoadingOutlined,
  ClockCircleOutlined,
  DeleteOutlined,
  DownloadOutlined,
  WarningOutlined,
} from '@ant-design/icons';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import {
  runResearch,
  listResearchJobs,
  getResearchJob,
  importResearchToKB,
  deleteResearchJob,
  getResearchDownloadUrl,
  retryResearchJob,
  resetResearchJob,
} from '../utils/api';
import type { ResearchJob } from '../types';

const { Text, Paragraph } = Typography;
const { TextArea } = Input;

interface FormValues {
  topic: string;
  query: string;
  max_papers: number;
}

export default function LiteratureResearch() {
  const queryClient = useQueryClient();
  const [form] = Form.useForm<FormValues>();
  const [pollingJobId, setPollingJobId] = useState<string | null>(null);
  const [selectedJob, setSelectedJob] = useState<ResearchJob | null>(null);
  const [isDetailModalOpen, setIsDetailModalOpen] = useState(false);
  const [downloadingJobId, setDownloadingJobId] = useState<string | null>(null);

  // Query all jobs
  const { data: jobs = [], isLoading: jobsLoading, refetch } = useQuery({
    queryKey: ['research-jobs'],
    queryFn: listResearchJobs,
    refetchInterval: 5000,
  });

  // Poll specific job if running
  const { data: activeJob } = useQuery({
    queryKey: ['research-job', pollingJobId],
    queryFn: () => getResearchJob(pollingJobId!),
    enabled: !!pollingJobId,
    refetchInterval: (query) => {
      const data = query.state.data as ResearchJob | undefined;
      return data?.status === 'running' ? 3000 : false;
    },
  });

  const runMutation = useMutation({
    mutationFn: (values: FormValues) =>
      runResearch(values.topic, values.query, values.max_papers),
    onSuccess: (data) => {
      message.success(`Research job started: ${data.job_id}`);
      setPollingJobId(data.job_id);
      queryClient.invalidateQueries({ queryKey: ['research-jobs'] });
    },
    onError: (error: any) => {
      message.error(`Failed to start research: ${error.message}`);
    },
  });

  const importMutation = useMutation({
    mutationFn: importResearchToKB,
    onSuccess: (data) => {
      message.success(`Imported ${data.chunks_added} chunks to knowledge base`);
      queryClient.invalidateQueries({ queryKey: ['papers'] });
      queryClient.invalidateQueries({ queryKey: ['stats'] });
    },
    onError: (error: any) => {
      message.error(`Import failed: ${error.message}`);
    },
  });

  const deleteMutation = useMutation({
    mutationFn: deleteResearchJob,
    onSuccess: (data) => {
      message.success('Job deleted');
      queryClient.invalidateQueries({ queryKey: ['research-jobs'] });
      if (selectedJob?.job_id === data.job_id) {
        setIsDetailModalOpen(false);
        setSelectedJob(null);
      }
    },
    onError: (error: any) => {
      message.error(`Delete failed: ${error.response?.data?.detail || error.message}`);
    },
  });

  const retryMutation = useMutation({
    mutationFn: retryResearchJob,
    onSuccess: (data) => {
      message.success(`Retrying job from stage: ${data.last_successful_stage || 'beginning'}`);
      setPollingJobId(data.job_id);
      queryClient.invalidateQueries({ queryKey: ['research-jobs'] });
    },
    onError: (error: any) => {
      message.error(`Retry failed: ${error.response?.data?.detail || error.message}`);
    },
  });

  const resetMutation = useMutation({
    mutationFn: resetResearchJob,
    onSuccess: (data) => {
      message.success('Job reset to initial state');
      queryClient.invalidateQueries({ queryKey: ['research-jobs'] });
      if (selectedJob?.job_id === data.job_id) {
        setSelectedJob(data);
      }
    },
    onError: (error: any) => {
      message.error(`Reset failed: ${error.response?.data?.detail || error.message}`);
    },
  });

  const handleSubmit = (values: FormValues) => {
    runMutation.mutate(values);
  };

  const handleImport = (jobId: string) => {
    importMutation.mutate(jobId);
  };

  const handleDownload = async (jobId: string) => {
    setDownloadingJobId(jobId);
    try {
      const response = await fetch(getResearchDownloadUrl(jobId));
      if (!response.ok) {
        const text = await response.text();
        let detail = text;
        try { detail = JSON.parse(text).detail; } catch { /* ignore */ }
        throw new Error(detail || `HTTP ${response.status}`);
      }
      const disposition = response.headers.get('content-disposition') || '';
      const match = disposition.match(/filename\*=UTF-8''([^;]+)/i)
        || disposition.match(/filename="([^"]+)"/i);
      const filename = match ? decodeURIComponent(match[1]) : `${jobId.slice(0, 8)}_reports.zip`;
      const blob = await response.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = filename;
      a.click();
      URL.revokeObjectURL(url);
      message.success('下载完成');
    } catch (err: any) {
      message.error(`下载失败: ${err.message}`);
    } finally {
      setDownloadingJobId(null);
    }
  };

  const showJobDetail = (job: ResearchJob) => {
    setSelectedJob(job);
    setIsDetailModalOpen(true);
  };

  const getStatusIcon = (status: string) => {
    switch (status) {
      case 'pending': return <ClockCircleOutlined style={{ color: '#faad14' }} />;
      case 'running': return <LoadingOutlined style={{ color: '#1890ff' }} />;
      case 'completed': return <CheckCircleOutlined style={{ color: '#52c41a' }} />;
      case 'failed': return <CloseCircleOutlined style={{ color: '#ff4d4f' }} />;
      default: return null;
    }
  };

  const getStatusTag = (status: string) => {
    const colors: Record<string, string> = {
      pending: 'default', running: 'processing', completed: 'success', failed: 'error',
    };
    return (
      <Tag icon={getStatusIcon(status)} color={colors[status]}>
        {status.toUpperCase()}
      </Tag>
    );
  };

  const columns = [
    { title: 'Job ID', dataIndex: 'job_id', width: 280, ellipsis: true },
    { title: 'Topic', dataIndex: 'topic' },
    {
      title: 'Status',
      dataIndex: 'status',
      width: 120,
      render: (status: string) => getStatusTag(status),
    },
    {
      title: 'Progress',
      key: 'progress',
      width: 150,
      render: (_: any, record: ResearchJob) => {
        const isAnalyzing = record.current_stage === 'analyzing' && record.total_papers > 0;
        const numerator = isAnalyzing ? record.analyzed_papers : record.processed_papers;
        const pct = record.total_papers > 0
          ? Math.round((numerator / record.total_papers) * 100) : 0;
        return (
          <Space direction="vertical" size={0} style={{ width: '100%' }}>
            <Progress percent={pct} size="small"
              status={record.status === 'failed' ? 'exception' : 'active'} />
            <Text type="secondary" style={{ fontSize: 12 }}>
              {isAnalyzing ? `深度分析 ${record.analyzed_papers}/${record.total_papers}` : `${record.processed_papers}/${record.total_papers} papers`}
            </Text>
          </Space>
        );
      },
    },
    {
      title: 'Created',
      dataIndex: 'created_at',
      width: 180,
      render: (text: string) => (
        <Text type="secondary">{new Date(text).toLocaleString()}</Text>
      ),
    },
    {
      title: 'Actions',
      key: 'actions',
      width: 320,
      render: (_: any, record: ResearchJob) => (
        <Space wrap>
          <Button size="small" onClick={() => showJobDetail(record)}>Details</Button>
          {record.status === 'failed' && (
            <Button size="small" type="primary" icon={<ReloadOutlined />}
              onClick={() => retryMutation.mutate(record.job_id)}
              loading={retryMutation.isPending && pollingJobId === record.job_id}>
              Retry
            </Button>
          )}
          {record.status === 'completed' && (
            <Button size="small" type="primary" icon={<ImportOutlined />}
              onClick={() => handleImport(record.job_id)}
              loading={importMutation.isPending}>
              Import
            </Button>
          )}
          {record.status === 'completed' && (
            <Button size="small" icon={<DownloadOutlined />}
              loading={downloadingJobId === record.job_id}
              onClick={() => handleDownload(record.job_id)}>
              Download
            </Button>
          )}
          {record.status !== 'running' && (
            <Popconfirm title="Delete this job?"
              description="This will permanently remove the job and its data."
              onConfirm={() => deleteMutation.mutate(record.job_id)}
              okText="Delete" cancelText="Cancel" okButtonProps={{ danger: true }}>
              <Button size="small" danger icon={<DeleteOutlined />}>Delete</Button>
            </Popconfirm>
          )}
        </Space>
      ),
    },
  ];

  return (
    <Space direction="vertical" style={{ width: '100%' }} size="large">
      {/* Configuration Form */}
      <Card title={<Space><ExperimentOutlined /><span>Literature Research</span></Space>}>
        <Paragraph type="secondary">
          Run automated PubMed literature research. Enter a topic and NCBI query string.
        </Paragraph>
        <Alert
          type="info"
          showIcon
          message="请先确认 PubMed 检索式"
          description={
            <span>
              建议先通过{' '}
              <a href="https://pubmed.ncbi.nlm.nih.gov/advanced/" target="_blank" rel="noopener noreferrer">
                PubMed Advanced Search
              </a>
              {' '}确认检索式能返回预期结果，然后将确认好的检索式输入到下方的 NCBI/PubMed Query 中。
            </span>
          }
          style={{ marginBottom: 16 }}
        />

        <Form form={form} layout="vertical" onFinish={handleSubmit}
          initialValues={{ topic: 'NIPD', query: 'NIPD[Title/Abstract] AND monogenic[Title/Abstract]', max_papers: 50 }}>
          <Form.Item name="topic" label="Topic"
            rules={[{ required: true, message: 'Please enter topic' }]}
            help="Short topic name for identification">
            <Input placeholder="e.g., NIPD, CRISPR" />
          </Form.Item>
          <Form.Item name="query" label="NCBI/PubMed Query"
            rules={[{ required: true, message: 'Please enter query' }]}
            help="Full NCBI query with field tags [Title/Abstract], [Date], etc.">
            <TextArea rows={3}
              placeholder="e.g., NIPD[Title/Abstract] AND monogenic[Title/Abstract] AND 2024[Date]" />
          </Form.Item>
          <Form.Item name="max_papers" label="Max Papers"
            rules={[{ required: true, message: 'Please enter max papers' }]}
            help="Maximum number of papers to retrieve from PubMed">
            <InputNumber min={1} max={500} style={{ width: '100%' }} />
          </Form.Item>
          <Form.Item>
            <Button type="primary" icon={<SearchOutlined />}
              onClick={() => form.submit()} loading={runMutation.isPending} size="large">
              Run Research
            </Button>
          </Form.Item>
        </Form>

        {/* Active Job Progress */}
        {activeJob && activeJob.status === 'running' && (
          <Card type="inner" title="Active Research Job"
            style={{ marginTop: 24, background: '#f6ffed' }}>
            <Space direction="vertical" style={{ width: '100%' }}>
              <Text strong>Topic: {activeJob.topic}</Text>
              <Text type="secondary">Stage: {activeJob.current_stage || 'processing'}</Text>
              <Progress
                percent={activeJob.total_papers > 0
                  ? Math.round(
                      (activeJob.current_stage === 'analyzing'
                        ? activeJob.analyzed_papers
                        : activeJob.processed_papers) / activeJob.total_papers * 100
                    ) : 0}
                status="active"
                format={(pct) =>
                  activeJob.current_stage === 'analyzing'
                    ? `深度分析 ${activeJob.analyzed_papers}/${activeJob.total_papers} (${pct}%)`
                    : `${pct}% (${activeJob.processed_papers}/${activeJob.total_papers})`
                }
              />
              {activeJob.warnings && activeJob.warnings.length > 0 && (
                <Alert
                  type="warning"
                  icon={<WarningOutlined />}
                  showIcon
                  message={`注意：${activeJob.warnings.length} 项部分失败`}
                  description={
                    <List
                      size="small"
                      dataSource={activeJob.warnings}
                      renderItem={(w) => <List.Item style={{ padding: '2px 0', fontSize: 12 }}>{w}</List.Item>}
                    />
                  }
                />
              )}
            </Space>
          </Card>
        )}

        {/* Completed job warnings (shown below active card area) */}
        {activeJob && activeJob.status === 'completed' && activeJob.warnings && activeJob.warnings.length > 0 && (
          <Alert
            style={{ marginTop: 16 }}
            type="warning"
            icon={<WarningOutlined />}
            showIcon
            message={`任务完成，但有 ${activeJob.warnings.length} 项部分失败`}
            description={
              <List
                size="small"
                dataSource={activeJob.warnings}
                renderItem={(w) => <List.Item style={{ padding: '2px 0', fontSize: 12 }}>{w}</List.Item>}
              />
            }
            closable
          />
        )}
      </Card>

      {/* Jobs List */}
      <Card title="Research Jobs"
        extra={<Button icon={<ReloadOutlined />} onClick={() => refetch()}>Refresh</Button>}>
        <Table dataSource={jobs} columns={columns} loading={jobsLoading}
          rowKey="job_id" pagination={{ pageSize: 10 }} />
      </Card>

      {/* Job Detail Modal */}
      <Modal
        title="Research Job Details"
        open={isDetailModalOpen}
        onCancel={() => setIsDetailModalOpen(false)}
        width={800}
        footer={[
          <Button key="close" onClick={() => setIsDetailModalOpen(false)}>Close</Button>,
          selectedJob?.status === 'failed' && (
            <Popconfirm
              key="reset"
              title="Reset this job?"
              description="This will clear all progress and start fresh."
              onConfirm={() => selectedJob && resetMutation.mutate(selectedJob.job_id)}
              okText="Reset" cancelText="Cancel">
              <Button loading={resetMutation.isPending}>Reset</Button>
            </Popconfirm>
          ),
          selectedJob?.status === 'failed' && (
            <Button key="retry" type="primary" icon={<ReloadOutlined />}
              loading={retryMutation.isPending}
              onClick={() => selectedJob && retryMutation.mutate(selectedJob.job_id)}>
              Retry from Checkpoint
            </Button>
          ),
          selectedJob?.status === 'completed' ? (
            <Button key="download" icon={<DownloadOutlined />}
              loading={downloadingJobId === selectedJob?.job_id}
              onClick={() => selectedJob && handleDownload(selectedJob.job_id)}>
              Download
            </Button>
          ) : null,
          selectedJob?.status === 'completed' ? (
            <Button key="import" type="primary" icon={<ImportOutlined />}
              onClick={() => {
                selectedJob && handleImport(selectedJob.job_id);
                setIsDetailModalOpen(false);
              }}>
              Import to KB
            </Button>
          ) : null,
        ]}
      >
        {selectedJob && (
          <Descriptions bordered column={1}>
            <Descriptions.Item label="Job ID">{selectedJob.job_id}</Descriptions.Item>
            <Descriptions.Item label="Topic">{selectedJob.topic}</Descriptions.Item>
            <Descriptions.Item label="Query">
              <Text style={{ fontFamily: 'monospace', fontSize: 12 }}>{selectedJob.query}</Text>
            </Descriptions.Item>
            <Descriptions.Item label="Max Papers">{selectedJob.max_papers}</Descriptions.Item>
            <Descriptions.Item label="Status">{getStatusTag(selectedJob.status)}</Descriptions.Item>
            <Descriptions.Item label="Stage">{selectedJob.current_stage || '—'}</Descriptions.Item>
            {/* Checkpoint Status */}
            {selectedJob.stage_completed && (
              <Descriptions.Item label="Completed Stages">
                <Space direction="vertical" size={0}>
                  {Object.entries(selectedJob.stage_completed).map(([stage, completed]) => (
                    <Space key={stage}>
                      {completed ? (
                        <CheckCircleOutlined style={{ color: '#52c41a' }} />
                      ) : (
                        <ClockCircleOutlined style={{ color: '#d9d9d9' }} />
                      )}
                      <Text style={{ fontSize: 12, color: completed ? undefined : '#999' }}>
                        {stage === 'searching' && '文献检索 (PubMed)'}
                        {stage === 'enriching' && '引用富化 (Semantic Scholar)'}
                        {stage === 'analyzing' && '深度分析 (LLM)'}
                        {stage === 'converting' && '报告生成'}
                        {completed ? ' ✓' : ' (pending)'}
                      </Text>
                    </Space>
                  ))}
                </Space>
              </Descriptions.Item>
            )}
            {selectedJob.last_successful_stage && (
              <Descriptions.Item label="Resume From">
                <Tag color="blue">{selectedJob.last_successful_stage}</Tag>
                {selectedJob.stage_retry_count ? (
                  <Text type="secondary" style={{ fontSize: 12, marginLeft: 8 }}>
                    (retried {selectedJob.stage_retry_count} time{selectedJob.stage_retry_count > 1 ? 's' : ''})
                  </Text>
                ) : null}
              </Descriptions.Item>
            )}
            <Descriptions.Item label="Progress">
              {selectedJob.processed_papers} / {selectedJob.total_papers} papers
            </Descriptions.Item>
            <Descriptions.Item label="Created">
              {new Date(selectedJob.created_at).toLocaleString()}
            </Descriptions.Item>
            {selectedJob.completed_at && (
              <Descriptions.Item label="Completed">
                {new Date(selectedJob.completed_at).toLocaleString()}
              </Descriptions.Item>
            )}
            {selectedJob.result_path && (
              <Descriptions.Item label="本地 Markdown 路径">
                <Text copyable style={{ fontFamily: 'monospace', fontSize: 12, wordBreak: 'break-all' }}>
                  {selectedJob.result_path}
                </Text>
              </Descriptions.Item>
            )}
            {selectedJob.error_message && (
              <Descriptions.Item label="错误">
                <Alert
                  type="error"
                  message={selectedJob.error_message}
                  description={
                    selectedJob.last_successful_stage ? (
                      <Text type="secondary">
                        提示：可以从已完成的阶段继续运行，点击 Retry from Checkpoint 按钮
                      </Text>
                    ) : null
                  }
                  showIcon
                />
              </Descriptions.Item>
            )}
            {selectedJob.warnings && selectedJob.warnings.length > 0 && (
              <Descriptions.Item label={
                <Space><WarningOutlined style={{ color: '#faad14' }} /><span>部分失败</span></Space>
              }>
                <List
                  size="small"
                  dataSource={selectedJob.warnings}
                  renderItem={(w) => (
                    <List.Item style={{ padding: '3px 0' }}>
                      <Text type="warning" style={{ fontSize: 12 }}>{w}</Text>
                    </List.Item>
                  )}
                />
              </Descriptions.Item>
            )}
          </Descriptions>
        )}
      </Modal>
    </Space>
  );
}
