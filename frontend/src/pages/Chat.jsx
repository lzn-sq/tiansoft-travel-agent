import React, { useEffect, useRef, useState } from 'react';
import { Avatar, Button, Input, Spin, message } from 'antd';
import { RobotOutlined, SendOutlined, StopOutlined, UserOutlined } from '@ant-design/icons';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { useOutletContext } from 'react-router-dom';
import { apiFetch, apiJson } from '../api';

const GREETING = {
  id: 'init',
  role: 'assistant',
  content: '您好，我是企业级财务审核 AI。请把您的流水账发给我。',
};

export default function Chat() {
  const { sessionId, refreshSessions } = useOutletContext();

  const [inputText, setInputText] = useState('');
  const [messages, setMessages] = useState([GREETING]);
  const [loading, setLoading] = useState(false);
  const [historyLoading, setHistoryLoading] = useState(false);

  const bottomRef = useRef(null);
  const fullReplyRef = useRef('');
  const abortRef = useRef(null);
  const mountedRef = useRef(true);

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
      abortRef.current?.abort();
    };
  }, []);

  // 切换会话时中止进行中的请求并加载历史消息
  useEffect(() => {
    let cancelled = false;
    abortRef.current?.abort();
    setLoading(false);

    if (!sessionId) {
      setMessages([GREETING]);
      return undefined;
    }

    setHistoryLoading(true);
    apiJson(`/api/sessions/${sessionId}/messages`)
      .then((data) => {
        if (cancelled) return;
        const items = (data.messages || []).map((item) => ({
          id: item.id,
          role: item.role,
          content: item.content,
        }));
        setMessages(items.length > 0 ? items : [GREETING]);
      })
      .catch((error) => {
        if (!cancelled && error.message !== 'UNAUTHORIZED') message.error(error.message);
      })
      .finally(() => {
        if (!cancelled) setHistoryLoading(false);
      });

    return () => {
      cancelled = true;
    };
  }, [sessionId]);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages, loading]);

  const stopStreaming = () => {
    abortRef.current?.abort();
  };

  const sendMessage = async () => {
    if (loading || !sessionId) return;

    const text = inputText.trim();
    if (!text) return;

    const controller = new AbortController();
    abortRef.current = controller;

    setInputText('');
    setLoading(true);
    fullReplyRef.current = '';

    const userMsgId = `${Date.now()}-user`;
    const aiMsgId = `${Date.now()}-ai`;

    setMessages((prev) => [
      ...prev,
      { id: userMsgId, role: 'user', content: text },
      { id: aiMsgId, role: 'assistant', content: '' },
    ]);

    let stopped = false;

    try {
      const response = await apiFetch('/api/chat/stream', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ session_id: sessionId, text }),
        signal: controller.signal,
      });

      if (!response.ok) {
        const data = await response.json().catch(() => ({}));
        throw new Error(data.detail || `请求失败（${response.status}）`);
      }

      const reader = response.body.getReader();
      const decoder = new TextDecoder('utf-8');
      let sseBuffer = '';

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        sseBuffer += decoder.decode(value, { stream: true });
        const parts = sseBuffer.split('\n\n');
        sseBuffer = parts.pop();

        for (const part of parts) {
          if (!part.startsWith('data: ')) continue;
          let chunkText = '';
          try {
            chunkText = JSON.parse(part.substring(6)).text ?? '';
          } catch {
            continue;
          }
          if (!chunkText) continue;

          fullReplyRef.current += chunkText;
          // 用闭包中的 aiMsgId 定位消息，避免流结束时 ref 被清空导致丢字
          setMessages((prev) =>
            prev.map((item) =>
              item.id === aiMsgId ? { ...item, content: fullReplyRef.current } : item
            )
          );
        }
      }
    } catch (error) {
      if (error.name === 'AbortError') {
        stopped = true;
      } else if (error.message !== 'UNAUTHORIZED') {
        message.error(error.message || '网络异常，请确保后端服务已启动');
        setMessages((prev) =>
          prev.map((item) =>
            item.id === aiMsgId
              ? { ...item, content: item.content || '⚠️ 请求失败，请检查后端服务。' }
              : item
          )
        );
      }
    } finally {
      if (mountedRef.current) {
        if (stopped) {
          const partial = fullReplyRef.current;
          setMessages((prev) =>
            prev.map((item) =>
              item.id === aiMsgId
                ? { ...item, content: `${partial}${partial ? '\n\n' : ''}⏹️ 已停止生成。` }
                : item
            )
          );
        }
        setLoading(false);
      }
      abortRef.current = null;
      fullReplyRef.current = '';
      refreshSessions?.();
    }
  };

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '75vh' }}>
      <div
        style={{
          flex: 1,
          overflowY: 'auto',
          padding: '10px 20px',
          background: '#f9f9f9',
          borderRadius: 8,
        }}
      >
        {historyLoading ? (
          <div style={{ display: 'flex', justifyContent: 'center', padding: 60 }}>
            <Spin />
          </div>
        ) : (
          messages.map((msg) => (
            <div
              key={msg.id}
              style={{
                display: 'flex',
                justifyContent: msg.role === 'user' ? 'flex-end' : 'flex-start',
                marginBottom: 20,
                alignItems: 'flex-start',
              }}
            >
              {msg.role === 'assistant' && (
                <Avatar
                  size={40}
                  icon={<RobotOutlined />}
                  style={{ background: '#52c41a', flexShrink: 0, marginRight: 10 }}
                />
              )}

              <div
                style={{
                  maxWidth: '80%',
                  padding: '12px 18px',
                  borderRadius: 8,
                  background: msg.role === 'user' ? '#1890ff' : '#fff',
                  color: msg.role === 'user' ? '#fff' : '#333',
                  border: msg.role === 'user' ? 'none' : '1px solid #eee',
                  lineHeight: 1.6,
                  boxShadow: '0 1px 2px rgba(0,0,0,0.05)',
                  wordBreak: 'break-word',
                }}
              >
                {msg.role === 'assistant' && msg.content === '' ? (
                  <div style={{ display: 'flex', alignItems: 'center', gap: 8, color: '#888' }}>
                    <Spin size="small" /> 正在查询与计算...
                  </div>
                ) : msg.role === 'assistant' ? (
                  <div className="markdown-body">
                    <ReactMarkdown remarkPlugins={[remarkGfm]}>{msg.content}</ReactMarkdown>
                  </div>
                ) : (
                  msg.content
                )}
              </div>

              {msg.role === 'user' && (
                <Avatar
                  size={40}
                  icon={<UserOutlined />}
                  style={{ background: '#1890ff', flexShrink: 0, marginLeft: 10 }}
                />
              )}
            </div>
          ))
        )}
        <div ref={bottomRef} />
      </div>

      <div style={{ display: 'flex', gap: 10, marginTop: 15 }}>
        <Input
          size="large"
          value={inputText}
          onChange={(event) => setInputText(event.target.value)}
          onPressEnter={() => sendMessage()}
          disabled={loading || historyLoading || !sessionId}
          placeholder="例如：我于本月29日乘坐C2202一等座到北京开会，住宿两晚630元，打车75元，我是普通员工，帮我算算。"
        />
        {loading ? (
          <Button type="primary" danger size="large" icon={<StopOutlined />} onClick={stopStreaming}>
            停止
          </Button>
        ) : (
          <Button
            type="primary"
            size="large"
            icon={<SendOutlined />}
            onClick={sendMessage}
            disabled={historyLoading || !sessionId}
          >
            发送
          </Button>
        )}
      </div>
    </div>
  );
}
