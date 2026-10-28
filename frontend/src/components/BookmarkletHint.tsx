import { useEffect, useRef } from 'react';
import { bookmarkletCode } from '../lib/savePage';

/**
 * The bookmarklet, to drag to the bookmarks bar. React blocks a `javascript:` href
 * it renders, so the href is set on the element itself.
 */
function BookmarkletLink() {
  const ref = useRef<HTMLAnchorElement>(null);
  useEffect(() => {
    ref.current?.setAttribute('href', bookmarkletCode(window.location.origin));
  }, []);
  return (
    <a
      ref={ref}
      onClick={(event) => event.preventDefault()}
      className="inline-flex min-h-[2rem] cursor-grab items-center rounded-md border border-line-strong px-3 text-[0.8125rem] font-medium text-fg"
    >
      Save to INSIGHT
    </a>
  );
}

/** One quiet line with the bookmarklet (the save page, the Add source dialog). */
export default function BookmarkletHint() {
  return (
    <p className="flex flex-wrap items-center gap-x-2 gap-y-1 text-[0.75rem] text-fg-3">
      <span>Save pages from any site: drag</span>
      <BookmarkletLink />
      <span>to your bookmarks bar, then click it on a page you want to keep.</span>
    </p>
  );
}
