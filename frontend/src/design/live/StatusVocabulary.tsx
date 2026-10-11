import StatusGlyph from '../../components/ui/StatusGlyph';
import { STATUS_LABEL, type Status } from '../../components/ui/styles';
import Section from './Section';

const STATUSES = Object.keys(STATUS_LABEL) as Status[];

/** Every status as the app draws it (P11): a shape plus a word, and the dense glyph-only form. */
export default function StatusVocabulary({ rules }: { rules?: string }) {
  return (
    <Section title="Status" rules={rules}>
      <ul className="grid grid-cols-1 gap-x-8 sm:grid-cols-2">
        {STATUSES.map((status) => (
          <li key={status} className="flex min-h-[2.5rem] items-center gap-4 border-b border-line">
            <span className="w-24 shrink-0 font-mono text-[0.75rem] text-fg-3">{status}</span>
            <StatusGlyph status={status} />
            <span className="ml-auto"><StatusGlyph status={status} hideLabel /></span>
          </li>
        ))}
      </ul>
    </Section>
  );
}
