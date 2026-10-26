import React, { useState, useRef, useEffect } from 'react';
import { Input, Button, Avatar, message, Spin } from 'antd';
import { UserOutlined, RobotOutlined, SendOutlined } from '@ant-design/icons';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';

export default function Chat() {
  const [inputText, setInputText] = useState('');
  const [messages, setMessages] = useState([{ role: 'assistant', content: '您好，我是企业级多智能体系统。' }]);
  const [loading, setLoading] = useState(false);
  const [sessionId, setSessionId] = useState('');
  const bottomRef = useRef(null);

  // 初始化时从后端获取 Session ID
  useEffect(() => {
    const initSession = async () => {
      try {
        const res = await fetch('http://127.0.0.1:8000/api/session');
        const data = await res.json();
        setSessionId(data.session_id);
      } catch (e) {
        message.error("无法连接后端创建会话");
      }
    };
    initSession();
  }, []);

  useEffect(() => { bottomRef.current?.scrollIntoView({ behavior: 'smooth' }); }, [messages, loading]);

  const sendMessage = async () => {
    const text = inputText.trim();
    if (!text || loading || !sessionId) return;

    setInputText('');
    setLoading(true);
    
    const aiMsgIndex = messages.length + 1;
    setMessages(prev => [...prev, { role: 'user', content: text }, { role: 'assistant', content: '' }]);

    try {
      // 核心变化：只传 session_id 和当前 text
      const response = await fetch('http://127.0.0.1:8000/api/chat/stream', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ session_id: sessionId, text: text })
      });

      const reader = response.body.getReader();
      const decoder = new TextDecoder('utf-8');
      let fullReply = '';
      let sseBuffer = '';

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        sseBuffer += decoder.decode(value, { stream: true });
        const parts = sseBuffer.split('\n\n');
        sseBuffer = parts.pop();

        for (const part of parts) {
          if (part.startsWith('data: ')) {
            fullReply += part.replace('data: ', '');
            setMessages(prev => {
              const updated = [...prev];
              if (updated[aiMsgIndex]) {
                updated[aiMsgIndex] = { role: 'assistant', content: fullReply };
              }
              return updated;
            });
          }
        }
      }
    } catch (e) {
      message.error("网络异常");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '75vh' }}>
      <div style={{ flex: 1, overflowY: 'auto', padding: '10px 20px', background: '#f9f9f9', borderRadius: 8 }}>
        {messages.map((msg, index) => (
          <div key={index} style={{ display: 'flex', justifyContent: msg.role === 'user' ? 'flex-end' : 'flex-start', marginBottom: 20, alignItems: 'flex-start' }}>
            {msg.role === 'assistant' && <Avatar size={40} icon={<RobotOutlined />} style={{ background: '#52c41a', flexShrink: 0, marginRight: 10 }} />}
            <div style={{ maxWidth: '80%', padding: '12px 18px', borderRadius: 8, background: msg.role === 'user' ? '#1890ff' : '#fff', color: msg.role === 'user' ? '#fff' : '#333', border: msg.role === 'user' ? 'none' : '1px solid #eee', wordBreak: 'break-word', lineHeight: '1.6' }}>
              {msg.role === 'assistant' && msg.content === '' ? (
                <div style={{ display: 'flex', alignItems: 'center', gap: '8px', color: '#888' }}>
                  <Spin size="small" /> 正在规划任务...
                </div>
              ) : (
                <ReactMarkdown remarkPlugins={[remarkGfm]}>{msg.content}</ReactMarkdown>
              )}
            </div>
            {msg.role === 'user' && <Avatar size={40} icon={<UserOutlined />} style={{ background: '#1890ff', flexShrink: 0, marginLeft: 10 }} />}
          </div>
        ))}
        <div ref={bottomRef} />
      </div>
      
      <div style={{ display: 'flex', gap: 10, marginTop: 15 }}>
        <Input size="large" value={inputText} onChange={e => setInputText(e.target.value)} onPressEnter={sendMessage} disabled={loading} placeholder="输入..." />
        <Button type="primary" size="large" icon={<SendOutlined />} onClick={sendMessage} loading={loading}>发送</Button>
      </div>
    </div>
  );
}