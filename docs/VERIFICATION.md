# Standalone delivery verification — 2026-10-20

The acceptance boundary is an independently installable repository and CLI that preserves graphs, cited pseudocode, blast radius, and progressive disclosure while depending on the unmodified published Graphify package.

| Check | Result |
|---|---|
| Full companion suite, Python 3.12.2 | 135 passed, 112 warnings, 50.69 seconds |
| Full companion suite, Python 3.10.20 | 135 passed, 112 warnings, 50.02 seconds |
| Full companion suite, Python 3.13.13 | 135 passed, 112 warnings, 50.32 seconds |
| Ruff | Passed |
| Pyright (all companion source/tests) | Zero errors and warnings |
| Bandit, companion source | Zero medium/high findings; two low subprocess notices |
| Wheel and source distribution | Built successfully |
| Fresh wheel installation | Generated real Git-comparison JSON and HTML from an unrelated temporary project |
| Runtime dependency | Stock `graphifyy==0.9.92` from PyPI, loaded from site-packages |
| Namespace separation | Wheel contains `graphify_review`, with no bundled `graphify` package |
| Browser, 1320 × 1000 | Four SVG diagrams, 24 disclosure panels, no scripts or external assets |
| Browser, 390 × 844 | Page width remains 390; impact details expand and a graph citation reaches the correct base source excerpt |

The suite includes 111 transferred source/model/renderer regression cases and 24 standalone CLI/compatibility cases. It verifies committed evidence despite a dirty index/worktree, source and metadata limits, canonical Graphify corpus boundaries, decorator mapping, impact, inferred-side citations, malicious text, symlink/output recovery, version mismatches, and unchanged canonical graph/cache files. Warnings come from Graphify's notices about switching temporary cache roots and are retained.

The example uses the real builder against committed fixture source. Its behavioral pseudocode is an explicitly mocked, authored response and is visibly identified. No live model-provider call was made.

The initial native Windows CI run exposed a CP1252 console encoding failure after artifact generation. New subprocess regressions reproduced the failure with CP1252 and ASCII on macOS. Console text now escapes unrepresentable characters while the UTF-8 artifacts retain their original Unicode. The repaired native Windows run is tracked by [CI](https://github.com/mikkelkrogsholm/graphify-review/actions). Local Windows execution was not performed. Hostile concurrent directory changes remain outside the documented trusted-local-output boundary. See [BOUNDARIES.md](BOUNDARIES.md).

Reproduction:

```bash
uv sync --frozen
uv run --frozen pytest -q
uv run --frozen ruff check .
uv run --frozen pyright
uv build
uv run --frozen python -m examples.generate
```
