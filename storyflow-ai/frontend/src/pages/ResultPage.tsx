import React, { useState, useEffect } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import {
  Card, Button, Typography, Tabs, Image, Row, Col,
  Space, Spin, Result, Empty, Tag, Descriptions,
} from 'antd';
import {
  DownloadOutlined, ArrowLeftOutlined, UserOutlined, VideoCameraOutlined,
} from '@ant-design/icons';
import { getStoryResult } from '../api';
import type { StoryResultResponse } from '../types';

const { Title, Text, Paragraph } = Typography;

const ResultPage: React.FC = () => {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const [data, setData] = useState<StoryResultResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!id) return;
    getStoryResult(id)
      .then(setData)
      .catch(() => setError('加载结果失败'))
      .finally(() => setLoading(false));
  }, [id]);

  if (loading) {
    return (
      <div style={{ display: 'flex', justifyContent: 'center', alignItems: 'center', minHeight: '60vh' }}>
        <Spin size="large" />
      </div>
    );
  }

  if (error || !data) {
    return (
      <div style={{ maxWidth: 700, margin: '80px auto', padding: '0 24px' }}>
        <Result status="error" title="加载失败" subTitle={error || '未找到结果'}
          extra={<Button type="primary" onClick={() => navigate('/')}>返回首页</Button>} />
      </div>
    );
  }

  const scriptTab = {
    key: 'script',
    label: <Space>剧本</Space>,
    children: (
      <div style={{ padding: '8px 0' }}>
        {data.episodes.length > 0 ? (
          data.episodes.map((ep) => (
            <Card key={ep.episode_no} size="small" style={{ marginBottom: 16 }} title={`第${ep.episode_no}集：${ep.title || ''}`}>
              {ep.summary && <Paragraph type="secondary" style={{ marginBottom: 8 }}>{ep.summary}</Paragraph>}
              {ep.script && (
                <Paragraph style={{ fontSize: 14, lineHeight: 1.8, whiteSpace: 'pre-wrap', margin: 0 }}>
                  {ep.script}
                </Paragraph>
              )}
            </Card>
          ))
        ) : <Empty description="暂无剧本内容" />}
      </div>
    ),
  };

  const storyboardTab = {
    key: 'scenes',
    label: <Space>分镜</Space>,
    children: (
      <div style={{ padding: '8px 0' }}>
        {data.scenes.length > 0 ? (
          <Row gutter={[16, 16]}>
            {data.scenes.map((scene) => (
              <Col xs={24} sm={12} md={8} key={scene.scene_no}>
                <Card size="small"
                  cover={
                    scene.image_url ? (
                      <Image alt={`场景 ${scene.scene_no}`} src={scene.image_url}
                        style={{ height: 200, objectFit: 'cover' }} preview />
                    ) : (
                      <div style={{ height: 200, display: 'flex', alignItems: 'center', justifyContent: 'center', background: '#f0f0f0', color: '#999' }}>
                        暂无图片
                      </div>
                    )
                  }
                >
                  <Space>
                    <Tag color="blue">场景 {scene.scene_no}</Tag>
                    {scene.camera && <Tag>{scene.camera}</Tag>}
                    {scene.duration && <Tag>{scene.duration}s</Tag>}
                  </Space>
                </Card>
              </Col>
            ))}
          </Row>
        ) : <Empty description="暂无分镜数据" />}
      </div>
    ),
  };

  const characterTab = {
    key: 'characters',
    label: <Space>角色</Space>,
    children: (
      <div style={{ padding: '8px 0' }}>
        {data.characters.length > 0 ? (
          <Row gutter={[16, 16]}>
            {data.characters.map((char, idx) => (
              <Col xs={24} sm={12} md={8} key={idx}>
                <Card hoverable style={{ textAlign: 'center' }}>
                  <div style={{ width: 100, height: 100, borderRadius: '50%', background: '#e6f4ff',
                    display: 'flex', alignItems: 'center', justifyContent: 'center', margin: '0 auto 12px' }}>
                    <UserOutlined style={{ fontSize: 36, color: '#1677ff' }} />
                  </div>
                  <Title level={5} style={{ marginBottom: 8 }}>{char.name}</Title>
                  <Descriptions column={1} size="small" style={{ textAlign: 'left' }}>
                    {char.gender && <Descriptions.Item label="性别">{char.gender}</Descriptions.Item>}
                    {char.age && <Descriptions.Item label="年龄">{char.age}</Descriptions.Item>}
                  </Descriptions>
                  {char.appearance && Object.keys(char.appearance).length > 0 && (
                    <div style={{ marginTop: 8, textAlign: 'left' }}>
                      {Object.entries(char.appearance).map(([k, v]) => (
                        <Text key={k} type="secondary" style={{ fontSize: 12, display: 'block' }}>
                          {k}: {v}
                        </Text>
                      ))}
                    </div>
                  )}
                </Card>
              </Col>
            ))}
          </Row>
        ) : <Empty description="暂无角色数据" />}
      </div>
    ),
  };

  return (
    <div style={{ maxWidth: 960, margin: '0 auto', padding: '40px 24px' }}>
      <Space style={{ marginBottom: 24, width: '100%', justifyContent: 'space-between' }}>
        <Button type="text" icon={<ArrowLeftOutlined />} onClick={() => navigate('/')} size="large">
          返回首页
        </Button>
      </Space>

      <Card style={{ borderRadius: 12, marginBottom: 24 }} styles={{ body: { padding: '32px 40px' } }}>
        <div style={{ textAlign: 'center', marginBottom: 24 }}>
          <Title level={3} style={{ marginBottom: 4 }}>{data.title}</Title>
          <Space>
            {data.genre && <Tag color="blue">{data.genre}</Tag>}
            <Tag color="green">已完成</Tag>
          </Space>
        </div>

        {data.video_url ? (
          <div>
            <video controls style={{ width: '100%', maxWidth: 720, borderRadius: 8, display: 'block', margin: '0 auto' }} src={data.video_url}>
              您的浏览器不支持视频播放
            </video>
            <div style={{ textAlign: 'center', marginTop: 16 }}>
              <Button type="primary" size="large" icon={<DownloadOutlined />}
                href={data.video_url} download style={{ minWidth: 160, height: 44 }}>
                下载 MP4
              </Button>
            </div>
          </div>
        ) : (
          <div style={{ textAlign: 'center', padding: '60px 0' }}>
            <VideoCameraOutlined style={{ fontSize: 48, color: '#d9d9d9', marginBottom: 16 }} />
            <br />
            <Text type="secondary">视频暂未生成</Text>
          </div>
        )}
      </Card>

      <Card style={{ borderRadius: 12 }} styles={{ body: { padding: '24px 32px' } }}>
        <Tabs items={[scriptTab, storyboardTab, characterTab]} defaultActiveKey="script" size="large" />
      </Card>
    </div>
  );
};

export default ResultPage;