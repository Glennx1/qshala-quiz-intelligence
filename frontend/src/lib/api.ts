import {
  DashboardStats,
  DocumentItem,
  Slide,
  HistoricalQuestion,
  Quiz,
  GeneratedQuestion,
  IngestionStatus,
  TopicItem,
  TopicSummary,
} from './types';

export function getApiBase(): string {
  if (process.env.NEXT_PUBLIC_API_URL) {
    return process.env.NEXT_PUBLIC_API_URL;
  }
  if (typeof window !== 'undefined') {
    return '/api/v1';
  }
  if (process.env.VERCEL_URL) {
    return `https://${process.env.VERCEL_URL}/api/v1`;
  }
  return 'http://localhost:8000/api/v1';
}

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
    const res = await fetch(`${getApiBase()}/stats`, { cache: 'no-store' });
    return handleResponse<DashboardStats>(res);
  },

  // Documents
  listDocuments: async (): Promise<DocumentItem[]> => {
    const res = await fetch(`${getApiBase()}/documents`, { cache: 'no-store' });
    return handleResponse<DocumentItem[]>(res);
  },

  getDocument: async (id: string): Promise<DocumentItem> => {
    const res = await fetch(`${getApiBase()}/documents/${id}`, { cache: 'no-store' });
    return handleResponse<DocumentItem>(res);
  },

  getDocumentSlides: async (id: string): Promise<Slide[]> => {
    const res = await fetch(`${getApiBase()}/documents/${id}/slides`, { cache: 'no-store' });
    return handleResponse<Slide[]>(res);
  },

  getIngestionStatus: async (id: string): Promise<IngestionStatus> => {
    const res = await fetch(`${getApiBase()}/documents/${id}/status`, { cache: 'no-store' });
    return handleResponse<IngestionStatus>(res);
  },

  uploadDocument: async (file: File, title?: string, year?: number): Promise<DocumentItem> => {
    const formData = new FormData();
    formData.append('file', file);
    if (title) formData.append('title', title);
    if (year) formData.append('year', year.toString());

    const res = await fetch(`${getApiBase()}/documents/upload`, {
      method: 'POST',
      body: formData,
    });
    return handleResponse<DocumentItem>(res);
  },

  deleteDocument: async (id: string): Promise<{ message: string }> => {
    const res = await fetch(`${getApiBase()}/documents/${id}`, {
      method: 'DELETE',
    });
    return handleResponse<{ message: string }>(res);
  },

  // Questions / Knowledge Base Vault
  getTopics: async (): Promise<TopicItem[]> => {
    const res = await fetch(`${getApiBase()}/questions/topics`, { cache: 'no-store' });
    return handleResponse<TopicItem[]>(res);
  },

  getTopicSummary: async (topic: string): Promise<TopicSummary> => {
    const res = await fetch(`${getApiBase()}/questions/topics/${encodeURIComponent(topic)}/summary`, { cache: 'no-store' });
    return handleResponse<TopicSummary>(res);
  },

  searchQuestions: async (params: {
    query?: string;
    topic?: string;
    subtopic?: string;
    tag?: string;
    grade_min?: number;
    grade_max?: number;
    difficulty?: string;
    sort_by?: string;
    sort_order?: 'asc' | 'desc';
    limit?: number;
    offset?: number;
  }): Promise<HistoricalQuestion[]> => {
    const searchParams = new URLSearchParams();
    if (params.query) searchParams.append('query', params.query);
    if (params.topic) searchParams.append('topic', params.topic);
    if (params.subtopic) searchParams.append('subtopic', params.subtopic);
    if (params.tag) searchParams.append('tag', params.tag);
    if (params.grade_min) searchParams.append('grade_min', params.grade_min.toString());
    if (params.grade_max) searchParams.append('grade_max', params.grade_max.toString());
    if (params.difficulty) searchParams.append('difficulty', params.difficulty);
    if (params.sort_by) searchParams.append('sort_by', params.sort_by);
    if (params.sort_order) searchParams.append('sort_order', params.sort_order);
    if (params.limit) searchParams.append('limit', params.limit.toString());
    if (params.offset) searchParams.append('offset', params.offset.toString());

    const res = await fetch(`${getApiBase()}/questions?${searchParams.toString()}`, { cache: 'no-store' });
    return handleResponse<HistoricalQuestion[]>(res);
  },

  updateQuestionTags: async (
    questionId: string,
    tags: string[],
    topics?: string[],
    topic?: string,
    subtopic?: string
  ): Promise<HistoricalQuestion> => {
    const res = await fetch(`${getApiBase()}/questions/${questionId}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ tags, topics, topic, subtopic }),
    });
    return handleResponse<HistoricalQuestion>(res);
  },

  addQuestionTag: async (questionId: string, tag: string): Promise<HistoricalQuestion> => {
    const res = await fetch(`${getApiBase()}/questions/${questionId}/tags?tag=${encodeURIComponent(tag)}`, {
      method: 'POST',
    });
    return handleResponse<HistoricalQuestion>(res);
  },

  deleteQuestionTag: async (questionId: string, tagName: string): Promise<HistoricalQuestion> => {
    const res = await fetch(`${getApiBase()}/questions/${questionId}/tags/${encodeURIComponent(tagName)}`, {
      method: 'DELETE',
    });
    return handleResponse<HistoricalQuestion>(res);
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
    const res = await fetch(`${getApiBase()}/quizzes/generate`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
    return handleResponse<Quiz>(res);
  },

  listQuizzes: async (): Promise<Quiz[]> => {
    const res = await fetch(`${getApiBase()}/quizzes`, { cache: 'no-store' });
    return handleResponse<Quiz[]>(res);
  },

  getQuiz: async (id: string): Promise<Quiz> => {
    const res = await fetch(`${getApiBase()}/quizzes/${id}`, { cache: 'no-store' });
    return handleResponse<Quiz>(res);
  },

  updateQuestion: async (
    questionId: string,
    data: Partial<GeneratedQuestion>
  ): Promise<GeneratedQuestion> => {
    const res = await fetch(`${getApiBase()}/quizzes/questions/${questionId}`, {
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
    const res = await fetch(`${getApiBase()}/quizzes/questions/${questionId}/action`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ action, custom_instruction: customInstruction }),
    });
    return handleResponse<GeneratedQuestion>(res);
  },

  deleteQuestion: async (questionId: string): Promise<{ message: string }> => {
    const res = await fetch(`${getApiBase()}/quizzes/questions/${questionId}`, {
      method: 'DELETE',
    });
    return handleResponse<{ message: string }>(res);
  },

  exportQuizUrl: (quizId: string, format: 'json' | 'csv' | 'pptx'): string => {
    return `${getApiBase()}/quizzes/${quizId}/export?format=${format}`;
  },
};
