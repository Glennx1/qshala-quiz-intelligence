import { Quiz } from './types';

const STORAGE_KEY = 'qshala_generated_quizzes';

/**
 * Retrieves all locally saved quizzes from localStorage.
 */
export function getLocalQuizzes(): Quiz[] {
  if (typeof window === 'undefined') return [];
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return [];
    const parsed = JSON.parse(raw);
    return Array.isArray(parsed) ? parsed : [];
  } catch (err) {
    console.error('Error reading quizzes from localStorage:', err);
    return [];
  }
}

/**
 * Saves or updates a quiz in localStorage so it persists across serverless container restarts.
 */
export function saveLocalQuiz(quiz: Quiz): void {
  if (typeof window === 'undefined' || !quiz || !quiz.id) return;
  try {
    const current = getLocalQuizzes();
    const existingIndex = current.findIndex((q) => q.id === quiz.id);
    let updated: Quiz[];
    if (existingIndex >= 0) {
      updated = [...current];
      updated[existingIndex] = { ...updated[existingIndex], ...quiz };
    } else {
      updated = [quiz, ...current];
    }
    // Cap at 100 recent quizzes to prevent storage bloat
    if (updated.length > 100) {
      updated = updated.slice(0, 100);
    }
    localStorage.setItem(STORAGE_KEY, JSON.stringify(updated));
  } catch (err) {
    console.error('Error saving quiz to localStorage:', err);
  }
}

/**
 * Retrieves a specific quiz from localStorage by its ID.
 */
export function getLocalQuiz(id: string): Quiz | null {
  if (typeof window === 'undefined' || !id) return null;
  const list = getLocalQuizzes();
  return list.find((q) => q.id === id) || null;
}

/**
 * Deletes a quiz from localStorage by its ID.
 */
export function deleteLocalQuiz(id: string): void {
  if (typeof window === 'undefined' || !id) return;
  try {
    const current = getLocalQuizzes();
    const filtered = current.filter((q) => q.id !== id);
    localStorage.setItem(STORAGE_KEY, JSON.stringify(filtered));
  } catch (err) {
    console.error('Error deleting quiz from localStorage:', err);
  }
}

/**
 * Seamlessly merges backend database quizzes with local browser-persisted quizzes,
 * deduplicating by ID and sorting newest first.
 */
export function mergeQuizzes(backendQuizzes: Quiz[], localQuizzes: Quiz[]): Quiz[] {
  const map = new Map<string, Quiz>();

  // Add backend quizzes first
  for (const bq of backendQuizzes) {
    if (bq && bq.id) {
      map.set(bq.id, bq);
    }
  }

  // Overlay local quizzes
  for (const lq of localQuizzes) {
    if (lq && lq.id) {
      const existing = map.get(lq.id);
      if (!existing) {
        map.set(lq.id, lq);
      } else {
        map.set(lq.id, {
          ...existing,
          ...lq,
          questions: (lq.questions && lq.questions.length > 0) ? lq.questions : existing.questions,
        });
      }
    }
  }

  // Sort newest first
  return Array.from(map.values()).sort((a, b) => {
    const tA = a.created_at ? new Date(a.created_at).getTime() : 0;
    const tB = b.created_at ? new Date(b.created_at).getTime() : 0;
    return tB - tA;
  });
}
