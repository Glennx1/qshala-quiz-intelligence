'use client';

import { useState, useEffect, Suspense } from 'react';
import { useSearchParams } from 'next/navigation';
import {
  Search,
  Filter,
  ExternalLink,
  Loader2,
  ArrowUpDown,
  Layers,
  Tag,
  Plus,
  AlertTriangle,
  Eye,
  CheckCircle,
  XCircle,
  Volume2,
  Video,
  Play,
  Image as ImageIcon,
  Copy,
  X,
  FileSpreadsheet,
  Star
} from 'lucide-react';
import { api, resolveMediaUrl, getFallbackMediaUrl } from '../../lib/api';
import { HistoricalQuestion, TopicItem, DocumentItem } from '../../lib/types';
import SlideViewerModal from '../../components/SlideViewerModal';
import TagManagerModal from '../../components/TagManagerModal';
import MediaViewerModal from '../../components/MediaViewerModal';

const PLACEHOLDER_ICONS = new Set([
  'slide_41_img_1.png', 'slide_40_img_1.png', 'slide_49_img_1.png',
  'slide_53_img_1.png', 'slide_120_img_1.png', 'slide_122_img_1.png',
  'image16.png'
]);

function isPlaceholderIcon(url?: string | null): boolean {
  if (!url) return false;
  const name = url.replace(/\\/g, '/').split('/').pop()?.toLowerCase();
  return name ? PLACEHOLDER_ICONS.has(name) : false;
}

function QuestionFormatDisplay({
  q,
  getImageSrc,
  setPreviewImage,
  handleImgError
}: {
  q: HistoricalQuestion;
  getImageSrc: (url: string) => string;
  setPreviewImage: (url: string) => void;
  handleImgError: (url: string) => void;
}) {
  const fmt = q.question_format;
  const payload = q.format_data || q.format_payload;

  if (fmt === 'CONNECT_4' || fmt === 'CONNECT') {
    const rawImgs = (q.question_images && q.question_images.length > 0 ? q.question_images : q.image_refs || [])
      .filter(x => !isPlaceholderIcon(x));
    return (
      <div className="space-y-2 mt-1">
        {q.question_text && q.question_text.trim() && (
          <div className="font-semibold text-[13.5px] text-slate-900 leading-snug">
            {q.question_text}
          </div>
        )}
        {rawImgs.length > 0 && (
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-2 pt-1">
            {rawImgs.slice(0, 4).map((imgUrl, i) => (
              <button
                key={i}
                type="button"
                onClick={() => setPreviewImage(imgUrl)}
                className="relative rounded-lg overflow-hidden border border-blue-200 bg-slate-50 aspect-video hover:border-blue-400 hover:shadow-xs transition-all cursor-pointer group"
                title={`Clue ${i + 1}: click to view`}
              >
                <img
                  src={getImageSrc(imgUrl)}
                  onError={() => handleImgError(imgUrl)}
                  alt={`Clue ${i + 1}`}
                  className="w-full h-full object-cover group-hover:scale-105 transition-transform"
                />
                <span className="absolute top-1 left-1 rounded bg-blue-700/80 px-1.5 py-0.5 text-[8.5px] font-bold text-white uppercase">
                  Clue {i + 1}
                </span>
              </button>
            ))}
          </div>
        )}
        <div className="text-[12.5px] text-slate-700 font-normal">
          <span className="font-bold text-blue-700">Common Link:</span>{' '}
          <span className="font-semibold text-slate-900">{q.answer}</span>
        </div>
      </div>
    );
  }

  if (fmt === 'STEPPED_CLUE' || fmt === 'THREE_CLUE') {
    const clues = payload?.clues;
    return (
      <div className="space-y-1.5 mt-1">
        {clues && Array.isArray(clues) && clues.length > 0 ? (
          <div className="space-y-1.5 pt-1">
            {clues.map((clue: any, i: number) => (
              <div key={i} className="flex items-start gap-2 rounded-md bg-amber-50/70 border border-amber-200/80 px-2.5 py-1.5 text-[12.5px]">
                <span className="shrink-0 rounded bg-amber-200/90 text-amber-900 font-mono text-[10.5px] font-bold px-1.5 py-0.5">
                  {clue.points || `Clue ${clue.step || i + 1}`}
                </span>
                <span className="text-slate-800 leading-snug">{clue.text || q.question_text}</span>
              </div>
            ))}
          </div>
        ) : (
          <div className="font-semibold text-[13.5px] text-slate-900 leading-snug">
            {q.question_text}
          </div>
        )}
        <div className="text-[12.5px] text-slate-700 font-normal pt-0.5">
          <span className="font-bold text-amber-800">Answer:</span>{' '}
          <span className="font-semibold text-slate-900">{q.answer}</span>
        </div>
      </div>
    );
  }

  if (fmt === 'ARRANGE_ORDER') {
    const items = payload?.items;
    return (
      <div className="space-y-2 mt-1">
        <div className="font-semibold text-[13.5px] text-slate-900 leading-snug">
          {q.question_text}
        </div>
        {items && Array.isArray(items) && items.length > 0 && (
          <div className="flex flex-wrap gap-1.5 pt-1">
            {items.map((item: any, i: number) => (
              <span key={i} className="inline-flex items-center gap-1.5 rounded-lg border border-purple-200 bg-purple-50/60 px-2.5 py-1 text-[12px] text-slate-800 font-medium">
                <span className="font-bold text-purple-700">[{item.key || String.fromCharCode(65 + i)}]</span>
                <span>{item.text || item.label}</span>
              </span>
            ))}
          </div>
        )}
        <div className="text-[12.5px] text-slate-700 font-normal pt-0.5">
          <span className="font-bold text-purple-700">Correct Sequence:</span>{' '}
          <span className="font-semibold text-slate-900">{q.answer}</span>
        </div>
      </div>
    );
  }

  // STANDARD_QA default
  return (
    <>
      <div className="font-semibold text-[13.5px] text-slate-900 leading-snug">
        {q.question_text}
      </div>
      <div className="mt-1 text-[12px] text-slate-600 font-normal">
        Answer: <span className="font-semibold text-slate-800">{q.answer}</span>
      </div>
    </>
  );
}

function KnowledgeBaseContent() {
  const searchParams = useSearchParams();
  const initialTopic = searchParams.get('topic') || '';

  const [activeTab, setActiveTab] = useState<'all' | 'duplicates' | 'review'>('all');
  const [duplicateCount, setDuplicateCount] = useState<number>(0);
  const [reviewCount, setReviewCount] = useState<number>(0);

  const [query, setQuery] = useState('');
  const [topic, setTopic] = useState(initialTopic);
  const [subtopic, setSubtopic] = useState('');
  const [tagFilter, setTagFilter] = useState('');
  const [difficulty, setDifficulty] = useState('');
  const [formatFilter, setFormatFilter] = useState('');
  const [selectedDeckId, setSelectedDeckId] = useState<string>('');
  const [gradeMin, setGradeMin] = useState<number | ''>('');
  const [sortBy, setSortBy] = useState('created_at');
  const [sortOrder, setSortOrder] = useState<'desc' | 'asc'>('desc');

  const [topicsList, setTopicsList] = useState<TopicItem[]>([]);
  const [documentsList, setDocumentsList] = useState<DocumentItem[]>([]);
  const [availableSubtopics, setAvailableSubtopics] = useState<string[]>([]);
  const [questions, setQuestions] = useState<HistoricalQuestion[]>([]);
  const [loading, setLoading] = useState(true);
  const [selectedSlide, setSelectedSlide] = useState<any>(null);
  const [selectedQuestionForTags, setSelectedQuestionForTags] = useState<HistoricalQuestion | null>(null);
  const [selectedQuestionForMedia, setSelectedQuestionForMedia] = useState<HistoricalQuestion | null>(null);
  const [selectedDuplicateForReview, setSelectedDuplicateForReview] = useState<HistoricalQuestion | null>(null);
  const [resolvingId, setResolvingId] = useState<string | null>(null);
  const [previewImage, setPreviewImage] = useState<string | null>(null);
  const [imgFallbackUrls, setImgFallbackUrls] = useState<Record<string, string>>({});

  const getImageSrc = (rawUrl: string | null | undefined) => {
    if (!rawUrl) return '';
    if (imgFallbackUrls[rawUrl]) {
      return imgFallbackUrls[rawUrl];
    }
    return resolveMediaUrl(rawUrl);
  };

  const handleImgError = (rawUrl: string) => {
    const current = getImageSrc(rawUrl);
    const nextFallback = getFallbackMediaUrl(current);
    if (nextFallback && nextFallback !== current) {
      setImgFallbackUrls((prev) => ({ ...prev, [rawUrl]: nextFallback }));
    }
  };

  // Fetch topics list, documents list, and duplicate count on mount
  useEffect(() => {
    const loadMetadata = async () => {
      try {
        const list = await api.getTopics();
        setTopicsList(list);
        const docs = await api.listDocuments();
        setDocumentsList(docs);
        const dups = await api.getDuplicateCandidates();
        setDuplicateCount(dups.length);
        try {
          setReviewCount(await api.getReviewCount());
        } catch { /* review count is best-effort */ }
      } catch (err) {
        console.error('Failed to load initial metadata:', err);
      }
    };
    loadMetadata();
  }, []);

  // When topic changes, load topic summary for subtopics
  useEffect(() => {
    if (topic) {
      api.getTopicSummary(topic)
        .then((summary) => setAvailableSubtopics(summary.subtopics || []))
        .catch(() => setAvailableSubtopics([]));
    } else {
      setAvailableSubtopics([]);
      setSubtopic('');
    }
  }, [topic]);

  const fetchQuestions = async () => {
    setLoading(true);
    try {
      if (activeTab === 'review') {
        const data = await api.getReviewCandidates();
        setQuestions(data);
        setReviewCount(data.length);
        return;
      }
      const data = await api.searchQuestions({
        query: query.trim() || undefined,
        topic: topic || undefined,
        subtopic: subtopic || undefined,
        tag: tagFilter.trim() || undefined,
        difficulty: difficulty || undefined,
        question_format: formatFilter || undefined,
        document_id: selectedDeckId || undefined,
        grade_min: gradeMin !== '' ? Number(gradeMin) : undefined,
        duplicate_status: activeTab === 'duplicates' ? 'POSSIBLE_DUPLICATE' : undefined,
        sort_by: sortBy,
        sort_order: sortOrder,
        limit: 100,
      });
      setQuestions(data);
    } catch (err) {
      console.error(err);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchQuestions();
  }, [activeTab, topic, subtopic, tagFilter, difficulty, formatFilter, selectedDeckId, gradeMin, sortBy, sortOrder]);

  const handleSearch = (e: React.FormEvent) => {
    e.preventDefault();
    fetchQuestions();
  };

  const handleQuestionTagsSaved = (updated: HistoricalQuestion) => {
    // Editing tags confirms a human label, so the question leaves the review queue.
    if (activeTab === 'review') {
      setQuestions((prev) => prev.filter((item) => item.id !== updated.id));
      setReviewCount((prev) => Math.max(0, prev - 1));
      return;
    }
    setQuestions((prev) =>
      prev.map((item) => (item.id === updated.id ? { ...item, ...updated } : item))
    );
  };

  const handleAcceptReview = async (questionId: string) => {
    setResolvingId(questionId);
    try {
      await api.acceptReview(questionId);
      setQuestions((prev) => prev.filter((q) => q.id !== questionId));
      setReviewCount((prev) => Math.max(0, prev - 1));
    } catch (err) {
      console.error('Failed to accept review question:', err);
    } finally {
      setResolvingId(null);
    }
  };

  const handleResolveDuplicate = async (questionId: string, action: 'CONFIRM_DUPLICATE' | 'DISMISS_UNIQUE') => {
    setResolvingId(questionId);
    try {
      await api.resolveDuplicate(questionId, action);
      setQuestions((prev) => prev.filter((q) => q.id !== questionId));
      setDuplicateCount((prev) => Math.max(0, prev - 1));
      setSelectedDuplicateForReview(null);
    } catch (err) {
      console.error('Failed to resolve duplicate:', err);
    } finally {
      setResolvingId(null);
    }
  };

  const handleViewSlide = (q: HistoricalQuestion) => {
    const rawQImgs = (q.question_images && q.question_images.length > 0)
      ? q.question_images
      : (q.image_refs || []);
    const qImgs = rawQImgs.filter(x => !isPlaceholderIcon(x));
    const ansImgs = (q.answer_images || []).filter(x => !isPlaceholderIcon(x));
    const allSlideImgs = Array.from(new Set([...qImgs, ...ansImgs]));

    setSelectedSlide({
      document_title: q.document_title,
      slide_number: q.slide_number,
      extracted_text: `${q.question_text}\n\n${(q.options || []).join('\n')}\n\nAnswer: ${q.answer}`,
      speaker_notes: q.explanation,
      slide_type: 'QUESTION',
      image_paths: allSlideImgs,
    });
  };

  return (
    <div className="p-6 sm:p-8 lg:p-10 max-w-7xl mx-auto space-y-6">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between border-b border-slate-200/60 pb-5 gap-4">
        <div>
          <h1 className="text-[28px] sm:text-[32px] font-bold tracking-tight text-slate-900 leading-tight">
            Questions
          </h1>
          <p className="mt-1 text-[14px] text-slate-500 font-normal leading-relaxed">
            Verified, structured, and deduplicated questions across all historical QShala tournaments.
          </p>
        </div>

        {/* View Tabs */}
        <div className="flex items-center bg-slate-100 p-1 rounded-lg border border-slate-200/80">
          <button
            type="button"
            onClick={() => setActiveTab('all')}
            className={`px-3.5 py-1.5 rounded-md text-[13px] font-semibold transition-all cursor-pointer ${
              activeTab === 'all'
                ? 'bg-white text-slate-900 shadow-sm'
                : 'text-slate-600 hover:text-slate-900'
            }`}
          >
            All Questions
          </button>
          <button
            type="button"
            onClick={() => setActiveTab('duplicates')}
            className={`flex items-center gap-1.5 px-3.5 py-1.5 rounded-md text-[13px] font-semibold transition-all cursor-pointer ${
              activeTab === 'duplicates'
                ? 'bg-amber-500 text-white shadow-sm'
                : 'text-amber-700 hover:text-amber-800'
            }`}
          >
            <AlertTriangle className="h-3.5 w-3.5" />
            <span>Possible Duplicates</span>
            {duplicateCount > 0 && (
              <span className={`px-1.5 py-0.2 rounded-full text-[11px] font-bold ${
                activeTab === 'duplicates' ? 'bg-white text-amber-600' : 'bg-amber-200 text-amber-900'
              }`}>
                {duplicateCount}
              </span>
            )}
          </button>
          <button
            type="button"
            onClick={() => setActiveTab('review')}
            className={`flex items-center gap-1.5 px-3.5 py-1.5 rounded-md text-[13px] font-semibold transition-all cursor-pointer ${
              activeTab === 'review'
                ? 'bg-indigo-600 text-white shadow-sm'
                : 'text-indigo-700 hover:text-indigo-800'
            }`}
          >
            <Eye className="h-3.5 w-3.5" />
            <span>Needs Review</span>
            {reviewCount > 0 && (
              <span className={`px-1.5 py-0.2 rounded-full text-[11px] font-bold ${
                activeTab === 'review' ? 'bg-white text-indigo-600' : 'bg-indigo-200 text-indigo-900'
              }`}>
                {reviewCount}
              </span>
            )}
          </button>
        </div>
      </div>

      {/* Search & Filters Bar */}
      <div className="rounded-xl border border-slate-200/80 bg-white p-4 shadow-sm shadow-slate-100/50 space-y-3">
        <form onSubmit={handleSearch} className="flex gap-2">
          <div className="relative flex-1">
            <Search className="absolute left-3.5 top-3 h-4 w-4 text-slate-400" />
            <input
              type="text"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="Search questions, answers, topics, or presentation deck name..."
              className="w-full rounded-lg border border-slate-200 bg-white py-2 pl-10 pr-4 text-[14px] font-normal text-slate-900 placeholder:text-slate-400 focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
            />
          </div>

          <button
            type="submit"
            className="rounded-lg bg-blue-600 px-4 py-2 text-[13px] font-semibold text-white hover:bg-blue-700 transition-colors cursor-pointer"
          >
            Search
          </button>
        </form>

        {/* Dynamic Filters & Sorting */}
        <div className="flex flex-wrap items-center gap-3 pt-2 border-t border-slate-100 text-[13px]">
          <div className="flex items-center gap-1.5 text-slate-500 font-medium">
            <Filter className="h-3.5 w-3.5" />
            <span>Filters:</span>
          </div>

          {/* Presentation Deck Filter */}
          <select
            value={selectedDeckId}
            onChange={(e) => setSelectedDeckId(e.target.value)}
            className="rounded-md border border-slate-200 bg-white px-2.5 py-1.5 text-[13px] font-normal text-slate-700 focus:border-blue-500 focus:outline-none cursor-pointer max-w-[210px] truncate"
            title="Filter by Presentation Deck"
          >
            <option value="">All Presentations / Decks ({documentsList.length})</option>
            {documentsList.map((doc) => (
              <option key={doc.id} value={doc.id}>
                {doc.title || doc.filename}
              </option>
            ))}
          </select>

          {/* Dynamic Topics Dropdown */}
          <select
            value={topic}
            onChange={(e) => {
              setTopic(e.target.value);
              setSubtopic('');
            }}
            className="rounded-md border border-slate-200 bg-white px-2.5 py-1.5 text-[13px] font-normal text-slate-700 focus:border-blue-500 focus:outline-none cursor-pointer"
          >
            <option value="">All Topics ({topicsList.reduce((a, b) => a + b.count, 0)})</option>
            {topicsList.map((t) => (
              <option key={t.topic} value={t.topic}>
                {t.topic} ({t.count})
              </option>
            ))}
          </select>

          {/* Subtopic Filter (if available) */}
          {availableSubtopics.length > 0 && (
            <select
              value={subtopic}
              onChange={(e) => setSubtopic(e.target.value)}
              className="rounded-md border border-slate-200 bg-white px-2.5 py-1.5 text-[13px] font-normal text-slate-700 focus:border-blue-500 focus:outline-none cursor-pointer"
            >
              <option value="">All Subtopics</option>
              {availableSubtopics.map((sub) => (
                <option key={sub} value={sub}>
                  {sub}
                </option>
              ))}
            </select>
          )}

          {/* Difficulty */}
          <select
            value={difficulty}
            onChange={(e) => setDifficulty(e.target.value)}
            className="rounded-md border border-slate-200 bg-white px-2.5 py-1.5 text-[13px] font-normal text-slate-700 focus:border-blue-500 focus:outline-none cursor-pointer"
          >
            <option value="">All Difficulties</option>
            <option value="Easy">Easy</option>
            <option value="Medium">Medium</option>
            <option value="Hard">Hard</option>
          </select>

          {/* Format Filter */}
          <select
            value={formatFilter}
            onChange={(e) => setFormatFilter(e.target.value)}
            className="rounded-md border border-slate-200 bg-white px-2.5 py-1.5 text-[13px] font-normal text-slate-700 focus:border-indigo-500 focus:outline-none cursor-pointer"
          >
            <option value="">All Formats</option>
            <option value="CONNECT_4">Connect 4</option>
            <option value="STEPPED_CLUE">Stepped Clue (Portfolio Builder)</option>
            <option value="ARRANGE_ORDER">Arrange the Order (Ticker Tangle)</option>
            <option value="BUZZER">Buzzer (Closing Bell)</option>
            <option value="VISUAL_CLUE">Visual Clue</option>
            <option value="VIDEO_CLUE">Video Clue</option>
            <option value="AUDIO_CLUE">Audio Clue</option>
            <option value="QA">Direct Question & Answer</option>
          </select>

          {/* Tag Filter */}
          <div className="relative">
            <Tag className="absolute left-2.5 top-1/2 -translate-y-1/2 h-3.5 w-3.5 text-slate-400" />
            <input
              type="text"
              placeholder="Filter by tag..."
              value={tagFilter}
              onChange={(e) => setTagFilter(e.target.value.replace(/^#+/, ''))}
              className="rounded-md border border-slate-200 bg-white pl-8 pr-6 py-1.5 text-[13px] font-normal text-slate-700 placeholder-slate-400 focus:border-indigo-500 focus:outline-none w-[140px]"
            />
            {tagFilter && (
              <button
                type="button"
                onClick={() => setTagFilter('')}
                className="absolute right-2 top-1/2 -translate-y-1/2 text-slate-400 hover:text-slate-600 text-[12px] font-bold"
                title="Clear tag filter"
              >
                &times;
              </button>
            )}
          </div>

          {/* Sorting */}
          <div className="flex items-center gap-1.5 ml-auto">
            <ArrowUpDown className="h-3.5 w-3.5 text-slate-400" />
            <select
              value={sortBy}
              onChange={(e) => setSortBy(e.target.value)}
              className="rounded-md border border-slate-200 bg-white px-2.5 py-1.5 text-[13px] font-normal text-slate-700 focus:border-blue-500 focus:outline-none cursor-pointer"
            >
              <option value="created_at">Date Added</option>
              <option value="difficulty_score">Difficulty Score</option>
              <option value="curiosity_score">Curiosity Score</option>
              <option value="occurrence_count">Occurrences</option>
            </select>

            <button
              type="button"
              onClick={() => setSortOrder(sortOrder === 'asc' ? 'desc' : 'asc')}
              className="px-2 py-1.5 rounded-md border border-slate-200 bg-white text-slate-600 hover:bg-slate-50 text-[12px] font-semibold cursor-pointer"
              title="Toggle sort direction"
            >
              {sortOrder.toUpperCase()}
            </button>
          </div>

          {(query || topic || subtopic || tagFilter || difficulty || formatFilter || gradeMin || selectedDeckId) && (
            <button
              type="button"
              onClick={() => {
                setQuery('');
                setTopic('');
                setSubtopic('');
                setTagFilter('');
                setDifficulty('');
                setFormatFilter('');
                setGradeMin('');
                setSelectedDeckId('');
              }}
              className="text-[13px] text-blue-600 hover:underline cursor-pointer font-medium"
            >
              Clear filters
            </button>
          )}
        </div>
      </div>

      {/* Professional CMS Data Table */}
      <div className="rounded-xl border border-slate-200/80 bg-white shadow-sm shadow-slate-100/50 overflow-hidden">
        {loading ? (
          <div className="flex flex-col items-center justify-center py-20">
            <Loader2 className="h-6 w-6 animate-spin text-blue-600 mb-2" />
            <p className="text-[13px] text-slate-400 font-normal">Loading questions...</p>
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-left text-[13px] border-collapse">
              <thead>
                <tr className="border-b border-slate-100 bg-slate-50/60 font-semibold text-[12px] uppercase tracking-wider text-slate-600">
                  <th className="py-3 px-4 w-6/12">Question</th>
                  <th className="py-3 px-4">Topics</th>
                  <th className="py-3 px-4 text-right">Actions</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {questions.length === 0 ? (
                  <tr>
                    <td colSpan={3} className="py-12 text-center text-slate-400">
                      {activeTab === 'duplicates'
                        ? 'No possible duplicates pending review!'
                        : activeTab === 'review'
                        ? 'Nothing needs review — every tag is confirmed!'
                        : 'No questions match your current search and filters.'}
                    </td>
                  </tr>
                ) : (
                  questions.map((q) => {
                    const rawQImgs = (q.question_images && q.question_images.length > 0 ? q.question_images : q.image_refs || []);
                    const cleanQImgs = rawQImgs.filter(x => !isPlaceholderIcon(x));
                    const cleanAnsImgs = (q.answer_images || []).filter(x => !isPlaceholderIcon(x));
                    const hasVideoClue = Boolean(
                      ((q.video_refs && q.video_refs.length > 0 && !q.video_refs.some(r => r.toLowerCase().includes('timer') || q.question_format === 'ARRANGE_ORDER')) ||
                       (q.question_videos && q.question_videos.length > 0 && !q.question_videos.some(r => r.toLowerCase().includes('timer') || q.question_format === 'ARRANGE_ORDER')) ||
                       (q.raw_media_refs && q.raw_media_refs.some(r => (r.endsWith('.mp4') || r.endsWith('.webm') || r.endsWith('.mov')) && !r.toLowerCase().includes('timer') && q.question_format !== 'ARRANGE_ORDER')))
                    );

                    return (
                      <tr key={q.id} className="hover:bg-slate-50/70 transition-colors group">
                        <td className="py-3.5 px-4">
                          {/* Duplicate Alert Banner */}
                          {q.duplicate_status === 'POSSIBLE_DUPLICATE' && (
                            <div className="mb-2 flex items-center justify-between rounded-md bg-amber-50 border border-amber-200 px-2.5 py-1.5 text-[11.5px] text-amber-800">
                              <span className="flex items-center gap-1.5 font-semibold">
                                <AlertTriangle className="h-3.5 w-3.5 text-amber-600" />
                                Possible Duplicate ({Math.round((q.duplicate_similarity || 0.92) * 100)}% Match)
                              </span>
                              <button
                                type="button"
                                onClick={() => setSelectedDuplicateForReview(q)}
                                className="rounded bg-amber-600 px-2 py-0.5 font-semibold text-white hover:bg-amber-700 transition-colors text-[11px] cursor-pointer"
                              >
                                Review Match
                              </button>
                            </div>
                          )}

                          <div className="flex items-start gap-1.5">
                            {q.question_label && (
                              <span className="mt-0.5 shrink-0 rounded bg-slate-100 border border-slate-200 px-1.5 py-0.5 text-[10.5px] font-bold text-slate-600">
                                {q.question_label}
                              </span>
                            )}
                            {q.question_format && (
                              <span
                                className={`mt-0.5 shrink-0 rounded-full border px-2 py-0.5 text-[10.5px] font-bold ${
                                  q.question_format === 'CONNECT_4' || q.question_format === 'CONNECT'
                                    ? 'bg-blue-100 border-blue-200 text-blue-700'
                                    : q.question_format === 'STEPPED_CLUE' || q.question_format === 'THREE_CLUE'
                                    ? 'bg-amber-100 border-amber-200 text-amber-700'
                                    : q.question_format === 'ARRANGE_ORDER'
                                    ? 'bg-purple-100 border-purple-200 text-purple-700'
                                    : q.question_format === 'BUZZER'
                                    ? 'bg-rose-50 border-rose-200 text-rose-700'
                                    : q.question_format === 'VIDEO_CLUE'
                                    ? 'bg-purple-50 border-purple-200 text-purple-700'
                                    : q.question_format === 'AUDIO_CLUE'
                                    ? 'bg-emerald-50 border-emerald-200 text-emerald-700'
                                    : 'bg-slate-100 border-slate-200 text-slate-700'
                                }`}
                                title={`Format: ${q.question_format}`}
                              >
                                {q.question_format === 'CONNECT_4' || q.question_format === 'CONNECT'
                                  ? 'Connect 4'
                                  : q.question_format === 'STEPPED_CLUE' || q.question_format === 'THREE_CLUE'
                                  ? 'Stepped Clue'
                                  : q.question_format === 'ARRANGE_ORDER'
                                  ? 'Arrange'
                                  : q.question_format === 'BUZZER'
                                  ? 'Buzzer'
                                  : q.question_format === 'VIDEO_CLUE'
                                  ? 'Video Clue'
                                  : q.question_format === 'AUDIO_CLUE'
                                  ? 'Audio Clue'
                                  : q.question_format === 'VISUAL_CLUE'
                                  ? 'Visual Clue'
                                  : 'Direct QA'}
                              </span>
                            )}
                            <div className="flex-1 min-w-0">
                              <QuestionFormatDisplay
                                q={q}
                                getImageSrc={getImageSrc}
                                setPreviewImage={setPreviewImage}
                                handleImgError={handleImgError}
                              />
                            </div>
                            {q.star_marked && (
                              <span className="mt-0.5 inline-flex shrink-0 items-center gap-0.5 rounded bg-amber-50 border border-amber-200 px-1.5 py-0.5 text-[10.5px] font-bold text-amber-700">
                                <Star className="h-3 w-3 fill-amber-400 text-amber-500" />Star
                              </span>
                            )}
                          </div>

                          {/* Video Clue Prominent Button */}
                          {hasVideoClue && (
                            <div className="mt-2.5 flex items-center gap-2">
                              <button
                                type="button"
                                onClick={() => setSelectedQuestionForMedia(q)}
                                className="inline-flex items-center gap-2 rounded-lg bg-gradient-to-r from-violet-600 to-indigo-600 px-3 py-1.5 text-[12px] font-bold text-white shadow-xs hover:from-violet-700 hover:to-indigo-700 hover:shadow transition-all cursor-pointer group"
                                title="Watch and hear embedded video clue"
                              >
                                <div className="flex h-5 w-5 items-center justify-center rounded-full bg-white/20 group-hover:scale-110 transition-transform">
                                  <Play className="h-3 w-3 fill-white text-white ml-0.5" />
                                </div>
                                <span>Watch Video Clue</span>
                              </button>
                            </div>
                          )}

                          {/* Clue and Answer Images Thumbnails (excluding placeholder camera icons) */}
                          {(cleanQImgs.length > 0 || cleanAnsImgs.length > 0) && (
                            <div className="mt-2 flex flex-wrap items-center gap-1.5">
                              {cleanQImgs.slice(0, 3).map((imgUrl, i) => (
                                <button
                                  key={i}
                                  type="button"
                                  onClick={() => setPreviewImage(imgUrl)}
                                  className="relative rounded-md overflow-hidden border border-slate-200 hover:border-blue-400 bg-white transition-all cursor-pointer group shadow-xs"
                                  title="Question image: click to view"
                                >
                                  <img
                                    src={getImageSrc(imgUrl)}
                                    onError={() => handleImgError(imgUrl)}
                                    alt={`Question image ${i + 1}`}
                                    className="h-9 w-13 object-cover group-hover:scale-105 transition-transform"
                                  />
                                  <span className="absolute inset-x-0 bottom-0 bg-sky-700/80 text-center text-[8px] font-bold uppercase leading-3 text-white">Question</span>
                                </button>
                              ))}
                              {cleanAnsImgs.slice(0, 2).map((imgUrl, i) => (
                                <button
                                  key={`ans-${i}`}
                                  type="button"
                                  onClick={() => setPreviewImage(imgUrl)}
                                  className="relative rounded-md overflow-hidden border border-emerald-300 ring-1 ring-emerald-400/50 hover:border-emerald-500 bg-white transition-all cursor-pointer group shadow-xs"
                                  title="Answer image: click to view"
                                >
                                  <img
                                    src={getImageSrc(imgUrl)}
                                    onError={() => handleImgError(imgUrl)}
                                    alt={`Answer image ${i + 1}`}
                                    className="h-9 w-13 object-cover group-hover:scale-105 transition-transform"
                                  />
                                  <span className="absolute inset-x-0 bottom-0 bg-emerald-700/80 text-center text-[8px] font-bold uppercase leading-3 text-white">Answer</span>
                                </button>
                              ))}
                            </div>
                          )}

                          {/* Audio Clue Inline Player (if question has audio) */}
                          {((q.question_audio && q.question_audio.length > 0) || (q.audio_refs && q.audio_refs.length > 0)) && (
                            <div className="mt-2 flex items-center gap-2 p-1.5 rounded-lg bg-teal-50/80 border border-teal-200/80 max-w-sm">
                              <Volume2 className="h-4 w-4 text-teal-600 shrink-0 ml-1" />
                              <audio
                                controls
                                src={getImageSrc((q.question_audio && q.question_audio.length > 0 ? q.question_audio : q.audio_refs || [])[0])}
                                onError={() => handleImgError((q.question_audio && q.question_audio.length > 0 ? q.question_audio : q.audio_refs || [])[0])}
                                className="w-full h-7 text-xs accent-teal-600"
                                preload="none"
                              />
                            </div>
                          )}

                          {/* Multimodal Badges: Images, Audio, Video */}
                          <div className="mt-2 flex flex-wrap items-center gap-1.5">
                            {((cleanQImgs.length > 0) ||
                              (cleanAnsImgs.length > 0) ||
                              hasVideoClue ||
                              (q.question_audio && q.question_audio.length > 0) ||
                              (q.answer_audio && q.answer_audio.length > 0) ||
                              (q.audio_refs && q.audio_refs.length > 0) ||
                              q.visual_clues ||
                              q.audio_transcript ||
                              q.video_transcript ||
                              (q.raw_media_refs && q.raw_media_refs.length > 0)) && (
                              <button
                                type="button"
                                onClick={() => setSelectedQuestionForMedia(q)}
                                className="inline-flex items-center gap-1.5 rounded-md bg-blue-50 hover:bg-blue-100 border border-blue-200 px-2 py-0.5 text-[11px] font-bold text-blue-700 transition-colors cursor-pointer shadow-2xs"
                                title="Click to view slide images, audio, video & transcripts in a popup"
                              >
                                <ImageIcon className="h-3 w-3 text-blue-600" />
                                <span>View Media</span>
                                {cleanQImgs.length + cleanAnsImgs.length > 0 && (
                                  <span className="rounded-full bg-blue-200/80 text-blue-800 text-[10px] px-1 py-0.2 font-mono">
                                    {cleanQImgs.length + cleanAnsImgs.length}
                                  </span>
                                )}
                                {((q.question_audio && q.question_audio.length > 0) || (q.audio_refs && q.audio_refs.length > 0) || q.audio_transcript) && (
                                  <Volume2 className="h-2.5 w-2.5 text-teal-600" />
                                )}
                                {hasVideoClue && <Video className="h-2.5 w-2.5 text-violet-600" />}
                              </button>
                            )}

                            {hasVideoClue && (
                              <button
                                type="button"
                                onClick={() => setSelectedQuestionForMedia(q)}
                                className="inline-flex items-center gap-1 rounded bg-violet-50 hover:bg-violet-100 border border-violet-200 px-1.5 py-0.5 text-[10.5px] font-semibold text-violet-700 cursor-pointer"
                                title="Click to watch embedded video clue"
                              >
                                <Video className="h-2.5 w-2.5" />
                                Video Clue
                              </button>
                            )}

                            {((q.question_audio && q.question_audio.length > 0) || (q.audio_refs && q.audio_refs.length > 0)) && (
                              <button
                                type="button"
                                onClick={() => setSelectedQuestionForMedia(q)}
                                className="inline-flex items-center gap-1 rounded bg-teal-50 hover:bg-teal-100 border border-teal-200 px-1.5 py-0.5 text-[10.5px] font-semibold text-teal-700 cursor-pointer"
                                title="Click to play audio clue"
                              >
                                <Volume2 className="h-2.5 w-2.5" />
                                Audio Clue
                              </button>
                            )}
                            {q.answer_audio && q.answer_audio.length > 0 && (
                              <button
                                type="button"
                                onClick={() => setSelectedQuestionForMedia(q)}
                                className="inline-flex items-center gap-1 rounded bg-emerald-50 hover:bg-emerald-100 border border-emerald-200 px-1.5 py-0.5 text-[10.5px] font-semibold text-emerald-700 cursor-pointer"
                                title="Click to play answer reveal audio"
                              >
                                <Volume2 className="h-2.5 w-2.5" />
                                Reveal Audio
                              </button>
                            )}

                            {cleanQImgs.length + cleanAnsImgs.length > 0 && (
                              <button
                                type="button"
                                onClick={() => setSelectedQuestionForMedia(q)}
                                className="inline-flex items-center gap-1 rounded bg-sky-50 hover:bg-sky-100 border border-sky-200 px-1.5 py-0.5 text-[10.5px] font-semibold text-sky-700 cursor-pointer"
                                title="Click to preview slide images"
                              >
                                <ImageIcon className="h-2.5 w-2.5" />
                                {cleanQImgs.length + cleanAnsImgs.length} Images
                              </button>
                            )}
                          {q.audio_transcript && (
                            <button
                              type="button"
                              onClick={() => setSelectedQuestionForMedia(q)}
                              className="inline-flex items-center gap-1 rounded bg-teal-50 hover:bg-teal-100 border border-teal-200 px-1.5 py-0.5 text-[10.5px] font-semibold text-teal-800 max-w-[200px] truncate cursor-pointer"
                              title={q.audio_transcript}
                            >
                              <Volume2 className="h-2.5 w-2.5 flex-shrink-0" />
                              <span className="truncate">{q.audio_transcript}</span>
                            </button>
                          )}
                          {Boolean(
                            q.video_transcript ||
                            q.question_format === 'VIDEO_CLUE' ||
                            q.question_type === 'VIDEO_CLUE' ||
                            ((q.question_text || '').toLowerCase().match(/\b(video|clip|watch)\b/)) ||
                            ((q as any).video_refs && (q as any).video_refs.some((r: string) => !r.toLowerCase().includes('timer') && !r.toLowerCase().includes('1min') && !r.toLowerCase().includes('countdown')))
                          ) && (
                            <button
                              type="button"
                              onClick={() => setSelectedQuestionForMedia(q)}
                              className="inline-flex items-center gap-1 rounded bg-violet-100 hover:bg-violet-200 border border-violet-300 px-1.5 py-0.5 text-[10.5px] font-bold text-violet-900 max-w-[200px] truncate cursor-pointer shadow-2xs"
                              title={q.video_transcript || "Tournament Video Clue"}
                            >
                              <Video className="h-3 w-3 text-violet-700 flex-shrink-0" />
                              <span className="truncate">{q.video_transcript ? `Video: ${q.video_transcript}` : 'Video Clue'}</span>
                            </button>
                          )}
                          {(q.repeated_count ?? 0) > 0 && (
                            <button
                              type="button"
                              onClick={() => setSelectedQuestionForTags(q)}
                              className="rounded bg-emerald-50 hover:bg-emerald-100 border border-emerald-200 px-1.5 py-0.5 text-[10.5px] font-semibold text-emerald-700 flex items-center gap-1 cursor-pointer"
                              title={(q.repeated || []).map((r) => r.label).join('\n')}
                            >
                              <Layers className="h-2.5 w-2.5" />
                              Repeated ×{q.repeated_count}
                            </button>
                          )}
                        </div>
                      </td>

                      {/* Topics */}
                      <td className="py-3.5 px-4 align-top">
                        <div className="flex flex-col gap-2">
                          {(q.topic_paths && q.topic_paths.length > 0) ? (
                            <>
                              {q.topic_paths.slice(0, 3).map((p, pi) => (
                                <div key={pi} className="flex flex-col gap-1">
                                  <div className="flex flex-wrap items-center gap-1 text-[11px]">
                                    <span className="rounded-md bg-amber-50 border border-amber-200 px-2 py-0.5 font-semibold text-amber-800">{p.l1}</span>
                                    {p.l2 && <><span className="text-slate-300">›</span><span className="font-medium text-slate-600">{p.l2}</span></>}
                                  </div>
                                  {p.keywords && p.keywords.length > 0 && (
                                    <div className="flex flex-wrap gap-1">
                                      {p.keywords.slice(0, 5).map((k) => (
                                        <button
                                          key={k}
                                          type="button"
                                          onClick={() => setTagFilter(tagFilter.toLowerCase() === k.toLowerCase() ? '' : k)}
                                          className={`rounded px-1.5 py-0.5 text-[10.5px] font-medium cursor-pointer ${tagFilter.toLowerCase() === k.toLowerCase() ? 'bg-indigo-600 text-white' : 'bg-slate-100 text-slate-600 hover:bg-slate-200'}`}
                                          title={`Filter by ${k}`}
                                        >
                                          {k}
                                        </button>
                                      ))}
                                    </div>
                                  )}
                                </div>
                              ))}
                              {q.topic_paths.length > 3 && <span className="text-[11px] text-slate-400">+{q.topic_paths.length - 3} more</span>}
                            </>
                          ) : (
                            <>
                              <span className="rounded-md bg-amber-50 border border-amber-200 px-2 py-0.5 text-[11px] font-semibold text-amber-800 w-fit">{q.topic}</span>
                              {q.subtopic && !q.subtopic.toLowerCase().includes('round') && !q.subtopic.toLowerCase().includes('closing bell') && !q.subtopic.toLowerCase().includes('market indicators') && (
                                <span className="text-[11px] text-slate-500 font-medium">{q.subtopic.replace(/^[–—\-:\s]+/, '')}</span>
                              )}
                            </>
                          )}
                        </div>
                      </td>

                      <td className="py-3.5 px-4 text-right align-top">
                        <div className="flex items-center justify-end gap-3">
                          {q.duplicate_status === 'POSSIBLE_DUPLICATE' ? (
                            <button
                              onClick={() => setSelectedDuplicateForReview(q)}
                              className="inline-flex items-center gap-1 rounded bg-amber-600 px-2 py-1 text-[11px] font-bold text-white hover:bg-amber-700 cursor-pointer"
                            >
                              <span>Resolve</span>
                            </button>
                          ) : (
                            <>
                              {activeTab === 'review' && (
                                <button
                                  disabled={resolvingId === q.id}
                                  onClick={() => handleAcceptReview(q.id)}
                                  className="inline-flex items-center gap-1 rounded bg-emerald-600 px-2 py-1 text-[11px] font-bold text-white hover:bg-emerald-700 cursor-pointer disabled:opacity-50"
                                  title="Confirm the AI tag as-is"
                                >
                                  <CheckCircle className="h-3 w-3" />
                                  <span>Accept</span>
                                </button>
                              )}
                              <button
                                onClick={() => setSelectedQuestionForTags(q)}
                                className="inline-flex items-center gap-1 text-[12px] font-semibold text-indigo-600 hover:text-indigo-700 cursor-pointer"
                                title={activeTab === 'review' ? 'Correct the tag (confirms a human label)' : 'View and edit every tag on this question'}
                              >
                                <Tag className="h-3 w-3" />
                                <span>{activeTab === 'review' ? 'Correct' : 'Edit tags'}</span>
                              </button>
                              <button
                                onClick={() => handleViewSlide(q)}
                                className="inline-flex items-center gap-1 text-[12px] font-semibold text-blue-600 hover:text-blue-700 cursor-pointer"
                              >
                                <span>View slide</span>
                                <ExternalLink className="h-3 w-3" />
                              </button>
                            </>
                          )}
                        </div>
                      </td>
                    </tr>
                  );
                })
                )}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* Duplicate Review & Resolution Modal */}
      {selectedDuplicateForReview && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/50 backdrop-blur-xs p-4">
          <div className="w-full max-w-3xl rounded-xl bg-white shadow-xl border border-slate-200 overflow-hidden flex flex-col max-h-[90vh]">
            <div className="flex items-center justify-between border-b border-slate-100 px-6 py-4 bg-amber-50/50">
              <div className="flex items-center gap-2">
                <AlertTriangle className="h-5 w-5 text-amber-600" />
                <h3 className="text-[16px] font-bold text-slate-900">
                  Duplicate Candidate Review ({Math.round((selectedDuplicateForReview.duplicate_similarity || 0.92) * 100)}% Match)
                </h3>
              </div>
              <button
                type="button"
                onClick={() => setSelectedDuplicateForReview(null)}
                className="text-slate-400 hover:text-slate-600 p-1 rounded-md"
              >
                <X className="h-5 w-5" />
              </button>
            </div>

            <div className="p-6 space-y-6 overflow-y-auto">
              <p className="text-[13px] text-slate-600 leading-relaxed">
                This newly ingested question has a cosine similarity score of{' '}
                <span className="font-bold text-amber-700">
                  {(selectedDuplicateForReview.duplicate_similarity || 0.92).toFixed(3)}
                </span>{' '}
                against an existing question in your Knowledge Base. Review both versions below:
              </p>

              <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                {/* Candidate (New) Question */}
                <div className="rounded-lg border border-amber-200 bg-amber-50/20 p-4 space-y-3">
                  <div className="flex items-center justify-between border-b border-amber-100 pb-2">
                    <span className="text-[11px] font-bold uppercase tracking-wider text-amber-800">
                      Newly Ingested Candidate
                    </span>
                    <span className="text-[11px] text-slate-500 font-medium">
                      {selectedDuplicateForReview.document_title || 'Current Deck'}
                    </span>
                  </div>

                  <div>
                    <span className="text-[11px] font-semibold text-slate-500 uppercase">Question</span>
                    <p className="text-[13.5px] font-medium text-slate-900 mt-0.5">
                      {selectedDuplicateForReview.question_text}
                    </p>
                  </div>

                  <div>
                    <span className="text-[11px] font-semibold text-slate-500 uppercase">Answer</span>
                    <p className="text-[13.5px] font-bold text-slate-800 mt-0.5">
                      {selectedDuplicateForReview.answer}
                    </p>
                  </div>

                  {selectedDuplicateForReview.audio_transcript && (
                    <div className="rounded bg-white/80 p-2 border border-amber-100 text-[11.5px]">
                      <span className="font-bold text-slate-700">Audio transcript:</span>{' '}
                      {selectedDuplicateForReview.audio_transcript}
                    </div>
                  )}

                  {selectedDuplicateForReview.video_transcript && (
                    <div className="rounded bg-white/80 p-2 border border-amber-100 text-[11.5px]">
                      <span className="font-bold text-slate-700">Video transcript:</span>{' '}
                      {selectedDuplicateForReview.video_transcript}
                    </div>
                  )}
                </div>

                {/* Matched Original Question */}
                <div className="rounded-lg border border-slate-200 bg-slate-50/50 p-4 space-y-3">
                  <div className="flex items-center justify-between border-b border-slate-200 pb-2">
                    <span className="text-[11px] font-bold uppercase tracking-wider text-slate-600">
                      Existing Knowledge Base Match
                    </span>
                    <span className="text-[11px] font-mono text-slate-400">
                      ID: {selectedDuplicateForReview.duplicate_of_id?.slice(0, 8) || 'Match'}
                    </span>
                  </div>

                  <div>
                    <span className="text-[11px] font-semibold text-slate-500 uppercase">Question</span>
                    <p className="text-[13.5px] font-medium text-slate-900 mt-0.5">
                      {selectedDuplicateForReview.duplicate_of_text || selectedDuplicateForReview.question_text}
                    </p>
                  </div>

                  <div>
                    <span className="text-[11px] font-semibold text-slate-500 uppercase">Answer</span>
                    <p className="text-[13.5px] font-bold text-slate-800 mt-0.5">
                      {selectedDuplicateForReview.duplicate_of_answer || selectedDuplicateForReview.answer}
                    </p>
                  </div>

                  <div className="rounded bg-white p-2 border border-slate-200 text-[11.5px] text-slate-500">
                    Already appears in repository across historical tournaments.
                  </div>
                </div>
              </div>
            </div>

            <div className="flex items-center justify-end gap-3 border-t border-slate-100 bg-slate-50 px-6 py-4">
              <button
                type="button"
                onClick={() => setSelectedDuplicateForReview(null)}
                className="rounded-lg border border-slate-300 px-4 py-2 text-[13px] font-medium text-slate-700 hover:bg-white transition-colors cursor-pointer"
              >
                Cancel
              </button>
              <button
                type="button"
                disabled={resolvingId === selectedDuplicateForReview.id}
                onClick={() => handleResolveDuplicate(selectedDuplicateForReview.id, 'DISMISS_UNIQUE')}
                className="rounded-lg border border-emerald-300 bg-emerald-50 px-4 py-2 text-[13px] font-semibold text-emerald-800 hover:bg-emerald-100 transition-colors cursor-pointer flex items-center gap-1.5"
              >
                <CheckCircle className="h-4 w-4 text-emerald-600" />
                <span>Dismiss as Unique</span>
              </button>
              <button
                type="button"
                disabled={resolvingId === selectedDuplicateForReview.id}
                onClick={() => handleResolveDuplicate(selectedDuplicateForReview.id, 'CONFIRM_DUPLICATE')}
                className="rounded-lg bg-blue-600 px-4 py-2 text-[13px] font-semibold text-white hover:bg-blue-700 transition-colors cursor-pointer flex items-center gap-1.5"
              >
                <Copy className="h-4 w-4" />
                <span>Confirm Duplicate (Link Provenance)</span>
              </button>
            </div>
          </div>
        </div>
      )}

      {selectedSlide && (
        <SlideViewerModal
          isOpen={!!selectedSlide}
          onClose={() => setSelectedSlide(null)}
          slide={selectedSlide}
        />
      )}

      {selectedQuestionForTags && (
        <TagManagerModal
          isOpen={!!selectedQuestionForTags}
          onClose={() => setSelectedQuestionForTags(null)}
          question={selectedQuestionForTags}
          onSaved={handleQuestionTagsSaved}
          onFilterDeck={(id) => setSelectedDeckId(id)}
          availableTopics={topicsList.map((t) => t.topic)}
        />
      )}

      {selectedQuestionForMedia && (
        <MediaViewerModal
          question={selectedQuestionForMedia}
          onClose={() => setSelectedQuestionForMedia(null)}
        />
      )}

      {/* Lightbox Image Zoom Modal */}
      {previewImage && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/80 backdrop-blur-sm p-4 cursor-pointer"
          onClick={() => setPreviewImage(null)}
        >
          <div
            className="relative max-w-4xl max-h-[90vh] bg-white rounded-xl shadow-2xl p-2 border border-slate-700 overflow-hidden cursor-default"
            onClick={(e) => e.stopPropagation()}
          >
            <button
              onClick={() => setPreviewImage(null)}
              className="absolute top-3 right-3 z-10 rounded-full bg-slate-900/70 p-1.5 text-white hover:bg-slate-900 transition-colors cursor-pointer"
            >
              <X className="h-5 w-5" />
            </button>
            <img
              src={getImageSrc(previewImage)}
              onError={() => previewImage && handleImgError(previewImage)}
              alt="Vault Visual Asset"
              className="max-h-[82vh] w-auto object-contain rounded-lg mx-auto"
            />
          </div>
        </div>
      )}
    </div>
  );
}

export default function KnowledgeBasePage() {
  return (
    <Suspense fallback={<div className="p-8 text-center text-slate-400">Loading...</div>}>
      <KnowledgeBaseContent />
    </Suspense>
  );
}
