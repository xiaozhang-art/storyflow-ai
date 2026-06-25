/**
 * StoryFlow AI - TypeScript type definitions for API contracts.
 */

// ==================== Story ====================

export interface StoryCreateRequest {
  title: string;
  prompt: string;
  genre: string;
}

export interface StoryResponse {
  id: string;
  title: string | null;
  prompt: string | null;
  genre: string | null;
  total_episode: number;
  status: StoryStatus;
  created_at: string;
}

export type StoryStatus =
  | "created"
  | "generating"
  | "script_done"
  | "character_done"
  | "storyboard_done"
  | "image_done"
  | "voice_done"
  | "completed"
  | "failed";

export interface GenerateResponse {
  task_id: string;
  message: string;
}

// ==================== Task ====================

export interface TaskStatusResponse {
  id: string;
  story_id: string;
  status: "pending" | "running" | "completed" | "failed";
  progress: number;
  current_step: string;
  error_message: string | null;
  created_at: string;
}

export interface TaskProgressEvent {
  task_id: string;
  status: string;
  progress: number;
  current_step: string;
  message: string;
}

// ==================== Result ====================

export interface CharacterResult {
  name: string;
  gender: string | null;
  age: number | null;
  appearance: Record<string, string>;
  personality: Record<string, string> | null;
  avatar_url: string | null;
}

export interface EpisodeResult {
  episode_no: number;
  title: string | null;
  summary: string | null;
  script: string | null;
}

export interface SceneResult {
  scene_no: number;
  prompt: string | null;
  camera: string | null;
  duration: number | null;
  image_url: string | null;
}

export interface StoryResultResponse {
  story_id: string;
  title: string | null;
  genre: string | null;
  video_url: string;
  episodes: EpisodeResult[];
  characters: CharacterResult[];
  scenes: SceneResult[];
}

// ==================== Workflow Steps ====================

export type WorkflowStep =
  | "init"
  | "script"
  | "character"
  | "storyboard"
  | "image"
  | "voice"
  | "video"
  | "done"
  | "error";

export interface StepInfo {
  key: WorkflowStep;
  label: string;
  description: string;
  progressValue: number;
}

export const WORKFLOW_STEPS: StepInfo[] = [
  { key: "script", label: "剧本生成", description: "AI 编写剧情大纲、角色设定和完整对白", progressValue: 10 },
  { key: "character", label: "角色设计", description: "生成角色视觉描述卡片，确保形象一致性", progressValue: 25 },
  { key: "storyboard", label: "分镜生成", description: "将剧本拆解为逐场景分镜脚本", progressValue: 40 },
  { key: "image", label: "图片生成", description: "使用 SDXL 生成每镜动漫风格画面", progressValue: 65 },
  { key: "voice", label: "配音生成", description: "为角色台词生成 AI 语音", progressValue: 80 },
  { key: "video", label: "视频合成", description: "合成视频、添加字幕、导出 MP4", progressValue: 100 },
];