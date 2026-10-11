/**
 * The studio's map (Handbook mode): where each design doc lives under /design
 * and how the rail groups them. Pure functions over the parsed docs, so the
 * rail is built from whatever files sit in docs/ (D1) and is tested here.
 */
import { META_BLOCK, docSlug, type DesignDoc } from './coverage';

/** The doc as it reads: the `meta` block is for the coverage test, not the reader. */
export function docBody(doc: DesignDoc): string {
  return doc.text.replace(META_BLOCK, '');
}

/** The first `# ` heading, else the file name. */
export function docTitle(doc: DesignDoc): string {
  return /^# (.+?)\s*$/m.exec(doc.text)?.[1] ?? docSlug(doc);
}

/** The studio URL of a doc, by its place under docs/. */
export function docHref(doc: DesignDoc): string {
  if (doc.path === 'principles.md') return '/design';
  if (doc.path === 'decisions.md') return '/design/decisions';
  if (doc.path === 'system/components.md') return '/design/components';
  const [folder] = doc.path.split('/');
  const section = folder === 'pages' || folder === 'parked' || folder === 'system' ? folder : 'docs';
  return `/design/${section}/${docSlug(doc)}`;
}

export interface RailItem {
  label: string;
  href: string;
  /** A quiet note after the label in the third tone (a prototype's status and age). */
  note?: string;
  /** Shown under the item while it (or a child) is the current place. */
  children?: RailItem[];
}

export interface RailGroup {
  label: string;
  items: RailItem[];
}

export interface PrototypeRef {
  id: string;
  label: string;
  /** Status and age, `review · 1 day`. */
  note?: string;
}

/** Pages in the order you meet them: the feed, a post, where it's managed, the frame around all three. */
const PAGE_ORDER = ['reader', 'post', 'sources', 'shell'];

function byOrder(order: readonly string[]) {
  const rank = (slug: string) => (order.includes(slug) ? order.indexOf(slug) : order.length);
  return (a: DesignDoc, b: DesignDoc) => rank(docSlug(a)) - rank(docSlug(b)) || docTitle(a).localeCompare(docTitle(b));
}

/** The page docs (`pages/*.md`) in the order you meet the pages. */
export function pageDocsInOrder(docs: readonly DesignDoc[]): DesignDoc[] {
  return docs.filter((doc) => doc.path.startsWith('pages/')).sort(byOrder(PAGE_ORDER));
}

const link = (doc: DesignDoc): RailItem => ({ label: docTitle(doc), href: docHref(doc) });

/**
 * The Handbook rail: Studio (principles, system, components, decisions) ·
 * Pages · Prototypes · Parked. Every doc in docs/ has exactly one place in it.
 */
export function railGroups(
  docs: readonly DesignDoc[],
  components: readonly string[],
  prototypes: readonly PrototypeRef[],
): RailGroup[] {
  const under = (folder: string) => docs.filter((doc) => doc.path.startsWith(`${folder}/`));
  const systemDocs = under('system')
    .filter((doc) => doc.path !== 'system/components.md')
    .sort((a, b) => docTitle(a).localeCompare(docTitle(b)));
  const parked = [...under('parked')].sort(byOrder([])).map(link);
  return [
    {
      label: 'Studio',
      items: [
        { label: 'Principles', href: '/design' },
        { label: 'System', href: '/design/system', children: systemDocs.map(link) },
        {
          label: 'Components',
          href: '/design/components',
          children: components.map((name) => ({ label: name, href: `/design/components/${name}` })),
        },
        { label: 'Decisions', href: '/design/decisions' },
      ],
    },
    { label: 'Pages', items: pageDocsInOrder(docs).map(link) },
    {
      label: 'Prototypes',
      items: prototypes.map((prototype) => ({ label: prototype.label, href: `/design/prototypes/${prototype.id}`, note: prototype.note })),
    },
    // Retired pages kept as a doc; hidden while there are none.
    ...(parked.length ? [{ label: 'Parked', items: parked }] : []),
  ];
}

export interface InventoryRule {
  /** The first cell: the component(s) and their variants. */
  use: string;
  do: string;
  dont: string;
}

/** A primitive's row in the component inventory (system/components.md), by its name in the first cell. */
export function inventoryRule(inventory: string, name: string): InventoryRule | undefined {
  for (const line of inventory.split('\n')) {
    const cells = line.split('|').slice(1, -1).map((cell) => cell.trim());
    if (cells.length === 3 && cells[0].includes(`\`${name}\``)) return { use: cells[0], do: cells[1], dont: cells[2] };
  }
  return undefined;
}
