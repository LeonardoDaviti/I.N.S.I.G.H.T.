import { useId, type ReactNode } from 'react';
import TextLink from '../../components/ui/TextLink';

/** A live specimen's frame: a heading that names the region, a line on where the rules live, the specimen. */
export default function Section({ title, rules, children }: { title: string; rules?: string; children: ReactNode }) {
  const id = useId();
  return (
    <section aria-labelledby={id} className="mt-12 first:mt-0">
      <div className="mb-4 flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1">
        <h2 id={id} className="text-[1.0625rem] font-semibold leading-[1.35] tracking-[-0.01em] text-fg">{title}</h2>
        {rules ? <TextLink to={`/design/system/${rules}`} muted className="text-[0.8125rem]">the rules</TextLink> : null}
      </div>
      {children}
    </section>
  );
}
