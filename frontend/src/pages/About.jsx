import React from 'react';
import { Card, Typography } from 'antd';
const { Title, Paragraph } = Typography;

export default function About() {
  return (
    <Card title="系统架构说明">
      <Title level={4}>技术栈</Title>
      <Paragraph>React + Ant Design + FastAPI + LangGraph + ChromaDB + DeepSeek</Paragraph>
      <Title level={4}>多智能体协作</Title>
      <Paragraph>本系统采用状态图（StateGraph）架构。审批与打款节点独立运行。当审批结果合规，状态机会自动流转至打款节点。</Paragraph>
    </Card>
  );
}