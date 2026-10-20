# Graphify Review

Independent companion CLI built on the published `graphifyy` dependency.

- Keep Graphify imports in `src/graphify_review/graphify_adapter.py`.
- Do not patch the installed dependency or depend on a sibling Graphify checkout.
- Keep graph extraction deterministic; inference remains opt-in and visibly inferred.
- Preserve pinned source evidence, disclosed limits, offline HTML, and progressive disclosure.
- Run `uv run --frozen pytest`, `uv run --frozen ruff check .`, and `uv run --frozen pyright` after code changes.
- A dependency-version update requires the adapter contract and source-boundary tests to pass.
- Never execute reviewed project code or modify its checkout, index, or canonical graph/cache.
