// A day or night the reader pinned, set before anything is painted: a classic script in <head>,
// not a module (those run only once the page is parsed). The switch itself is in lib/ui.js.
(() => {
  let pinned = null;
  try { pinned = localStorage.getItem('theme'); } catch {}
  if (pinned === 'light' || pinned === 'dark') document.documentElement.dataset.theme = pinned;
})();
