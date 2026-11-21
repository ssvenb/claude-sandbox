// A tab's icon says what it is and how it is doing: the agent's lamp in the colour of what it does
// (amber working or starting, green idle, violet waiting on your answer), an empty ring once ended.
const tile = (inner: string): string =>
  `data:image/svg+xml,${encodeURIComponent(`<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 32 32'><rect width='32' height='32' rx='7' fill='#1b1d36'/>${inner}</svg>`)}`;

export const FAVICON = {
  working: tile("<circle cx='16' cy='16' r='10' fill='#f2b84b'/>"),
  starting: tile("<circle cx='16' cy='16' r='8' fill='none' stroke='#f2b84b' stroke-width='4' stroke-dasharray='30 21'/>"),
  idle: tile("<circle cx='16' cy='16' r='8' fill='#6fd3a2'/>"),
  question: tile("<circle cx='16' cy='16' r='10' fill='#c69cff'/>"),
  unlit: tile("<circle cx='16' cy='16' r='7' fill='none' stroke='#8c8fb3' stroke-width='3'/>"),
} as const;
export type FaviconName = keyof typeof FAVICON;

export function setFavicon(name: FaviconName): void {
  const link = document.getElementById('icon') as HTMLLinkElement | null;
  if (link && link.getAttribute('href') !== FAVICON[name]) link.href = FAVICON[name];
}
