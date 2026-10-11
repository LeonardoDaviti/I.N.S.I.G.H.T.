import StatusGlyph from '../../../components/ui/StatusGlyph';
import { TBody, THead, Table, TableFrame, Td, Th, Tr } from '../../../components/ui/Table';
import { Variant, Variants } from '../parts';

const ROWS = [
  { name: 'Simon Willison', platform: 'rss', posts: 1284, status: 'ok' },
  { name: 'Hacker News', platform: 'rss', posts: 12847, status: 'failing' },
  { name: 'تيليجرام', platform: 'telegram', posts: 3, status: 'backoff' },
] as const;

/** A data table in its frame: hairlines, small text, tabular numbers, a status column. */
export default function TableSpecimen() {
  return (
    <Variants className="sm:grid-cols-1">
      <Variant label="TableFrame · Table" wide>
        <TableFrame>
          <Table>
            <THead>
              <Tr><Th>Source</Th><Th>Platform</Th><Th className="text-right">Posts</Th><Th>Status</Th></Tr>
            </THead>
            <TBody>
              {ROWS.map((row) => (
                <Tr key={row.name}>
                  <Td dir="auto">{row.name}</Td>
                  <Td className="text-fg-2">{row.platform}</Td>
                  <Td className="text-right">{row.posts.toLocaleString('en-US')}</Td>
                  <Td><StatusGlyph status={row.status} /></Td>
                </Tr>
              ))}
            </TBody>
          </Table>
        </TableFrame>
      </Variant>
    </Variants>
  );
}
