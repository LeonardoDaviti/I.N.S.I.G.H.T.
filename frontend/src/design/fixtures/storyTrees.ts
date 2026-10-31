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
