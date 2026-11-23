import { Page, PageHeader, Tabs, TabsContent, TabsList, TabsTrigger } from '../components/ui';
import MarkXNews from '../components/markx/MarkXNews';
import MarkXBack from '../components/markx/MarkXBack';
import MarkXRoundup from '../components/markx/MarkXRoundup';
import { MarkXBriefing, MarkXWorker } from '../components/markx/MarkXOverview';
import MarkXEntities from '../components/markx/MarkXEntities';
import { useSearchParams } from 'react-router-dom';

const TABS = ['news', 'briefing', 'entities', 'worker'] as const;
type Tab = (typeof TABS)[number];

/**
 * Mark X, `/markx`, while INSIGHT_MARKX is on: Haiku's stories beside Mark IX's, never read by the reader's feed
 * or News; the day's briefing, the entities, and the worker's queue and runs.
 */
export default function MarkXPage() {
  const [params, setParams] = useSearchParams();
  const tab: Tab = (TABS as readonly string[]).includes(params.get('tab') ?? '') ? (params.get('tab') as Tab) : 'news';
  return (
    <Page>
      <PageHeader
        title="Mark X"
        meta="Shadow · Haiku reads and judges every post beside Mark IX; nothing here changes your feed or News"
      >
        <Tabs value={tab} onValueChange={(next) => setParams(next === 'news' ? {} : { tab: next }, { replace: true })}>
          <TabsList aria-label="Mark X">
            {TABS.map((t) => <TabsTrigger key={t} value={t}>{t}</TabsTrigger>)}
          </TabsList>
          <TabsContent value="news"><MarkXNews /><MarkXBack /><MarkXRoundup /></TabsContent>
          <TabsContent value="briefing"><MarkXBriefing /></TabsContent>
          <TabsContent value="entities"><MarkXEntities /></TabsContent>
          <TabsContent value="worker"><MarkXWorker /></TabsContent>
        </Tabs>
      </PageHeader>
    </Page>
  );
}
