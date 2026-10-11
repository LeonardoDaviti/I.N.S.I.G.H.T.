import { useMemo } from 'react';
import { Link, Navigate, Route, Routes, useParams } from 'react-router-dom';
import Button from '../../components/ui/Button';
import { COMPONENT_SPECIMENS, DOCS, docAt, prototypeRefs } from '../library';
import { prototypeById } from '../prototypeRegistry';
import { railGroups } from '../studio';
import { parseDoc } from '../coverage';
import { prototypeAge } from '../prototypes';
import { benchHref } from '../bench';
import { frameScenario } from '../fixtures/scenarios';
import { Rail, RailPicker } from '../handbook/Rail';
import DocView from '../handbook/DocView';
import NotFound from '../handbook/NotFound';
import PageSpecimen from '../handbook/PageSpecimen';
import { SystemDoc, SystemOverview } from '../handbook/SystemPage';
import { ComponentIndex, ComponentPage } from '../handbook/ComponentPage';

const COMPONENTS = [...COMPONENT_SPECIMENS.keys()];

/** The doc at a fixed studio URL. */
function DocAt({ href }: { href: string }) {
  const doc = docAt(href);
  return doc ? <DocView doc={doc} /> : <NotFound what="doc" />;
}

/** A prototype's README (D6), its status and age, and the way into Bench, where it is compared. */
function PrototypeDoc() {
  const { id = '' } = useParams();
  const prototype = prototypeById(id);
  if (!prototype) return <NotFound what="prototype" />;
  return (
    <>
      <DocView doc={parseDoc(`prototypes/${id}/README.md`, prototype.readme)} />
      <div className="mx-auto mt-10 flex w-full max-w-reading flex-wrap items-center justify-between gap-x-6 gap-y-3 border-t border-line pt-5">
        <p className="text-[0.8125rem] text-fg-3">
          <span className="font-mono">{prototype.id}</span> · {prototype.status} · {prototypeAge(prototype, new Date())} · {prototype.page} / {prototype.states.join(', ')}
        </p>
        <Button asChild size="sm" variant="secondary">
          <Link to={benchHref(prototype.id)}>Open in Bench</Link>
        </Button>
      </div>
    </>
  );
}

/**
 * A page or parked doc, then its specimen at full width, offering the doc's
 * `states:` that have a frame scenario. A parked page has none, so no specimen.
 */
function PageDoc({ section }: { section: 'pages' | 'parked' }) {
  const { slug = '' } = useParams();
  const doc = docAt(`/design/${section}/${slug}`);
  if (!doc) return <NotFound what="page doc" />;
  const states = (doc.meta.states?.length ? doc.meta.states : ['normal']).filter((state) => frameScenario(slug, state));
  return (
    <>
      <DocView doc={doc} />
      {states.length ? <PageSpecimen key={slug} page={slug} states={states} /> : null}
    </>
  );
}

/**
 * Handbook mode, the default (verdict A): the rail on the left, the doc in a
 * centred column, specimens under page docs at full width.
 */
export default function HandbookMode() {
  // The rail's prototype ages count from now, so they are read when the mode mounts.
  const groups = useMemo(() => railGroups(DOCS, COMPONENTS, prototypeRefs(new Date())), []);
  return (
    <div className="mx-auto flex w-full max-w-[90rem] gap-8 px-4 sm:px-6">
      <aside className="studio-rail sticky top-[calc(var(--topbar-h)+3rem)] hidden h-[calc(100dvh-var(--topbar-h)-3rem)] w-56 shrink-0 overflow-y-auto border-r border-line py-8 pr-3 md:block">
        <Rail groups={groups} />
      </aside>
      <div className="min-w-0 flex-1 pb-24 pt-6 md:pt-10">
        <div className="mb-8 md:hidden">
          <RailPicker groups={groups} />
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
