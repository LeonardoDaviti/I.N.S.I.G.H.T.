import { Page, PageHeader, Tabs, TabsContent, TabsList, TabsTrigger } from '../components/ui';
import MarkXNews from '../components/markx/MarkXNews';
import { MarkXBriefing, MarkXEntities, MarkXWorker } from '../components/markx/MarkXOverview';
import { useSearchParams } from 'react-router-dom';

const TABS = ['news', 'briefing', 'entities', 'worker', 'labels'] as const;
type Tab = (typeof TABS)[number];

/**
 * Mark X Shadow (issue 0086 E), `/markx`, while INSIGHT_MARKX is on: Haiku's stories beside Mark IX's, never read by
 * the reader's feed or News. News (Mark X's News against Mark IX's, only the differences by default), the day's
 * briefing, the main-subject entities, the worker's queue and runs. Labels are part F.
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
          <TabsContent value="news"><MarkXNews /></TabsContent>
          <TabsContent value="briefing"><MarkXBriefing /></TabsContent>
          <TabsContent value="entities"><MarkXEntities /></TabsContent>
          <TabsContent value="worker"><MarkXWorker /></TabsContent>
          <TabsContent value="labels">
            <p className="text-[0.875rem] text-fg-2">Your labels come next (0086 part F): every merge and each decision near a bar, one tap each.</p>
          </TabsContent>
        </Tabs>
      </PageHeader>
    </Page>
  );
}
