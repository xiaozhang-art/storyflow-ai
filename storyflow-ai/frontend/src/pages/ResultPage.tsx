import React, { useState, useEffect } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import {
  Card,
  Button,
  Typography,
  Tabs,
  Image,
  Row,
  Col,
  Space,
  Spin,
  Result,
  Empty,
  Tag,
} from 'antd';
import {
  DownloadOutlined,
  ArrowLeftOutlined,
  UserOutlined,
  VideoCameraOutlined,
} from '@ant-design/icons';
import { getStory, Story } from '../api';

const { Title, Text, Paragraph } = Typography;

const ResultPage: React.FC = () => {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const [story, setStory] = useState<Story | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const fetchStory = async () => {
      if (!id) return;
      try {
        const data = await getStory(id);
        setStory(data);
      } catch {
        setError('加载故事失败');
      } finally {
        setLoading(false);
      }
    };
    fetchStory();
  }, [id]);

  if (loading) {
    return (
      <div style={{ display: 'flex', justifyContent: 'center', alignItems: 'center', minHeight: '60vh' }}>
        <Spin size="large" tip="加载中..." />
      </div>
    );
  }

  if (error || !story) {
    return (
      <div style={{ maxWidth: 700, margin: '80px auto', padding: '0 24px' }}>
        <Result
          status="error"
          title="加载失败"
          subTitle={error || '未找到该故事'}
          extra={
            <Button type="primary" onClick={() => navigate('/')}>
              返回首页
            </Button>
          }
        />
      </div>
    );
  }

  const tabItems = [
    {
      key: 'script',
      label: (
        <Space>
          📝 剧本
        </Space>
      ),
      children: (
        <div style={{ padding: '8px 0' }}>
          {story.script ? (
            <Paragraph
              style={{ fontSize: 15, lineHeight: 1.8, whiteSpace: 'pre-wrap' }}
            >
              {story.script}
            </Paragraph>
          ) : (
            <Empty description="暂无剧本内容" />
          )}
        </div>
      ),
    },
    {
      key: 'scenes',
      label: (
        <Space>
          🎬 分镜
        </Space>
      ),
      children: (
        <div style={{ padding: '8px 0' }}>
          {story.scenes && story.scenes.length > 0 ? (
            <Row gutter={[16, 16]}>
              {story.scenes.map((scene) => (
                <Col xs={24} sm={12} md={8} key={scene.id}>
                  <Card
                    size="small"
                    cover={
                      scene.image_url ? (
                        <Image
                          alt={`场景 ${scene.scene_number}`}
                          src={scene.image_url}
                          style={{ height: 200, objectFit: 'cover' }}
                          preview={true}
                        />
                      ) : (
                        <div
                          style={{
                            height: 200,
                            display: 'flex',
                            alignItems: 'center',
                            justifyContent: 'center',
                            background: '#f0f0f0',
                            color: '#999',
                          }}
                        >
                          暂无图片
                        </div>
                      )
                    }
                    bodyStyle={{ padding: '12px' }}
                  >
                    <Tag color="blue">场景 {scene.scene_number}</Tag>
                    <Paragraph
                      ellipsis={{ rows: 2 }}
                      style={{ marginTop: 8, marginBottom: 0, fontSize: 13 }}
                    >
                      {scene.description}
                    </Paragraph>
                    {scene.dialogue && (
                      <Text
                        type="secondary"
                        style={{ fontSize: 12, display: 'block', marginTop: 4, fontStyle: 'italic' }}
                      >
                        "{scene.dialogue}"
                      </Text>
                    )}
                  </Card>
                </Col>
              ))}
            </Row>
          ) : (
            <Empty description="暂无分镜数据" />
          )}
        </div>
      ),
    },
    {
      key: 'characters',
      label: (
        <Space>
          👤 角色
        </Space>
      ),
      children: (
        <div style={{ padding: '8px 0' }}>
          {story.characters && story.characters.length > 0 ? (
            <Row gutter={[16, 16]}>
              {story.characters.map((char) => (
                <Col xs={24} sm={12} md={8} key={char.id}>
                  <Card
                    hoverable
                    style={{ textAlign: 'center' }}
                    bodyStyle={{ padding: '20px' }}
                    cover={
                      char.reference_image_url ? (
                        <div style={{ padding: 16 }}>
                          <Image
                            alt={char.name}
                            src={char.reference_image_url}
                            style={{
                              width: 120,
                              height: 120,
                              borderRadius: '50%',
                              objectFit: 'cover',
                            }}
                            preview={true}
                          />
                        </div>
                      ) : (
                        <div
                          style={{
                            padding: '24px 16px',
                            display: 'flex',
                            justifyContent: 'center',
                          }}
                        >
                          <div
                            style={{
                              width: 120,
                              height: 120,
                              borderRadius: '50%',
                              background: '#e6f4ff',
                              display: 'flex',
                              alignItems: 'center',
                              justifyContent: 'center',
                            }}
                          >
                            <UserOutlined style={{ fontSize: 40, color: '#1677ff' }} />
                          </div>
                        </div>
                      )
                    }
                  >
                    <Title level={5} style={{ marginBottom: 8 }}>
                      {char.name}
                    </Title>
                    <Paragraph
                      type="secondary"
                      ellipsis={{ rows: 2 }}
                      style={{ marginBottom: 0, fontSize: 13 }}
                    >
                      {char.description}
                    </Paragraph>
                  </Card>
                </Col>
              ))}
            </Row>
          ) : (
            <Empty description="暂无角色数据" />
          )}
        </div>
      ),
    },
  ];

  return (
    <div style={{ maxWidth: 960, margin: '0 auto', padding: '40px 24px' }}>
      <Space style={{ marginBottom: 24, width: '100%', justifyContent: 'space-between' }}>
        <Button
          type="text"
          icon={<ArrowLeftOutlined />}
          onClick={() => navigate('/')}
          size="large"
        >
          返回首页
        </Button>
      </Space>

      <Card style={{ borderRadius: 12, marginBottom: 24 }} bodyStyle={{ padding: '32px 40px' }}>
        <div style={{ textAlign: 'center', marginBottom: 24 }}>
          <Title level={3} style={{ marginBottom: 4 }}>
            {story.title}
          </Title>
          <Space>
            <Tag color="blue">{story.genre}</Tag>
            <Tag color="green">已完成</Tag>
          </Space>
        </div>

        {story.video_url ? (
          <div>
            <video
              controls
              style={{
                width: '100%',
                maxWidth: 720,
                borderRadius: 8,
                display: 'block',
                margin: '0 auto',
              }}
              src={story.video_url}
            >
              您的浏览器不支持视频播放
            </video>
            <div style={{ textAlign: 'center', marginTop: 16 }}>
              <Button
                type="primary"
                size="large"
                icon={<DownloadOutlined />}
                href={story.video_url}
                download
                style={{ minWidth: 160, height: 44 }}
              >
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

      <Card
        style={{ borderRadius: 12 }}
        bodyStyle={{ padding: '24px 32px' }}
      >
        <Tabs items={tabItems} defaultActiveKey="script" size="large" />
      </Card>
    </div>
  );
};

export default ResultPage;