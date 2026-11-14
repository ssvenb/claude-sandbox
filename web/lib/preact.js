// Preact and htm, vendored under /vendor (no build step): components are written as htm tagged
// templates, `html\`<div class=${c}>${text}</div>\``. Text is always text: nothing here becomes HTML
// unless a component asks for it by name (dangerouslySetInnerHTML), which only the icons do.
import {h, render, Component, Fragment, createContext} from 'preact';
import {useState, useEffect, useLayoutEffect, useRef, useMemo, useContext, useCallback, useReducer} from 'preact/hooks';
import htm from 'htm';

export const html = htm.bind(h);
export {h, render, Component, Fragment, createContext,
        useState, useEffect, useLayoutEffect, useRef, useMemo, useContext, useCallback, useReducer};

// A component's way to draw itself again on demand, for state kept outside of it.
export const useUpdate = () => useReducer(n => n + 1, 0)[1];
