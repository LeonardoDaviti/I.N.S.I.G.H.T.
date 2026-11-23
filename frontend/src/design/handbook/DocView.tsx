import MarkdownRenderer from '../../components/ui/MarkdownRenderer';
import type { DesignDoc } from '../coverage';
import { docBody } from '../studio';

/** A design doc in the centred reading column, through the app's own renderer. */
export default function DocView({ doc }: { doc: DesignDoc }) {
  return (
    <article className="mx-auto w-full max-w-reading text-[1rem] leading-[1.65]">
      <MarkdownRenderer content={docBody(doc)} />
    </article>
  );
}
