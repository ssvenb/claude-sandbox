import { useEffect } from 'react';
import { setFavicon, type FaviconName } from '../lib/favicon';

/** What the browser's tab says: the page's title (left as it is while there is none) and its icon. */
export function useTabIdentity(title: string | null, icon: FaviconName): void {
  useEffect(() => {
    if (title) document.title = title;
    setFavicon(icon);
  }, [title, icon]);
}
