// What the agent writes, as markdown built into elements (react-markdown): never as HTML, since
// it is the agent's text, and other people's, quoted. HTML in it stays text; a link opens in a
// tab of its own and only to the web or a mail address; a picture is a link to it, not loaded.
import { isValidElement, memo, type ReactNode } from 'react';
import ReactMarkdown, { type Components, type Options } from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { CodeBlock } from './CodeBlock';

const SAFE = /^(https?:|mailto:)/i;
const safeUrl = (url: string): string => (SAFE.test(url) ? url : '');
// GitHub's tables, task lists, bare links and ~~strikethrough~~ (two tildes: one is "about", as in ~5 minutes).
const PLUGINS: Options['remarkPlugins'] = [[remarkGfm, { singleTilde: false }]];

const Link = ({ href, children }: { href?: string; children?: ReactNode }) =>
  href ? <a href={href} target="_blank" rel="noopener noreferrer">{children}</a> : <>{children}</>;

const COMPONENTS: Components = {
  a: ({ href, children }) => <Link href={href}>{children}</Link>,
  img: ({ src, alt }) => <Link href={typeof src === 'string' ? src : undefined}>{alt || (typeof src === 'string' ? src : '')}</Link>,
  // Fenced code: its language and a Copy button over it.
  pre: ({ children }) => {
    const code = isValidElement<{ className?: string; children?: ReactNode }>(children) ? children.props : { children };
    return <CodeBlock text={String(code.children ?? '').replace(/\n$/, '')} lang={/language-(\S+)/.exec(code.className ?? '')?.[1] ?? ''} />;
  },
  // A wide table scrolls on its own, not the column.
  table: ({ children }) => <div className="scroller"><table>{children}</table></div>,
  h5: ({ children }) => <h4>{children}</h4>,
  h6: ({ children }) => <h4>{children}</h4>,
};

export const Markdown = memo(function Markdown({ text }: { text: string }) {
  return <ReactMarkdown remarkPlugins={PLUGINS} components={COMPONENTS} urlTransform={safeUrl}>{text}</ReactMarkdown>;
});
