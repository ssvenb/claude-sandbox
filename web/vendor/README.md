# Vendored

Unmodified ES module builds, served as they are (no build step). Only the trailing
`//# sourceMappingURL` comment is dropped, since the maps are not vendored.

| File | Package | From |
| --- | --- | --- |
| preact.module.js | preact 10.29.8 | `dist/preact.module.js` |
| hooks.module.js | preact 10.29.8 | `hooks/dist/hooks.module.js` |
| htm.module.js | htm 3.1.1 | `dist/htm.module.js` |

Licenses: [LICENSE-preact](LICENSE-preact) (MIT), [LICENSE-htm](LICENSE-htm) (Apache-2.0).
The pages resolve the bare names `preact`, `preact/hooks` and `htm` here through an import map.

To update: `npm pack preact@10 htm@3` in a scratch directory, and copy the same files over.
