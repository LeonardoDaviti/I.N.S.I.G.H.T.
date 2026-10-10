import { useState } from 'react';
import { ChevronRight } from 'lucide-react';
import type { CredentialProviderView } from '../../services/api';
import { StatusGlyph } from '../ui';
import { ErrorState, LoadingState } from '../states';
import { cn } from '../../lib/utils';
import ConnectionField from './ConnectionField';
import SubstackHowTo from './SubstackHowTo';
import TelegramSignIn from './TelegramSignIn';
import TestButton from './TestButton';
import { providerStatus } from './connectionStatus';
import { useConnections } from './useConnections';
import { useAnalysisEnabled } from '../../hooks/useAnalysis';

const ROW = 'flex w-full min-w-0 items-start gap-3 px-1 py-3 text-left';

function ProviderSection({ view, open, onToggle }: { view: CredentialProviderView; open: boolean; onToggle: () => void }) {
  const status = providerStatus(view);
  const panelId = `connection-${view.provider}`;
  const writable = view.fields.filter((f) => f.writable);
  const heading = (
    <>
      <span className="min-w-0 flex-1">
        <span className="block text-[0.9375rem] font-semibold text-fg">{view.label}</span>
        <span className="block text-[0.8125rem] font-normal text-fg-2">{view.description}</span>
        {status.message && !open ? (
          <span className="mt-1 block text-[0.75rem] font-normal text-fg [overflow-wrap:anywhere]">
            <span aria-hidden="true" className="mr-1 font-semibold">×</span>{status.message}
          </span>
        ) : null}
      </span>
      <span className="shrink-0 pt-0.5 font-normal">
        <StatusGlyph status={status.glyph} label={status.label} />
      </span>
    </>
  );
  return (
    <li className="border-b border-line last:border-b-0" data-provider={view.provider}>
      <h3 className="m-0">
        {view.needed ? (
          <button
            type="button"
            aria-expanded={open}
            aria-controls={panelId}
            onClick={onToggle}
            className={cn(ROW, 'rounded-sm hover:bg-raised/60 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-fg')}
          >
            <ChevronRight aria-hidden="true" className={cn('mt-[0.2rem] h-4 w-4 shrink-0 text-fg-3', open && 'rotate-90')} />
            {heading}
          </button>
        ) : (
          <div className={ROW}>
            <span aria-hidden="true" className="h-4 w-4 shrink-0" />
            {heading}
          </div>
        )}
      </h3>
      {open && view.needed ? (
        <div id={panelId} className="space-y-5 pb-5 pl-8 pr-1 pt-1">
          {view.provider === 'substack' ? <SubstackHowTo /> : null}
          {writable.map((field) => (
            <ConnectionField key={field.key} provider={view.provider} field={field} hideHint={view.provider === 'substack'} />
          ))}
          {view.sign_in ? (
            <div className="space-y-1.5">
              <p className="text-[0.8125rem] font-medium text-fg">Sign in</p>
              <TelegramSignIn view={view} />
            </div>
          ) : null}
          {view.testable ? <TestButton view={view} /> : null}
        </div>
      ) : null}
    </li>
  );
}

/**
 * Sources → Connections (spec §10.1): one row per provider with its state; a row
 * opens its fields. Write-only: a saved value shows as "set · ••••a3f", never itself.
 */
export default function ConnectionsPanel({ initialOpen }: { initialOpen?: string | null }) {
  const query = useConnections();
  const analysisEnabled = useAnalysisEnabled();
  const [open, setOpen] = useState<ReadonlySet<string>>(() => new Set(initialOpen ? [initialOpen] : []));

  if (query.isPending) return <LoadingState label="Loading connections" rows={4} />;
  if (query.isError) {
    return <ErrorState title="Could not load connections" error={query.error} onRetry={() => void query.refetch()} />;
  }
  return (
    <section aria-label="Connections" className="max-w-[44rem]">
      <p className="mb-3 text-[0.8125rem] text-fg-2">
        Secrets some sources need. This is the only place they live: stored encrypted on this machine and never shown again after saving.
      </p>
      <ul className="border-t border-line">
        {query.data.providers.filter((view) => analysisEnabled || !view.analysis_only).map((view) => (
          <ProviderSection
            key={view.provider}
            view={view}
            open={open.has(view.provider)}
            onToggle={() => setOpen((prev) => {
              const next = new Set(prev);
              if (next.has(view.provider)) next.delete(view.provider);
              else next.add(view.provider);
              return next;
            })}
          />
        ))}
      </ul>
    </section>
  );
}
