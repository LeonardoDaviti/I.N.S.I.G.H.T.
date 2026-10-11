import { describe, expect, it } from 'vitest';

import { parseDoc } from './coverage';
import {
  acceptInstruction, isOpen, parsePrototype, prototypeAge, prototypeProblems, rejectInstruction,
} from './prototypes';

const README = [
  '```meta',
  'hypothesis: Normal wrap fills the first line, and reads better than pretty',
  'principles: P1, P4',
  'page: post',
  'states: long-title, article',
  'status: review',
  'created: 2026-10-10',
  '```',
  '',
  '# Post title: normal wrap',
  '',
  'Body.',
].join('\n');

const known = {
  principles: new Set([1, 2, 3, 4]),
  hasState: (page: string, state: string) => page === 'post' && ['article', 'long-title'].includes(state),
};

describe('parsePrototype', () => {
  it('reads the meta block of a prototype README, keeping commas in the hypothesis', () => {
    const prototype = parsePrototype('2026-10-10-title-wrap', README);
    expect(prototype).toMatchObject({
      id: '2026-10-10-title-wrap',
      slug: 'title-wrap',
      title: 'Post title: normal wrap',
      hypothesis: 'Normal wrap fills the first line, and reads better than pretty',
      principles: [1, 4],
      page: 'post',
      states: ['long-title', 'article'],
      status: 'review',
      created: '2026-10-10',
    });
  });
});

describe('prototypeProblems', () => {
  it('accepts a complete prototype', () => {
    expect(prototypeProblems(parsePrototype('2026-10-10-title-wrap', README), known)).toEqual([]);
  });

  it('names every gap: folder name, status, date, hypothesis, principles, page and states', () => {
    const broken = README
      .replace('status: review', 'status: shipped')
      .replace('created: 2026-10-10', 'created: 2026-10-09')
      .replace(/hypothesis: .*/, '')
      .replace('P1, P4', 'P4, P13')
      .replace('states: long-title, article', 'states: long-title, huge');
    expect(prototypeProblems(parsePrototype('title-wrap', broken), known)).toEqual([
      'prototypes/title-wrap: the folder is not named <yyyy-mm-dd>-<slug>',
      'prototypes/title-wrap: status "shipped" is not draft, review, accepted or rejected',
      'prototypes/title-wrap: created 2026-10-09 does not match the folder date',
      'prototypes/title-wrap: no one-sentence hypothesis',
      'prototypes/title-wrap: cites P13, which principles.md does not define',
      'prototypes/title-wrap: post/huge has no page doc state or frame scenario',
    ]);
  });

  it('wants at least one principle, a page and a state', () => {
    const bare = '```meta\nhypothesis: H.\nstatus: draft\ncreated: 2026-10-10\n```\n# Bare';
    expect(prototypeProblems(parsePrototype('2026-10-10-bare', bare), known)).toEqual([
      'prototypes/2026-10-10-bare: serves no principle',
      'prototypes/2026-10-10-bare: names no page to compare against',
      'prototypes/2026-10-10-bare: names no state to compare on',
    ]);
  });
});

describe('the lifecycle (D6)', () => {
  it('keeps draft and review open; accepted and rejected are closed', () => {
    const at = (status: string) => parsePrototype('2026-10-10-x', README.replace('status: review', `status: ${status}`));
    expect(['draft', 'review', 'accepted', 'rejected'].map((status) => isOpen(at(status)))).toEqual([true, true, false, false]);
  });

  it('says how old a prototype is, in whole days', () => {
    const prototype = parsePrototype('2026-10-10-title-wrap', README);
    expect(prototypeAge(prototype, new Date('2026-10-10T18:00:00'))).toBe('today');
    expect(prototypeAge(prototype, new Date('2026-10-11T09:00:00'))).toBe('1 day');
    expect(prototypeAge(prototype, new Date('2026-10-24T09:00:00'))).toBe('14 days');
  });

  it('turns accept and reject into the instruction the agent takes', () => {
    expect(acceptInstruction('2026-10-10-title-wrap')).toBe('accept prototype 2026-10-10-title-wrap');
    expect(rejectInstruction('2026-10-10-title-wrap', '  pretty reads calmer ')).toBe('reject prototype 2026-10-10-title-wrap: pretty reads calmer');
    expect(rejectInstruction('2026-10-10-title-wrap', ' ')).toBe('reject prototype 2026-10-10-title-wrap: <reason>');
  });
});
