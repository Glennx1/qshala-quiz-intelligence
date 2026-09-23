'use client';

import { useState, useEffect } from 'react';
import { X, Tag, Plus, Check, Loader2, Sparkles, AlertCircle } from 'lucide-react';
import { HistoricalQuestion } from '../lib/types';
import { api } from '../lib/api';

interface Props {
  isOpen: boolean;
  onClose: () => void;
  question: HistoricalQuestion | null;
  onSaved: (updated: HistoricalQuestion) => void;
  availableTopics?: string[];
}

export default function TagManagerModal({
  isOpen,
  onClose,
  question,
  onSaved,
  availableTopics = [],
}: Props) {
  const [tags, setTags] = useState<string[]>([]);
  const [primaryTopic, setPrimaryTopic] = useState('');
  const [topics, setTopics] = useState<string[]>([]);
  const [newTagInput, setNewTagInput] = useState('');
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (question) {
      setTags(question.tags ? [...question.tags] : []);
      setPrimaryTopic(question.topic || '');
      setTopics(question.topics ? [...question.topics] : [question.topic || '']);
      setNewTagInput('');
      setError(null);
    }
  }, [question, isOpen]);

  if (!isOpen || !question) return null;

  const handleAddTag = () => {
    const clean = newTagInput.trim().replace(/^#+/, '').trim();
    if (!clean) return;

    if (!tags.some((t) => t.toLowerCase() === clean.toLowerCase())) {
      setTags([...tags, clean]);
    }
    setNewTagInput('');
  };

  const handleKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === 'Enter' || e.key === ',') {
      e.preventDefault();
      handleAddTag();
    }
  };

  const handleRemoveTag = (tagToRemove: string) => {
    setTags(tags.filter((t) => t.toLowerCase() !== tagToRemove.toLowerCase()));
  };

  const handleToggleTopic = (topicName: string) => {
    if (topics.includes(topicName)) {
      if (topics.length > 1) {
        setTopics(topics.filter((t) => t !== topicName));
      }
    } else {
      setTopics([...topics, topicName]);
    }
  };

  const handleSave = async () => {
    setSaving(true);
    setError(null);
    try {
      const updated = await api.updateQuestionTags(
        question.id,
        tags,
        topics,
        primaryTopic
      );
      onSaved(updated);
      onClose();
    } catch (err: any) {
      console.error('Failed to update tags:', err);
      setError(err?.message || 'Failed to save tags. Please try again.');
    } finally {
      setSaving(false);
    }
  };

  // Quick suggestions extracted from question text entities
  const words = question.question_text
    .split(/\s+/)
    .map((w) => w.replace(/[^a-zA-Z0-9]/g, ''))
    .filter((w) => w.length > 3 && w[0] === w[0].toUpperCase());
  const suggestions = Array.from(new Set(words)).filter(
    (w) => !tags.some((t) => t.toLowerCase() === w.toLowerCase())
  ).slice(0, 5);

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/40 p-4 backdrop-blur-sm animate-in fade-in">
      <div className="relative w-full max-w-xl overflow-hidden rounded-xl border border-slate-200 bg-white shadow-2xl">
        {/* Header */}
        <div className="flex items-center justify-between border-b border-slate-100 px-6 py-4">
          <div className="flex items-center gap-3">
            <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-indigo-50 text-indigo-600">
              <Tag className="h-4 w-4" />
            </div>
            <div>
              <h3 className="text-[16px] font-bold text-slate-900">
                Manage Question Tags & Topics
              </h3>
              <p className="text-[12px] text-slate-500 font-normal">
                Curate classification and discoverability for this question
              </p>
            </div>
          </div>

          <button
            onClick={onClose}
            className="rounded-lg p-1.5 text-slate-400 hover:bg-slate-100 hover:text-slate-700 transition-colors cursor-pointer"
          >
            <X className="h-4 w-4" />
          </button>
        </div>

        {/* Content Body */}
        <div className="max-h-[70vh] overflow-y-auto p-6 space-y-5 text-[13px]">
          {/* Question Context Preview */}
          <div className="rounded-lg border border-slate-200/70 bg-slate-50/70 p-3.5 space-y-1.5">
            <span className="text-[11px] font-bold uppercase tracking-wider text-slate-500">
              Question Context
            </span>
            <p className="font-semibold text-slate-800 leading-snug">
              {question.question_text}
            </p>
            <p className="text-[12px] text-slate-600">
              <span className="font-semibold text-slate-700">Answer:</span>{' '}
              <span className="font-bold text-emerald-700">{question.answer}</span>
            </p>
          </div>

          {error && (
            <div className="flex items-center gap-2 rounded-lg bg-red-50 border border-red-200 p-3 text-[12.5px] text-red-700">
              <AlertCircle className="h-4 w-4 shrink-0" />
              <span>{error}</span>
            </div>
          )}

          {/* Current Tags Section */}
          <div className="space-y-2">
            <div className="flex items-center justify-between">
              <label className="text-[12px] font-bold uppercase tracking-wider text-slate-700">
                Active Tags ({tags.length})
              </label>
              <span className="text-[11px] text-slate-400">Click &times; to remove</span>
            </div>

            {tags.length === 0 ? (
              <p className="text-[12px] text-slate-400 italic py-1">
                No tags assigned yet. Add one below!
              </p>
            ) : (
              <div className="flex flex-wrap gap-1.5 min-h-[36px] p-2 rounded-lg border border-slate-200 bg-slate-50/30">
                {tags.map((tag) => (
                  <span
                    key={tag}
                    className="inline-flex items-center gap-1 rounded-md bg-indigo-50 border border-indigo-200/80 px-2 py-1 text-[12px] font-medium text-indigo-700 group hover:bg-indigo-100 transition-colors"
                  >
                    <span>#{tag}</span>
                    <button
                      type="button"
                      onClick={() => handleRemoveTag(tag)}
                      className="ml-0.5 text-indigo-400 hover:text-indigo-800 focus:outline-none cursor-pointer"
                      title={`Remove tag #${tag}`}
                    >
                      <X className="h-3 w-3" />
                    </button>
                  </span>
                ))}
              </div>
            )}
          </div>

          {/* Add New Tag Input */}
          <div className="space-y-1.5">
            <label className="text-[12px] font-bold uppercase tracking-wider text-slate-700">
              Add New Tag
            </label>
            <div className="flex items-center gap-2">
              <div className="relative flex-1">
                <span className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-400 font-bold text-[13px]">
                  #
                </span>
                <input
                  type="text"
                  value={newTagInput}
                  onChange={(e) => setNewTagInput(e.target.value)}
                  onKeyDown={handleKeyDown}
                  placeholder="e.g. Renaissance, Nobel Prize, Astronomy (Press Enter)"
                  className="w-full rounded-lg border border-slate-200 bg-white pl-7 pr-3 py-2 text-[13px] text-slate-800 placeholder-slate-400 focus:border-indigo-500 focus:outline-none focus:ring-1 focus:ring-indigo-500"
                />
              </div>
              <button
                type="button"
                onClick={handleAddTag}
                disabled={!newTagInput.trim()}
                className="inline-flex items-center gap-1 rounded-lg bg-indigo-600 px-3.5 py-2 text-[12.5px] font-semibold text-white hover:bg-indigo-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors cursor-pointer shrink-0"
              >
                <Plus className="h-3.5 w-3.5" />
                <span>Add</span>
              </button>
            </div>
          </div>

          {/* Quick Suggestions */}
          {suggestions.length > 0 && (
            <div className="space-y-1.5">
              <span className="text-[11px] font-semibold uppercase tracking-wider text-slate-400 flex items-center gap-1">
                <Sparkles className="h-3 w-3 text-amber-500" />
                Suggested from Question Text
              </span>
              <div className="flex flex-wrap gap-1.5">
                {suggestions.map((sug) => (
                  <button
                    key={sug}
                    type="button"
                    onClick={() => {
                      if (!tags.some((t) => t.toLowerCase() === sug.toLowerCase())) {
                        setTags([...tags, sug]);
                      }
                    }}
                    className="inline-flex items-center gap-1 rounded border border-dashed border-slate-300 bg-white px-2 py-0.5 text-[11px] font-medium text-slate-600 hover:border-indigo-400 hover:text-indigo-600 transition-colors cursor-pointer"
                  >
                    <Plus className="h-2.5 w-2.5" />
                    <span>#{sug}</span>
                  </button>
                ))}
              </div>
            </div>
          )}

          {/* Primary Topic Selector */}
          <div className="space-y-1.5 pt-2 border-t border-slate-100">
            <label className="text-[12px] font-bold uppercase tracking-wider text-slate-700">
              Primary Topic
            </label>
            <select
              value={primaryTopic}
              onChange={(e) => {
                setPrimaryTopic(e.target.value);
                if (!topics.includes(e.target.value)) {
                  setTopics([e.target.value, ...topics]);
                }
              }}
              className="w-full rounded-lg border border-slate-200 bg-white px-3 py-2 text-[13px] text-slate-800 focus:border-indigo-500 focus:outline-none cursor-pointer"
            >
              {availableTopics.length > 0 ? (
                availableTopics.map((top) => (
                  <option key={top} value={top}>
                    {top}
                  </option>
                ))
              ) : (
                <option value={question.topic}>{question.topic}</option>
              )}
            </select>
          </div>

          {/* Multi-Topics (Secondary Categories) */}
          {availableTopics.length > 0 && (
            <div className="space-y-1.5">
              <label className="text-[12px] font-bold uppercase tracking-wider text-slate-700">
                Tournament Categories (Multi-Topic)
              </label>
              <div className="flex flex-wrap gap-1.5">
                {availableTopics.map((top) => {
                  const isSelected = topics.includes(top);
                  return (
                    <button
                      key={top}
                      type="button"
                      onClick={() => handleToggleTopic(top)}
                      className={`rounded-md px-2.5 py-1 text-[11px] font-medium border transition-colors cursor-pointer ${
                        isSelected
                          ? 'bg-amber-50 border-amber-200 text-amber-900 font-semibold'
                          : 'bg-white border-slate-200 text-slate-600 hover:bg-slate-50'
                      }`}
                    >
                      {top} {isSelected && '✓'}
                    </button>
                  );
                })}
              </div>
            </div>
          )}
        </div>

        {/* Footer */}
        <div className="flex items-center justify-end gap-2.5 border-t border-slate-100 bg-slate-50/60 px-6 py-3.5">
          <button
            type="button"
            onClick={onClose}
            disabled={saving}
            className="rounded-lg border border-slate-200 bg-white px-4 py-2 text-[13px] font-semibold text-slate-700 hover:bg-slate-50 transition-colors cursor-pointer"
          >
            Cancel
          </button>
          <button
            type="button"
            onClick={handleSave}
            disabled={saving}
            className="inline-flex items-center gap-1.5 rounded-lg bg-indigo-600 px-4 py-2 text-[13px] font-semibold text-white hover:bg-indigo-700 disabled:opacity-50 transition-colors cursor-pointer"
          >
            {saving ? (
              <>
                <Loader2 className="h-3.5 w-3.5 animate-spin" />
                <span>Saving...</span>
              </>
            ) : (
              <>
                <Check className="h-3.5 w-3.5" />
                <span>Save Changes</span>
              </>
            )}
          </button>
        </div>
      </div>
    </div>
  );
}
