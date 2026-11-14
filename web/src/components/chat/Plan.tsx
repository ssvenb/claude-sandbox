import type { PlanItem } from '../../api/events';
import { Steps } from './Steps';

/** The plan the agent works through: the step it is on, and all of them on request. */
export function Plan({ items }: { items: PlanItem[] | null }) {
  if (!items?.length) return <details id="plan" hidden />;
  const done = items.filter(t => t.status === 'done').length;
  const now = items.find(t => t.status === 'active') ?? items.find(t => t.status === 'pending');
  return (
    <details id="plan">
      <summary>
        <b>Plan</b>
        <span>{done === items.length ? 'All done' : now?.text || ''}</span>
        <i>{done} of {items.length}</i>
      </summary>
      <Steps items={items} />
    </details>
  );
}
