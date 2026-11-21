import { TextLink } from '../ui';
import type { MarkxBriefLine, MarkxBriefSense, MarkxEntityBrief, MarkxNumberSeries } from '../../services/markx';

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
            {l.note ? <span className="text-fg-2" data-brief-note=""> — {l.note}</span> : null}
            {l.who?.length ? <span className="text-fg-3"> · {l.who.join(', ')}</span> : null}
            <Cites line={l} brief={brief} />
          </li>
        ))}
      </ul>
    </div>
  );
}

/** 0272: each recurring measure's values over time, a small plain table, oldest first, each value cited; values of
 * one date that disagree are marked as disputed (0097), side by side. */
function Numbers({ series, brief }: { series: MarkxNumberSeries[]; brief: MarkxEntityBrief }) {
  if (!series.length) return null;
  return (
    <div className="mt-2" data-brief-part="Numbers over time">
      <h3 className="text-[0.8125rem] font-semibold text-fg-2">Numbers over time</h3>
      {series.map((s) => (
        <table key={`${s.measure}|${s.unit ?? ''}`} className="mt-1 w-full text-[0.875rem] leading-6"
          data-measure={s.measure}>
          <caption className="text-left text-fg-2">{s.measure}{s.unit ? ` (${s.unit})` : ''}
            {s.disputes ? <span className="text-fg-3"> · {s.disputes} disputed</span> : null}</caption>
          <tbody>
            {s.points.map((p) => (
              <tr key={`${p.post}|${p.value}|${p.setting ?? ''}`} data-dispute={p.dispute || undefined}>
                <td className="w-28 pr-2 tabular-nums text-fg-3">{p.as_of ?? p.at ?? ''}</td>
                <td className="pr-2 tabular-nums text-fg [overflow-wrap:anywhere]">
                  {p.shown}{p.dispute ? <span className="text-fg-3"> (disputed)</span> : null}
                  <Cites line={{ cites: [{ post: p.post, n: p.n, quote: p.quote }] }} brief={brief} />
                </td>
                <td className="text-fg-3 [overflow-wrap:anywhere]">{p.setting ?? ''}</td>
              </tr>
            ))}
          </tbody>
        </table>
      ))}
    </div>
  );
}

function Parts({ lines, brief }: {
  lines: Pick<MarkxBriefSense, 'what' | 'how' | 'results' | 'numbers'>; brief: MarkxEntityBrief;
}) {
  return (
    <>
      <Part label="What it is" lines={lines.what} brief={brief} />
      <Part label="How it works" lines={lines.how} brief={brief} />
      <Part label="Results" lines={lines.results} brief={brief} />
      <Numbers series={lines.numbers ?? []} brief={brief} />
    </>
  );
}

/** 0274: one brief a sense when the entity's posts hold several things of its name, each from its own posts. */
export function EntityBrief({ brief }: { brief: MarkxEntityBrief | null | undefined }) {
  if (!brief) return null;
  const senses = brief.senses ?? [];
  if (senses.length) {
    return (
      <section aria-label="Brief" className="mt-3" data-brief-as-of={brief.as_of ?? undefined}>
        <p className="text-[0.8125rem] text-fg-3">This name stands for {senses.length} different things in its posts.</p>
        {senses.map((s, i) => (
          <div key={i} className="mt-3" data-brief-sense={i + 1}>
            <h3 className="text-[0.875rem] font-semibold text-fg [overflow-wrap:anywhere]">
              {s.label ?? `Sense ${i + 1}`}
              <span className="font-normal text-fg-3">
                {s.maker ? ` · ${s.maker}` : ''} · {s.post_count} {s.post_count === 1 ? 'post' : 'posts'}
              </span>
            </h3>
            <Parts lines={s} brief={brief} />
          </div>
        ))}
      </section>
    );
  }
  if (!(brief.what.length || brief.how.length || brief.results.length || brief.numbers?.length)) return null;
  return (
    <section aria-label="Brief" className="mt-3" data-brief-as-of={brief.as_of ?? undefined}>
      <Parts lines={brief} brief={brief} />
    </section>
  );
}
