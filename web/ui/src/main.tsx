// One app, three pages, picked by the address: "/" the dashboard, "/chat#<id>" a session's
// conversation, "/session#<id>" a terminal. web/server.py serves the same index.html for each.
import { lazy, StrictMode, Suspense, type ComponentType, type ReactNode } from 'react';
import { createRoot } from 'react-dom/client';
import { Loading } from './components/common/Spinner';
import Dashboard from './pages/Dashboard';
import './styles/base.css';
import './styles/dashboard.css';
import './styles/settings.css';
import './styles/chat.css';
import './styles/terminal.css';

interface Page {
  component: ComponentType;
  /** What stands in its place while its code loads. */
  loading?: ReactNode;
}

// A session's page brings what only it needs (the chat its markdown and diffs, the terminal
// xterm.js), loaded only where there is one. The styles of all three come with the app, so a
// page is laid out and in its colours from its first paint.
const PAGES: Record<string, Page> = {
  '/': { component: Dashboard },
  '/chat': { component: lazy(() => import('./pages/Chat')) },
  '/session': {
    component: lazy(() => import('./pages/Terminal')),
    loading: <div id="stage"><div id="wait"><Loading text="Connecting to the terminal" /></div></div>,
  },
};
const page = PAGES[location.pathname] ?? PAGES['/']!;

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <Suspense fallback={page.loading}>
      <page.component />
    </Suspense>
  </StrictMode>,
);
