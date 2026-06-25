import React, { useState, useEffect, useRef, useCallback } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { Card, Steps, Progress, Button, Typography, Space, Spin, Alert, Result } from 'antd';
import { CheckCircleOutlined, ArrowLeftOutlined, ReloadOutlined } from '@ant-design/icons';
import { getStory, getTaskStatus, connectWebSocket, Story, TaskStatus, WebSocketMessage } from '../api';

const { Title, Text } = Typography;

const STEP_TITLES = [
  '剧本生成',
  '角色设计',
  '分镜生成',
  '图片生成',
  '配音生成',
  '视频合成',
];

const STEP_ICONS = [
  '📝',
  '👤',
  '🎬',
  '🖼️',
  '🎙️',
  '🎞️',
];

const StoryPage: React.FC = () => {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const [story, setStory] = useState<Story | null>(null);
  const [taskStatus, setTaskStatus] = useState<TaskStatus | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [wsConnected, setWsConnected] = useState(false);
  const wsRef = useRef<WebSocket | null>(null);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const fetchStory = useCallback(async () => {
    if (!id) return;
    try {
      const data = await getStory(id);
      setStory(data);
      if (data.status === 'completed') {
        setLoading(false);
        setTaskStatus({
          task_id: data.task_id || '',
          status: 'completed',
          current_step: 6,
          total_steps: 6,
          progress: 100,
          message: '生成完成',
          result: null,
          error: null,
        });
      }
    } catch {
      setError('加载故事信息失败');
      setLoading(false);
    }
  }, [id]);

  const fetchTaskStatus = useCallback(async () => {
    if (!story?.task_id) return;
    try {
      const status = await getTaskStatus(story.task_id);
      setTaskStatus(status);
      if (status.status === 'completed' || status.status === 'failed') {
        if (pollRef.current) {
          clearInterval(pollRef.current);
          pollRef.current = null;
        }
        if (wsRef.current) {
          wsRef.current.close();
          wsRef.current = null;
        }
      }
    } catch {
      // Silently ignore polling errors
    }
  }, [story?.task_id]);

  useEffect(() => {
    fetchStory();
  }, [fetchStory]);

  useEffect(() => {
    if (!story?.task_id) return;
    if (story.status === 'completed') return;

    setLoading(false);

    // Start WebSocket connection
    const ws = connectWebSocket(story.task_id, (msg: WebSocketMessage) => {
      setWsConnected(true);
      if (msg.type === 'progress') {
        setTaskStatus((prev) => ({
          task_id: msg.task_id,
          status: msg.status as TaskStatus['status'] || 'running',
          current_step: msg.current_step ?? prev?.current_step ?? 0,
          total_steps: msg.total_steps ?? prev?.total_steps ?? 6,
          progress: msg.progress ?? prev?.progress ?? 0,
          message: msg.message ?? '',
          result: msg.result ?? null,
          error: msg.error ?? null,
        }));
      } else if (msg.type === 'complete') {
        setTaskStatus({
          task_id: msg.task_id,
          status: 'completed',
          current_step: 6,
          total_steps: 6,
          progress: 100,
          message: '生成完成！',
          result: msg.result ?? null,
          error: null,
        });
        ws.close();
        if (pollRef.current) {
          clearInterval(pollRef.current);
          pollRef.current = null;
        }
      } else if (msg.type === 'error') {
        setTaskStatus((prev) => ({
          ...prev!,
          status: 'failed',
          error: msg.error || '未知错误',
        }));
        ws.close();
        if (pollRef.current) {
          clearInterval(pollRef.current);
          pollRef.current = null;
        }
      }
    });

    wsRef.current = ws;

    // Fallback polling every 3 seconds
    pollRef.current = setInterval(fetchTaskStatus, 3000);

    return () => {
      ws.close();
      if (pollRef.current) {
        clearInterval(pollRef.current);
        pollRef.current = null;
      }
    };
  }, [story?.task_id, story?.status, fetchTaskStatus]);

  const currentStep = taskStatus ? Math.min(taskStatus.current_step, 5) : 0;
  const progressPercent = taskStatus?.progress ?? 0;
  const isCompleted = taskStatus?.status === 'completed';
  const isFailed = taskStatus?.status === 'failed';

  if (loading) {
    return (
      <div style={{ display: 'flex', justifyContent: 'center', alignItems: 'center', minHeight: '60vh' }}>
        <Spin size="large" tip="加载中..." />
      </div>
    );
  }

  if (error) {
    return (
      <div style={{ maxWidth: 700, margin: '80px auto', padding: '0 24px' }}>
        <Result
          status="error"
          title="加载失败"
          subTitle={error}
          extra={
            <Button type="primary" onClick={() => navigate('/')}>
              返回首页
            </Button>
          }
        />
      </div>
    );
  }

  return (
    <div style={{ maxWidth: 800, margin: '0 auto', padding: '40px 24px' }}>
      <Card style={{ borderRadius: 12 }} bodyStyle={{ padding: '40px 48px' }}>
        <Space style={{ marginBottom: 8, width: '100%', justifyContent: 'space-between' }}>
          <Button
            type="text"
            icon={<ArrowLeftOutlined />}
            onClick={() => navigate('/')}
          >
            返回首页
          </Button>
          {!wsConnected && !isCompleted && !isFailed && (
            <Text type="secondary" style={{ fontSize: 12 }}>WebSocket 未连接，使用轮询模式</Text>
          )}
        </Space>

        <div style={{ textAlign: 'center', marginBottom: 36 }}>
          <Title level={3} style={{ marginBottom: 4 }}>
            {story?.title || '漫剧生成中'}
          </Title>
          <Text type="secondary">
            {isCompleted
              ? '🎉 漫剧生成完成！'
              : isFailed
                ? '❌ 生成失败'
                : taskStatus?.message || '正在努力生成中...'}
          </Text>
        </div>

        {isFailed && taskStatus?.error && (
          <Alert
            type="error"
            message="生成失败"
            description={taskStatus.error}
            showIcon
            style={{ marginBottom: 24 }}
            action={
              <Button
                size="small"
                icon={<ReloadOutlined />}
                onClick={() => window.location.reload()}
              >
                重试
              </Button>
            }
          />
        )}

        <Steps
          current={currentStep}
          direction="horizontal"
          size="small"
          style={{ marginBottom: 32 }}
        >
          {STEP_TITLES.map((title, index) => (
            <Steps.Step
              key={title}
              title={title}
              icon={<span style={{ fontSize: 18 }}>{STEP_ICONS[index]}</span>}
            />
          ))}
        </Steps>

        <div style={{ marginBottom: 32 }}>
          <Progress
            percent={Math.round(progressPercent)}
            status={isFailed ? 'exception' : isCompleted ? 'success' : 'active'}
            strokeColor={isCompleted ? '#52c41a' : undefined}
            size="default"
          />
          <div style={{ textAlign: 'center', marginTop: 8 }}>
            <Text type="secondary" style={{ fontSize: 14 }}>
              {isCompleted
                ? '100%'
                : `${Math.round(progressPercent)}%`}
            </Text>
          </div>
        </div>

        {isCompleted && (
          <div style={{ textAlign: 'center' }}>
            <Button
              type="primary"
              size="large"
              icon={<CheckCircleOutlined />}
              onClick={() => navigate(`/story/${id}/result`)}
              style={{ minWidth: 180, height: 48, fontSize: 16 }}
            >
              查看结果
            </Button>
          </div>
        )}
      </Card>
    </div>
  );
};

export default StoryPage;