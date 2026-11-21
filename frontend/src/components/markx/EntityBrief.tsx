import { TextLink } from '../ui';
import type { MarkxBriefLine, MarkxEntityBrief } from '../../services/markx';

/** 0261: an entity's brief on its page: what it is, how it works, its results (who measured them), each line with
 * quiet superscript citations to the posts it rests on (the quote on hover), the way a track's "What changed" cites. */

const postHref = (id: string) => `/posts/${encodeURIComponent(id)}`;

function Cites({ line, brief }: { line: Pick<MarkxBriefLine, 'cites'>; brief: MarkxEntityBrief }) {
  const byN = new Map(brief.posts.map((p) => [p.n, p]));
  return (
    <>
      {line.cites.map((c) => {
        const p = byN.get(c.n);
        const title = [c.quote ? `“${c.quote}”` : null, p?.title, p?.source].filter(Boolean).join(' · ');
        return (
          <sup key={c.n} className="ml-0.5 text-[0.6875rem] tabular-nums">
            <TextLink to={postHref(c.post)} muted title={title || undefined} aria-label={`source ${c.n}`}>{c.n}</TextLink>
          </sup>
        );
      })}
    </>
  );
}

function Part({ label, lines, brief }: { label: string; lines: MarkxBriefLine[]; brief: MarkxEntityBrief }) {
  if (!lines.length) return null;
  return (
    <div className="mt-2" data-brief-part={label}>
      <h3 className="text-[0.8125rem] font-semibold text-fg-2">{label}</h3>
      <ul className="mt-1 list-disc space-y-1 pl-5">
        {lines.map((l) => (
          <li key={l.thing} className="text-[0.9375rem] leading-6 text-fg [overflow-wrap:anywhere]">
            {l.text}
            {l.who?.length ? <span className="text-fg-3"> · {l.who.join(', ')}</span> : null}
            <Cites line={l} brief={brief} />
          </li>
        ))}
      </ul>
    </div>
  );
}

export function EntityBrief({ brief }: { brief: MarkxEntityBrief | null | undefined }) {
  if (!brief || !(brief.what.length || brief.how.length || brief.results.length)) return null;
  return (
    <section aria-label="Brief" className="mt-3" data-brief-as-of={brief.as_of ?? undefined}>
      <Part label="What it is" lines={brief.what} brief={brief} />
      <Part label="How it works" lines={brief.how} brief={brief} />
      <Part label="Results" lines={brief.results} brief={brief} />
    </section>
  );
}
