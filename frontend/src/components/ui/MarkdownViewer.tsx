import type { ReactNode } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { Prism as SyntaxHighlighter } from 'react-syntax-highlighter';
import { vscDarkPlus } from 'react-syntax-highlighter/dist/esm/styles/prism';

/** 코드 블록의 children(react-markdown이 넘기는 텍스트 노드)을 문자열로 모은다. */
function codeTextOf(children: ReactNode): string {
  if (typeof children === 'string' || typeof children === 'number') return String(children);
  if (Array.isArray(children))
    return children.map((child: ReactNode) => codeTextOf(child)).join('');
  return '';
}

interface MarkdownViewerProps {
  content: string;
}

export function MarkdownViewer({ content }: MarkdownViewerProps) {
  // blockId: [id] 형태의 내부 마커를 렌더링 전에 제거합니다.
  const filteredContent = content.replace(/blockId:\s*[\w-]+\s*/gi, '');

  return (
    <ReactMarkdown
      remarkPlugins={[remarkGfm]}
      components={{
        code(props) {
          const { children, className, node: _node, ref: _ref, ...rest } = props;
          void _node;
          void _ref;
          const match = /language-(\w+)/.exec(className || '');
          return match ? (
            <SyntaxHighlighter
              {...rest}
              PreTag="div"
              children={codeTextOf(children).replace(/\n$/, '')}
              language={match[1]}
              style={vscDarkPlus}
              className="!my-4 rounded-md border border-slate-700/50 !bg-[#1e1e1e]"
            />
          ) : (
            <code
              {...rest}
              className={`${className || ''} rounded bg-slate-800/80 px-1.5 py-0.5 font-mono text-[13px] text-blue-200`}
            >
              {children}
            </code>
          );
        },
        p: ({ children }) => (
          <p className="mb-3 text-[15px] leading-relaxed break-words last:mb-0">{children}</p>
        ),
        ul: ({ children }) => <ul className="mb-4 list-disc space-y-1.5 pl-5">{children}</ul>,
        ol: ({ children }) => <ol className="mb-4 list-decimal space-y-1.5 pl-5">{children}</ol>,
        li: ({ children }) => <li className="leading-relaxed text-slate-300">{children}</li>,
        a: ({ href, children }) => (
          <a
            href={href}
            target="_blank"
            rel="noopener noreferrer"
            className="text-blue-400 underline underline-offset-2 hover:text-blue-300"
          >
            {children}
          </a>
        ),
        h1: ({ children }) => (
          <h1 className="mt-6 mb-4 text-2xl font-bold text-slate-100">{children}</h1>
        ),
        h2: ({ children }) => (
          <h2 className="mt-5 mb-3 border-b border-slate-700/50 pb-2 text-xl font-bold text-slate-100">
            {children}
          </h2>
        ),
        h3: ({ children }) => (
          <h3 className="mt-4 mb-2 text-lg font-bold text-slate-200">{children}</h3>
        ),
        table: ({ children }) => (
          <div className="mb-4 overflow-x-auto rounded-lg border border-slate-700/50">
            <table className="w-full text-left text-sm">{children}</table>
          </div>
        ),
        thead: ({ children }) => (
          <thead className="bg-slate-800/50 text-xs text-slate-300 uppercase">{children}</thead>
        ),
        th: ({ children }) => (
          <th className="border-b border-slate-700/50 px-4 py-3 font-semibold">{children}</th>
        ),
        td: ({ children }) => (
          <td className="border-b border-slate-700/50 px-4 py-3 text-slate-300">{children}</td>
        ),
        blockquote: ({ children }) => (
          <blockquote className="my-4 rounded-r border-l-4 border-blue-500/50 bg-blue-500/5 py-2 pl-4 text-slate-400 italic">
            {children}
          </blockquote>
        ),
      }}
    >
      {filteredContent}
    </ReactMarkdown>
  );
}
