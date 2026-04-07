import { useState } from 'react';
import { Layout as AntLayout, Menu, Typography, Badge } from 'antd';
import {
  MessageOutlined,
  SearchOutlined,
  FieldTimeOutlined,
  UploadOutlined,
  FileTextOutlined,
  EditOutlined,
  ExperimentOutlined,
  ShareAltOutlined,
} from '@ant-design/icons';
import { useAppStore } from '../stores/appStore';
import ChatInterface from './ChatInterface';
import KnowledgeExplorer from './KnowledgeExplorer';
import TimelineView from './TimelineView';
import PaperUpload from './PaperUpload';
import ReviewDashboard from './ReviewDashboard';
import WritingAssistant from './WritingAssistant';
import LiteratureResearch from './LiteratureResearch';
import HypergraphTimeline from './HypergraphTimeline';

const { Sider, Content, Header } = AntLayout;
const { Title } = Typography;

const menuItems = [
  { key: 'research', icon: <ExperimentOutlined />, label: 'Research' },
  { key: 'chat', icon: <MessageOutlined />, label: 'Chat' },
  { key: 'knowledge', icon: <SearchOutlined />, label: 'Knowledge' },
  { key: 'timeline', icon: <FieldTimeOutlined />, label: 'Timeline' },
  { key: 'hypergraph', icon: <ShareAltOutlined />, label: 'Hypergraph' },
  { key: 'upload', icon: <UploadOutlined />, label: 'Upload' },
  { key: 'review', icon: <FileTextOutlined />, label: 'Review' },
  { key: 'writing', icon: <EditOutlined />, label: 'Writing' },
];

export default function Layout() {
  const { activeTab, setActiveTab, sidebarCollapsed, toggleSidebar } = useAppStore();

  const renderContent = () => {
    switch (activeTab) {
      case 'chat': return <ChatInterface />;
      case 'knowledge': return <KnowledgeExplorer />;
      case 'timeline': return <TimelineView />;
      case 'research': return <LiteratureResearch />;
      case 'hypergraph': return <HypergraphTimeline />;
      case 'upload': return <PaperUpload />;
      case 'review': return <ReviewDashboard />;
      case 'writing': return <WritingAssistant />;
      default: return <ChatInterface />;
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
        <Header style={{ background: '#fff', padding: '0 24px', borderBottom: '1px solid #f0f0f0', display: 'flex', alignItems: 'center' }}>
          <Title level={4} style={{ margin: 0 }}>
            {menuItems.find(i => i.key === activeTab)?.label || 'Chat'}
          </Title>
        </Header>
        <Content style={{ padding: 24, overflow: 'auto' }}>
          {renderContent()}
        </Content>
      </AntLayout>
    </AntLayout>
  );
}
