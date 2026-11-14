import { useState } from 'react';
import { message } from '../../api/client';
import type { BackgroundTask } from '../../api/events';
import { Icon } from '../common/Icon';
import { Spin } from '../common/Spinner';
import { useChatActions } from './ChatContext';

/** A background task: a line, and a button that stops it (turning until the list comes without it). */
function TaskRow({ task }: { task: BackgroundTask }) {
  const { stopTask } = useChatActions();
  const [stopping, setStopping] = useState(false);
  const halt = () => {
    setStopping(true);
    stopTask(task.id).catch(e => {
      setStopping(false);
      alert(message(e));
    });
  };
  return (
    <li>
      <span className="kind">{task.kind || 'task'}</span>
      <span className="text" title={task.text || ''}>{task.text || ''}</span>
      <span className="at" title={task.note || ''}>{task.note || ''}</span>
      <button type="button" className={'icon stop' + (stopping ? ' busy' : '')} disabled={stopping} aria-label="Stop task" title="Stop" onClick={halt}>
        <Icon name="stop" />
      </button>
    </li>
  );
}

/** What the agent runs in the background, as its own task list has it: apart from the
 *  conversation, since it goes on while the agent answers and after its turn. */
export function BackgroundTasks({ tasks }: { tasks: BackgroundTask[] }) {
  return (
    <details id="tasks" hidden={!tasks.length}>
      {!!tasks.length && (
        <>
          <summary>
            <Spin />
            <b>Background</b>
            <span>{tasks.map(t => t.text).filter(Boolean).join(' · ')}</span>
            <i>{tasks.length} running</i>
          </summary>
          <ul>{tasks.map(t => <TaskRow key={t.id} task={t} />)}</ul>
        </>
      )}
    </details>
  );
}
