import MarkdownRenderer from '../../../components/ui/MarkdownRenderer';
import { Variant, Variants } from '../parts';

const SAMPLE = `## A section heading

A paragraph at the reading size with **bold**, *italic*, \`inline code\` and [a link](https://example.com).

- a list item
- another, a little longer, so it wraps on a phone

> A quote in the secondary tone.

| Step | Size |
| --- | --- |
| display | 1.75rem |
| reading | 1.125rem |

\`\`\`ts
const tone = 'monochrome';
\`\`\``;

/** Prose in em units at the post's reading size: headings, lists, quote, table, code. */
export default function MarkdownRendererSpecimen() {
  return (
    <Variants>
      <Variant label="reading · 1.125rem" wide>
        <div className="w-full max-w-reading text-reading">
          <MarkdownRenderer content={SAMPLE} />
        </div>
      </Variant>
      <Variant label="empty">
        <MarkdownRenderer content="" />
      </Variant>
    </Variants>
  );
}
