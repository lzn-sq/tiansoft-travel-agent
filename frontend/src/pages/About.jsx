import React from 'react';
import { Card, Divider, Tag, Typography } from 'antd';

const { Title, Paragraph, Text } = Typography;

export default function About() {
  return (
    <Card title="系统架构说明">
      <Title level={4}>技术栈</Title>
      <Paragraph>
        <Tag color="blue">React 19 + Ant Design</Tag>
        <Tag color="green">FastAPI</Tag>
        <Tag color="purple">LangGraph StateGraph</Tag>
        <Tag color="orange">ChromaDB</Tag>
        <Tag color="cyan">DeepSeek</Tag>
        <Tag color="gold">智谱 embedding-2</Tag>
      </Paragraph>

      <Divider />

      <Title level={4}>多智能体协作</Title>
      <Paragraph>
        对话由 LangGraph 状态图编排，依次经过
        <Text strong> 信息抽取 → 必填校验 → 审核 Agent → 确认/打款 </Text>
        四个阶段。必填项缺失时会走追问分支并直接结束；审核结果合规时只展示金额并提示确认，
        用户明确回复“确认打款”后才会进入打款节点，生成 <Text code>PAY-XXXXXX</Text> 打款单。
      </Paragraph>

      <Title level={4}>制度知识库（RAG）</Title>
      <Paragraph>
        差旅制度被切分为多个片段，使用智谱 <Text code>embedding-2</Text> 生成向量并存入 ChromaDB。
        审核 Agent 通过 <Text code>search_policy</Text> 工具按语义检索相关条款；
        当向量服务不可用时自动降级为关键词检索，保证流程不中断。
      </Paragraph>

      <Title level={4}>安全与稳定性</Title>
      <Paragraph>
        用户名密码登录（bcrypt 存储）+ JWT 鉴权；登录、对话接口均有限流；
        CORS 采用白名单；会话按用户隔离，历史消息自动裁剪后送入模型；
        SSE 以 JSON 帧传输，前端支持手动停止生成与 401 自动跳转登录。
      </Paragraph>
    </Card>
  );
}
