import React, { useEffect, useState } from 'react';
import { Button, Card, Form, Input, Tabs, Typography, message } from 'antd';
import { LockOutlined, UserOutlined } from '@ant-design/icons';
import { useNavigate } from 'react-router-dom';
import { API_BASE, getToken, setAuth } from '../api';

const { Title, Text } = Typography;

export default function Login() {
  const navigate = useNavigate();
  const [loading, setLoading] = useState(false);
  const [tab, setTab] = useState('login');

  useEffect(() => {
    if (getToken()) navigate('/', { replace: true });
  }, [navigate]);

  const handleSubmit = async (values) => {
    const isRegister = tab === 'register';
    if (isRegister && values.confirm !== values.password) {
      message.error('两次输入的密码不一致');
      return;
    }

    setLoading(true);
    try {
      const response = await fetch(`${API_BASE}/api/auth/${isRegister ? 'register' : 'login'}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ username: values.username.trim(), password: values.password }),
      });
      const data = await response.json().catch(() => ({}));
      if (!response.ok) {
        throw new Error(data.detail || '登录失败');
      }
      setAuth(data.access_token, data.username);
      message.success(isRegister ? '注册成功，已自动登录' : '登录成功');
      navigate('/', { replace: true });
    } catch (error) {
      message.error(error.message || '无法连接后端，请检查服务是否启动');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div
      style={{
        minHeight: '100vh',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        background: 'linear-gradient(135deg, #0f2027 0%, #203a43 50%, #2c5364 100%)',
      }}
    >
      <Card style={{ width: 400, borderRadius: 12, boxShadow: '0 12px 40px rgba(0,0,0,0.3)' }}>
        <div style={{ textAlign: 'center', marginBottom: 16 }}>
          <Title level={3} style={{ marginBottom: 4 }}>
            天软差旅合规审核
          </Title>
          <Text type="secondary">请先登录后使用智能审查</Text>
        </div>

        <Tabs
          activeKey={tab}
          onChange={(key) => setTab(key)}
          centered
          items={[
            { key: 'login', label: '登录' },
            { key: 'register', label: '注册' },
          ]}
        />

        <Form layout="vertical" onFinish={handleSubmit} requiredMark={false} key={tab}>
          <Form.Item
            name="username"
            label="用户名"
            rules={[{ required: true, message: '请输入用户名' }, { min: 3, message: '至少 3 个字符' }]}
          >
            <Input size="large" prefix={<UserOutlined />} placeholder="请输入用户名" autoComplete="username" />
          </Form.Item>
          <Form.Item
            name="password"
            label="密码"
            rules={[{ required: true, message: '请输入密码' }, { min: 6, message: '至少 6 个字符' }]}
          >
            <Input.Password
              size="large"
              prefix={<LockOutlined />}
              placeholder="请输入密码"
              autoComplete={tab === 'login' ? 'current-password' : 'new-password'}
            />
          </Form.Item>
          {tab === 'register' && (
            <Form.Item
              name="confirm"
              label="确认密码"
              rules={[{ required: true, message: '请再次输入密码' }]}
            >
              <Input.Password size="large" prefix={<LockOutlined />} placeholder="请再次输入密码" />
            </Form.Item>
          )}
          <Button type="primary" htmlType="submit" size="large" block loading={loading}>
            {tab === 'login' ? '登录' : '注册并登录'}
          </Button>
        </Form>
      </Card>
    </div>
  );
}
