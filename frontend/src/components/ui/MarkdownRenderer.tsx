import ReactMarkdown from 'react-markdown';
import { Link } from 'react-router-dom';
import remarkGfm from 'remark-gfm';
import { decodeEntities } from '../../lib/inertHtml';
import rehypeRaw from 'rehype-raw';
import rehypeSanitize from 'rehype-sanitize';
import { defaultSchema } from 'hast-util-sanitize';

interface MarkdownRendererProps {
  content: string;
  className?: string;
  /** Rewrites each image's src (a post body loads its images through /api/media). */
  imageSrc?: (src: string) => string | undefined;
  /** False for stored plain text: read as markdown only, so a literal "<details>" in it shows as text. */
  html?: boolean;
  /** Links that are stored posts, href as written -> post id: each opens that post in INSIGHT, with a ↗ beside it. */
  internalLinks?: Record<string, string>;
}

/** Strips the indentation in front of tags: feed HTML often arrives indented, and markdown reads four leading
 *  spaces as a code block. */
function dedentHtml(content: string): string {
  return /^\s*</.test(content) ? content.replace(/^[ \t]+(?=<)/gm, '') : content;
}

// eslint-disable-next-line react-refresh/only-export-components
export function normalizeRendererContent(content: string): string {
  const looksLikeEscapedHtml = /&lt;(?:!--|\/?(?:p|div|span|a|img|ul|ol|li|blockquote|code|pre|h[1-6]|table|thead|tbody|tr|td|th))/i.test(content);
  if (!looksLikeEscapedHtml) {
    return dedentHtml(content);
  }

  return dedentHtml(decodeEntities(content).replace(/<!--\s*SC_(?:OFF|ON)\s*-->/g, '').trim());
}

/** A body holds HTML when it has a tag; some feeds store plain text in the HTML field. */
const HTML_TAG_RE = /<\/?[a-z][a-z0-9]*[\s/>]|<!--/i;

const HTML_PLUGINS: NonNullable<Parameters<typeof ReactMarkdown>[0]['rehypePlugins']> = [
  rehypeRaw,
  [
    rehypeSanitize,
    {
      ...defaultSchema,
      // keep figures and a table's caption; GitHub's schema would unwrap them into loose text
      tagNames: [...(defaultSchema.tagNames || []), 'figure', 'figcaption', 'caption'],
      ancestors: { ...defaultSchema.ancestors, caption: ['table'] },
      attributes: {
        ...defaultSchema.attributes,
        a: [
          ...(defaultSchema.attributes?.a || []),
          ['href'],
          ['target'],
          ['rel'],
        ],
        img: [
          ['src'],
          ['alt'],
          ['title'],
          ['width'],
          ['height'],
        ],
      },
    },
  ],
];

export default function MarkdownRenderer({ content, className = "", imageSrc, html = true, internalLinks }: MarkdownRendererProps) {
  if (!content) return null;

  const normalizedContent = html ? normalizeRendererContent(content) : content;
  // Plain text keeps its line breaks; in HTML a source's newlines inside a <p> (hard-wrapped feeds, X's
  // "<br>\n<br>") are only spaces.
  const plainText = !html || !HTML_TAG_RE.test(normalizedContent);

  return (
    <div className={`markdown-content min-w-0 break-words ${className}`}>
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        // without rehype-raw, react-markdown shows any HTML in the text as text
        rehypePlugins={html ? HTML_PLUGINS : []}
        skipHtml={false}
        // monochrome reading styles in em, so the same renderer fits the post column and a chat bubble;
        // hierarchy is weight and size, never hue
        components={{
          p: ({ children }) => (
            <p dir="auto" className={`mb-[1em] text-fg last:mb-0 ${plainText ? 'whitespace-pre-wrap' : ''}`}>
              {children}
            </p>
          ),
          h1: ({ children }) => (
            <h1 dir="auto" className="text-pretty mb-[0.6em] mt-[1.6em] text-[1.5em] font-semibold leading-[1.2] tracking-[-0.02em] text-fg first:mt-0">
              {children}
            </h1>
          ),
          h2: ({ children }) => (
            <h2 dir="auto" className="text-pretty mb-[0.5em] mt-[1.5em] text-[1.25em] font-semibold leading-[1.25] tracking-[-0.015em] text-fg first:mt-0">
              {children}
            </h2>
          ),
          h3: ({ children }) => (
            <h3 dir="auto" className="text-pretty mb-[0.4em] mt-[1.3em] text-[1.05em] font-semibold leading-[1.35] tracking-[-0.01em] text-fg first:mt-0">
              {children}
            </h3>
          ),
          // feeds often mark sections with h4–h6; Tailwind's reset would leave them as body text
          h4: ({ children }) => (
            <h4 dir="auto" className="text-pretty mb-[0.35em] mt-[1.2em] text-[1em] font-semibold leading-[1.4] tracking-[-0.01em] text-fg first:mt-0">
              {children}
            </h4>
          ),
          h5: ({ children }) => (
            <h5 dir="auto" className="text-pretty mb-[0.3em] mt-[1.1em] text-[0.95em] font-semibold leading-[1.4] text-fg first:mt-0">
              {children}
            </h5>
          ),
          h6: ({ children }) => (
            <h6 dir="auto" className="text-pretty mb-[0.3em] mt-[1.1em] text-[0.95em] font-semibold leading-[1.4] text-fg-2 first:mt-0">
              {children}
            </h6>
          ),
          strong: ({ children }) => (
            <strong className="font-semibold text-fg">
              {children}
            </strong>
          ),
          em: ({ children }) => (
            <em className="italic">
              {children}
            </em>
          ),
          ul: ({ children }) => (
            <ul className="mb-[1em] ml-[1.25em] list-disc space-y-[0.35em] marker:text-fg-3">
              {children}
            </ul>
          ),
          ol: ({ children }) => (
            <ol className="mb-[1em] ml-[1.25em] list-decimal space-y-[0.35em] marker:text-fg-3 marker:tabular-nums">
              {children}
            </ol>
          ),
          li: ({ children }) => (
            <li dir="auto" className="pl-[0.2em] text-fg">
              {children}
            </li>
          ),
          blockquote: ({ children }) => (
            <blockquote dir="auto" className="my-[1.25em] border-l-2 border-line-strong pl-[1em] text-fg-2">
              {children}
            </blockquote>
          ),
          // react-markdown 10 has no `inline` flag: `code` is the inline style, a fenced block is `pre > code`
          code: ({ children, className: codeClass }) => (
            <code className={`rounded-sm bg-raised px-[0.3em] py-[0.1em] font-mono text-[0.875em] text-fg [overflow-wrap:anywhere] ${codeClass ?? ''}`}>
              {children}
            </code>
          ),
          // only real code (`pre > code`) keeps its lines and scrolls sideways; a <pre> of bare text is prose
          // (GitHub commit bodies) and wraps, or a 390px screen would cut it off
          pre: ({ children, node }) => {
            const isCode = Boolean(node?.children.some((child) => child.type === 'element' && child.tagName === 'code'));
            const flow = isCode
              ? 'overflow-x-auto [&>code]:[overflow-wrap:normal]'
              : 'whitespace-pre-wrap [overflow-wrap:anywhere] [&>code]:whitespace-pre-wrap';
            return (
              <pre className={`my-[1.25em] max-w-full rounded-md border border-line bg-surface p-[1em] text-[0.85em] leading-[1.6] [&>code]:bg-transparent [&>code]:p-0 [&>code]:text-[1em] ${flow}`}>
                {children}
              </pre>
            );
          },
          img: ({ src, alt, title, width, height }) => {
            const w = Number(width);
            const h = Number(height);
            const sized = w > 0 && h > 0;
            return (
              <img
                src={typeof src === 'string' ? (imageSrc ? imageSrc(src) : src) : undefined}
                alt={alt ?? ''}
                title={title}
                width={sized ? w : undefined}
                height={sized ? h : undefined}
                loading="lazy"
                decoding="async"
                // until a size-less feed image loads it holds a 16:10 frame, so the text does not jump
                onLoad={(event) => { event.currentTarget.dataset.loaded = ''; }}
                // A dead image link would leave a broken-image frame in the text.
                onError={(event) => { event.currentTarget.hidden = true; }}
                className={`my-[1.25em] h-auto max-w-full rounded-md border border-line ${sized ? '' : 'aspect-[16/10] w-full bg-raised object-contain data-[loaded]:aspect-auto data-[loaded]:w-auto data-[loaded]:bg-transparent'}`}
              />
            );
          },
          // a figure keeps its image and caption together, the caption small and muted under it
          figure: ({ children }) => (
            <figure className="my-[1.25em] [&_img]:my-0">
              {children}
            </figure>
          ),
          figcaption: ({ children }) => (
            <figcaption dir="auto" className="mt-[0.6em] text-[0.875em] leading-[1.5] text-fg-2 [&_p]:mb-[0.4em] [&_p]:text-fg-2">
              {children}
            </figcaption>
          ),
          caption: ({ children }) => (
            <caption dir="auto" className="caption-bottom border-t border-line px-[0.85em] py-[0.6em] text-left text-fg-2">
              {children}
            </caption>
          ),
          table: ({ children }) => (
            <div className="my-[1.25em] max-w-full overflow-x-auto rounded-md border border-line">
              <table className="min-w-full border-collapse text-[0.875em] tabular-nums">
                {children}
              </table>
            </div>
          ),
          thead: ({ children }) => (
            <thead>
              {children}
            </thead>
          ),
          tbody: ({ children }) => (
            <tbody>
              {children}
            </tbody>
          ),
          tr: ({ children }) => (
            <tr className="border-b border-line last:border-b-0">
              {children}
            </tr>
          ),
          // a cell keeps its span, so a row of a kept table lines up with its header
          th: ({ children, colSpan, rowSpan }) => (
            <th colSpan={colSpan} rowSpan={rowSpan} className="border-b border-line-strong px-[0.85em] py-[0.6em] text-left font-semibold text-fg">
              {children}
            </th>
          ),
          td: ({ children, colSpan, rowSpan }) => (
            <td colSpan={colSpan} rowSpan={rowSpan} className="px-[0.85em] py-[0.6em] align-top text-fg">
              {children}
            </td>
          ),
          a: ({ href, children }) => {
            const postId = href ? internalLinks?.[href.trim()] : undefined;
            const original = (
              <a
                href={href}
                target="_blank"
                rel="noopener noreferrer"
                className={postId ? 'ml-[0.15em] text-[0.85em] text-fg-3 no-underline hover:text-fg' : 'text-link [overflow-wrap:anywhere]'}
                {...(postId ? { 'aria-label': 'Open the original', title: 'Open the original', 'data-original-link': '' } : {})}
              >
                {postId ? '↗' : children}
              </a>
            );
            return postId ? (
              <>
                <Link to={`/posts/${encodeURIComponent(postId)}`} data-internal-link className="text-link [overflow-wrap:anywhere]">
                  {children}
                </Link>
                {original}
              </>
            ) : original;
          },
          hr: () => (
            <hr className="my-[2em] border-t border-line" />
          ),
        }}
      >
        {normalizedContent}
      </ReactMarkdown>
    </div>
  );
}
