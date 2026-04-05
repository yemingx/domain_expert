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
  Checkbox,
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
  FileTextOutlined,
} from '@ant-design/icons';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import {
  runResearch,
  listResearchJobs,
  getResearchJob,
  importResearchToKB,
  deleteResearchJob,
  getResearchDownloadUrl,
  convertResearchReport,
} from '../utils/api';
import type { ResearchJob } from '../types';

const { Text, Paragraph } = Typography;
const { TextArea } = Input;

const ALL_FORMATS = ['word', 'html', 'html_ppt', 'pdf_ppt'];
const FORMAT_LABELS: Record<string, string> = {
  word: 'Word (.docx)',
  html: 'HTML 阅读版',
  html_ppt: 'HTML PPT',
  pdf_ppt: 'PDF PPT',
};

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
  const [convertFormats, setConvertFormats] = useState<string[]>(ALL_FORMATS);
  const [convertingJobId, setConvertingJobId] = useState<string | null>(null);

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

  const handleSubmit = (values: FormValues) => {
    runMutation.mutate(values);
  };

  const handleImport = (jobId: string) => {
    importMutation.mutate(jobId);
  };

  const handleConvert = async (jobId: string) => {
    if (convertFormats.length === 0) {
      message.warning('请至少选择一种格式');
      return;
    }
    setConvertingJobId(jobId);
    try {
      const blob = await convertResearchReport(jobId, convertFormats);
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `report_${jobId.slice(0, 8)}.zip`;
      a.click();
      URL.revokeObjectURL(url);
      message.success('报告已生成并下载');
      queryClient.invalidateQueries({ queryKey: ['research-jobs'] });
      queryClient.invalidateQueries({ queryKey: ['research-job', jobId] });
    } catch (err: any) {
      message.error(`生成失败: ${err.response?.data?.detail || err.message}`);
    } finally {
      setConvertingJobId(null);
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
      width: 420,
      render: (_: any, record: ResearchJob) => (
        <Space wrap>
          <Button size="small" onClick={() => showJobDetail(record)}>Details</Button>
          {record.status === 'completed' && (
            <Button size="small" type="primary" icon={<ImportOutlined />}
              onClick={() => handleImport(record.job_id)}
              loading={importMutation.isPending}>
              Import
            </Button>
          )}
          {record.status === 'completed' && record.result_path && (
            <Button size="small" icon={<FileTextOutlined />}
              loading={convertingJobId === record.job_id}
              onClick={() => handleConvert(record.job_id)}>
              生成报告
            </Button>
          )}
          {record.status === 'completed' && (
            <Button size="small" icon={<DownloadOutlined />}
              onClick={() => window.open(getResearchDownloadUrl(record.job_id))}>
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
            </Space>
          </Card>
        )}
      </Card>

      {/* Report Format Selection */}
      <Card title="报告格式选择" size="small">
        <Space direction="vertical">
          <Text type="secondary">
            点击"生成报告"时生成以下格式（需要 job 已完成且含深度分析的 Markdown）：
          </Text>
          <Checkbox.Group
            options={ALL_FORMATS.map(f => ({ label: FORMAT_LABELS[f], value: f }))}
            value={convertFormats}
            onChange={(vals) => setConvertFormats(vals as string[])}
          />
        </Space>
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
          selectedJob?.status === 'completed' && selectedJob?.result_path ? (
            <Button key="convert" icon={<FileTextOutlined />}
              loading={convertingJobId === selectedJob?.job_id}
              onClick={() => selectedJob && handleConvert(selectedJob.job_id)}>
              生成报告 (zip)
            </Button>
          ) : null,
          selectedJob?.status === 'completed' ? (
            <Button key="download" icon={<DownloadOutlined />}
              onClick={() => selectedJob && window.open(getResearchDownloadUrl(selectedJob.job_id))}>
              Download CSV+JSON
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
              <Descriptions.Item label="Error">
                <Text type="danger">{selectedJob.error_message}</Text>
              </Descriptions.Item>
            )}
          </Descriptions>
        )}
      </Modal>
    </Space>
  );
}
