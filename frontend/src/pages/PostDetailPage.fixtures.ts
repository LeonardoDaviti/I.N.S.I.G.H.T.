import type { Api, Post, PostDetailResponse } from '../services/api';

/**
 * Dev-only `?data=` fixtures for the post page (spec §F.7, break-ui). The post id in
 * the URL is ignored: every fixture answers for whichever post is open.
 */
export const POST_FIXTURE_NAMES = ['worst', 'empty', 'missing', 'slow'] as const;

const UNBROKEN = 'https://github.com/anthropics/claude-code/commit/' + 'f0aaf74ef7184398'.repeat(6);

/** A GitHub commit feed body: a <pre> of prose with no language, plus a real fence. */
const WORST_HTML = `
<p>Pushed by <strong>a-very-long-github-handle-without-any-breaks-at-all-${'x'.repeat(40)}</strong> to <a href="${UNBROKEN}">${UNBROKEN}</a></p>
<pre>Update claude-api skill: Claude Opus 5.5 default, Claude Sonnet 5.5 pricing, the fallback billing table and every model id that changed this week (${'model-id-'.repeat(18)}end)

* bump the default model in every SDK example and in the migration guide so that nobody copies the old id
* ${'unbreakable_identifier_'.repeat(8)}</pre>
<p dir="rtl">مرحبا بالعالم — هذا نص عربي طويل داخل منشور إنجليزي لاختبار الاتجاه.</p>
<pre><code class="language-ts">const ${'reallyLongVariableName'.repeat(4)} = await client.messages.create({ model: 'claude-opus-5-5', max_tokens: 1024 });</code></pre>
<table><tr><th>${'Column '.repeat(6)}</th><th>Value</th></tr><tr><td>${'cell-'.repeat(30)}</td><td>1,234,567,890</td></tr></table>
<img src="/missing-image-for-fixture.webp" alt="A broken image link" />
${Array.from({ length: 8 }, (_, i) => `<p>Paragraph ${i + 1}. Lorem ipsum dolor sit amet, consectetur adipiscing elit, sed do eiusmod tempor incididunt ut labore et dolore magna aliqua. 日本語のテキストも混ざっています。 🚀🔥</p>`).join('\n')}
`;

function post(overrides: Partial<Post>): Post {
  return {
    id: 'fixture-post',
    title: 'Fixture post',
    content: '',
    source: 'https://github.com/anthropics/claude-code/commits/main.atom',
    source_display_name: 'anthropics/claude-code',
    platform: 'rss',
    url: UNBROKEN,
    published_at: new Date(Date.now() - 3 * 3600_000).toISOString(),
    ...overrides,
  };
}

const DETAILS: Record<string, PostDetailResponse> = {
  worst: {
    success: true,
    post: post({
      title: `Update claude-api skill: Claude Opus 5.5 default, Claude Sonnet 5.5 pricing and ${'Supercalifragilisticexpialidocious'.repeat(3)} across every SDK example`,
      source_display_name: `${'anthropics-organisation-with-a-very-long-name/'.repeat(3)}claude-code`,
      content: WORST_HTML,
      content_html: WORST_HTML,
      categories: Array.from({ length: 24 }, (_, i) => `category-${i}-${'long'.repeat(i % 4)}`),
    }),
    reader_state: { open_count: 98765, total_read_seconds: 987654, first_opened_at: '2024-01-01T00:00:00Z' } as PostDetailResponse['reader_state'],
  },
  empty: { success: true, post: post({ title: '', content: '', content_html: '', url: undefined, published_at: null, source_display_name: undefined }) },
  missing: { success: false, error: 'Post not found', post: null },
  slow: { success: true, post: post({ title: 'Slow load: the skeleton should match this layout', content: WORST_HTML, content_html: WORST_HTML }) },
};

/** The post detail behind `?data=<name>`, for the studio's frames (Design Studio D4). */
export function postFixtureDetail(name: string): PostDetailResponse | null {
  return DETAILS[name] ?? null;
}

/** The fixture API for `?data=<name>`: reads come from the fixtures, writes are no-ops. */
export function postFixtureApi(name: string): Partial<Api> | null {
  const detail = DETAILS[name];
  if (!detail) return null;
  const delay = name === 'slow' ? 2500 : 0;
  const ok = async () => ({ success: true });
  return {
    getPostDetail: async () => {
      if (delay) await new Promise((resolve) => setTimeout(resolve, delay));
      return detail;
    },
    recordPostOpen: ok,
    recordPostReadingSession: ok,
    togglePostFavorite: ok,
  } as unknown as Partial<Api>;
}
