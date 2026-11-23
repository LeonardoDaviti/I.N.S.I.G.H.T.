import { useSourcesHealth } from '../../hooks/useSourcesHealth';
import { sourceLabel } from '../../lib/sourceLabel';
import SilentNotice from './SilentNotice';

/** Discover's followed sources gone silent far beyond their rhythm, each with where it went, Switch or It stopped.
 *  Read from source health; nothing while it loads or when it can't be read. */
export default function SilentSources({ now = new Date() }: { now?: Date }) {
  const health = useSourcesHealth();
  const rows = (health.data?.rows ?? []).filter((row) => row.silent);
  if (!rows.length) return null;
  return (
    <section aria-label="Sources you follow that went silent" className="mb-2">
      <h2 className="pt-1 text-[0.75rem] font-medium text-fg-3">Sources you follow that went silent</h2>
      <ul>
        {rows.map((row) => (
          <li key={row.source_id} className="border-b border-line py-3 last:border-b-0">
            <h3 className="mb-1 text-[0.9375rem] font-semibold leading-6 text-fg [overflow-wrap:anywhere]">{sourceLabel(row.display_name)}</h3>
            <SilentNotice row={row} now={now} compact />
          </li>
        ))}
      </ul>
    </section>
  );
}
