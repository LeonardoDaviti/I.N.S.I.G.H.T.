import { useState } from 'react';
import { describeCoverage } from '../../lib/archiveCoverage';
import { errorMessage } from '../../lib/apiError';
import { smartArchiveApi, type ArchiveCoverage } from '../../services/smartArchive';

/**
 * A feed's coverage (issue 0143), under the archive's counts: "Stored 19 of ~34", the platform its site is built
 * with and how the rest is read, each other way's reason in `text-fg-3`, and the last resort the owner opts in to:
 * the Web Archive's index of the site's addresses.
 */
export default function ArchiveCoverageLine({ sourceId, coverage, onChanged }: {
  sourceId: string;
  coverage: ArchiveCoverage;
  onChanged?: () => void;
}) {
  const said = describeCoverage(coverage);
  const [webArchive, setWebArchive] = useState(Boolean(coverage.web_archive));
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const toggle = async (on: boolean) => {
    setSaving(true);
    setError(null);
    try {
      await smartArchiveApi.setWebArchive(sourceId, on);
      setWebArchive(on);
      onChanged?.();
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="space-y-1 text-[0.8125rem]" aria-label="Archive coverage" data-coverage>
      <p className="tabular-nums text-fg">{said.figure}</p>
      {said.how ? <p className="text-[0.75rem] text-fg-2">{said.how}</p> : null}
      {said.reasons.length ? (
        <ul className="text-[0.75rem] text-fg-3 [overflow-wrap:anywhere]" aria-label="Why the rest is not stored">
          {said.reasons.map((reason) => <li key={reason}>{reason}</li>)}
        </ul>
      ) : null}
      <label className="flex items-start gap-2 pt-1 text-[0.75rem] text-fg-2">
        <input
          type="checkbox"
          className="mt-0.5 h-4 w-4 accent-[rgb(var(--text))]"
          checked={webArchive}
          disabled={saving}
          onChange={(e) => void toggle(e.target.checked)}
        />
        <span>
          Also look in the Web Archive's index of this site
          <span className="text-fg-3"> (last resort: each page read from the site, or its archived copy when gone)</span>
        </span>
      </label>
      {error ? <p className="text-[0.75rem] text-fg-2">Not saved: {error}</p> : null}
    </div>
  );
}
