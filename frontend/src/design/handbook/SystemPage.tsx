import { useParams } from 'react-router-dom';
import { docAt } from '../library';
import { SYSTEM_SPECIMENS } from '../live';
import DocView from './DocView';
import NotFound from './NotFound';

/**
 * /design/system: the system as the running page draws it (D3). Every value
 * is read from the page, so nothing here is a copy that can go stale; each
 * section links to the doc with its rules.
 */
export function SystemOverview() {
  return (
    <div className="mx-auto w-full max-w-3xl">
      <h1 className="text-[1.5rem] font-semibold leading-[1.2] tracking-[-0.02em] text-fg">System</h1>
      <p className="mb-10 mt-3 max-w-reading text-fg-2">
        Tokens, type, space, motion and status, read live from the running app. The rules for each are in the docs listed under System in the rail.
      </p>
      {SYSTEM_SPECIMENS.map(([slug, Specimen]) => <Specimen key={slug} rules={slug} />)}
    </div>
  );
}

/** /design/system/:slug: a system doc, then its live specimen where it has one. */
export function SystemDoc() {
  const { slug = '' } = useParams();
  const doc = docAt(`/design/system/${slug}`);
  if (!doc) return <NotFound what="system doc" />;
  const Specimen = SYSTEM_SPECIMENS.find(([name]) => name === slug)?.[1];
  return (
    <>
      <DocView doc={doc} />
      {Specimen ? (
        <div className="mx-auto mt-14 w-full max-w-3xl border-t border-line pt-8">
          <Specimen />
        </div>
      ) : null}
    </>
  );
}
