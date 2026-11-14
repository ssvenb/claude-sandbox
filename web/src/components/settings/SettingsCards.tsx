import type { JsonObject, PluginManifest, ProjectConfig, SettingSpec } from '../../api/types';
import { CardGroup } from './Card';
import type { CardSpec } from './cards';
import { Field, type FieldProps } from './Field';
import { envSlot, isObject, ON, slot, type Holder, type Slot } from './slots';

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
  const env: Holder = create => {
    if (create && !draft.env) draft.env = {};
    return object(draft.env);
  };
  const section = (plugin: string): Holder => create => {
    if (create) {
      const plugins = (draft.plugins ??= {}) as JsonObject;
      plugins[plugin] ??= {};
    }
    return object(object(draft.plugins)?.[plugin]);
  };
  const envField = (spec: SettingSpec, required?: boolean): FieldProps =>
    ({ spec, slot: envSlot(slot(env, spec.env!), spec), name: 'env.' + spec.env, required });

  // env keys nobody declares: a plain name → value list, so nothing in the file goes missing.
  const declaredEnv = new Set([...declared.kernel.settings, ...declared.agents.flatMap(a => a.settings), ...declared.plugins.flatMap(p => p.settings)]
    .filter(s => s.env).map(s => s.env!));
  const others: Slot = {
    get: () => {
      const o = Object.fromEntries(Object.entries(env() ?? {}).filter(([k]) => !declaredEnv.has(k)));
      return Object.keys(o).length ? o : undefined;
    },
    set: v => {
      const held = env();
      for (const k of Object.keys(held ?? {})) if (!declaredEnv.has(k)) delete held![k];
      if (v) Object.assign(env(true)!, v);
    },
  };

  const agentNow = env()?.AGENT ?? declared.kernel.settings.find(s => s.env === 'AGENT')?.default;
  const sandbox: CardSpec[] = [
    { key: 'general', title: 'General', description: declared.kernel.description, fields: declared.kernel.settings.map(s => envField(s)) },
    ...declared.agents.map(a => ({
      key: 'agent-' + a.name, title: a.name + ' agent', description: a.description,
      fields: a.settings.map(s => envField(s)), tag: a.name === agentNow ? 'selected' : '',
    })),
    {
      key: 'other', title: 'Other variables', description: 'Further sandbox settings for the env block, by name (see .env.example).',
      fields: [{ spec: { type: 'map', label: 'Variables', placeholder: 'NAME' }, slot: others, name: 'env-other' }],
    },
  ];

  const plugin = (p: PluginManifest): CardSpec => {
    const sec = section(p.name);
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
      tag: p.requiredAgent ? p.requiredAgent + ' only' : '',
      more: ' ' + p.settings.map(s => [s.label, s.key, s.env].join(' ')).join(' ').toLowerCase(),
      right: <Field spec={{ type: 'boolean', label: 'Enabled', default: p.defaultEnabled }} slot={enabled}
        name={'enabled-' + p.name} ariaLabel={p.name + ' enabled'} head />,
      fields: p.settings.map(spec => spec.env
        ? envField(spec, spec.required || (p.requiredEnv ?? []).includes(spec.env))
        : { spec, slot: slot(sec, spec.key!), name: `plugins.${p.name}.${spec.key}` }),
      after: kept.length ? <p className="kept">Also holds {kept.join(', ')}: kept as is (edit it in the JSON view).</p> : undefined,
    };
  };

  return (
    <>
      <p>Unset settings come from the repo's .env or your shell, else their default. ↺ reset unsets one again.</p>
      <CardGroup title="Sandbox" cards={sandbox} query={query} />
      <CardGroup title="Plugins" cards={declared.plugins.map(plugin)} query={query} />
    </>
  );
}
