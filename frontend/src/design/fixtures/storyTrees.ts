/**
 * Stories as trees (issue 0064), from the lab's real cases: GPT-6.1 Terra (OpenAI's own post is
 * the origin; HN's row of its address and two citers under it, LessWrong under Simon) and
 * Claude Fable 5 (the origin is Anthropic's page, outside INSIGHT, linked by 14; this row is one
 * of its citers, a copy under another).
 */
import type { FeedItem, StoryPost, StoryParentReason } from '../../services/api';
import { feedItem } from '../../components/reader/fixtures';
import { HOUR, at, sourceId } from './sites';

function storyPost(now: Date, id: string, source: string, name: string, title: string, hoursAgo: number,
  parent: string | null, reason: StoryParentReason, extra: Partial<StoryPost> = {}): StoryPost {
  const when = at(now, -hoursAgo * HOUR);
  return {
    id, title, url: `https://example.org/${id}`, source_id: sourceId(source), source_display_name: name, platform: 'rss',
    sort_at: when, published_at: when, read_at: null, role: 'report', parent_id: parent, parent_reason: reason, ...extra,
  };
}

/**
 * X (issue 0066), from the lab: badlogicgames' thread "software is dead. sad." (5 replies to
 * itself, and a quote of its first post 2 hours later: one row "Thread · 7 posts"), and
 * steipete's repost of badlogicgames' tweet.
 */
export const THREAD_REPLIES: [string, string, number][] = [
  ['p-bg-1', 'pretty joyless now. guess i switch to gardening.', 4.9],
  ['p-bg-2', "there will remain some niche holdouts, where some bespoke, artisan, well crafted piece of software is still appreciated.\n\nbut i'm too tired to find such a niche.", 4.8],
  ['p-bg-3', "and it's not like the new kind of software is any good by the old standards (and yes, that was true for most old software as well).\n\nit just doesn't matter anymore.", 4.7],
  ['p-bg-4', 'and unsurprisingly, instead of being aghast at all this and its effects on humanity at large, many of my peers clap.', 4.6],
  ['p-bg-5', "if this tech would actually solve the big problems, i'd be all for it. but it's mostly used to make more slop, faster.", 4.5],
];

export function xItems(now: Date): FeedItem[] {
  const replies = THREAD_REPLIES.map(([id, text, hoursAgo], i) => storyPost(now, id, 's-bg', 'badlogicgames', text.split('\n')[0], hoursAgo,
    i ? THREAD_REPLIES[i - 1][0] : 'p-bg', 'thread', { text, url: `https://nitter.local/badlogicgames/status/${id}`, read_at: i < 2 ? at(now, -HOUR) : null }));
  const thread = feedItem({
    id: 'p-bg', title: 'software is dead. sad.', excerpt: '', source_id: sourceId('s-bg'), source_display_name: 'badlogicgames',
    url: 'https://nitter.local/badlogicgames/status/2115002476311241104#m', sort_at: at(now, -5 * HOUR), published_at: at(now, -5 * HOUR), read_at: null,
    story: { id: 'p-bg', voices: 1, first: 'p-bg', parent_id: null, parent_reason: null, origin: null, thread: true,
      sources: [{ id: sourceId('s-bg'), name: 'badlogicgames' }],
      posts: [...replies, storyPost(now, 'p-bg-giraffe', 's-bg', 'badlogicgames', 'this thread is brought to you by this very cool giraffe', 3,
        'p-bg', 'quote')] },
  }, now);
  const repost = feedItem({
    id: 'p-steipete-rt', title: 'how i work with agents in 2026.', excerpt: 'ignore all other guides on here.',
    source_id: sourceId('s-steipete'), source_display_name: 'steipete', sort_at: at(now, -2 * HOUR), published_at: at(now, -2 * HOUR),
    url: 'https://nitter.local/badlogicgames/status/2114444636303364349#m', read_at: null, repost: { by: ['steipete'], author: 'badlogicgames' },
  }, now);
  return [repost, thread];
}

export function storyTreeItems(now: Date): FeedItem[] {
  const terra = feedItem({
    id: 'p-terra', title: 'Introducing GPT-6.1 Terra',
    excerpt: 'GPT-6.1 Terra is our new everyday model: close to Sol on most benchmarks at a fifth of the price.',
    url: 'https://openai.com/index/introducing-gpt-6-1-terra', source_id: sourceId('s-openai'), source_display_name: 'OpenAI News',
    sort_at: at(now, -6 * HOUR), published_at: at(now, -6 * HOUR), read_at: null,
    story: {
      id: 'p-terra', voices: 5, first: 'p-terra', parent_id: null, parent_reason: null, origin: null,
      sources: [{ id: sourceId('s-openai'), name: 'OpenAI News' }, { id: sourceId('s-hn'), name: 'Hacker News: Front Page' },
        { id: sourceId('s-ds'), name: 'data_secrets' }, { id: sourceId('s-simon'), name: 'Simon Willison’s Weblog' },
        { id: sourceId('s-lw'), name: 'LessWrong' }],
      posts: [
        storyPost(now, 'p-terra-hn', 's-hn', 'Hacker News: Front Page', 'GPT-6.1 Terra', 5.5, 'p-terra', 'address', { role: 'share' }),
        storyPost(now, 'p-terra-ds', 's-ds', 'data_secrets', 'Вышла GPT-6.1 Terra: почти как Sol, но в пять раз дешевле', 5.3, 'p-terra', 'citation'),
        storyPost(now, 'p-terra-simon', 's-simon', 'Simon Willison’s Weblog', 'GPT-6.1 Terra', 3, 'p-terra', 'citation', { read_at: at(now, -HOUR) }),
        storyPost(now, 'p-terra-lw', 's-lw', 'LessWrong', 'AI #192: the week in models, with notes on Terra’s pricing', 1, 'p-terra-simon', 'citation'),
      ],
    },
  }, now);
  const fable = feedItem({
    id: 'p-fable', title: 'Вышел Claude 5 Fable', source_id: sourceId('s-newz'), source_display_name: 'ai_newz', platform: 'telegram',
    excerpt: 'Это общедоступная версия Mythos, в которой Anthropic убрала кибер-возможности.',
    sort_at: at(now, -8 * HOUR), published_at: at(now, -8 * HOUR), read_at: null,
    story: {
      id: 'p-fable', voices: 4, first: null, parent_id: null, parent_reason: 'citation',
      origin: { url: 'https://www.anthropic.com/news/claude-fable-5-mythos-5', title: 'Claude Fable 5 and Mythos 5', linked_by: 14 },
      sources: [{ id: sourceId('s-newz'), name: 'ai_newz' }, { id: sourceId('s-denis'), name: 'denissexy' },
        { id: sourceId('s-toshoseti'), name: 'toshoseti' }, { id: sourceId('s-simon'), name: 'Simon Willison’s Weblog' }],
      posts: [
        storyPost(now, 'p-fable-denis', 's-denis', 'denissexy', 'Вышла новая модель от Claude: Fable 5, которая кодит лучше чем Opus', 7.9, null, 'citation'),
        storyPost(now, 'p-fable-tosho', 's-toshoseti', 'toshoseti', 'Вышла новая модель от Claude: Fable 5, которая кодит лучше чем Opus', 7.5, 'p-fable-denis', 'copy', { role: 'share' }),
        storyPost(now, 'p-fable-simon', 's-simon', 'Simon Willison’s Weblog', 'Initial impressions of Claude Fable 5', 2, null, 'citation'),
      ],
    },
  }, now);
  return [terra, fable];
}
