import { useCallback, useEffect, useRef, useState, type RefObject } from 'react';
import { useQueryClient } from '@tanstack/react-query';

import type { Api, PostDetailResponse } from '../services/api';
import { patchFeeds } from './useReaderMutations';
import { postKey } from './usePost';

/** About three screens of text: a shorter post is read in one go, nothing to continue. */
export const LONG_POST_CHARS = 4500;
/** Saved once scrolling has stopped this long, and at once on leaving. */
export const SAVE_AFTER_MS = 3000;

/**
 * The share of a post read, when worth showing (issue 0030): started (5%) and not
 * nearly done (90%); otherwise null. The post's offer and its feed row use the same.
 */
export function resumeShare(block?: number | null, blocks?: number | null): number | null {
  if (block == null || !blocks) return null;
  const share = block / blocks;
  return share >= 0.05 && share <= 0.9 ? share : null;
}

/** The body's text blocks, in order: what a position counts. */
const BLOCKS = 'p, li, h1, h2, h3, h4, h5, h6, pre, blockquote, table, figure';

/** The line under the sticky navigation: the top of what can be read. */
function readingLine(): number {
  return document.querySelector('[data-nav-band]')?.getBoundingClientRect().bottom ?? 0;
}

/** The top block in view of `body`, or null when the line is not inside the body. */
function topBlock(body: HTMLElement): [number, number] | null {
  const line = readingLine();
  const rect = body.getBoundingClientRect();
  if (rect.top > line || rect.bottom <= line) return null;
  const blocks = body.querySelectorAll(BLOCKS);
  for (let i = 0; i < blocks.length; i += 1) {
    if (blocks[i].getBoundingClientRect().bottom > line) return [i, blocks.length];
  }
  return null;
}

interface Options {
  postId: string;
  api: Api;
  /** The post body: its text blocks are counted. */
  body: RefObject<HTMLElement | null>;
  /** The end of the post: once it passes the top half of the screen, the post is finished. */
  end: RefObject<HTMLElement | null>;
  /** Where the post was left, from its reader state. */
  saved: { resume_block?: number | null; resume_blocks?: number | null } | null;
  /** Long enough to track at all (LONG_POST_CHARS); off for fixtures and videos. */
  enabled: boolean;
  /** The post opened from the URL offers to continue; one joining the stream below does not. */
  offer: boolean;
}

/**
 * Continue where I stopped (issue 0030). The position is a block, not a scroll offset,
 * so images loading or another width do not move it. Nothing is saved until you scroll;
 * then a few seconds after scrolling stops, and at once when the tab hides or the post
 * leaves; while the offer stands, only a place past the old one replaces it. Reaching
 * the end clears it. Nothing scrolls by itself: `resume` is a button's.
 */
export function useReadingPosition({ postId, api, body, end, saved, enabled, offer }: Options) {
  const queryClient = useQueryClient();
  const [offered] = useState(() => (offer && enabled ? resumeShare(saved?.resume_block, saved?.resume_blocks) : null));
  const [offerOpen, setOfferOpen] = useState(offered !== null);
  // While the offer stands, scrolling about above the old place does not overwrite it.
  const keepOld = useRef(offered !== null);
  const stored = useRef(saved?.resume_block ?? null);
  const finished = useRef(false);

  const store = useCallback((block: number | null, blocks: number | null) => {
    stored.current = block;
    void api.savePostPosition(postId, block, blocks);
    // The feed row and a cached copy of the post show the same position.
    patchFeeds(queryClient, new Set([postId]), { resume_block: block, resume_blocks: blocks });
    queryClient.setQueryData<PostDetailResponse>(postKey(postId), (data) => (
      data ? { ...data, reader_state: { ...data.reader_state, resume_block: block, resume_blocks: blocks } } : data
    ));
  }, [api, postId, queryClient]);

  useEffect(() => {
    if (!enabled) return undefined;
    let pending: [number, number] | null = null;
    let timer: number | undefined;
    const flush = () => {
      window.clearTimeout(timer);
      const at = pending;
      pending = null;
      if (!at || finished.current || at[0] === stored.current) return;
      if (keepOld.current && stored.current !== null && at[0] < stored.current) return;
      keepOld.current = false;
      store(at[0], at[1]);
      setOfferOpen(false); // you read on past it: the old position is gone
    };
    const onScroll = () => {
      const node = body.current;
      const at = node && !finished.current ? topBlock(node) : null;
      if (!at) return;
      pending = at;
      window.clearTimeout(timer);
      timer = window.setTimeout(flush, SAVE_AFTER_MS);
    };
    const onVisibility = () => { if (document.hidden) flush(); };
    window.addEventListener('scroll', onScroll, { passive: true });
    document.addEventListener('visibilitychange', onVisibility);
    return () => {
      window.removeEventListener('scroll', onScroll);
      document.removeEventListener('visibilitychange', onVisibility);
      flush();
    };
  }, [body, enabled, store]);

  // Finished: the end has passed the top half of the screen, the moment the stream counts it read.
  useEffect(() => {
    const node = end.current;
    if (!enabled || !node || typeof IntersectionObserver === 'undefined') return undefined;
    const observer = new IntersectionObserver(([entry]) => {
      if (!entry?.isIntersecting) return;
      observer.disconnect();
      finished.current = true;
      setOfferOpen(false);
      if (stored.current !== null) store(null, null);
    }, { rootMargin: '100000px 0px -50% 0px' });
    observer.observe(node);
    return () => observer.disconnect();
  }, [enabled, end, store]);

  const resume = useCallback(() => {
    setOfferOpen(false);
    keepOld.current = false;
    const blocks = body.current?.querySelectorAll<HTMLElement>(BLOCKS);
    const count = saved?.resume_blocks;
    if (!blocks?.length || saved?.resume_block == null || !count) return;
    // The same body has the same blocks; scale in case it changed since.
    const index = Math.min(blocks.length - 1, Math.round((saved.resume_block * blocks.length) / count));
    const target = blocks[index];
    target.style.scrollMarginTop = 'calc(var(--topbar-h) + 3rem)';
    target.scrollIntoView?.({ block: 'start' });
    // Focus follows, so a keyboard or a screen reader carries on from there.
    target.tabIndex = -1;
    target.focus({ preventScroll: true });
  }, [body, saved]);

  return {
    /** The offer's percentage while it is shown, else null. */
    offerPercent: offerOpen && offered !== null ? Math.round(offered * 100) : null,
    resume,
  };
}
