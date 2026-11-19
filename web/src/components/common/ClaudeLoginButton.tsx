import { message, post } from '../../api/client';
import { BusyButton } from './BusyButton';
import { Icon } from './Icon';

async function login() {
  // A tab the server sends on to claude.com's sign-in (a real link, so no popup blocker); that page ends on a code.
  window.open('/api/claude-login', '_blank');
  const code = prompt('Sign in to Claude in the new tab, then paste the code it shows here:');
  if (!code?.trim()) return;
  try {
    await post('/api/claude-login', { code });
    alert('Claude is signed in on the server.');
  } catch (e) {
    alert(message(e));
  }
}

/** Signs the server's claude (its ~/.claude, what claude-home hands sessions) in afresh. */
export function ClaudeLoginButton({ onClick }: { onClick: () => void }) {
  return (
    <BusyButton className="term" title="Sign the server's claude in again" aria-label="Sign in to Claude"
      onClick={() => { onClick(); return login(); }}>
      <Icon name="sync" /><span>Sign in to Claude</span>
    </BusyButton>
  );
}
