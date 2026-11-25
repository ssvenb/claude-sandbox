import { useState } from 'react';
import type { JsonObject, PluginManifest, ProjectConfig, SettingSpec } from '../../api/types';
import { CardGroup } from './Card';
import type { CardSpec } from './cards';
import { Field, type FieldProps } from './Field';
import { useForm } from './FormContext';
import { isObject, ON, slot, type Holder, type Slot } from './slots';

interface Props {
  /** What the sandbox, the agents and the plugins declare. */
  declared: ProjectConfig;
  /** The file as it is being edited: the controls write into it. */
  draft: JsonObject;
  /** What the filter holds, in lower case. */
  query: string;
}

const object = (v: unknown): JsonObject | undefined => (isObject(v as JsonObject) ? (v as JsonObject) : undefined);

/** The settings as a form: each setting the sandbox, an agent or a plugin declares gets a control
 *  of its type, each plugin a switch. Whatever the form has no control for stays as it is. */
export function SettingsCards({ declared, draft, query }: Props) {
  const form = useForm();
  const [gen, setGen] = useState(0);  // the plugins reset: their controls are drawn anew
  // Where an owner's settings sit: the sandbox's at the top, an agent's or a plugin's in its section.
  const section = (group: 'agents' | 'plugins', name: string): Holder => create => {
    if (create) {
      const all = (draft[group] ??= {}) as JsonObject;
      all[name] ??= {};
    }
    return object(object(draft[group])?.[name]);
  };
  const field = (at: Holder, path: string, spec: SettingSpec, required?: boolean): FieldProps =>
    ({ spec, slot: slot(at, spec.key!), name: path ? `${path}.${spec.key}` : spec.key!, required });
  const top: Holder = () => draft;

  const isAgent = (s: SettingSpec) => s.key === 'agent' || s.key === 'agentVersion';  // the Agents card's own
  const sandbox: CardSpec[] = [
    {
      key: 'general', title: 'General', description: declared.kernel.description, fields: [
        { spec: { type: 'string', label: 'Repository', description: 'The repo the agent works on: a path on this machine, or a git URL (cloned only in the container). Empty: a new, empty repo in the container.', placeholder: 'https://github.com/owner/repo', monospace: true },
          slot: slot(() => draft, 'repo'), name: 'repo' },
        ...declared.kernel.settings.filter(s => !isAgent(s)).map(s => field(top, '', s)),
      ],
    },
    {
      key: 'agents', title: 'Agents', fields: declared.kernel.settings.filter(isAgent).map(s => field(top, '', s)),
      cards: declared.agents.map(a => ({
        key: 'agent-' + a.name, title: a.name, description: a.description,
        fields: a.settings.map(s => field(section('agents', a.name), 'agents.' + a.name, s)),
        // Its own plugins: kept in the file whichever agent runs, applied only with this one.
        cardsTitle: 'Plugins', cards: declared.plugins.filter(p => p.requiredAgent === a.name).map(plugin),
      })),
    },
  ];

  function plugin(p: PluginManifest): CardSpec {
    const sec = section('plugins', p.name);
    const enabled: Slot = {
      get: () => { const e = sec()?.enabled; return e === undefined ? undefined : ON.includes(e); },
      set: v => {
        if (v !== undefined) sec(true)!.enabled = v;
        else if (sec()) delete sec()!.enabled;
      },
    };
    const on = enabled.get() ?? p.defaultEnabled;
    const declaredKeys = new Set(['enabled', ...p.settings.filter(s => s.key).map(s => s.key!)]);
    const kept = Object.keys(sec() ?? {}).filter(k => !declaredKeys.has(k));
    return {
      key: 'plugin-' + p.name, title: p.name, description: p.description, off: !on,
      more: ' ' + p.settings.map(s => [s.label, s.key].join(' ')).join(' ').toLowerCase(),
      right: <Field spec={{ type: 'boolean', label: 'Enabled', default: p.defaultEnabled }} slot={enabled}
        name={'enabled-' + p.name} ariaLabel={p.name + ' enabled'} head />,
      fields: p.settings.map(spec => field(sec, 'plugins.' + p.name, spec, (p.requiredEnv ?? []).includes(spec.env ?? ''))),
      after: kept.length ? <p className="kept">Also holds {kept.join(', ')}: kept as is (edit it in the JSON view).</p> : undefined,
    };
  }

  // Every plugin back to its defaults: what it declares unset (what the form has no control for stays).
  const resetPlugins = () => {
    for (const p of declared.plugins) {
      const sec = section('plugins', p.name)();
      if (sec) for (const k of ['enabled', ...p.settings.map(s => s.key!)]) delete sec[k];
    }
    setGen(g => g + 1);
    form.changed();
  };
  const agentNames = new Set(declared.agents.map(a => a.name));

  return (
    <>
      <CardGroup key={'sandbox' + gen} title="Sandbox" cards={sandbox} query={query} />
      <CardGroup key={'plugins' + gen} title="Plugins" query={query}
        cards={declared.plugins.filter(p => !p.requiredAgent || !agentNames.has(p.requiredAgent)).map(plugin)}
        action={<button type="button" className="reset-all" onClick={resetPlugins}>Reset all</button>} />
    </>
  );
}
