import axios from 'axios';

const api = axios.create({
  baseURL: '/api',
  timeout: 30000,
  headers: {
    'Content-Type': 'application/json',
  },
});

export interface Story {
  id: string;
  title: string;
  prompt: string;
  genre: string;
  status: string;
  task_id: string | null;
  video_url: string | null;
  script: string | null;
  scenes: Scene[] | null;
  characters: Character[] | null;
  created_at: string;
  updated_at: string;
}

export interface Scene {
  id: string;
  story_id: string;
  scene_number: number;
  description: string;
  dialogue: string;
  image_url: string | null;
  audio_url: string | null;
}

export interface Character {
  id: string;
  story_id: string;
  name: string;
  description: string;
  reference_image_url: string | null;
}

export interface TaskStatus {
  task_id: string;
  status: 'pending' | 'running' | 'completed' | 'failed';
  current_step: number;
  total_steps: number;
  progress: number;
  message: string;
  result: Record<string, unknown> | null;
  error: string | null;
}

export interface CreateStoryRequest {
  title: string;
  prompt: string;
  genre: string;
}

export async function createStory(data: CreateStoryRequest): Promise<Story> {
  const response = await api.post<Story>('/stories', data);
  return response.data;
}

export async function getStory(id: string): Promise<Story> {
  const response = await api.get<Story>(`/stories/${id}`);
  return response.data;
}

export async function listStories(): Promise<Story[]> {
  const response = await api.get<Story[]>('/stories');
  return response.data;
}

export async function startGeneration(storyId: string): Promise<{ task_id: string }> {
  const response = await api.post<{ task_id: string }>(`/stories/${storyId}/generate`);
  return response.data;
}

export async function getTaskStatus(taskId: string): Promise<TaskStatus> {
  const response = await api.get<TaskStatus>(`/tasks/${taskId}/status`);
  return response.data;
}

export interface WebSocketMessage {
  type: 'progress' | 'complete' | 'error';
  task_id: string;
  status?: string;
  current_step?: number;
  total_steps?: number;
  progress?: number;
  message?: string;
  result?: Record<string, unknown>;
  error?: string;
}

export function connectWebSocket(
  taskId: string,
  onMessage: (msg: WebSocketMessage) => void,
): WebSocket {
  const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
  const wsUrl = `${protocol}//${window.location.host}/ws/tasks/${taskId}`;
  const ws = new WebSocket(wsUrl);

  ws.onopen = () => {
    console.log(`WebSocket connected for task ${taskId}`);
  };

  ws.onmessage = (event) => {
    try {
      const data: WebSocketMessage = JSON.parse(event.data);
      onMessage(data);
    } catch {
      console.error('Failed to parse WebSocket message', event.data);
    }
  };

  ws.onerror = (error) => {
    console.error('WebSocket error', error);
  };

  ws.onclose = () => {
    console.log(`WebSocket disconnected for task ${taskId}`);
  };

  return ws;
}