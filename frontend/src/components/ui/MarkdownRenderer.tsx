import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import rehypeRaw from 'rehype-raw';
import rehypeSanitize from 'rehype-sanitize';
import { defaultSchema } from 'hast-util-sanitize';

interface MarkdownRendererProps {
  content: string;
  className?: string;
  /** Rewrites each image's src (a post body loads its images through /api/media). */
  imageSrc?: (src: string) => string | undefined;
  /**
   * False for stored plain text (a post with no HTML body): it is read as markdown only, so
   * a literal "<details>" or "&lt;p&gt;" in it shows as text, never as an element.
   */
  html?: boolean;
}

function decodeHtmlEntities(input: string): string {
  if (typeof document === 'undefined') {
    return input
      .replace(/&lt;/g, '<')
      .replace(/&gt;/g, '>')
      .replace(/&amp;/g, '&')
      .replace(/&quot;/g, '"')
      .replace(/&#39;/g, "'");
  }

  const textarea = document.createElement('textarea');
  textarea.innerHTML = input;
  return textarea.value;
}

/**
 * Feed HTML often arrives indented ("\n    <p>On Friday…"). Markdown reads four
 * leading spaces as a code block, so the whole article rendered as one
 * monospaced line of raw tags. Strip the indentation in front of tags.
 */
function dedentHtml(content: string): string {
  return /^\s*</.test(content) ? content.replace(/^[ \t]+(?=<)/gm, '') : content;
}

// Exported for tests.
// eslint-disable-next-line react-refresh/only-export-components
export function normalizeRendererContent(content: string): string {
  const looksLikeEscapedHtml = /&lt;(?:!--|\/?(?:p|div|span|a|img|ul|ol|li|blockquote|code|pre|h[1-6]|table|thead|tbody|tr|td|th))/i.test(content);
  if (!looksLikeEscapedHtml) {
    return dedentHtml(content);
  }

  return dedentHtml(decodeHtmlEntities(content).replace(/<!--\s*SC_(?:OFF|ON)\s*-->/g, '').trim());
}

const HTML_PLUGINS: NonNullable<Parameters<typeof ReactMarkdown>[0]['rehypePlugins']> = [
  rehypeRaw,
  [
    rehypeSanitize,
    {
      ...defaultSchema,
      // The reader keeps an article's figures and a table's caption (issue 0042); GitHub's
      // schema would unwrap them into loose text.
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

export default function MarkdownRenderer({ content, className = "", imageSrc, html = true }: MarkdownRendererProps) {
  if (!content) {
    return <p className="text-fg-3">No content available</p>;
  }

  const normalizedContent = html ? normalizeRendererContent(content) : content;

  return (
    <div className={`markdown-content min-w-0 break-words ${className}`}>
      <ReactMarkdown
        // Enable GFM and treat single newlines as breaks
        remarkPlugins={[remarkGfm]}
        // Without rehype-raw, react-markdown shows any HTML in the text as text.
        rehypePlugins={html ? HTML_PLUGINS : []}
        skipHtml={false}
        // Monochrome reading styles (design docs system/typography.md): sizes and spacing are in em so
        // the same renderer reads well in the 1.125rem post column and in a small
        // chat bubble. Hierarchy is weight and size, never hue.
        components={{
          // Custom paragraph to preserve single line breaks from plain text sources
          p: ({ children }) => (
            <p dir="auto" className="mb-[1em] whitespace-pre-wrap text-fg last:mb-0">
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
          // Feeds often mark sections with h4–h6 ("Codex voice mode"). Tailwind's reset
          // would leave them as body text; keep them on the same scale, by size, weight
          // and spacing only.
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
          // react-markdown 10 has no `inline` flag: `code` is always the inline style and
          // a fenced block is `pre > code`, which the `pre` override resets.
          code: ({ children, className: codeClass }) => (
            <code className={`rounded-sm bg-raised px-[0.3em] py-[0.1em] font-mono text-[0.875em] text-fg [overflow-wrap:anywhere] ${codeClass ?? ''}`}>
              {children}
            </code>
          ),
          // Only real code (a fence, `pre > code`) keeps its lines and scrolls sideways.
          // A <pre> of bare text is prose (GitHub commit bodies): it wraps, or a 390px
          // screen would cut it off.
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
                // Feed images rarely carry a size: until one loads it holds a 16:10
                // frame, so the text below does not jump down when it arrives.
                onLoad={(event) => { event.currentTarget.dataset.loaded = ''; }}
                // A dead image link would leave a broken-image frame in the text.
                onError={(event) => { event.currentTarget.hidden = true; }}
                className={`my-[1.25em] h-auto max-w-full rounded-md border border-line ${sized ? '' : 'aspect-[16/10] w-full bg-raised object-contain data-[loaded]:aspect-auto data-[loaded]:w-auto data-[loaded]:bg-transparent'}`}
              />
            );
          },
          // A figure keeps its image and caption together; the caption sits under it, small
          // and muted like a byline (issue 0042).
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
          // A wide table scrolls sideways inside the column; the page never does.
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
          // A cell keeps its span, so a row of a kept table lines up with its header.
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
          a: ({ href, children }) => (
            <a
              href={href}
              target="_blank"
              rel="noopener noreferrer"
              className="text-link [overflow-wrap:anywhere]"
            >
              {children}
            </a>
          ),
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
