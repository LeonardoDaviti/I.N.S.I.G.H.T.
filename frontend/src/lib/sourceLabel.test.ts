import test from 'node:test';
import assert from 'node:assert/strict';

import { sourceLabel, sourceLabelList } from './sourceLabel.ts';

const DERIVED: Array<[string, string]> = [
  ['https://github.com/anthropics/claude-code/commits.atom', 'anthropics/claude-code'],
  ['github.com/modelcontextprotocol/modelcontextprotocol/commits.atom', 'modelcontextprotocol/modelcontextprotocol'],
  ['https://github.com/anthropics/skills/releases.atom', 'anthropics/skills releases'],
  ['https://rss.arxiv.org/rss/cs.CL', 'arXiv cs.CL'],
  ['rss.arxiv.org/rss/cs.LG', 'arXiv cs.LG'],
  ['http://export.arxiv.org/api/query?search_query=cat:cs.AI&sortBy=submittedDate', 'arXiv cs.AI'],
  ['https://www.reddit.com/r/LocalLLaMA/.rss', 'r/LocalLLaMA'],
  ['https://tg.i-c-a.su/rss/dennis_it?limit=50', '@dennis_it'],
  ['https://simonwillison.net/atom/everything/', 'simonwillison.net'],
  ['simonwillison.net/atom/everything', 'simonwillison.net'],
  ['https://www.seangoedecke.com/rss.xml', 'seangoedecke.com'],
  ['https://nnteacher.bearblog.dev/feed/', 'nnteacher.bearblog.dev'],
  ['https://export.arxiv.org/api/query?search_query=cat:physics.optics+OR+cat:cs.CV&max_results=200', 'arXiv physics.optics'],
  ['https://tg.i-c-a.su/rss/seeall_notes?limit=50', '@seeall_notes'],
  ['https://rsshub.app/telegram/channel/durov', '@durov'],
  ['https://t.me/s/durov', '@durov'],
  ['https://medium.com/@nn_teacher/feed', '@nn_teacher'],
  ['https://feeds.feedburner.com/oreilly/radar', 'oreilly'],
  // The Nitter and Telegram RSS templates' addresses (issue 0027): one name per account, not the host.
  ['https://nitter.local/nn_teacher/rss', '@nn_teacher'],
  ['https://nitter.net/sw_notes/rss', '@sw_notes'],
  ['https://telegram.local/rss/seeall_notes?limit=50', '@seeall_notes'],
];

test('sourceLabel: a feed URL (with or without its scheme) becomes a derived name', () => {
  for (const [raw, label] of DERIVED) assert.equal(sourceLabel(raw), label, raw);
});

test('sourceLabel: real names stay as they are', () => {
  for (const name of ['r/x', 'r/Spectacles (Snap)', 'Road to VR', "Tom's Guide - smart glasses", 'arXiv physics.optics', 'anna_and_ml', 'cs.CL', 'example.com', '9to5Google - Android XR']) {
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

test('sourceLabelList names each source by the one rule', () => {
  assert.equal(sourceLabelList(['Simon Willison', 'https://github.com/anthropics/claude-code/commits.atom', 'danlunotes.com/atom.xml']),
    'Simon Willison, anthropics/claude-code, danlunotes.com');
  assert.equal(sourceLabelList([]), '');
});
