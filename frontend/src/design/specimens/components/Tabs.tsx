import { Tabs, TabsContent, TabsList, TabsTrigger } from '../../../components/ui/Tabs';
import { Variant, Variants } from '../parts';

/** Lowercase underline tabs; switching is instant. */
export default function TabsSpecimen() {
  return (
    <Variants className="sm:grid-cols-1">
      <Variant label="three views" wide>
        <Tabs defaultValue="sources" className="w-full">
          <TabsList>
            <TabsTrigger value="sources">sources</TabsTrigger>
            <TabsTrigger value="connections">connections</TabsTrigger>
            <TabsTrigger value="ingestion">ingestion</TabsTrigger>
          </TabsList>
          <TabsContent value="sources" className="text-[0.875rem] text-fg-2">90 sources in 6 tracks.</TabsContent>
          <TabsContent value="connections" className="text-[0.875rem] text-fg-2">Substack, Telegram.</TabsContent>
          <TabsContent value="ingestion" className="text-[0.875rem] text-fg-2">Last run 14:20, 2 failing.</TabsContent>
        </Tabs>
      </Variant>
    </Variants>
  );
}
