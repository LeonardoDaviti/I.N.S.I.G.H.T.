import test from 'node:test';
import assert from 'node:assert/strict';

import { coveredBy, originHref, originLabel, repostLine, storyTree, suggestionReason } from './story.ts';
import { citedBy } from './classics.ts';

const story = (names: string[]) => ({ id: 's', voices: names.length, posts: [], sources: names.map((name, i) => ({ id: String(i), name })) });

test('coveredBy names two sources, then counts the rest', () => {
  assert.equal(coveredBy(story(['Anthropic', 'Simon Willison'])), 'covered by 2 · Anthropic, Simon Willison');
  assert.equal(coveredBy(story(['Anthropic', 'Simon Willison', 'https://tg.i-c-a.su/rss/denissexy?limit=50', 'B'])),
    'covered by 4 · Anthropic, Simon Willison, +2');
});

test('suggestionReason says how many of your sources link it, who, and how many articles', () => {
  assert.equal(suggestionReason({
    key: 'metr.org', url: 'https://metr.org', voices: 1, article_count: 1, link_count: 1, voice_names: ['Simon Willison'], articles: [],
  }), 'linked by 1 of your sources (Simon Willison) · 1 article');
  assert.equal(suggestionReason({
    key: 'darioamodei.com', url: 'https://darioamodei.com', voices: 4, article_count: 8, link_count: 8,
    voice_names: ['A', 'B', 'C', 'D'], articles: [], classics: 2,
  }), 'linked by 4 of your sources (A, B, C, +1) · 8 articles · 2 classics', 'a site that holds classics says so (issue 0051)');
});

test('a story, a suggestion and a classic name a source without a display name by its address (server data)', () => {
  // The backend sends the address when a source has no display name, or an empty one.
  assert.equal(coveredBy(story(['https://github.com/anthropics/claude-code/commits.atom', 'https://danluu.com/atom.xml'])),
    'covered by 2 · anthropics/claude-code, danluu.com');
  assert.equal(suggestionReason({
    key: 'metr.org', url: 'https://metr.org', voices: 2, article_count: 1, link_count: 2,
    voice_names: ['https://www.reddit.com/r/LocalLLaMA/.rss', 'http://antirez.com/rss'], articles: [],
  }), 'linked by 2 of your sources (r/LocalLLaMA, antirez.com) · 1 article');
  assert.equal(citedBy({ citers: [{ name: 'https://www.theatlantic.com/feed/author/derek-thompson/', at: '2026-03-15T12:00:00Z' }] }),
    'theatlantic.com, Mar 2026');
});

// ---- stories as trees (issue 0064) -------------------------------------------------------------

type Reason = 'address' | 'repost' | 'thread' | 'quote' | 'citation' | 'copy' | 'time' | 'none';
const at = (h: number) => new Date(Date.UTC(2026, 9, 26, h)).toISOString();
const sp = (id: string, h: number, parent_id: string | null, parent_reason: Reason | null) => ({
  id, title: id, url: `https://x.test/${id}`, source_id: id, source_display_name: id, platform: 'rss',
  sort_at: at(h), published_at: null, read_at: null, role: 'report' as const, parent_id, parent_reason,
});
const lines = (tree: ReturnType<typeof storyTree>) =>
  tree.map((l) => `${'  '.repeat(l.depth)}${l.kind === 'post' ? l.post.id : l.kind === 'page' ? 'PAGE' : 'SELF'}`);

test('storyTree: the origin row lists what came from it, two levels of indent at most (GPT-6.1 Terra)', () => {
  const terra = {
    id: 'openai', voices: 4, first: 'openai', sources: [], parent_id: null, parent_reason: null,
    posts: [sp('hn', 18, 'openai', 'address'), sp('ds', 19, 'openai', 'citation'), sp('simon', 23, 'openai', 'citation'),
      sp('lw', 30, 'simon', 'citation'), sp('deeper', 31, 'lw', 'citation')],
  };
  assert.deepEqual(lines(storyTree(terra, 'openai', at(0))), ['hn', 'ds', 'simon', '  lw', '  deeper']);
});

test('storyTree: on another post the origin comes first and this post sits in its place', () => {
  const story = {
    id: 'openai', voices: 4, first: 'openai', sources: [], parent_id: 'openai', parent_reason: 'citation' as const,
    posts: [sp('openai', 0, null, null), sp('hn', 18, 'openai', 'address'), sp('lw', 30, 'simon', 'citation'), sp('x', 32, 'lw', 'copy')],
  };
  assert.deepEqual(lines(storyTree(story, 'simon', at(23))), ['openai', '  hn', '  SELF', '    lw', '    x']);
});

test('storyTree: an outside page origin heads the list, its citers under it', () => {
  const story = {
    id: 'a', voices: 3, first: null, sources: [], parent_id: null, parent_reason: 'citation' as const,
    origin: { url: 'https://www.anthropic.com/news/claude-fable-5', title: 'Claude Fable 5', linked_by: 3 },
    posts: [sp('b', 2, null, 'citation'), sp('c', 3, 'b', 'citation')],
  };
  assert.deepEqual(lines(storyTree(story, 'a', at(1))), ['PAGE', '  SELF', '  b', '    c']);
  assert.deepEqual(originLabel(story.origin), { site: 'anthropic.com', title: 'Claude Fable 5', linkedBy: 'linked by 3' });
  assert.equal(originHref(story.origin), '/save?url=https%3A%2F%2Fwww.anthropic.com%2Fnews%2Fclaude-fable-5&title=Claude+Fable+5');
  assert.equal(originLabel({ url: 'https://openai.com/index/gpt-6-astra', title: null, linked_by: 10 }).title, 'openai.com/index/gpt-6-astra');
});

// ---- X: reposts, quotes and threads (issue 0066) ------------------------------------------------

test('a thread is one item: "Thread · 6 posts", its replies a list in their order, a quote of it under its root', () => {
  // badlogicgames, 27 Oct: "software is dead. sad." and five replies to itself, two of them in one hour's tie.
  const thread = {
    id: 't0', voices: 1, first: 't0', sources: [{ id: 'bg', name: 'badlogicgames' }], parent_id: null, parent_reason: null, thread: true,
    posts: [sp('t1', 8, 't0', 'thread'), sp('t2', 9, 't1', 'thread'), sp('t3', 9, 't2', 'thread'), sp('t4', 9, 't3', 'thread'),
      sp('t5', 10, 't4', 'thread'), sp('giraffe', 11, 't0', 'quote')],
  };
  assert.equal(coveredBy({ ...thread, posts: thread.posts.slice(0, 5) }), 'Thread · 6 posts');
  assert.deepEqual(lines(storyTree(thread, 't0', at(7))), ['t1', 't2', 't3', 't4', 't5', 'giraffe']);
  const atReply = {
    ...thread, parent_id: 't2', parent_reason: 'thread' as const,
    posts: [sp('t0', 7, null, null), ...thread.posts.filter((p) => p.id !== 't3')],
  };
  assert.deepEqual(lines(storyTree(atReply, 't3', at(9))), ['t0', '  t1', '  t2', '  SELF', '  t4', '  t5', '  giraffe'],
    'opened at a reply: the root first, the thread in its order under it');
});

test('repostLine names who reposted a tweet, and its author', () => {
  assert.equal(repostLine({ by: ['steipete'], author: 'badlogicgames' }), '↻ @steipete, from @badlogicgames');
  assert.equal(repostLine({ by: ['_akhaliq', 'ggerganov'], author: 'ClementDelangue' }), '↻ @_akhaliq, @ggerganov, from @ClementDelangue');
});

test('storyTree: no tree (before the job drew it, News) lists the posts flat, as before', () => {
  const story = { id: 'a', voices: 2, sources: [], posts: [sp('b', 2, null, null), sp('c', 3, null, null)] };
  assert.deepEqual(lines(storyTree(story, 'a')), ['b', 'c']);
});
