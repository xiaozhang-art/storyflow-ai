import axios from 'axios';
import type {
  StoryCreateRequest,
  StoryResponse,
  GenerateResponse,
  TaskStatusResponse,
  TaskProgressEvent,
  StoryResultResponse,
} from '../types';

const api = axios.create({
  baseURL: '/api',
  timeout: 30000,
  headers: {
    'Content-Type': 'application/json',
  },
});

// ==================== Story API ====================

export async function createStory(data: StoryCreateRequest): Promise<StoryResponse> {
  const response = await api.post<StoryResponse>('/story', data);
  return response.data;
}

export async function getStory(id: string): Promise<StoryResponse> {
  const response = await api.get<StoryResponse>(`/story/${id}`);
  return response.data;
}

export async function listStories(skip = 0, limit = 20): Promise<StoryResponse[]> {
  const response = await api.get<StoryResponse[]>('/story', {
    params: { skip, limit },
  });
  return response.data;
}

export async function startGeneration(storyId: string): Promise<GenerateResponse> {
  const response = await api.post<GenerateResponse>(`/story/${storyId}/generate`);
  return response.data;
}

export async function getStoryResult(storyId: string): Promise<StoryResultResponse> {
  const response = await api.get<StoryResultResponse>(`/story/${storyId}/result`);
  return response.data;
}

// ==================== Task API ====================

export async function getTaskStatus(taskId: string): Promise<TaskStatusResponse> {
  const response = await api.get<TaskStatusResponse>(`/task/${taskId}`);
  return response.data;
}

// ==================== WebSocket ====================

export function connectWebSocket(
  taskId: string,
  onMessage: (msg: TaskProgressEvent) => void,
): WebSocket {
  const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
  const wsUrl = `${protocol}//${window.location.host}/api/task/${taskId}/ws`;
  const ws = new WebSocket(wsUrl);

  ws.onmessage = (event) => {
    try {
      const data: TaskProgressEvent = JSON.parse(event.data);
      onMessage(data);
    } catch {
      console.error('Failed to parse WebSocket message', event.data);
    }
  };

  return ws;
}