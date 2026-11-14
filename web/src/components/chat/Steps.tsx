import type { PlanItem } from '../../api/events';
import { Spin } from '../common/Spinner';

/** The steps of a plan: done, the one it is on, and those to come. */
export function Steps({ items }: { items: PlanItem[] }) {
  return (
    <ul className="steps">
      {items.map((t, k) => (
        <li key={k} className={t.status}>
          <span className="box">{t.status === 'done' ? '✓' : t.status === 'active' ? <Spin /> : '○'}</span>
          <span>{t.text}</span>
        </li>
      ))}
    </ul>
  );
}
