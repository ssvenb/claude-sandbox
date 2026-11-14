import { DASHBOARD_TAB } from '../../lib/session';
import { Icon } from './Icon';

/** A session page's way back to the dashboard: to its tab when `toItsTab`, else in this one. */
export function HomeLink({ toItsTab = true }: { toItsTab?: boolean }) {
  return (
    <a className="home" href="/" target={toItsTab ? DASHBOARD_TAB : undefined} title="Dashboard" aria-label="Dashboard">
      <Icon name="back" />
    </a>
  );
}
