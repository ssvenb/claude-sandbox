// The dashboard: on top, the first message of a new session; under it, on the left what is
// running, grouped by project, and on the right each project with what its plugins list.
import { useCallback, useMemo, useRef, useState } from 'react';
import { message } from '../api/client';
import { getConfig } from '../api/sessions';
import type { Session } from '../api/types';
import { Loading } from '../components/common/Spinner';
import { ThemeSwitch } from '../components/common/ThemeSwitch';
import { DashboardContext, type DashboardActions } from '../components/dashboard/DashboardContext';
import { NewSession } from '../components/dashboard/NewSession';
import { NoProjects } from '../components/dashboard/NoProjects';
import { ProjectPanel } from '../components/dashboard/ProjectPanel';
import { RunningSessions } from '../components/dashboard/RunningSessions';
import { SettingsDialog, type OpenSettings } from '../components/settings/SettingsDialog';
import { useDashboard } from '../hooks/useDashboard';
import { endedIn, isLive, listedIn, runningIn, tiedItems } from '../lib/board';

export default function Dashboard() {
  const board = useDashboard();
  const { state, plugins, loaded, reload, start, openTerminal, stop, remove, show, openItem } = board;
  const [settings, setSettings] = useState<OpenSettings | null>(null);
  const openings = useRef(0);

  const configure = useCallback(async (project: string) => {
    try {
      const declared = await getConfig(project);
      setSettings({ project, declared, opening: ++openings.current });
    } catch (e) {
      alert(message(e));
    }
  }, []);
  const actions = useMemo<DashboardActions>(() => ({ start, openTerminal, stop, remove, show, openItem, configure }),
    [start, openTerminal, stop, remove, show, openItem, configure]);

  const itemsOf = (s: Session) => tiedItems(state, plugins, s);
  const groups = state.projects.map(project => ({ project, sessions: runningIn(state, project) })).filter(g => g.sessions.length);

  return (
    <DashboardContext value={actions}>
      <main id="board">
        {!loaded ? <Loading as="p" text="Reading your projects" /> : (
          <>
            <div className="top">
              {state.projects.length ? <NewSession projects={state.projects} /> : <div className="starter" />}
              <ThemeSwitch />
            </div>
            {state.projects.length ? (
              <div className={'board' + (groups.length ? '' : ' quiet')}>
                {!!groups.length && <RunningSessions groups={groups} itemsOf={itemsOf} />}
                <aside className="projects">
                  <h2 className="band">Projects</h2>
                  {state.projects.map(project => {
                    const info = plugins[project];
                    const ended = endedIn(state, project).map(session => ({
                      session, items: itemsOf(session), resumable: !!session.run_id && !isLive(state, session.run_id),
                    }));
                    return <ProjectPanel key={project} project={project} info={info} lists={info ? listedIn(state, project, info) : []} ended={ended} />;
                  })}
                </aside>
              </div>
            ) : <NoProjects file={state.projects_file} />}
          </>
        )}
      </main>
      <SettingsDialog settings={settings} onClose={() => setSettings(null)} onSaved={project => void reload(project)} />
    </DashboardContext>
  );
}
