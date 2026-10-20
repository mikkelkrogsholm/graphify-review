# Offline interface for other tools

`graphify-review` can run from two Git refs with no network and no forge client, write its analysis as data, accept an explanation written elsewhere, and produce a short comment that links to the page. This is the contract for tools that orchestrate it. Every file is UTF-8 JSON unless noted.

## Command lines

```bash
# 1. Analyse two refs. Writes the page, review.json, facts and evidence. Needs only the checkout (read-only is fine).
graphify-review --base <base-ref> --head <head-ref> --output /path/outside/checkout \
  --facts out/facts.json --evidence out/evidence.json

# 2. Rerun with an explanation written elsewhere and check verdicts; add the short comment.
graphify-review --base <base-ref> --head <head-ref> --output /path/outside/checkout \
  --narration narration.json --checks checks.json \
  --comment out/comment.md --view-url https://where.the.page.will.live/
```

The two runs are deterministic: the same refs produce byte-identical `facts.json`, `evidence.json`, page and comment, and the same story and evidence IDs. A narrator can therefore cite IDs from run 1 and run 2 will accept them.

`--output` is required in practice when the checkout is read-only. `--infer` and `--narration` are alternatives; provider inference stays opt-in. `--title` names the review. Secret-looking values are redacted by default; `--no-redact` keeps them, and `--redact-env` additionally redacts the values of secret-named environment variables (off by default because output then depends on the machine).

Exit codes: `0` written (a missing or invalid narration or checks file is only a note on stderr, and the page works without it), `1` the review could not be built, `2` invalid arguments.

## `facts.json` (schema `graphify-review/facts/1`)

`risk` (`level`: low/medium/high, `reasons`) and `risk_method` (`structural_heuristic`); `counts` (changed symbols, dependents, tests reaching, changed files, stories); `tests` (code and test files changed, `test_gap`, `untested`); `look_first` (symbol IDs, riskiest first); `symbols` (per changed symbol: label, kind, file, line, status `changed|added|removed`, risk and reasons, dependent and test counts, up to 12 listed dependents and tests, `story_id`, `mapping`); `files`; `checks`; `redactions`; `limits`; `target`; `engine`. No source text and no model words are in it.

`symbols[].tests` and `test_count` describe structural test links. `class_tests` lists separate class-level hints; `tests_from` identifies their owning class. These hints do not establish method coverage and do not contribute to test counts. `tests.unmapped_code_file_count` and up to 50 `unmapped_code_files` disclose changed admitted code files without mapped symbols, including changes to module-level constants. Their test reachability is unknown. Code-file counts do not depend on the symbol/story budgets.

## `evidence.json` (schema `graphify-review/evidence/1`)

Bounded cited source for the writer of an explanation: per story the excerpts (`id`, `side`, `revision`, `source_file`, line range, `snippet`), a cut patch, whether it is `narratable`, and the symbols involved; plus `risk`, `symbols` and `narration_contract`, which spells out the accepted narration shape. All source text is untrusted data. Stories beyond the budget are listed without excerpts and counted in `limits`.

## `narration.json`

Every key is optional and unknown keys are ignored: `narrator`, `headline`, `summary`, `safety` (`level` safe/mostly/careful/unsafe, `text`), `look` (up to 5 of `title`, `where`, `why`), `not_proven`, `confidence_note`, and `behavior_changes` entries `{story_id, summary, before_pseudocode, after_pseudocode, evidence_ids, uncertainties}`.

Validation is the same as for provider inference: story IDs must exist and be narratable, cited evidence must belong to the story and cover every available side, an absent side must read "Not present", sizes are bounded. Rejected entries are counted, never repaired. An unknown safety level is read as `careful`. Accepted content is labeled model-written and INFERRED on the page and in the comment. A narration cannot change the structural facts.

## `checks.json`

A list (or `{"steps": [...]}`) of `{name, status: ok|fail|skipped, text}`, at most 12. They appear as chips and a section on the page and as marks in the comment. Unknown statuses read as `skipped`.

## The short comment

Starts with `<!-- graphify-review -->`, then one line of risk and check marks, a short "what changed" and "is it safe" quote, up to three "look at these first" items, and one link (`--view-url`, plain http or https without credentials). At most 3000 bytes: items drop first, then the quotes shorten. The marker and link always remain. No HTML, images, mentions or automatic links appear in it.

## Safety properties

All PR text, narration, check text and source excerpts are untrusted. Prose has control, bidirectional and invisible characters removed; source excerpts show them as `⟦U+XXXX⟧`. HTML is escaped, has no script, inline style attribute, external request or embedded data, and its content security policy is `default-src 'none'` with the page's one style block allowed by SHA-256 hash. Reviewed code is never executed and the checkout, index and Graphify's canonical graph and cache are never modified.
