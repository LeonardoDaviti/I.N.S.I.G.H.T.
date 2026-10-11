import { Link, useParams } from 'react-router-dom';
import { COMPONENT_SPECIMENS, docAt } from '../library';
import { inventoryRule } from '../studio';
import DocView from './DocView';
import NotFound from './NotFound';

const INVENTORY = '/design/components';

/** /design/components: the inventory doc, then every primitive's specimen. */
export function ComponentIndex() {
  const doc = docAt(INVENTORY);
  return (
    <>
      {doc ? <DocView doc={doc} /> : null}
      <nav aria-labelledby="primitives" className="mx-auto mt-12 w-full max-w-reading border-t border-line pt-6">
        <h2 id="primitives" className="mb-3 text-[0.8125rem] lowercase text-fg-3">specimens</h2>
        <ul aria-label="Primitives" className="grid grid-cols-2 gap-x-6 gap-y-1 sm:grid-cols-3">
          {[...COMPONENT_SPECIMENS.keys()].map((name) => (
            <li key={name}>
              <Link to={`${INVENTORY}/${name}`} className="text-link text-[0.875rem]">{name}</Link>
            </li>
          ))}
        </ul>
      </nav>
    </>
  );
}

/** Strip the doc's inline-code ticks for a one-line rule. */
const plain = (text: string) => text.replace(/`/g, '');

/**
 * /design/components/:name: one `components/ui` primitive in its variants
 * and states, with its source file and its line from the inventory.
 */
export function ComponentPage() {
  const { name = '' } = useParams();
  const Specimen = COMPONENT_SPECIMENS.get(name);
  if (!Specimen) return <NotFound what="component" />;
  const rule = inventoryRule(docAt(INVENTORY)?.text ?? '', name);
  return (
    <div className="mx-auto w-full max-w-3xl">
      <h1 className="text-[1.5rem] font-semibold leading-[1.2] tracking-[-0.02em] text-fg">{name}</h1>
      <p className="mt-1.5 font-mono text-[0.75rem] text-fg-3">src/components/ui/{name}.tsx</p>
      {rule ? (
        <dl className="mt-5 grid grid-cols-[4rem_minmax(0,1fr)] gap-x-4 gap-y-1.5 text-[0.875rem]">
          <dt className="text-fg-3">do</dt>
          <dd className="text-fg">{plain(rule.do)}</dd>
          <dt className="text-fg-3">don’t</dt>
          <dd className="text-fg-2">{plain(rule.dont)}</dd>
        </dl>
      ) : null}
      <section aria-label="Specimen" className="mt-8 rounded-lg border border-line p-5 sm:p-7">
        <Specimen />
      </section>
    </div>
  );
}
