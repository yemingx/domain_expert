import { Suspense, lazy, useCallback, useEffect } from 'react';
import { Layout as AntLayout, Menu, Typography, Select, Space, Tag, Spin } from 'antd';
import {
  MessageOutlined,
  SearchOutlined,
  FieldTimeOutlined,
  UploadOutlined,
  FileTextOutlined,
  EditOutlined,
  ExperimentOutlined,
  ShareAltOutlined,
  BookOutlined,
  DatabaseOutlined,
} from '@ant-design/icons';
import {
  useActiveTab,
  useSelectedWikiKbId,
  useSetActiveTab,
  useSetSelectedWikiKbId,
  useSetWikiKbs,
  useSidebarCollapsed,
  useToggleSidebar,
  useWikiKbs,
} from '../stores/appStore';
import { listWikiKbs } from '../utils/api';

const ChatInterface = lazy(() => import('./ChatInterface'));
const KnowledgeExplorer = lazy(() => import('./KnowledgeExplorer'));
const TimelineView = lazy(() => import('./TimelineView'));
const PaperUpload = lazy(() => import('./PaperUpload'));
const ReviewDashboard = lazy(() => import('./ReviewDashboard'));
const WritingAssistant = lazy(() => import('./WritingAssistant'));
const LiteratureResearch = lazy(() => import('./LiteratureResearch'));
const HypergraphTimeline = lazy(() => import('./HypergraphTimeline'));
const WikiExplorer = lazy(() => import('./WikiExplorer'));

const { Sider, Content, Header } = AntLayout;
const { Title } = Typography;

const menuItems = [
  { key: 'research', icon: <ExperimentOutlined />, label: 'Research' },
  { key: 'chat', icon: <MessageOutlined />, label: 'Chat' },
  { key: 'knowledge', icon: <SearchOutlined />, label: 'Knowledge' },
  { key: 'wiki', icon: <BookOutlined />, label: 'Wiki' },
  { key: 'timeline', icon: <FieldTimeOutlined />, label: 'Timeline' },
  { key: 'hypergraph', icon: <ShareAltOutlined />, label: 'Hypergraph' },
  { key: 'upload', icon: <UploadOutlined />, label: 'Upload' },
  { key: 'review', icon: <FileTextOutlined />, label: 'Review' },
  { key: 'writing', icon: <EditOutlined />, label: 'Writing' },
];

const KB_REQUIRED_TABS = ['chat', 'knowledge', 'review', 'writing', 'upload'];

function ContentFallback() {
  return (
    <div style={{ display: 'flex', justifyContent: 'center', padding: '120px 0' }}>
      <Spin size="large" />
    </div>
  );
}

export default function Layout() {
  const activeTab = useActiveTab();
  const setActiveTab = useSetActiveTab();
  const sidebarCollapsed = useSidebarCollapsed();
  const toggleSidebar = useToggleSidebar();
  const wikiKbs = useWikiKbs();
  const setWikiKbs = useSetWikiKbs();
  const selectedWikiKbId = useSelectedWikiKbId();
  const setSelectedWikiKbId = useSetSelectedWikiKbId();

  const loadWikiKbs = useCallback(async () => {
    try {
      const kbs = await listWikiKbs();
      setWikiKbs(kbs);
      if (!selectedWikiKbId && kbs.length > 0) {
        setSelectedWikiKbId(kbs[0].id);
      }
    } catch {
      // ignore
    }
  }, [selectedWikiKbId, setSelectedWikiKbId, setWikiKbs]);

  useEffect(() => {
    loadWikiKbs();
  }, [loadWikiKbs]);

  const needsKb = KB_REQUIRED_TABS.includes(activeTab);

  const renderContent = () => {
    switch (activeTab) {
      case 'chat':
        return <ChatInterface />;
      case 'knowledge':
        return <KnowledgeExplorer />;
      case 'wiki':
        return <WikiExplorer onKbChange={loadWikiKbs} />;
      case 'timeline':
        return <TimelineView />;
      case 'research':
        return <LiteratureResearch />;
      case 'hypergraph':
        return <HypergraphTimeline />;
      case 'upload':
        return <PaperUpload />;
      case 'review':
        return <ReviewDashboard />;
      case 'writing':
        return <WritingAssistant />;
      default:
        return <ChatInterface />;
    }
  };

  return (
    <AntLayout style={{ minHeight: '100vh' }}>
      <Sider
        collapsible
        collapsed={sidebarCollapsed}
        onCollapse={toggleSidebar}
        theme="light"
        style={{ borderRight: '1px solid #f0f0f0' }}
      >
        <div style={{ padding: '16px', textAlign: 'center' }}>
          <Title level={sidebarCollapsed ? 5 : 4} style={{ margin: 0 }}>
            {sidebarCollapsed ? 'DE' : 'Domain Expert'}
          </Title>
        </div>
        <Menu
          mode="inline"
          selectedKeys={[activeTab]}
          items={menuItems}
          onClick={({ key }) => setActiveTab(key)}
        />
      </Sider>
      <AntLayout>
        <Header style={{ background: '#fff', padding: '0 24px', borderBottom: '1px solid #f0f0f0', display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
          <Title level={4} style={{ margin: 0 }}>
            {menuItems.find((item) => item.key === activeTab)?.label || 'Chat'}
          </Title>
          <Space>
            {needsKb && wikiKbs.length === 0 && (
              <Tag color="warning" icon={<DatabaseOutlined />}>
                No KB — create one in Wiki tab
              </Tag>
            )}
            {wikiKbs.length > 0 && (
              <Select
                placeholder="Select Knowledge Base"
                value={selectedWikiKbId}
                onChange={setSelectedWikiKbId}
                style={{ minWidth: 220 }}
                options={wikiKbs.map((kb) => ({
                  value: kb.id,
                  label: (
                    <Space>
                      <DatabaseOutlined />
                      <span>{kb.name}</span>
                    </Space>
                  ),
                }))}
              />
            )}
            {needsKb && !selectedWikiKbId && wikiKbs.length > 0 && (
              <Tag color="processing">Please select a KB</Tag>
            )}
          </Space>
        </Header>
        <Content style={{ padding: 24, overflow: 'auto' }}>
          <Suspense fallback={<ContentFallback />}>
            {renderContent()}
          </Suspense>
        </Content>
      </AntLayout>
    </AntLayout>
  );
}
