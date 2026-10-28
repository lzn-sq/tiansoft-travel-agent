import React, { useCallback, useEffect, useRef, useState } from 'react';
import { Avatar, Button, Dropdown, Layout, List, Menu, Popconfirm, Spin, Typography, message } from 'antd';
import {
  DeleteOutlined,
  InfoCircleOutlined,
  LogoutOutlined,
  MessageOutlined,
  PlusOutlined,
  RobotOutlined,
} from '@ant-design/icons';
import { Navigate, Outlet, useLocation, useNavigate } from 'react-router-dom';
import { apiJson, clearAuth, getToken, getUsername } from './api';

const { Header, Content, Sider } = Layout;
const { Text } = Typography;

export default function App() {
  const navigate = useNavigate();
  const location = useLocation();
  const token = getToken();
  const username = getUsername();

  const [sessions, setSessions] = useState([]);
  const [sessionId, setSessionId] = useState(null);
  const [booting, setBooting] = useState(true);
  const creatingRef = useRef(false);
  const bootstrappedRef = useRef(false);

  const refreshSessions = useCallback(async () => {
    try {
      const data = await apiJson('/api/sessions');
      setSessions(data.sessions || []);
      return data.sessions || [];
    } catch (error) {
      if (error.message !== 'UNAUTHORIZED') message.error(error.message);
      return [];
    }
  }, []);

  const createSession = useCallback(async () => {
    if (creatingRef.current) return null;
    creatingRef.current = true;
    try {
      const data = await apiJson('/api/session', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({}),
      });
      setSessionId(data.session_id);
      await refreshSessions();
      return data.session_id;
    } catch (error) {
      if (error.message !== 'UNAUTHORIZED') message.error(error.message);
      return null;
    } finally {
      creatingRef.current = false;
    }
  }, [refreshSessions]);

  useEffect(() => {
    if (!token) {
      setBooting(false);
      return;
    }
    if (bootstrappedRef.current) return;
    bootstrappedRef.current = true;
    (async () => {
      const list = await refreshSessions();
      if (list.length > 0) setSessionId(list[0].id);
      else await createSession();
      setBooting(false);
    })();
  }, [token, refreshSessions, createSession]);

  if (!token) return <Navigate to="/login" replace />;

  const handleNewChat = async () => {
    const id = await createSession();
    if (id) {
      setSessionId(id);
      navigate('/');
    }
  };

  const handleSelectSession = (id) => {
    setSessionId(id);
    navigate('/');
  };

  const handleDeleteSession = async (id) => {
    try {
      await apiJson(`/api/sessions/${id}`, { method: 'DELETE' });
      const list = await refreshSessions();
      if (id === sessionId) {
        if (list.length > 0) setSessionId(list[0].id);
        else await createSession();
      }
      message.success('会话已删除');
    } catch (error) {
      if (error.message !== 'UNAUTHORIZED') message.error(error.message);
    }
  };

  const handleLogout = () => {
    clearAuth();
    navigate('/login', { replace: true });
  };

  const navItems = [
    { key: '/', icon: <MessageOutlined />, label: '智能审查' },
    { key: '/about', icon: <InfoCircleOutlined />, label: '系统架构' },
  ];

  return (
    <Layout style={{ minHeight: '100vh' }}>
      <Sider width={260} style={{ display: 'flex', flexDirection: 'column' }}>
        <div
          style={{
            height: 32,
            margin: 16,
            background: 'rgba(255,255,255,0.2)',
            borderRadius: 6,
            color: 'white',
            textAlign: 'center',
            lineHeight: '32px',
            fontWeight: 'bold',
          }}
        >
          天软 Agent
        </div>

        <div style={{ padding: '0 16px 12px 16px' }}>
          <Button
            type="primary"
            icon={<PlusOutlined />}
            block
            onClick={handleNewChat}
            style={{ background: '#10a37f', border: 'none' }}
          >
            新建对话
          </Button>
        </div>

        <Menu
          theme="dark"
          selectedKeys={[location.pathname]}
          mode="inline"
          items={navItems}
          onClick={({ key }) => navigate(key)}
        />

        <div style={{ padding: '16px 16px 8px', color: 'rgba(255,255,255,0.45)', fontSize: 12 }}>
          历史会话
        </div>

        <div style={{ flex: 1, overflowY: 'auto', padding: '0 8px 16px' }}>
          {sessions.length === 0 ? (
            <Text style={{ color: 'rgba(255,255,255,0.35)', paddingLeft: 8, fontSize: 12 }}>
              暂无会话
            </Text>
          ) : (
            <List
              dataSource={sessions}
              split={false}
              renderItem={(item) => (
                <div
                  onClick={() => handleSelectSession(item.id)}
                  style={{
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'space-between',
                    gap: 6,
                    padding: '8px 10px',
                    marginBottom: 4,
                    borderRadius: 6,
                    cursor: 'pointer',
                    background: item.id === sessionId ? 'rgba(16,163,127,0.35)' : 'transparent',
                    color: 'rgba(255,255,255,0.85)',
                  }}
                >
                  <span
                    style={{
                      overflow: 'hidden',
                      textOverflow: 'ellipsis',
                      whiteSpace: 'nowrap',
                      fontSize: 13,
                    }}
                    title={item.title}
                  >
                    {item.title}
                  </span>
                  <Popconfirm
                    title="删除这个会话？"
                    okText="删除"
                    cancelText="取消"
                    onConfirm={(event) => {
                      event?.stopPropagation?.();
                      handleDeleteSession(item.id);
                    }}
                    onCancel={(event) => event?.stopPropagation?.()}
                  >
                    <Button
                      type="text"
                      size="small"
                      icon={<DeleteOutlined />}
                      style={{ color: 'rgba(255,255,255,0.65)' }}
                      onClick={(event) => event.stopPropagation()}
                    />
                  </Popconfirm>
                </div>
              )}
            />
          )}
        </div>
      </Sider>

      <Layout>
        <Header
          style={{
            background: '#fff',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            padding: '0 24px',
          }}
        >
          <span style={{ fontSize: 18, fontWeight: 'bold' }}>差旅合规多智能体协作系统</span>
          <Dropdown
            trigger={['click']}
            menu={{
              items: [{ key: 'logout', icon: <LogoutOutlined />, label: '退出登录' }],
              onClick: ({ key }) => key === 'logout' && handleLogout(),
            }}
          >
            <div style={{ cursor: 'pointer', display: 'flex', alignItems: 'center', gap: 8 }}>
              <Avatar size={28} icon={<RobotOutlined />} style={{ background: '#10a37f' }} />
              <span>{username || '用户'}</span>
            </div>
          </Dropdown>
        </Header>

        <Content style={{ margin: '16px' }}>
          <div style={{ padding: 24, minHeight: 360, background: '#fff', borderRadius: 8 }}>
            {booting ? (
              <div style={{ display: 'flex', justifyContent: 'center', padding: 80 }}>
                <Spin size="large" />
              </div>
            ) : (
              <Outlet context={{ sessionId, refreshSessions }} />
            )}
          </div>
        </Content>
      </Layout>
    </Layout>
  );
}
