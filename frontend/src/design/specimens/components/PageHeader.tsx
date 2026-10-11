import Button from '../../../components/ui/Button';
import PageHeader from '../../../components/ui/PageHeader';
import { Tabs, TabsList, TabsTrigger } from '../../../components/ui/Tabs';
import { Variant, Variants } from '../parts';

/** Title, meta line, one primary action, and tabs underneath. */
export default function PageHeaderSpecimen() {
  return (
    <Variants className="sm:grid-cols-1">
      <Variant label="title · meta · actions · tabs" wide>
        <PageHeader
          className="mb-0 w-full"
          title="Sources"
          meta="90 sources · as of just now"
          actions={<><Button variant="ghost">Import</Button><Button variant="primary">Add source</Button></>}
        >
          <Tabs defaultValue="sources">
            <TabsList>
              <TabsTrigger value="sources">sources</TabsTrigger>
              <TabsTrigger value="connections">connections</TabsTrigger>
              <TabsTrigger value="ingestion">ingestion</TabsTrigger>
            </TabsList>
          </Tabs>
        </PageHeader>
      </Variant>
      <Variant label="worst · a long title wraps, actions drop below" wide>
        <PageHeader
          className="mb-0 w-full"
          title="A track whose name somebody typed as one very long sentence about agentic news"
          actions={<Button variant="primary">Add source</Button>}
        />
      </Variant>
    </Variants>
  );
}
