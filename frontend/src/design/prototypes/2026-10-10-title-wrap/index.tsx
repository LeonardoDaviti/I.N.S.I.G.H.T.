import type { ReactNode } from 'react';

/** A frame override: only the post title (the post header's `h1`) wraps normally; body headings keep `pretty`. The
 *  id in the selector outranks the page's `text-pretty` class. */
const TITLE_WRAP = 'main#main header > h1 { text-wrap: wrap; }';

export default function TitleWrapPrototype({ children }: { children: ReactNode }) {
  return (
    <>
      <style>{TITLE_WRAP}</style>
      {children}
    </>
  );
}
