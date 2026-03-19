import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import rehypeRaw from 'rehype-raw';
import rehypeSanitize from 'rehype-sanitize';
import { defaultSchema } from 'hast-util-sanitize';

interface MarkdownRendererProps {
  content: string;
  className?: string;
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

function normalizeRendererContent(content: string): string {
  const looksLikeEscapedHtml = /&lt;(?:!--|\/?(?:p|div|span|a|img|ul|ol|li|blockquote|code|pre|h[1-6]|table|thead|tbody|tr|td|th))/i.test(content);
  if (!looksLikeEscapedHtml) {
    return content;
  }

  return decodeHtmlEntities(content).replace(/<!--\s*SC_(?:OFF|ON)\s*-->/g, '').trim();
}

export default function MarkdownRenderer({ content, className = "" }: MarkdownRendererProps) {
  if (!content) {
    return <p className="italic text-[var(--text-muted)]">No content available</p>;
  }

  const normalizedContent = normalizeRendererContent(content);

  return (
    <div className={`markdown-content ${className}`}>
      <ReactMarkdown
        // Enable GFM and treat single newlines as breaks
        remarkPlugins={[remarkGfm]}
        rehypePlugins={[
          rehypeRaw,
          [
            rehypeSanitize,
            {
              ...defaultSchema,
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
        ]}
  skipHtml={false}
        // Render soft line breaks as actual <br/>
        components={{
          // Custom paragraph to preserve single line breaks from plain text sources
          p: ({ children }) => (
            <p className="mb-4 whitespace-pre-wrap leading-relaxed text-[var(--text-normal)]">
              {children}
            </p>
          ),
          h1: ({ children }) => (
            <h1 className="mt-6 mb-4 border-b-2 border-[var(--gold-shadow)] pb-2 text-2xl font-bold text-[var(--text-normal)]">
              {children}
            </h1>
          ),
          h2: ({ children }) => (
            <h2 className="mt-5 mb-3 text-xl font-semibold text-[var(--gold-shadow)]">
              {children}
            </h2>
          ),
          h3: ({ children }) => (
            <h3 className="mt-4 mb-2 text-lg font-medium text-[var(--text-normal)]">
              {children}
            </h3>
          ),
          strong: ({ children }) => (
            <strong className="font-semibold text-[var(--text-normal)]">
              {children}
            </strong>
          ),
          em: ({ children }) => (
            <em className="italic text-[var(--gold-shadow)]">
              {children}
            </em>
          ),
          ul: ({ children }) => (
            <ul className="list-disc ml-5 mb-4 space-y-1">
              {children}
            </ul>
          ),
          ol: ({ children }) => (
            <ol className="list-decimal ml-5 mb-4 space-y-1">
              {children}
            </ol>
          ),
          li: ({ children }) => (
            <li className="leading-relaxed text-[var(--text-normal)]">
              {children}
            </li>
          ),
          blockquote: ({ children }) => (
            <blockquote className="my-4 rounded-r-lg border-l-4 border-[var(--gold-shadow)] bg-[var(--text-highlight-bg)] py-2 pl-4">
              <div className="italic text-[var(--text-normal)]">
                {children}
              </div>
            </blockquote>
          ),
          code: (props: any) => {
            if (props.inline) {
              return (
                <code className="rounded bg-[var(--background-secondary)] px-1.5 py-0.5 font-mono text-sm text-[var(--text-normal)]">
                  {props.children}
                </code>
              );
            }
            return (
              <pre className="my-4 overflow-x-auto rounded-lg border border-[var(--background-modifier-border)] bg-[var(--background-secondary)] p-4">
                <code className="font-mono text-sm text-[var(--text-normal)]">
                  {props.children}
                </code>
              </pre>
            );
          },
          table: ({ children }) => (
            <div className="overflow-x-auto my-4">
              <table className="min-w-full rounded-lg border border-[var(--background-modifier-border)]">
                {children}
              </table>
            </div>
          ),
          thead: ({ children }) => (
            <thead className="bg-[var(--background-secondary)]">
              {children}
            </thead>
          ),
          tbody: ({ children }) => (
            <tbody className="divide-y divide-[var(--background-modifier-border)]">
              {children}
            </tbody>
          ),
          tr: ({ children }) => (
            <tr className="hover:bg-[var(--background-secondary)]">
              {children}
            </tr>
          ),
          th: ({ children }) => (
            <th className="border-b border-[var(--background-modifier-border)] px-4 py-3 text-left text-xs font-medium uppercase tracking-wider text-[var(--text-muted)]">
              {children}
            </th>
          ),
          td: ({ children }) => (
            <td className="border-b border-[var(--background-modifier-border)] px-4 py-3 text-sm text-[var(--text-normal)]">
              {children}
            </td>
          ),
          a: ({ href, children }) => (
            <a
              href={href}
              target="_blank"
              rel="noopener noreferrer"
              className="underline transition-colors duration-200 text-[var(--gold-shadow)] hover:text-[var(--text-normal)]"
            >
              {children}
            </a>
          ),
          hr: () => (
            <hr className="my-6 border-t border-[var(--background-modifier-border)]" />
          ),
        }}
      >
        {normalizedContent}
      </ReactMarkdown>
    </div>
  );
}
