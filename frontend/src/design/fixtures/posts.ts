/**
 * The post page's states as post details (Design Studio D5): an article, media,
 * a long title, the h1–h6 scale and a Telegram post with no title. The long
 * title borrows the break-ui worst post (`PostDetailPage.fixtures.ts`).
 */
import type { Post, PostDetailResponse } from '../../services/api';
import { postFixtureDetail } from '../../pages/PostDetailPage.fixtures';

const HOUR = 3_600_000;

function detail(id: string, post: Partial<Post>, now: Date): PostDetailResponse {
  return {
    success: true,
    post: {
      id,
      source_id: 's-simon',
      title: 'Prompt caching is now generally available',
      content: '',
      content_html: '',
      source: 'https://simonwillison.net/atom/everything/',
      source_display_name: 'Simon Willison’s Weblog',
      platform: 'rss',
      url: `https://simonwillison.net/2026/Oct/9/${id}/`,
      published_at: new Date(now.getTime() - 3 * HOUR).toISOString(),
      ...post,
    },
    reader_state: { post_id: id, is_favorited: false, open_count: 1 },
  };
}

/** A grey picture as a data URI, so a frame never loads an image from the network. */
function picture(width: number, height: number, label: string): string {
  const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="${width}" height="${height}" viewBox="0 0 ${width} ${height}">`
    + `<rect width="100%" height="100%" fill="rgb(138,138,138)"/><text x="50%" y="50%" fill="rgb(242,242,242)" font-family="sans-serif" `
    + `font-size="${Math.round(height / 10)}" text-anchor="middle" dominant-baseline="middle">${label}</text></svg>`;
  return `data:image/svg+xml;utf8,${encodeURIComponent(svg)}`;
}

const ARTICLE = `
<p>Prompt caching lets you reuse a long prefix across requests. Send the same system prompt, tool definitions or document again and the model skips the work it has already done: the first token arrives sooner and the cached part costs a tenth of the price.</p>
<p>I have been using it for a month on a project that asks many questions of one 80,000-token manual. The numbers are not subtle. The median time to first token dropped from 4.1 seconds to 0.9, and the bill for the month came in at a little under a fifth of the month before.</p>
<h2>How it works</h2>
<p>You mark the end of the prefix you want cached. Everything up to that marker is stored for five minutes, and every hit resets the clock. A request that changes anything before the marker misses the cache and pays full price, so put the stable parts first: instructions, then tools, then documents, then the question.</p>
<blockquote><p>The cache is per prefix, not per conversation. Two different users asking about the same manual share the hit.</p></blockquote>
<p>There are two places where the behaviour still surprises people. A tool list that is built in a different order on each request never hits. And an image in the prefix counts as changed if it is re-encoded, even when it looks the same.</p>
<p>The <a href="https://docs.example.org/prompt-caching">documentation</a> has the details, including the minimum cacheable length per model.</p>
`;

const HEADINGS = `
<h1>Heading level one</h1>
<p>Body text under the first heading, at the reading measure, to check the space above and below.</p>
<h2>Heading level two</h2>
<p>A paragraph with <strong>strong</strong>, <em>emphasis</em>, <code>inline code</code> and a <a href="https://example.org">link</a>.</p>
<h3>Heading level three</h3>
<ul><li>An unordered list item</li><li>A second item that is long enough to wrap onto a second line at phone width, to check the hanging indent</li><li>A third</li></ul>
<h4>Heading level four</h4>
<ol><li>First step</li><li>Second step</li><li>Third step</li></ol>
<h5>Heading level five</h5>
<blockquote><p>A quotation, set apart from the body, with enough words to wrap at least once in the column.</p></blockquote>
<h6>Heading level six</h6>
<table><thead><tr><th>Model</th><th>Context</th><th>Price per Mtok</th></tr></thead>
<tbody><tr><td>Large</td><td>1,000,000</td><td>$15.00</td></tr><tr><td>Medium</td><td>200,000</td><td>$3.00</td></tr><tr><td>Small</td><td>200,000</td><td>$0.80</td></tr></tbody></table>
<pre><code class="language-python">import anthropic

client = anthropic.Anthropic()
message = client.messages.create(model="claude-opus-5-5", max_tokens=1024, messages=[{"role": "user", "content": "Hello"}])
print(message.content)</code></pre>
<hr />
<p>The last paragraph, after a rule.</p>
`;

const TELEGRAM = 'Новая открытая модель возглавила многоязычный рейтинг 🚀\n\n'
  + 'A new open-weights model tops the multilingual leaderboard this morning, ahead of last month’s leader by two points on average. '
  + 'Weights are on the hub under a permissive licence; the tech report is promised for next week.\n\n'
  + 'https://t.me/ai_newz/3150';

/** The post page's states by name; the post id in the URL is ignored. */
export function postStateDetail(state: string, now: Date = new Date()): PostDetailResponse | null {
  switch (state) {
    case 'article':
      return detail('p-article', { content_html: ARTICLE, content: ARTICLE.replace(/<[^>]+>/g, '') }, now);
    case 'media':
      return detail('p-media', {
        title: 'Hands-on: the lightest AR glasses yet',
        source_id: 's-roadtovr',
        source: 'https://www.roadtovr.com/feed/',
        source_display_name: 'Road to VR',
        content_html: '<p>We spent an afternoon with the new glasses. The frames weigh 38 grams, the display sits in the lower half of the right lens, and the battery lasts a working day.</p><p>The pictures below are from the demo room; the video is the maker’s own.</p>',
        content: 'We spent an afternoon with the new glasses.',
        images: [
          { url: picture(1600, 900, 'Hero 16:9') },
          { url: picture(900, 1200, 'Portrait 3:4') },
          { url: picture(2000, 200, 'Banner 10:1') },
        ],
        video: { provider: 'youtube', id: 'dQw4w9WgXcQ' },
      } as Partial<Post>, now);
    case 'long-title': {
      const worst = postFixtureDetail('worst');
      return worst ? { ...worst, post: { ...worst.post!, id: 'p-long-title' } } : null;
    }
    case 'headings':
      return detail('p-headings', { title: 'The prose scale, h1 to h6', content_html: HEADINGS, content: HEADINGS.replace(/<[^>]+>/g, '') }, now);
    case 'missing-title':
      return detail('p-missing-title', {
        title: '',
        source_id: 's-newz',
        source: 'https://t.me/s/ai_newz',
        source_display_name: 'ai_newz',
        platform: 'telegram',
        content: TELEGRAM,
        content_html: undefined,
        url: 'https://t.me/ai_newz/3150',
      }, now);
    default:
      return null;
  }
}
