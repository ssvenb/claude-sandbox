// Claude's part of the web UI: signing the server's claude (its ~/.claude, which home.sh hands
// sessions) in again, from the dashboard's menu: `signIn` in ../agent.json is what the server runs.
import { SignInButton } from '@ui/components/common/SignInButton';
import type { AgentUI } from '@ui/plugins';

// Claude's spark: rays of uneven length round a hub.
const SPARK = (
  <svg viewBox="0 0 20 20" aria-hidden="true">
    <path d="M9.57 8.15 L10.00 1.40 L10.43 8.15 L10.64 8.21 L13.89 3.94 L11.36 8.68 L11.50 8.84 L17.46 6.59 L11.86 9.62 L11.89 9.84 L16.73 10.97 L11.77 10.69 L11.68 10.89 L16.65 15.76 L11.12 11.54 L10.93 11.65 L12.08 17.10 L10.11 11.90 L9.89 11.90 L7.75 17.68 L9.07 11.65 L8.88 11.54 L4.79 14.52 L8.32 10.89 L8.23 10.69 L1.59 11.21 L8.11 9.84 L8.14 9.62 L3.54 7.05 L8.50 8.84 L8.64 8.68 L5.78 3.44 L9.36 8.21Z" fill="currentColor" stroke="currentColor" strokeWidth={1.1} strokeLinejoin="round" />
  </svg>
);

export default {
  Menu: ({ close }) => <SignInButton agent="claude" label="Sign in to Claude" icon={SPARK} onClick={close} />,
} satisfies AgentUI;
