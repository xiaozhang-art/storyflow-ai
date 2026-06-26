import React, { useState, useEffect } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import {
  Card, Button, Typography, Tabs, Image, Row, Col,
  Space, Spin, Result, Empty, Tag, Descriptions, Tooltip,
} from 'antd';
import {
  DownloadOutlined, ArrowLeftOutlined, UserOutlined, VideoCameraOutlined,
  SoundOutlined, PictureOutlined,
} from '@ant-design/icons';
import { getStoryResult } from '../api';
import type { StoryResultResponse, SceneResult, CharacterResult } from '../types';

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
    label: <span>剧本 ({data.episodes.length}集)</span>,
    children: (
      <div style={{ padding: '8px 0' }}>
        {data.episodes.length > 0 ? (
          data.episodes.map((ep) => (
            <Card key={ep.episode_no} size="small" style={{ marginBottom: 16 }}
              title={<span>第{ep.episode_no}集：{ep.title || '未命名'}</span>}>
              {ep.summary && (
                <Paragraph type="secondary" style={{ marginBottom: 8 }}>
                  {ep.summary}
                </Paragraph>
              )}
              {ep.script && (
                <div style={{
                  background: '#fafafa', padding: '12px 16px', borderRadius: 8,
                  fontSize: 14, lineHeight: 1.9, whiteSpace: 'pre-wrap', maxHeight: 400,
                  overflow: 'auto',
                }}>
                  {ep.script}
                </div>
              )}
            </Card>
          ))
        ) : <Empty description="暂无剧本内容" />}
      </div>
    ),
  };

  const storyboardTab = {
    key: 'scenes',
    label: <span>分镜 ({data.scenes.length}镜)</span>,
    children: (
      <div style={{ padding: '8px 0' }}>
        {data.scenes.length > 0 ? (
          <Row gutter={[16, 16]}>
            {data.scenes.map((scene) => (
              <Col xs={24} sm={12} lg={8} key={scene.scene_no}>
                <Card size="small" hoverable
                  cover={
                    scene.image_url ? (
                      <div style={{ position: 'relative', height: 200, overflow: 'hidden' }}>
                        <Image
                          alt={`场景 ${scene.scene_no}`}
                          src={scene.image_url}
                          style={{ height: 200, objectFit: 'cover' }}
                          preview
                        />
                      </div>
                    ) : (
                      <div style={{
                        height: 200, display: 'flex', alignItems: 'center', justifyContent: 'center',
                        background: '#f5f5f5', color: '#bbb', flexDirection: 'column', gap: 8,
                      }}>
                        <PictureOutlined style={{ fontSize: 32 }} />
                        <Text type="secondary" style={{ fontSize: 12 }}>图片缺失</Text>
                      </div>
                    )
                  }
                  actions={[
                    scene.audio_url ? (
                      <Tooltip title="已生成配音" key="audio">
                        <SoundOutlined style={{ color: '#52c41a' }} />
                      </Tooltip>
                    ) : (
                      <Tooltip title="未生成配音" key="audio">
                        <SoundOutlined style={{ color: '#d9d9d9' }} />
                      </Tooltip>
                    ),
                    scene.dialogue ? (
                      <Tooltip title={scene.dialogue} key="dialogue">
                        <span style={{ fontSize: 12, maxWidth: 120, overflow: 'hidden', textOverflow: 'ellipsis', display: 'inline-block', whiteSpace: 'nowrap' }}>
                          {scene.dialogue}
                        </span>
                      </Tooltip>
                    ) : (
                      <span style={{ color: '#d9d9d9', fontSize: 12 }} key="dialogue">无台词</span>
                    ),
                  ]}
                >
                  <Space size={4} wrap style={{ marginBottom: 8 }}>
                    <Tag color="blue">#{scene.scene_no}</Tag>
                    {scene.camera && <Tag>{scene.camera}</Tag>}
                    {scene.duration && <Tag>{scene.duration}s</Tag>}
                  </Space>
                  {scene.prompt && (
                    <Tooltip title={scene.prompt}>
                      <Paragraph
                        type="secondary"
                        ellipsis={{ rows: 2 }}
                        style={{ fontSize: 12, marginBottom: 0, lineHeight: 1.6 }}
                      >
                        {scene.prompt}
                      </Paragraph>
                    </Tooltip>
                  )}
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
    label: <span>角色 ({data.characters.length})</span>,
    children: (
      <div style={{ padding: '8px 0' }}>
        {data.characters.length > 0 ? (
          <Row gutter={[16, 16]}>
            {data.characters.map((char, idx) => (
              <Col xs={24} sm={12} md={8} key={idx}>
                <CharacterCard char={char} />
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
            <Tag>{data.episodes.length}集</Tag>
            <Tag>{data.scenes.length}镜</Tag>
          </Space>
        </div>

        {data.video_url ? (
          <div>
            <video controls playsInline
              style={{ width: '100%', maxWidth: 720, borderRadius: 8, display: 'block', margin: '0 auto' }}
              src={data.video_url}>
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

/** Character display card with appearance details. */
const CharacterCard: React.FC<{ char: CharacterResult }> = ({ char }) => {
  const appearance = char.appearance && typeof char.appearance === 'object'
    ? char.appearance
    : { hair: '', body: '', cloth: '', face: '' };

  const hasAppearance = Object.values(appearance).some(v => v && v.trim());

  return (
    <Card hoverable style={{ textAlign: 'center' }}>
      <div style={{
        width: 100, height: 100, borderRadius: '50%', background: '#e6f4ff',
        display: 'flex', alignItems: 'center', justifyContent: 'center', margin: '0 auto 12px',
      }}>
        <UserOutlined style={{ fontSize: 36, color: '#1677ff' }} />
      </div>
      <Title level={5} style={{ marginBottom: 8 }}>{char.name}</Title>
      <Descriptions column={1} size="small" style={{ textAlign: 'left' }}>
        {char.gender && <Descriptions.Item label="性别">{char.gender}</Descriptions.Item>}
        {char.age && <Descriptions.Item label="年龄">{char.age}</Descriptions.Item>}
      </Descriptions>
      {hasAppearance && (
        <div style={{ marginTop: 8, textAlign: 'left' }}>
          {appearance.hair && <Text type="secondary" style={{ fontSize: 12, display: 'block' }}>发型: {appearance.hair}</Text>}
          {appearance.face && <Text type="secondary" style={{ fontSize: 12, display: 'block' }}>五官: {appearance.face}</Text>}
          {appearance.body && <Text type="secondary" style={{ fontSize: 12, display: 'block' }}>体型: {appearance.body}</Text>}
          {appearance.cloth && <Text type="secondary" style={{ fontSize: 12, display: 'block' }}>服装: {appearance.cloth}</Text>}
        </div>
      )}
    </Card>
  );
};

export default ResultPage;