import { useTheme, type ThemeMode } from '../../hooks/useTheme';
import { Icon, type IconName } from './Icon';

const MODES: { mode: ThemeMode; title: string; icon: IconName }[] = [
  { mode: 'auto', title: 'Follow the browser', icon: 'auto' },
  { mode: 'light', title: 'Day', icon: 'sun' },
  { mode: 'dark', title: 'Night', icon: 'moon' },
];

/** Day, night, or whatever the browser says: three small buttons, one pressed. */
export function ThemeSwitch() {
  const [now, pick] = useTheme();
  return (
    <div className="theme" role="group" aria-label="Colours">
      {MODES.map(({ mode, title, icon }) => (
        <button key={mode} type="button" title={title} aria-label={title} aria-pressed={now === mode} onClick={() => pick(mode)}>
          <Icon name={icon} />
        </button>
      ))}
    </div>
  );
}
