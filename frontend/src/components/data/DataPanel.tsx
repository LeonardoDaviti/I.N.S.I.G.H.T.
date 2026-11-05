import { useEffect, useId, useState } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';

import { useApi } from '../../services/ApiContext';
import type { ExportProgress } from '../../services/api';
import { apiUrl } from '../../lib/request';
import { errorMessage } from '../../lib/apiError';
import { estimateBasis, exportPath, formatBytes, formatDuration, newExportToken, restoreCommand } from '../../lib/exportText';
import ConfirmDialog from '../ops/ConfirmDialog';
import { Button } from '../ui';
import { LoadingState, Notice } from '../states';

export const EXPORT_INFO_KEY = ['export-info'] as const;
const sectionTitle = 'text-[1.0625rem] font-semibold leading-[1.35] tracking-[-0.01em] text-fg';
const POLL_MS = 1000;

/** Start a download the browser saves itself (streamed to disk, never held in the page). */
function download(path: string) {
  const link = document.createElement('a');
  link.href = apiUrl(path);
  link.rel = 'noopener';
  document.body.appendChild(link);
  link.click();
  link.remove();
}

/**
 * Settings → Data (issue 0079): export everything as one zip (a CSV per table,
 * the schema, a manifest, how to restore it), stored logins left out unless
 * ticked, after a confirmation; and the sources list as sources.json. Before the
 * click: the database's size and an estimate; after: the file, its size and the
 * restore command.
 */
export default function DataPanel() {
  const api = useApi();
  const loginsId = useId();
  const queryClient = useQueryClient();
  const info = useQuery({ queryKey: EXPORT_INFO_KEY, queryFn: () => api.getExportInfo() });
  const [includeLogins, setIncludeLogins] = useState(false);
  const [confirming, setConfirming] = useState(false);
  const [token, setToken] = useState<string | null>(null);
  const [progress, setProgress] = useState<ExportProgress | null>(null);

  // Follow the download the server is writing: bytes so far, then done or stopped.
  useEffect(() => {
    if (!token) return undefined;
    let stopped = false;
    const poll = async () => {
      try {
        const state = await api.getExportProgress(token);
        if (stopped) return;
        setProgress(state);
        // A whole export is the next estimate's basis (issue 0105): read the line again.
        if (state.done) void queryClient.invalidateQueries({ queryKey: EXPORT_INFO_KEY });
        if (state.done || state.error) return;
      } catch {
        // Not started yet (404) or a blip: ask again.
      }
      if (!stopped) timer = window.setTimeout(poll, POLL_MS);
    };
    let timer = window.setTimeout(poll, POLL_MS);
    return () => { stopped = true; window.clearTimeout(timer); };
  }, [api, queryClient, token]);

  const start = () => {
    setConfirming(false);
    const next = newExportToken();
    setProgress(null);
    setToken(next);
    download(exportPath(next, includeLogins));
  };

  const running = token !== null && !progress?.done && !progress?.error;

  return (
    <section aria-label="Data" className="max-w-[44rem] space-y-8">
      <div className="space-y-3">
        <h2 className={sectionTitle}>Export everything</h2>
        <p className="text-[0.875rem] text-fg-2">
          One zip with every table as a CSV, the schema, a manifest and a README on how to restore it into INSIGHT
          or open it in any tool. It is written as it downloads; nothing is kept on the server.
        </p>
        {info.isPending ? <LoadingState label="Reading the database's size" rows={1} /> : null}
        {info.isError ? (
          <Notice tone="error" title="Could not read the database's size" message={errorMessage(info.error)}
            action={{ label: 'Retry', onClick: () => void info.refetch() }} />
        ) : null}
        {info.data ? (
          <p className="text-[0.875rem] text-fg" data-testid="export-estimate">
            The database is {formatBytes(info.data.database_bytes)}. The zip: about {formatBytes(info.data.estimate_bytes)},{' '}
            {formatDuration(info.data.estimate_seconds)} to write{estimateBasis(info.data) ? `, ${estimateBasis(info.data)}` : ''}.
          </p>
        ) : null}
        <div className="flex items-start gap-2.5">
          <input id={loginsId} type="checkbox" className="mt-1 accent-current" checked={includeLogins}
            disabled={running} onChange={(event) => setIncludeLogins(event.target.checked)} />
          <label htmlFor={loginsId} className="text-[0.875rem]">
            <span className="font-medium text-fg">Include stored logins</span>
            <span className="block text-fg-2">
              {includeLogins
                ? `Adds ${info.data?.logins_include ?? 'the stored logins'}.`
                : 'Left out: after a restore, enter them again in Sources → Connections.'}
            </span>
          </label>
        </div>
        <Button onClick={() => setConfirming(true)} disabled={running}>
          {running ? 'Exporting…' : 'Export everything'}
        </Button>

        {token && progress?.done ? (
          <Notice tone="completion" title={`${progress.file_name} · ${formatBytes(progress.bytes)}`}
            message="Saved by your browser. To restore it, copy it to the server's INSIGHT folder and run there:">
            <pre className="mt-2 overflow-x-auto rounded-md border border-line bg-raised p-2 font-mono text-[0.75rem] text-fg"
              data-testid="restore-command">{restoreCommand(progress.file_name)}</pre>
            <p className="mt-2 text-[0.8125rem] text-fg-2">It makes a new database, insight_restored; DEPLOYMENT.md says how to switch to it.</p>
          </Notice>
        ) : null}
        {token && progress?.error ? (
          <Notice tone="error" title={`${progress.file_name}: ${progress.error}`}
            message="The download is not a whole export. Try again." />
        ) : null}
        {running ? (
          <Notice tone="status" title={progress ? `Writing ${progress.file_name} · ${formatBytes(progress.bytes)} so far` : 'Starting the export'} />
        ) : null}
      </div>

      <div className="space-y-3">
        <h2 className={sectionTitle}>Export sources</h2>
        <p className="text-[0.875rem] text-fg-2">
          The sources list as sources.json, the file INSIGHT imports (only the sources a database lacks are added).
        </p>
        <a href={apiUrl('/api/export/sources.json')} download="sources.json" className="text-link text-[0.875rem] text-fg-2">
          Export sources (sources.json)
        </a>
      </div>

      <ConfirmDialog
        open={confirming}
        title="Export everything?"
        description={(
          <>
            The zip holds everything INSIGHT knows: every post, source, read state and note
            {includeLogins ? ', and the stored logins' : ' (stored logins left out)'}. Keep it somewhere private.
          </>
        )}
        confirmLabel="Export"
        onConfirm={start}
        onCancel={() => setConfirming(false)}
      />
    </section>
  );
}
