import { lazy, type ComponentType, type LazyExoticComponent } from 'react';

/** One blog post: its metadata, and its body loaded only when the post opens. */
export interface BlogPost {
  slug: string;
  title: string;
  summary: string;
  /** ISO date the post was published. */
  date: string;
  readingMinutes: number;
  Body: LazyExoticComponent<ComponentType>;
}

/** Newest first. */
export const POSTS: readonly BlogPost[] = [
  {
    slug: 'junior-to-senior',
    title: 'From junior to senior: how INSIGHT is learning to maintain itself',
    summary:
      'INSIGHT grew from 964 lines to 99,059 in sixteen months, and about half is weight. Five junior habits behind it, with real code; the image diet from 949 MB to 464 MB and what it teaches; and the decision to retire analysis, weighed both ways.',
    date: '2026-10-11',
    readingMinutes: 22,
    Body: lazy(() => import('./posts/junior-to-senior')),
  },
];

export function findPost(slug: string | undefined): BlogPost | undefined {
  return POSTS.find((post) => post.slug === slug);
}
