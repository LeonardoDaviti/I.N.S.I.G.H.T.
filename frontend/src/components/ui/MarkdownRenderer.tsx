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
    return <p className="text-gray-500 italic">No content available</p>;
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
            <p className="text-gray-800 leading-relaxed mb-4 whitespace-pre-wrap">
              {children}
            </p>
          ),
          h1: ({ children }) => (
            <h1 className="text-2xl font-bold text-gray-900 mt-6 mb-4 pb-2 border-b-2 border-indigo-500">
              {children}
            </h1>
          ),
          h2: ({ children }) => (
            <h2 className="text-xl font-semibold text-indigo-600 mt-5 mb-3">
              {children}
            </h2>
          ),
          h3: ({ children }) => (
            <h3 className="text-lg font-medium text-gray-700 mt-4 mb-2">
              {children}
            </h3>
          ),
          strong: ({ children }) => (
            <strong className="font-semibold text-gray-900">
              {children}
            </strong>
          ),
          em: ({ children }) => (
            <em className="italic text-indigo-600">
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
            <li className="text-gray-800 leading-relaxed">
              {children}
            </li>
          ),
          blockquote: ({ children }) => (
            <blockquote className="border-l-4 border-indigo-300 pl-4 py-2 my-4 bg-indigo-50 rounded-r-lg">
              <div className="text-gray-700 italic">
                {children}
              </div>
            </blockquote>
          ),
          code: (props: any) => {
            if (props.inline) {
              return (
                <code className="bg-gray-100 text-gray-800 px-1.5 py-0.5 rounded font-mono text-sm">
                  {props.children}
                </code>
              );
            }
            return (
              <pre className="bg-gray-100 border border-gray-200 rounded-lg p-4 my-4 overflow-x-auto">
                <code className="font-mono text-sm text-gray-800">
                  {props.children}
                </code>
              </pre>
            );
          },
          table: ({ children }) => (
            <div className="overflow-x-auto my-4">
              <table className="min-w-full border border-gray-200 rounded-lg">
                {children}
              </table>
            </div>
          ),
          thead: ({ children }) => (
            <thead className="bg-gray-50">
              {children}
            </thead>
          ),
          tbody: ({ children }) => (
            <tbody className="divide-y divide-gray-200">
              {children}
            </tbody>
          ),
          tr: ({ children }) => (
            <tr className="hover:bg-gray-50">
              {children}
            </tr>
          ),
          th: ({ children }) => (
            <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider border-b border-gray-200">
              {children}
            </th>
          ),
          td: ({ children }) => (
            <td className="px-4 py-3 text-sm text-gray-800 border-b border-gray-200">
              {children}
            </td>
          ),
          a: ({ href, children }) => (
            <a
              href={href}
              target="_blank"
              rel="noopener noreferrer"
              className="text-indigo-600 hover:text-indigo-800 underline transition-colors duration-200"
            >
              {children}
            </a>
          ),
          hr: () => (
            <hr className="my-6 border-t border-gray-300" />
          ),
        }}
      >
        {normalizedContent}
      </ReactMarkdown>
    </div>
  );
}
