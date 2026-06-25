import React, { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  Card,
  Form,
  Input,
  Select,
  Button,
  Row,
  Col,
  Tag,
  Space,
  Typography,
  Spin,
  message,
  List,
} from 'antd';
import {
  ThunderboltOutlined,
  HistoryOutlined,
  ClockCircleOutlined,
} from '@ant-design/icons';
import { createStory, listStories, startGeneration } from '../api';
import type { StoryResponse, StoryStatus } from '../types';

const { Title, Text } = Typography;
const { TextArea } = Input;

const GENRE_OPTIONS = [
  { label: '校园', value: '校园' },
  { label: '都市', value: '都市' },
  { label: '玄幻', value: '玄幻' },
  { label: '逆袭', value: '逆袭' },
  { label: '古风', value: '古风' },
  { label: '穿越', value: '穿越' },
];

const STATUS_COLORS: Record<StoryStatus, string> = {
  created: 'default',
  generating: 'processing',
  script_done: 'cyan',
  character_done: 'cyan',
  storyboard_done: 'cyan',
  image_done: 'cyan',
  voice_done: 'cyan',
  completed: 'success',
  failed: 'error',
};

const STATUS_LABELS: Record<StoryStatus, string> = {
  created: '已创建',
  generating: '生成中',
  script_done: '剧本完成',
  character_done: '角色完成',
  storyboard_done: '分镜完成',
  image_done: '图片完成',
  voice_done: '配音完成',
  completed: '已完成',
  failed: '失败',
};

const formatTime = (dateStr: string): string => {
  const date = new Date(dateStr);
  return date.toLocaleString('zh-CN', {
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  });
};

const HomePage: React.FC = () => {
  const navigate = useNavigate();
  const [form] = Form.useForm();
  const [loading, setLoading] = useState(false);
  const [storiesLoading, setStoriesLoading] = useState(false);
  const [stories, setStories] = useState<StoryResponse[]>([]);

  const loadStories = async () => {
    setStoriesLoading(true);
    try {
      const data = await listStories();
      setStories(data);
    } catch {
      message.error('加载历史记录失败');
    } finally {
      setStoriesLoading(false);
    }
  };

  useEffect(() => {
    loadStories();
  }, []);

  const handleSubmit = async (values: { title: string; prompt: string; genre: string }) => {
    setLoading(true);
    try {
      const story = await createStory({
        title: values.title,
        prompt: values.prompt,
        genre: values.genre,
      });
      const { task_id } = await startGeneration(story.id);
      message.success('漫剧生成已启动！');
      navigate(`/story/${story.id}`);
    } catch {
      message.error('创建失败，请稍后重试');
    } finally {
      setLoading(false);
    }
  };

  const handleStoryClick = (story: StoryResponse) => {
    if (story.status === 'completed') {
      navigate(`/story/${story.id}/result`);
    } else if (story.status === 'generating' || story.status.includes('_done')) {
      navigate(`/story/${story.id}`);
    } else {
      message.info('该故事尚未开始生成');
    }
  };

  return (
    <div style={{ maxWidth: 900, margin: '0 auto', padding: '40px 24px' }}>
      <div style={{ textAlign: 'center', marginBottom: 40 }}>
        <Title level={2} style={{ marginBottom: 8 }}>
          🎬 StoryFlow AI
        </Title>
        <Text type="secondary" style={{ fontSize: 16 }}>
          AI漫剧生成平台 — 输入创意，一键生成精彩漫剧
        </Text>
      </div>

      <Card
        style={{ marginBottom: 40, borderRadius: 12 }}
        bodyStyle={{ padding: '32px 40px' }}
      >
        <Title level={4} style={{ marginBottom: 24 }}>
          ✨ 创建新漫剧
        </Title>
        <Form
          form={form}
          layout="vertical"
          onFinish={handleSubmit}
          initialValues={{ genre: '校园' }}
        >
          <Row gutter={16}>
            <Col span={16}>
              <Form.Item
                name="title"
                label="漫剧标题"
                rules={[{ required: true, message: '请输入漫剧标题' }]}
              >
                <Input placeholder="例如：穿越时空的少女" size="large" />
              </Form.Item>
            </Col>
            <Col span={8}>
              <Form.Item
                name="genre"
                label="题材类型"
                rules={[{ required: true, message: '请选择题材' }]}
              >
                <Select
                  options={GENRE_OPTIONS}
                  size="large"
                  placeholder="选择题材"
                />
              </Form.Item>
            </Col>
          </Row>
          <Form.Item
            name="prompt"
            label="创意描述"
            rules={[{ required: true, message: '请输入创意描述' }]}
          >
            <TextArea
              rows={4}
              placeholder="描述你想要生成的漫剧故事，例如：一个现代女孩意外穿越到古代，凭借现代知识在古代世界闯荡的奇幻冒险故事..."
              size="large"
            />
          </Form.Item>
          <Form.Item style={{ marginBottom: 0, textAlign: 'right' }}>
            <Button
              type="primary"
              htmlType="submit"
              size="large"
              icon={<ThunderboltOutlined />}
              loading={loading}
              style={{ minWidth: 160, height: 48, fontSize: 16 }}
            >
              生成漫剧
            </Button>
          </Form.Item>
        </Form>
      </Card>

      <Card
        title={
          <Space>
            <HistoryOutlined />
            <span>最近生成</span>
          </Space>
        }
        style={{ borderRadius: 12 }}
        bodyStyle={{ padding: '16px 24px' }}
      >
        <Spin spinning={storiesLoading}>
          {stories.length === 0 ? (
            <div style={{ textAlign: 'center', padding: '40px 0' }}>
              <Text type="secondary">暂无生成记录，快去创建第一个漫剧吧！</Text>
            </div>
          ) : (
            <List
              dataSource={stories}
              renderItem={(story) => (
                <List.Item
                  style={{
                    cursor: 'pointer',
                    padding: '16px 8px',
                    borderRadius: 8,
                    transition: 'background 0.2s',
                  }}
                  onClick={() => handleStoryClick(story)}
                  actions={[
                    <Text type="secondary" key="time">
                      <ClockCircleOutlined style={{ marginRight: 4 }} />
                      {formatTime(story.created_at)}
                    </Text>,
                  ]}
                >
                  <List.Item.Meta
                    title={
                      <Space>
                        <span style={{ fontSize: 15 }}>{story.title}</span>
                        <Tag color="blue">{story.genre}</Tag>
                        <Tag color={STATUS_COLORS[story.status] || 'default'}>
                          {STATUS_LABELS[story.status] || story.status}
                        </Tag>
                      </Space>
                    }
                    description={
                      <Text
                        type="secondary"
                        ellipsis
                        style={{ maxWidth: 500, display: 'inline-block' }}
                      >
                        {story.prompt}
                      </Text>
                    }
                  />
                </List.Item>
              )}
            />
          )}
        </Spin>
      </Card>
    </div>
  );
};

export default HomePage;