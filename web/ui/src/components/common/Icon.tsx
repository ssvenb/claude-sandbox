// Icons are drawn, so they keep the colour of the button they are on.
import type { ReactNode } from 'react';

const stroke = (d: string, width = 2): ReactNode => (
  <path d={d} fill="none" stroke="currentColor" strokeWidth={width} strokeLinecap="round" strokeLinejoin="round" />
);

const GEAR = 'M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 1 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 1 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 1 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 1 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z';

const ICONS = {
  plus: { body: stroke('M10 4v12M4 10h12', 2.2) },
  prompt: { body: stroke('M4 6l4 4-4 4M10 15h6', 2.2) },
  trash: { body: stroke('M3.5 5.5h13M8 5.5V3.5h4v2M5.5 5.5l.8 11h7.4l.8-11M8.5 8.5v5M11.5 8.5v5') },
  play: { body: <path d="M6 4.2v11.6a.8.8 0 0 0 1.2.7l9.3-5.8a.8.8 0 0 0 0-1.4L7.2 3.5a.8.8 0 0 0-1.2.7z" fill="currentColor" /> },
  stop: { body: <rect x="4.5" y="4.5" width="11" height="11" rx="2" fill="currentColor" /> },
  vscode: {
    viewBox: '0 0 24 24',
    body: <path fill="currentColor" fillRule="evenodd" d="M17 1.5 22 4v16l-5 2.5-9.4-8.6-4.3 3.3L2 16.5v-9l1.3-.7 4.3 3.3zm0 5.7L10.7 12l6.3 4.8z" />,
  },
  gear: {
    viewBox: '0 0 24 24',
    body: (
      <g fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
        <circle cx="12" cy="12" r="3" />
        <path d={GEAR} />
      </g>
    ),
  },
  sync: { body: stroke('M16 10a6 6 0 0 1-10.6 3.9M4 10a6 6 0 0 1 10.6-3.9M15 2.5v3.8h-3.8M5 17.5v-3.8h3.8', 1.8) },
  send: { body: stroke('M10 16V4M4.5 9.5 10 4l5.5 5.5', 2.2) },
  back: { body: stroke('M11.5 4.5 6 10l5.5 5.5', 2.2) },
  sun: {
    body: (
      <g fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round">
        <circle cx="10" cy="10" r="3.4" />
        <path d="M10 2.2v2M10 15.8v2M2.2 10h2M15.8 10h2M4.5 4.5l1.4 1.4M14.1 14.1l1.4 1.4M4.5 15.5l1.4-1.4M14.1 5.9l1.4-1.4" />
      </g>
    ),
  },
  moon: { body: stroke('M16.5 11.8A7 7 0 0 1 8.2 3.5a7 7 0 1 0 8.3 8.3z', 1.8) },
  auto: {
    body: (
      <>
        <circle cx="10" cy="10" r="6.8" fill="none" stroke="currentColor" strokeWidth="1.8" />
        <path d="M10 3.2a6.8 6.8 0 0 1 0 13.6z" fill="currentColor" />
      </>
    ),
  },
} satisfies Record<string, { body: ReactNode; viewBox?: string }>;

export type IconName = keyof typeof ICONS;

export function Icon({ name }: { name: IconName }) {
  const icon: { body: ReactNode; viewBox?: string } = ICONS[name];
  return (
    <svg viewBox={icon.viewBox ?? '0 0 20 20'} aria-hidden="true">
      {icon.body}
    </svg>
  );
}
