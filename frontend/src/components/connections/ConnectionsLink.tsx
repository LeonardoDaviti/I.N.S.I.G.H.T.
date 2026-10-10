import type { SourceHealthRow } from '../../services/api';
import { TextLink } from '../ui';
import { connectionsHref, missingCredentialProvider } from './connectionStatus';

/** "Paid posts arrive as teasers. Add … in Sources → Connections" → its first sentence (the link says the rest). */
function firstSentence(text: string): string {
  const end = text.indexOf('. ');
  return end >= 0 ? text.slice(0, end + 1) : text;
}

/** "add in Connections" under a source that is unavailable (or reads teasers) for a missing credential. */
export default function ConnectionsLink({ row, className = '' }: { row: SourceHealthRow; className?: string }) {
  const provider = missingCredentialProvider(row);
  if (!provider) return null;
  return (
    <p className={`text-[0.75rem] text-fg-2 ${className}`}>
      {row.status !== 'unavailable' && row.credential_notice ? <span className="mr-1">{firstSentence(row.credential_notice)}</span> : null}
      <TextLink to={connectionsHref(provider)}>add in Connections</TextLink>
    </p>
  );
}
