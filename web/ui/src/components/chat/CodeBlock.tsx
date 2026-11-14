import { useState } from 'react';
import { copy } from '../../lib/clipboard';

/** A block of code, with its language and a button that copies it. */
export function CodeBlock({ text, lang }: { text: string; lang: string }) {
  const [copied, setCopied] = useState(false);
  const click = async () => {
    await copy(text);
    setCopied(true);
    setTimeout(() => setCopied(false), 1200);
  };
  return (
    <div className="code">
      {lang && <span className="lang">{lang}</span>}
      <button type="button" className="copy" onClick={click}>{copied ? 'Copied' : 'Copy'}</button>
      <pre><code>{text}</code></pre>
    </div>
  );
}
