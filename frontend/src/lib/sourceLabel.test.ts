import test from 'node:test';
import assert from 'node:assert/strict';

import { sourceLabel } from './sourceLabel.ts';

const DERIVED: Array<[string, string]> = [
  ['https://github.com/anthropics/claude-code/commits.atom', 'anthropics/claude-code'],
  ['github.com/modelcontextprotocol/modelcontextprotocol/commits.atom', 'modelcontextprotocol/modelcontextprotocol'],
  ['https://github.com/anthropics/skills/releases.atom', 'anthropics/skills releases'],
  ['https://rss.arxiv.org/rss/cs.CL', 'arXiv cs.CL'],
  ['rss.arxiv.org/rss/cs.LG', 'arXiv cs.LG'],
  ['http://export.arxiv.org/api/query?search_query=cat:cs.AI&sortBy=submittedDate', 'arXiv cs.AI'],
  ['https://www.reddit.com/r/LocalLLaMA/.rss', 'r/LocalLLaMA'],
  ['https://tg.i-c-a.su/rss/denissexy?limit=50', '@denissexy'],
  ['https://simonwillison.net/atom/everything/', 'simonwillison.net'],
  ['simonwillison.net/atom/everything', 'simonwillison.net'],
  ['https://www.seangoedecke.com/rss.xml', 'seangoedecke.com'],
  ['https://karpathy.bearblog.dev/feed/', 'karpathy.bearblog.dev'],
  ['https://export.arxiv.org/api/query?search_query=cat:physics.optics+OR+cat:cs.CV&max_results=200', 'arXiv physics.optics'],
  ['https://tg.i-c-a.su/rss/seeallochnaya?limit=50', '@seeallochnaya'],
  ['https://rsshub.app/telegram/channel/durov', '@durov'],
  ['https://t.me/s/durov', '@durov'],
  ['https://medium.com/@karpathy/feed', '@karpathy'],
  ['https://feeds.feedburner.com/oreilly/radar', 'oreilly'],
  // The Nitter and Telegram RSS templates' addresses (issue 0027): one name per account, not the host.
  ['https://nitter.local/karpathy/rss', '@karpathy'],
  ['https://nitter.net/simonw/rss', '@simonw'],
  ['https://telegram.local/rss/seeallochnaya?limit=50', '@seeallochnaya'],
];

test('sourceLabel: a feed URL (with or without its scheme) becomes a derived name', () => {
  for (const [raw, label] of DERIVED) assert.equal(sourceLabel(raw), label, raw);
});

test('sourceLabel: real names stay as they are', () => {
  for (const name of ['r/x', 'r/Spectacles (Snap)', 'Road to VR', "Tom's Guide - smart glasses", 'arXiv physics.optics', 'adel_and_ml', 'cs.CL', 'example.com', '9to5Google - Android XR']) {
    assert.equal(sourceLabel(name), name);
  }
});

test('sourceLabel: the first real display name wins over a URL', () => {
  assert.equal(sourceLabel('https://rss.arxiv.org/rss/cs.AI', 'arXiv AI'), 'arXiv AI');
  assert.equal(sourceLabel(null, '', 'https://rss.arxiv.org/rss/cs.AI'), 'arXiv cs.AI');
});

test('sourceLabel: a missing name says so', () => {
  assert.equal(sourceLabel(null), 'Unknown source');
  assert.equal(sourceLabel('  ', undefined), 'Unknown source');
});
