// One app, two pages, picked by the address: "/" the dashboard, "/chat#<id>" a session's
// conversation. src/server/server.py serves the same index.html for each.
import { lazy, StrictMode, Suspense, type ComponentType } from 'react';
import { createRoot } from 'react-dom/client';
import Dashboard from './pages/Dashboard';
import './styles/base.css';
import './styles/dashboard.css';
import './styles/settings.css';
import './styles/chat.css';

// A session's page brings what only it needs (its markdown and diffs), loaded only where there is
// one. The styles of both come with the app, so a page is laid out and in its colours from its
// first paint.
const PAGES: Record<string, ComponentType> = {
  '/': Dashboard,
  '/chat': lazy(() => import('./pages/Chat')),
};
const Page = PAGES[location.pathname] ?? PAGES['/']!;

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <Suspense>
      <Page />
    </Suspense>
  </StrictMode>,
);
