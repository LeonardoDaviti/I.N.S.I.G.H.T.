import type { Api, Expert, ExpertRunResult, Folder } from '../services/api';

/**
 * Tracks & experts fixtures (break-ui, spec §F.7): long/RTL/emoji names, 0/1/12,847
 * counts, a missing description, an expert whose folder was deleted, a fallback
 * (non-analysis) briefing and an expert with no briefing yet.
 */

export const TRACKS_FIXTURE_NAMES = ['worst', 'empty', 'one', 'huge'] as const;

export function folder(overrides: Partial<Folder> = {}): Folder {
  return {
    id: 'folder-1',
    name: 'Agentic News',
    description: 'Developments and trends in AI agents, harnesses, and tooling',
    kind: 'track',
    sort_order: 1,
    source_count: 2,
    post_count: 324,
    ...overrides,
  };
}

export function expert(overrides: Partial<Expert> = {}): Expert {
  return {
    id: 'expert-1',
    name: 'Agentic News',
    folder_id: 'folder-1',
    system_prompt: 'You track AI agents.',
    focus_instructions: null,
    output_variant: 'briefing',
    lookback_days: 7,
    schedule: 'daily',
    enabled: true,
    ...overrides,
  };
}

export function briefing(overrides: Partial<ExpertRunResult> = {}): ExpertRunResult {
  return {
    success: true,
    cached: true,
    briefing: '## This week\n\nTwo harnesses adopted the **skills** format.',
    topics: [{ title: 'Skills format', summary: 'Vendors converge on folders of instructions.', post_ids: ['p1', 'p2'] }],
    posts_processed: 42,
    start_date: '2026-10-02',
    end_date: '2026-10-09',
    generator: 'gemini-3.1-flash-lite-preview',
    ...overrides,
  };
}

const UNBREAKABLE = 'northwind-industries-holdings-agent-orchestration-runtime-release-notes-and-changelog-digest';

export const worstFolders: Folder[] = [
  folder({ id: 'wf-1', name: 'Smart Glasses Development, Display Optics, Teardowns and DIY Builds (incl. Vision Pro comparisons)', description: 'Every release, teardown, display-optics advance and DIY build in smart glasses / AR eyewear, tracked across vendors, forums, preprints and patents so nothing slips through the cracks.', source_count: 12847, post_count: 12847 }),
  folder({ id: 'wf-2', name: UNBREAKABLE, description: null, kind: 'folder', source_count: 0, post_count: 0 }),
  folder({ id: 'wf-3', name: 'أخبار الوكلاء', kind: 'track', source_count: 1, post_count: 1 }),
  folder({ id: 'wf-4', name: '🚀 AI 智能体', kind: 'folder', source_count: undefined, post_count: undefined }),
  folder({ id: 'wf-5', name: 'Jo', description: '' }),
];

export const worstExperts: Expert[] = [
  expert({ id: 'we-1', name: 'The Extremely Thorough Smart Glasses and Augmented Reality Eyewear Weekly Analyst', folder_id: 'wf-1', lookback_days: 90, schedule: 'every weekday at 07:30 Europe/Warsaw' }),
  expert({ id: 'we-2', name: 'Orphan', folder_id: 'deleted-folder', lookback_days: 1, schedule: null }),
  expert({ id: 'we-3', name: 'خبير', folder_id: 'wf-3' }),
];

const worstBriefings: Record<string, ExpertRunResult> = {
  'we-1': briefing({
    cached: false,
    generator: 'fallback',
    posts_processed: 12847,
    briefing: `## ${UNBREAKABLE}\n\nhttps://${UNBREAKABLE}.example.com/${UNBREAKABLE}\n\n- one\n- two`,
    topics: [{ title: UNBREAKABLE, summary: '', post_ids: ['p1'] }, { title: 'Zero', summary: 'No posts', post_ids: [] }],
  }),
  'we-3': briefing({ posts_processed: 1, topics: [], start_date: undefined, end_date: undefined, generator: null }),
};

const SETS: Record<string, { folders: Folder[]; experts: Expert[]; briefings: Record<string, ExpertRunResult> }> = {
  worst: { folders: worstFolders, experts: worstExperts, briefings: worstBriefings },
  empty: { folders: [], experts: [], briefings: {} },
  one: { folders: [folder({ source_count: 1, post_count: 1 })], experts: [expert()], briefings: { 'expert-1': briefing({ posts_processed: 1 }) } },
  huge: {
    folders: Array.from({ length: 120 }, (_, i) => folder({ id: `hf-${i}`, name: `Track ${i + 1}`, kind: i % 3 ? 'track' : 'folder', post_count: i * 113 })),
    experts: Array.from({ length: 40 }, (_, i) => expert({ id: `he-${i}`, name: `Expert ${i + 1}`, folder_id: `hf-${i}` })),
    briefings: {},
  },
};

/** The fixture API for `?data=<name>`: reads from the fixtures, writes are no-ops. */
export function tracksFixtureApi(name: string): Partial<Api> | null {
  const set = SETS[name];
  if (!set) return null;
  const unread: Record<string, number> = name === 'worst' ? { 'wf-1': 12847, 'wf-3': 1 } : name === 'one' ? { 'folder-1': 1 } : {};
  return {
    getFolders: async () => ({ success: true, folders: set.folders }),
    getExperts: async () => ({ success: true, experts: set.experts }),
    getExpertBriefing: async (id: string) => set.briefings[id] ?? { success: false, error: 'No briefing yet' },
    getUnreadCounts: async () => ({ total: Object.values(unread).reduce((a, b) => a + b, 0), by_source: {}, by_folder: unread }),
    runExpert: async (id: string) => set.briefings[id] ?? briefing({ cached: false }),
    createFolder: async () => ({ success: true }),
    deleteFolder: async () => ({ success: true }),
    createExpert: async () => ({ success: true }),
    deleteExpert: async () => ({ success: true }),
  };
}
