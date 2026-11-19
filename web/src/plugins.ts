// What plugins and agents draw themselves: each one's plugins/<name>/web/index.tsx or
// agents/<name>/web/index.tsx, bundled with the app at build time. The page knows none of them, only
// the places they may fill.
import type { ComponentType, ReactNode } from 'react';
import type { Session } from './api/types';

/** What a plugin adds to a session's chat page. */
export interface ChatParts {
  /** In the header, beside the session's state: always in view. */
  bar?: ReactNode;
  /** With the header's buttons, which drop into a row of their own on a phone. */
  actions?: ReactNode;
  /** Beside the chat on a desk: an `<aside className="side" popover="auto">`, which a smaller
   *  screen shows as a popover under the header, from a `side-toggle` button in `bar`. */
  aside?: ReactNode;
}

/** A plugin's page code: the default export of its web/index.tsx. */
export interface PluginUI {
  /** A hook, called on every draw of a session's chat page: with the session while its project
   *  enables the plugin, null while it does not, the page has no session yet, or it is gone. */
  useChat?: (session: Session | null) => ChatParts;
}

/** Sent on the window when the session's page goes away with its session (stopped and deleted, or
 *  gone): what a plugin opened for it may go with it. */
export const LEAVE = 'sandbox:leave';

const found = import.meta.glob<{ default: PluginUI }>('../../plugins/*/web/index.tsx', { eager: true });

/** Every plugin that brings page code, in the order of its name. */
export const PLUGINS = Object.entries(found)
  .map(([path, m]) => ({ name: path.split('/').at(-3)!, ...m.default }))
  .sort((a, b) => a.name.localeCompare(b.name));

/** An agent's page code: the default export of its web/index.tsx. */
export interface AgentUI {
  /** Its items in the dashboard's menu (⋯), e.g. signing its CLI on the server in again
   *  (components/common/SignInButton). `close` closes the menu. */
  Menu?: ComponentType<{ close: () => void }>;
}

const agents = import.meta.glob<{ default: AgentUI }>('../../agents/*/web/index.tsx', { eager: true });

/** Every agent that brings page code, in the order of its name. */
export const AGENTS = Object.entries(agents)
  .map(([path, m]) => ({ name: path.split('/').at(-3)!, ...m.default }))
  .sort((a, b) => a.name.localeCompare(b.name));
