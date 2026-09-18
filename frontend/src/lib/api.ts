import {
  DashboardStats,
  DocumentItem,
  Slide,
  HistoricalQuestion,
  Quiz,
  GeneratedQuestion,
  IngestionStatus,
} from './types';

const API_BASE = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000/api/v1';

async function handleResponse<T>(res: Response): Promise<T> {
  if (!res.ok) {
    const errorText = await res.text();
    try {
      const errJson = JSON.parse(errorText);
      throw new Error(errJson.detail || errJson.message || 'API request failed');
    } catch {
      throw new Error(errorText || `HTTP ${res.status}: ${res.statusText}`);
    }
  }
  return res.json();
}

export const api = {
  // Stats
  getStats: async (): Promise<DashboardStats> => {
    const res = await fetch(`${API_BASE}/stats`, { cache: 'no-store' });
    return handleResponse<DashboardStats>(res);
  },

  // Documents
  listDocuments: async (): Promise<DocumentItem[]> => {
    const res = await fetch(`${API_BASE}/documents`, { cache: 'no-store' });
    return handleResponse<DocumentItem[]>(res);
  },

  getDocument: async (id: string): Promise<DocumentItem> => {
    const res = await fetch(`${API_BASE}/documents/${id}`, { cache: 'no-store' });
    return handleResponse<DocumentItem>(res);
  },

  getDocumentSlides: async (id: string): Promise<Slide[]> => {
    const res = await fetch(`${API_BASE}/documents/${id}/slides`, { cache: 'no-store' });
    return handleResponse<Slide[]>(res);
  },

  getIngestionStatus: async (id: string): Promise<IngestionStatus> => {
    const res = await fetch(`${API_BASE}/documents/${id}/status`, { cache: 'no-store' });
    return handleResponse<IngestionStatus>(res);
  },

  uploadDocument: async (file: File, title?: string, year?: number): Promise<DocumentItem> => {
    const formData = new FormData();
    formData.append('file', file);
    if (title) formData.append('title', title);
    if (year) formData.append('year', year.toString());

    const res = await fetch(`${API_BASE}/documents/upload`, {
      method: 'POST',
      body: formData,
    });
    return handleResponse<DocumentItem>(res);
  },

  deleteDocument: async (id: string): Promise<{ message: string }> => {
    const res = await fetch(`${API_BASE}/documents/${id}`, {
      method: 'DELETE',
    });
    return handleResponse<{ message: string }>(res);
  },

  // Questions / Knowledge Base
  searchQuestions: async (params: {
    query?: string;
    topic?: string;
    grade_min?: number;
    grade_max?: number;
    difficulty?: string;
    limit?: number;
    offset?: number;
  }): Promise<HistoricalQuestion[]> => {
    const searchParams = new URLSearchParams();
    if (params.query) searchParams.append('query', params.query);
    if (params.topic) searchParams.append('topic', params.topic);
    if (params.grade_min) searchParams.append('grade_min', params.grade_min.toString());
    if (params.grade_max) searchParams.append('grade_max', params.grade_max.toString());
    if (params.difficulty) searchParams.append('difficulty', params.difficulty);
    if (params.limit) searchParams.append('limit', params.limit.toString());
    if (params.offset) searchParams.append('offset', params.offset.toString());

    const res = await fetch(`${API_BASE}/questions?${searchParams.toString()}`, { cache: 'no-store' });
    return handleResponse<HistoricalQuestion[]>(res);
  },

  // Quizzes
  generateQuiz: async (payload: {
    topic: string;
    subtopic?: string;
    audience_type?: string;
    grades?: number[];
    age_range?: string;
    grade_min?: number;
    grade_max?: number;
    difficulty?: string;
    difficulty_distribution?: Record<string, number>;
    question_count: number;
    question_types: string[];
    generation_mode: string;
    style?: string;
    raw_prompt?: string;
  }): Promise<Quiz> => {
    const res = await fetch(`${API_BASE}/quizzes/generate`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
    return handleResponse<Quiz>(res);
  },

  listQuizzes: async (): Promise<Quiz[]> => {
    const res = await fetch(`${API_BASE}/quizzes`, { cache: 'no-store' });
    return handleResponse<Quiz[]>(res);
  },

  getQuiz: async (id: string): Promise<Quiz> => {
    const res = await fetch(`${API_BASE}/quizzes/${id}`, { cache: 'no-store' });
    return handleResponse<Quiz>(res);
  },

  updateQuestion: async (
    questionId: string,
    data: Partial<GeneratedQuestion>
  ): Promise<GeneratedQuestion> => {
    const res = await fetch(`${API_BASE}/quizzes/questions/${questionId}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(data),
    });
    return handleResponse<GeneratedQuestion>(res);
  },

  executeQuestionAction: async (
    questionId: string,
    action: 'regenerate' | 'make_easier' | 'make_harder' | 'generate_similar',
    customInstruction?: string
  ): Promise<GeneratedQuestion> => {
    const res = await fetch(`${API_BASE}/quizzes/questions/${questionId}/action`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ action, custom_instruction: customInstruction }),
    });
    return handleResponse<GeneratedQuestion>(res);
  },

  deleteQuestion: async (questionId: string): Promise<{ message: string }> => {
    const res = await fetch(`${API_BASE}/quizzes/questions/${questionId}`, {
      method: 'DELETE',
    });
    return handleResponse<{ message: string }>(res);
  },

  exportQuizUrl: (quizId: string, format: 'json' | 'csv'): string => {
    return `${API_BASE}/quizzes/${quizId}/export?format=${format}`;
  },
};
