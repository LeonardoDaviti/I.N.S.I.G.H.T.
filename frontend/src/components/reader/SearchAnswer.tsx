import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';

import { questionsApi, type QuestionView } from '../../services/questions';

const POLL_MS = 4000;

/** Ask your posts: the search's words as a question, answered by the worker only from the reader's own posts, every
 *  sentence with superscripts to the posts it rests on ("Not in your sources" otherwise). Polls until answered. */
export default function SearchAnswer({ q }: { q: string }) {
  const [on, setOn] = useState(false);
  const [view, setView] = useState<QuestionView | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [asking, setAsking] = useState(false);

  useEffect(() => {
    let live = true;
    questionsApi.on().then((r) => { if (live) setOn(r.on); }).catch(() => { if (live) setOn(false); });
    return () => { live = false; };
  }, []);

  useEffect(() => { setView(null); setError(null); }, [q]);

  useEffect(() => {
    if (!view || view.status !== 'waiting') return undefined;
    const t = window.setTimeout(() => {
      questionsApi.get(view.id).then(setView).catch(() => setError('Could not read the answer'));
    }, POLL_MS);
    return () => window.clearTimeout(t);
  }, [view]);

  if (!on) return null;

  const ask = () => {
    setAsking(true);
    setError(null);
    questionsApi.ask(q).then(setView).catch(() => setError('Could not ask')).finally(() => setAsking(false));
  };

  return (
    <section aria-label="Answer from your posts" data-search-answer className="mb-3 rounded-md border border-line px-3 py-2 sm:px-4">
      {!view ? (
        <button type="button" onClick={ask} disabled={asking} className="text-[0.8125rem] text-fg-2 hover:text-fg">
          {asking ? 'Asking…' : 'Ask your posts this question'}
        </button>
      ) : view.status === 'waiting' ? (
        <p className="text-[0.8125rem] text-fg-3">Reading your posts… (the worker answers in a minute or two)</p>
      ) : view.status === 'failed' ? (
        <p className="text-[0.8125rem] text-fg-3">The worker could not answer this question.</p>
      ) : view.not_in_sources ? (
        <p className="text-[0.8125rem] text-fg-2">Not in your sources.</p>
      ) : (
        <>
          <p dir="auto" className="text-fg">
            {view.sentences.map((s, i) => (
              <span key={i}>
                {s.text}
                {s.cites.map((n) => (
                  <sup key={n} className="ml-0.5 text-fg-3">
                    <a href={`#answer-post-${n}`}>{n}</a>
                  </sup>
                ))}{' '}
              </span>
            ))}
          </p>
          <ol className="mt-2 flex flex-col gap-0.5 text-[0.8125rem] text-fg-2">
            {view.posts.map((p) => (
              <li key={p.n} id={`answer-post-${p.n}`} dir="auto">
                {p.n}. <Link to={`/posts/${p.id}`} className="hover:text-fg">{p.title ?? '(no title)'}</Link>
                {p.source ? ` · ${p.source}` : ''}{p.at ? ` · ${p.at.slice(0, 10)}` : ''}
              </li>
            ))}
          </ol>
        </>
      )}
      {error ? <p className="text-[0.8125rem] text-fg-3">{error}</p> : null}
    </section>
  );
}
