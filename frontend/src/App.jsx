import React from 'react';
import { Layout, Menu } from 'antd';
import { MessageOutlined, InfoCircleOutlined } from '@ant-design/icons';
import { Outlet, useNavigate, useLocation } from 'react-router-dom';

const { Header, Content, Sider } = Layout;

export default function App() {
  const navigate = useNavigate();
  const location = useLocation();

  const items = [
    { key: '/', icon: <MessageOutlined />, label: '智能审查' },
    { key: '/about', icon: <InfoCircleOutlined />, label: '系统架构' },
  ];

  return (
    <Layout style={{ minHeight: '100vh' }}>
      <Sider collapsible>
        <div style={{ height: 32, margin: 16, background: 'rgba(255,255,255,0.2)', borderRadius: 6, color:'white', textAlign:'center', lineHeight:'32px', fontWeight:'bold' }}>
          天软 Agent
        </div>
        <Menu theme="dark" selectedKeys={[location.pathname]} mode="inline" items={items} onClick={({ key }) => navigate(key)} />
      </Sider>
      <Layout>
        <Header style={{ background: '#fff', textAlign: 'center', fontSize: '18px', fontWeight: 'bold' }}>
          差旅合规多智能体协作系统
        </Header>
        <Content style={{ margin: '16px' }}>
          <div style={{ padding: 24, minHeight: 360, background: '#fff', borderRadius: 8 }}>
            <Outlet />
          </div>
        </Content>
      </Layout>
    </Layout>
  );
}