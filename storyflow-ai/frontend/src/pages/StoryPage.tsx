import React, { useState, useEffect, useRef, useCallback } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { Card, Steps, Progress, Button, Typography, Space, Spin, Alert, Result } from 'antd';
import { CheckCircleOutlined, ArrowLeftOutlined, ReloadOutlined } from '@ant-design/icons';
import { getStory, getTaskStatus, connectWebSocket } from '../api';
import type { StoryResponse, TaskProgressEvent, WorkflowStep } from '../types';
import { WORKFLOW_STEPS } from '../types';

const { Title, Text } = Typography;

const STEP_ICONS = ['📝', '👤', '🎬', '🖼️', '🎙️', '🎞️'];

/** Map current_step string to step index (0-5). */
function stepToIndex(step: string): number {
  const map: Record<WorkflowStep, number> = {
    init: 0, script: 0, character: 1, storyboard: 2,
    image: 3, voice: 4, video: 5, done: 6, error: -1,
  };
  return map[step as WorkflowStep] ?? 0;
}

const StoryPage: React.FC = () => {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const [story, setStory] = useState<StoryResponse | null>(null);
  const [progress, setProgress] = useState(0);
  const [currentStep, setCurrentStep] = useState('');
  const [message, setMessage] = useState('正在初始化...');
  const [errorMsg, setErrorMsg] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [isCompleted, setIsCompleted] = useState(false);
  const [isFailed, setIsFailed] = useState(false);
  const wsRef = useRef<WebSocket | null>(null);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const fetchStory = useCallback(async () => {
    if (!id) return;
    try {
      const data = await getStory(id);
      setStory(data);
      if (data.status === 'completed') {
        setIsCompleted(true);
        setProgress(100);
        setMessage('漫剧生成完成！');
        setLoading(false);
      } else if (data.status === 'failed') {
        setIsFailed(true);
        setMessage('生成失败');
        setLoading(false);
      }
    } catch {
      setErrorMsg('加载故事信息失败');
      setLoading(false);
    }
  }, [id]);

  useEffect(() => { fetchStory(); }, [fetchStory]);

  // Find task_id: we need to fetch from the story's related task
  const [taskId, setTaskId] = useState<string | null>(null);

  const fetchTaskStatus = useCallback(async () => {
    if (!taskId) return;
    try {
      const status = await getTaskStatus(taskId);
      setProgress(status.progress);
      setCurrentStep(status.current_step || '');
      setMessage(status.current_step || '');
      if (status.error_message) setErrorMsg(status.error_message);
      if (status.status === 'completed') {
        setIsCompleted(true);
        setProgress(100);
        setMessage('漫剧生成完成！');
        stopAll();
      } else if (status.status === 'failed') {
        setIsFailed(true);
        if (status.error_message) setErrorMsg(status.error_message);
        stopAll();
      }
    } catch { /* ignore polling errors */ }
  }, [taskId]);

  function stopAll() {
    if (pollRef.current) { clearInterval(pollRef.current); pollRef.current = null; }
    if (wsRef.current) { wsRef.current.close(); wsRef.current = null; }
  }

  // When story loads and isn't completed, find the task and connect
  useEffect(() => {
    if (!id || story?.status === 'completed' || story?.status === 'failed') return;

    setLoading(false);

    // Start generation if story is just created
    const initGeneration = async () => {
      try {
        const { startGeneration } = await import('../api');
        const result = await startGeneration(id);
        setTaskId(result.task_id);
      } catch {
        // Story may already be generating, try to find existing task
      }
    };

    if (story?.status === 'created') {
      initGeneration();
    } else if (story?.status === 'generating' || String(story?.status).includes('_done')) {
      // Need to get task_id - we'll poll the story status to find it
      // For now, connect WS with a fallback approach
    }
  }, [id, story?.status]);

  // Connect WebSocket and start polling when taskId is known
  useEffect(() => {
    if (!taskId || isCompleted || isFailed) return;

    const ws = connectWebSocket(taskId, (msg: TaskProgressEvent) => {
      setProgress(msg.progress);
      setCurrentStep(msg.current_step);
      setMessage(msg.message);
      if (msg.status === 'completed' || msg.status === 'done') {
        setIsCompleted(true);
        setProgress(100);
        setMessage('漫剧生成完成！');
        stopAll();
      } else if (msg.status === 'failed') {
        setIsFailed(true);
        setErrorMsg(msg.message);
        stopAll();
      }
    });
    wsRef.current = ws;

    pollRef.current = setInterval(fetchTaskStatus, 3000);

    return () => { stopAll(); };
  }, [taskId, isCompleted, isFailed, fetchTaskStatus]);

  const activeStep = stepToIndex(currentStep);

  if (loading) {
    return (
      <div style={{ display: 'flex', justifyContent: 'center', alignItems: 'center', minHeight: '60vh' }}>
        <Spin size="large" />
      </div>
    );
  }

  if (errorMsg && !story) {
    return (
      <div style={{ maxWidth: 700, margin: '80px auto', padding: '0 24px' }}>
        <Result status="error" title="加载失败" subTitle={errorMsg}
          extra={<Button type="primary" onClick={() => navigate('/')}>返回首页</Button>} />
      </div>
    );
  }

  return (
    <div style={{ maxWidth: 800, margin: '0 auto', padding: '40px 24px' }}>
      <Card style={{ borderRadius: 12 }} styles={{ body: { padding: '40px 48px' } }}>
        <Space style={{ marginBottom: 8, width: '100%', justifyContent: 'space-between' }}>
          <Button type="text" icon={<ArrowLeftOutlined />} onClick={() => navigate('/')}>
            返回首页
          </Button>
        </Space>

        <div style={{ textAlign: 'center', marginBottom: 36 }}>
          <Title level={3} style={{ marginBottom: 4 }}>
            {story?.title || '漫剧生成中'}
          </Title>
          <Text type="secondary">
            {isCompleted ? '漫剧生成完成！' : isFailed ? '生成失败' : message || '正在努力生成中...'}
          </Text>
        </div>

        {isFailed && errorMsg && (
          <Alert type="error" message="生成失败" description={errorMsg} showIcon
            style={{ marginBottom: 24 }}
            action={<Button size="small" icon={<ReloadOutlined />} onClick={() => window.location.reload()}>重试</Button>} />
        )}

        <Steps current={activeStep} direction="horizontal" size="small" style={{ marginBottom: 32 }}>
          {WORKFLOW_STEPS.map((step, index) => (
            <Steps.Step key={step.key} title={step.label}
              icon={<span style={{ fontSize: 18 }}>{STEP_ICONS[index]}</span>} />
          ))}
        </Steps>

        <div style={{ marginBottom: 32 }}>
          <Progress
            percent={Math.round(progress)}
            status={isFailed ? 'exception' : isCompleted ? 'success' : 'active'}
            strokeColor={isCompleted ? '#52c41a' : undefined}
          />
          <div style={{ textAlign: 'center', marginTop: 8 }}>
            <Text type="secondary">{Math.round(progress)}%</Text>
          </div>
        </div>

        {isCompleted && (
          <div style={{ textAlign: 'center' }}>
            <Button type="primary" size="large" icon={<CheckCircleOutlined />}
              onClick={() => navigate(`/story/${id}/result`)}
              style={{ minWidth: 180, height: 48, fontSize: 16 }}>
              查看结果
            </Button>
          </div>
        )}
      </Card>
    </div>
  );
};

export default StoryPage;