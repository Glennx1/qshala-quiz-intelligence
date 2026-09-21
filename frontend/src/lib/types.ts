export interface Slide {
  id: string;
  document_id: string;
  slide_number: number;
  slide_type: string;
  title: string | null;
  extracted_text: string;
  speaker_notes?: string | null;
  has_images: boolean;
  image_paths: string[];
  created_at: string;
}

export interface DocumentItem {
  id: string;
  filename: string;
  title: string;
  year?: number | null;
  file_type: string;
  file_size_bytes: number;
  slide_count: number;
  question_count: number;
  processing_status: 'PENDING' | 'PROCESSING' | 'COMPLETED' | 'FAILED';
  processing_error?: string | null;
  uploaded_at: string;
  slides?: Slide[];
}

export interface HistoricalQuestion {
  id: string;
  document_id: string;
  slide_id?: string | null;
  answer_slide_id?: string | null;
  question_text: string;
  answer: string;
  options?: string[] | null;
  explanation?: string | null;
  topic: string;
  subtopic?: string | null;
  topics?: string[];
  tags?: string[];
  difficulty: string;
  difficulty_score?: number;
  cognitive_level?: string;
  grade_min: number;
  grade_max: number;
  audience_suitability?: string[];
  question_hook?: string;
  curiosity_score?: number;
  temporal_nature?: string;
  occurrence_count?: number;
  content_hash?: string;
  question_type: string;
  source_year?: number | null;
  document_title?: string | null;
  slide_number?: number | null;
  created_at: string;
}

export interface RetrievalSource {
  id: string;
  historical_question_id?: string | null;
  document_id?: string | null;
  slide_id?: string | null;
  document_title?: string | null;
  slide_number?: number | null;
  relevance_score: number;
  source_quote?: string | null;
  rationale?: string | null;
}

export interface ValidationDetailItem {
  passed: boolean;
  score?: number;
  reason?: string;
  level?: string;
  grade_range?: string;
  distractor_quality?: string;
  most_similar_question?: string;
}

export interface ValidationDetails {
  answer_consistency?: ValidationDetailItem;
  factual_grounding?: ValidationDetailItem;
  grade_suitability?: ValidationDetailItem;
  duplicate_risk?: ValidationDetailItem;
  internal_consistency?: ValidationDetailItem;
  difficulty_alignment?: ValidationDetailItem;
  source_provenance?: ValidationDetailItem;
}

export interface GeneratedQuestion {
  id: string;
  quiz_id: string;
  order_index: number;
  question_text: string;
  options?: string[] | null;
  answer: string;
  explanation?: string | null;
  difficulty: string;
  grade_min?: number;
  grade_max?: number;
  topic?: string;
  question_type: string;
  validation_status: 'PASSED' | 'WARNING' | 'FAILED';
  validation_details?: ValidationDetails;
  duplicate_score: number;
  is_approved: boolean;
  created_at: string;
  retrieval_sources: RetrievalSource[];
}

export interface Quiz {
  id: string;
  title: string;
  topic: string;
  subtopic?: string | null;
  audience_type?: string;
  grades?: number[];
  age_range?: string | null;
  grade_min?: number | null;
  grade_max?: number | null;
  difficulty: string;
  difficulty_distribution?: Record<string, number>;
  question_count: number;
  question_types: string[];
  generation_mode: string;
  style: string;
  raw_prompt?: string | null;
  status: string;
  created_at: string;
  updated_at: string;
  questions: GeneratedQuestion[];
}

export interface DashboardStats {
  years_of_knowledge?: number;
  total_documents: number;
  total_slides: number;
  total_questions: number;
  total_topics: number;
  total_quizzes: number;
  recent_documents: {
    id: string;
    title: string;
    filename: string;
    slide_count: number;
    question_count: number;
    created_at: string;
    status: string;
  }[];
  recent_quizzes: {
    id: string;
    title: string;
    topic: string;
    question_count: number;
    difficulty: string;
    grade_range: string;
    created_at: string;
  }[];
  top_topics: {
    topic: string;
    count: number;
  }[];
}

export interface IngestionStatus {
  document_id: string;
  status: string;
  progress_percentage: number;
  current_step: string;
  slides_processed: number;
  questions_extracted: number;
  error?: string | null;
}
