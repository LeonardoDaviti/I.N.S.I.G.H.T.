import { Navigate, Route, Routes, useParams } from 'react-router-dom';
import { COMPONENT_SPECIMENS, DOCS, PROTOTYPES, docAt } from '../library';
import { railGroups } from '../studio';
import { parseDoc } from '../coverage';
import { Rail, RailPicker } from '../handbook/Rail';
import DocView from '../handbook/DocView';
import NotFound from '../handbook/NotFound';
import PageSpecimen from '../handbook/PageSpecimen';
import { SystemDoc, SystemOverview } from '../handbook/SystemPage';
import { ComponentIndex, ComponentPage } from '../handbook/ComponentPage';

const GROUPS = railGroups(DOCS, [...COMPONENT_SPECIMENS.keys()], PROTOTYPES);

/** The doc at a fixed studio URL. */
function DocAt({ href }: { href: string }) {
  const doc = docAt(href);
  return doc ? <DocView doc={doc} /> : <NotFound what="doc" />;
}

/** A prototype's README (D6); the compare view is Bench's (S5b). */
function PrototypeDoc() {
  const { id = '' } = useParams();
  const prototype = PROTOTYPES.find((candidate) => candidate.id === id);
  if (!prototype) return <NotFound what="prototype" />;
  return <DocView doc={parseDoc(`prototypes/${id}/README.md`, prototype.readme)} />;
}

/**
 * A page or parked doc, then its specimen at full width. A page specimen
 * offers the doc's `states:`; a parked page has one, its normal state.
 */
function PageDoc({ section }: { section: 'pages' | 'parked' }) {
  const { slug = '' } = useParams();
  const doc = docAt(`/design/${section}/${slug}`);
  if (!doc) return <NotFound what="page doc" />;
  const states = doc.meta.states?.length ? doc.meta.states : ['normal'];
  return (
    <>
      <DocView doc={doc} />
      <PageSpecimen key={slug} page={slug} states={states} />
    </>
  );
}

/**
 * Handbook mode, the default (verdict A): the rail on the left, the doc in a
 * centred column, specimens under page docs at full width.
 */
export default function HandbookMode() {
  return (
    <div className="mx-auto flex w-full max-w-[90rem] gap-8 px-4 sm:px-6">
      <aside className="studio-rail sticky top-[calc(var(--topbar-h)+3rem)] hidden h-[calc(100dvh-var(--topbar-h)-3rem)] w-56 shrink-0 overflow-y-auto border-r border-line py-8 pr-3 md:block">
        <Rail groups={GROUPS} />
      </aside>
      <div className="min-w-0 flex-1 pb-24 pt-6 md:pt-10">
        <div className="mb-8 md:hidden">
          <RailPicker groups={GROUPS} />
        </div>
        <Routes>
          <Route index element={<DocAt href="/design" />} />
          <Route path="principles" element={<Navigate to="/design" replace />} />
          <Route path="decisions" element={<DocAt href="/design/decisions" />} />
          <Route path="system" element={<SystemOverview />} />
          <Route path="system/:slug" element={<SystemDoc />} />
          <Route path="components" element={<ComponentIndex />} />
          <Route path="components/:name" element={<ComponentPage />} />
          <Route path="pages/:slug" element={<PageDoc section="pages" />} />
          <Route path="parked/:slug" element={<PageDoc section="parked" />} />
          <Route path="prototypes/:id" element={<PrototypeDoc />} />
          <Route path="*" element={<NotFound />} />
        </Routes>
      </div>
    </div>
  );
}
