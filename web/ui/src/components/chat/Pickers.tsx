import type { Model } from '../../api/events';

interface ModelProps {
  models: Model[];
  /** The model in use, which the agent may not list. */
  model?: string;
  onChoose: (id: string) => void;
}

const named = (m: Model): string => (m.name === m.id || !m.description ? m.name : `${m.name} (${m.description.split(' · ')[0]})`);

/** The agent's models, once it said which it has. */
export function ModelPicker({ models, model, onChoose }: ModelProps) {
  const known = models.some(m => m.id === model);
  return (
    <select id="model" aria-label="Model" hidden={!models.length} value={models.length ? model || models[0]!.id : ''} onChange={e => onChoose(e.target.value)}>
      {!known && model && <option value={model}>{model}</option>}
      {models.map(m => <option key={m.id} value={m.id} title={m.description || ''}>{named(m)}</option>)}
    </select>
  );
}

interface EffortProps {
  efforts: string[];
  effort?: string;
  onChoose: (level: string) => void;
}

/** How hard the agent thinks, where it lets you choose. */
export function EffortPicker({ efforts, effort, onChoose }: EffortProps) {
  return (
    <select id="effort" aria-label="Reasoning effort" hidden={!efforts.length} value={efforts.length ? effort || efforts[0] : ''} onChange={e => onChoose(e.target.value)}>
      {efforts.map(level => <option key={level} value={level}>{level} effort</option>)}
    </select>
  );
}
