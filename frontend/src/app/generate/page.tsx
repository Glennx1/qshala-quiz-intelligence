'use client';

import { useEffect, useRef, useState } from 'react';
import { useRouter } from 'next/navigation';
import { ArrowUp, Check, Eye, EyeOff, Lock, RefreshCw, Trash2, Unlock } from 'lucide-react';
import { getApiBase, resolveMediaUrl } from '../../lib/api';

type DraftQ = {
  id: string;
  question_text: string;
  answer: string;
  topic_l1?: string | null;
  subtopic_l2?: string | null;
  difficulty?: string | null;
  image_dependent?: boolean;
  question_images?: string[];
  answer_images?: string[];
  image_refs?: string[];
};
type Draft = { message: string; questions: DraftQ[]; bank_size: number; brief: { count: number } };

const GREETINGS = [
  'Who are we stumping today?',
  'Ready to ruin someone\u2019s weekend?',
  'Pick a topic. Pick a victim.',
  'Quizmaster mode: engaged.',
  'Let\u2019s make the back row sweat.',
  'Name a theme. I\u2019ll find the trivia.',
  'Fastest finger first. What\u2019s the round?',
  'Somewhere, a team is about to lose on a tiebreaker.',
  'Your audience thinks they\u2019re clever. Prove them right or wrong.',
  'Bring snacks. I\u2019ll bring the questions.',
  'No Googling in the back, please. What\u2019s the quiz?',
  'Tell me the vibe. I\u2019ll bring the buzzer.',
];
const PLACEHOLDERS = [
  '12 tough questions on fintech for a college finals',
  'A gentle warm-up on brands and logos, no images',
  'Family quiz night: food, festivals and cricket, 15 questions',
  'Something fiendish on banking, for people who think they know money',
];
const STAGES = ['Reading your brief', 'Searching the archive', 'Weeding out repeats', 'Shaping the order', 'Writing the intro'];
const FALLBACK_STARTERS = [
  '10 evergreen questions on Indian startups',
  'A tough 15-question finals round on banking and money',
  'Warm-up quiz on brands and logos, no images',
];

async function api<T>(path: string, body?: unknown): Promise<T> {
  const res = await fetch(`${getApiBase()}${path}`, {
    method: body === undefined ? 'GET' : 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (!res.ok) throw new Error((await res.json().catch(() => ({}))).detail || `Request failed (${res.status})`);
  return res.json();
}

export default function QuizzerHome() {
  const router = useRouter();
  const [greeting, setGreeting] = useState(GREETINGS[0]);
  const [prompt, setPrompt] = useState('');
  const [ph, setPh] = useState(PLACEHOLDERS[0]);
  const [starters, setStarters] = useState<string[]>(FALLBACK_STARTERS);
  const [loading, setLoading] = useState(false);
  const [stage, setStage] = useState(0);
  const [error, setError] = useState('');
  const [draft, setDraft] = useState<Draft | null>(null);
  const [qs, setQs] = useState<DraftQ[]>([]);
  const [locked, setLocked] = useState<Set<string>>(new Set());
  const [shown, setShown] = useState<Set<string>>(new Set());
  const [saving, setSaving] = useState(false);
  const [lastPrompt, setLastPrompt] = useState('');
  const area = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- random pick must run after hydration
    setGreeting(GREETINGS[Math.floor(Math.random() * GREETINGS.length)]);
    setPh(PLACEHOLDERS[Math.floor(Math.random() * PLACEHOLDERS.length)]);
    api<{ starters: string[] }>('/prompt-quiz/starters').then((d) => setStarters(d.starters.slice(0, 4))).catch(() => {});
  }, []);

  useEffect(() => {
    if (!loading) return;
    const t = setInterval(() => setStage((s) => Math.min(s + 1, STAGES.length - 1)), 700);
    return () => clearInterval(t);
  }, [loading]);

  useEffect(() => {
    const el = area.current;
    if (el) { el.style.height = 'auto'; el.style.height = Math.min(el.scrollHeight, 220) + 'px'; }
  }, [prompt]);

  async function run(text = prompt) {
    const p = text.trim();
    if (p.length < 2 || loading) return;
    setError(''); setStage(0); setLoading(true); setDraft(null);
    try {
      const d = await api<Draft>('/prompt-quiz/draft', { prompt: p });
      setDraft(d); setQs(d.questions); setLocked(new Set()); setShown(new Set()); setLastPrompt(p);
    } catch (e) { setError(e instanceof Error ? e.message : 'Something went wrong'); }
    finally { setLoading(false); }
  }

  async function swap(id: string) {
    try {
      const nq = await api<DraftQ>('/prompt-quiz/swap', { prompt: lastPrompt, question_id: id, keep_ids: qs.map((q) => q.id) });
      setQs((cur) => cur.map((q) => (q.id === id ? nq : q)));
    } catch { setError('No other matching question found for that slot.'); }
  }

  async function save() {
    setSaving(true);
    try {
      const r = await api<{ quiz_id: string }>('/prompt-quiz/save', { prompt: lastPrompt, question_ids: qs.map((q) => q.id) });
      router.push(`/quizzes/${r.quiz_id}`);
    } catch (e) { setError(e instanceof Error ? e.message : 'Save failed'); setSaving(false); }
  }

  const toggle = (set: Set<string>, id: string, fn: (s: Set<string>) => void) => {
    const n = new Set(set);
    if (n.has(id)) n.delete(id); else n.add(id);
    fn(n);
  };

  return (
    <div className="min-h-[calc(100vh-4rem)] px-5 pb-24">
      <div className={`mx-auto max-w-2xl transition-all ${draft ? 'pt-8' : 'pt-[16vh]'}`}>
        <h1 className="text-center font-serif text-[34px] sm:text-[42px] leading-tight tracking-tight text-slate-900" style={{ fontFamily: 'var(--font-fraunces), ui-serif, Georgia, Cambria, serif' }}>
          {greeting}
        </h1>

        <div className="mt-8 rounded-3xl border border-slate-200 bg-white shadow-sm focus-within:border-slate-400 focus-within:shadow-md transition">
          <textarea
            ref={area}
            value={prompt}
            rows={2}
            onChange={(e) => setPrompt(e.target.value)}
            onKeyDown={(e) => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); run(); } }}
            placeholder={ph}
            aria-label="Describe your quiz"
            className="w-full resize-none bg-transparent px-5 pt-4 text-[16px] leading-relaxed text-slate-900 placeholder:text-slate-400 focus:outline-none"
          />
          <div className="flex flex-wrap items-center gap-2 px-3 pb-3 pt-1">
            <button onClick={() => run()} disabled={loading || prompt.trim().length < 2} aria-label="Build quiz"
              className="ml-auto flex h-10 w-9 items-center justify-center rounded-full bg-slate-900 text-white transition disabled:opacity-30 hover:bg-slate-700">
              <ArrowUp size={18} />
            </button>
          </div>
        </div>

        {!draft && !loading && (
          <ul className="mt-6 space-y-1 text-center">
            {starters.map((s) => (
              <li key={s}>
                <button onClick={() => { setPrompt(s); run(s); }} className="text-[14px] text-slate-500 underline-offset-4 hover:text-slate-900 hover:underline">
                  {s}
                </button>
              </li>
            ))}
          </ul>
        )}

        {loading && (
          <div className="mt-8 text-center text-[14px] text-slate-500" role="status" aria-live="polite">
            <span className="inline-block animate-pulse">{STAGES[stage]}…</span>
          </div>
        )}
        {error && <p className="mt-6 text-center text-[14px] text-red-600" role="alert">{error}</p>}
      </div>

      {draft && (
        <section className="mx-auto mt-10 max-w-2xl">
          <p className="text-[15px] text-slate-600">{draft.message}</p>
          <ol className="mt-4 divide-y divide-slate-100 rounded-2xl border border-slate-200 bg-white">
            {qs.map((q, i) => (
              <li key={q.id} className="group px-5 py-4">
                <div className="flex gap-4">
                  <span className="mt-0.5 w-6 shrink-0 text-right text-[13px] tabular-nums text-slate-400">{i + 1}</span>
                  <div className="min-w-0 flex-1">
                    <p className="whitespace-pre-line text-[15px] leading-relaxed text-slate-900">{q.question_text}</p>
                    
                    {/* Visual Clue Preview */}
                    {((q.question_images && q.question_images.length > 0) || (q.image_refs && q.image_refs.length > 0)) && (
                      <div className="mt-2.5 flex items-center gap-2.5">
                        <img
                          src={resolveMediaUrl((q.question_images && q.question_images[0]) || (q.image_refs && q.image_refs[0]))}
                          alt="Question Clue"
                          className="h-16 w-24 rounded-lg object-contain bg-slate-50 border border-slate-200 shadow-xs"
                          loading="lazy"
                        />
                        <span className="text-[11px] font-medium text-slate-500 bg-slate-100 px-2 py-0.5 rounded-md">
                          Visual Clue
                        </span>
                      </div>
                    )}

                    {shown.has(q.id) && (
                      <div className="mt-2.5">
                        <p className="text-[14px] font-medium text-emerald-700">{q.answer}</p>
                        {q.answer_images && q.answer_images.length > 0 && (
                          <div className="mt-2 flex items-center gap-2">
                            <img
                              src={resolveMediaUrl(q.answer_images[0])}
                              alt="Answer Diagram"
                              className="h-16 w-24 rounded-lg object-contain bg-emerald-50/50 border border-emerald-200 shadow-xs"
                              loading="lazy"
                            />
                            <span className="text-[11px] font-medium text-emerald-700 bg-emerald-50 px-2 py-0.5 rounded-md">
                              Answer Diagram
                            </span>
                          </div>
                        )}
                      </div>
                    )}
                    <p className="mt-2 text-[12px] text-slate-400">{[q.subtopic_l2 || q.topic_l1, q.difficulty !== 'Unrated' ? q.difficulty : null, q.image_dependent ? 'has image' : null].filter(Boolean).join(' · ')}</p>
                  </div>
                  <div className="flex shrink-0 items-start gap-1 text-slate-400 opacity-60 transition group-hover:opacity-100 focus-within:opacity-100">
                    <button aria-label="Show answer" onClick={() => toggle(shown, q.id, setShown)} className="p-1.5 hover:text-slate-900">{shown.has(q.id) ? <EyeOff size={16} /> : <Eye size={16} />}</button>
                    <button aria-label={locked.has(q.id) ? 'Unlock' : 'Lock'} onClick={() => toggle(locked, q.id, setLocked)} className="p-1.5 hover:text-slate-900">{locked.has(q.id) ? <Lock size={16} /> : <Unlock size={16} />}</button>
                    <button aria-label="Swap for another" disabled={locked.has(q.id)} onClick={() => swap(q.id)} className="p-1.5 hover:text-slate-900 disabled:opacity-30"><RefreshCw size={16} /></button>
                    <button aria-label="Remove" disabled={locked.has(q.id)} onClick={() => setQs((c) => c.filter((x) => x.id !== q.id))} className="p-1.5 hover:text-red-600 disabled:opacity-30"><Trash2 size={16} /></button>
                  </div>
                </div>
              </li>
            ))}
          </ol>
          {qs.length === 0 && <p className="mt-4 text-[14px] text-slate-500">Nothing left. Try a broader prompt.</p>}
          <div className="mt-5 flex items-center gap-4">
            <button onClick={save} disabled={saving || qs.length === 0}
              className="inline-flex items-center gap-2 rounded-full bg-slate-900 px-5 py-2.5 text-[14px] font-medium text-white transition hover:bg-slate-700 disabled:opacity-40">
              <Check size={16} /> {saving ? 'Saving…' : `Save ${qs.length} questions`}
            </button>
            <button onClick={() => run(lastPrompt)} className="text-[14px] text-slate-500 hover:text-slate-900">Start over</button>
          </div>
        </section>
      )}

    </div>
  );
}
