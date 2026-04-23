# Contributing to stays

Thanks for your interest! This project is a lightweight, maintainable wrapper
around Google Hotels — PRs are welcome.

## Quick dev setup

```bash
git clone https://github.com/him229/stays.git
cd stays
make install-dev
uv run pre-commit install --hook-type pre-commit --hook-type pre-push
make test
```

The pre-commit hook runs `ruff format` + `ruff check --fix` on every commit;
the pre-push hook runs the offline pytest suite. Both mirror CI, so a green
local commit means a green CI run.

## Before you submit a PR

1. `make format` — apply ruff formatting
2. `make lint` — fix any lint findings
3. `make test` — all offline tests must pass (330+ tests, fully hermetic)
4. If you changed the MCP tool surface, run `make test-live` locally
   against the real Google API to confirm the serializer is still correct.
5. If you changed the parse layer, serializer, or CLI envelope shape, run
   `make test-all --browser-verify` to diff the programmatic output against
   a real browser render.

### Test breakdown

- `make test` — offline unit + integration tests (no network). Fast; always
  run before pushing.
- `make test-live` — live Google API tests (marker-gated). Rate-limit
  sensitive; run locally when touching anything that reaches the network.
- `make test-all` — everything, including the `--browser-verify` suites
  under `tests/browser_verification/` (Python API vs browser + CLI
  subprocess vs browser).
- Browser-verify driver is pluggable: set `STAYS_BROWSER_DRIVER=agent-browser`
  (default, preferred) or `STAYS_BROWSER_DRIVER=playwright` (fallback when
  agent-browser isn't installed). See `tests/browser_verification/README.md`.

### Golden-fixture tests

`tests/test_parse_golden.py`, `tests/test_serialize_golden.py`, and
`tests/test_cli_envelope_golden.py` pin byte-identical output of the parse,
serializer, and CLI envelope layers. If your change legitimately shifts any
of these outputs, regenerate the fixtures through the dedicated one-shot
script — never quietly relax an assertion or tweak the fixture by hand. A
silent fixture change hides exactly the kind of regression these tests are
meant to catch.

## Commit messages

Conventional-style prefix preferred: `feat:`, `fix:`, `chore:`, `docs:`,
`test:`, `ci:`. Keep the first line under 72 characters.

## Filing an issue

Please include:

- A minimal reproduction (Python snippet or MCP tool call + arguments)
- The exact `stays` and Python versions (`pip show stays` / `python --version`)
- Whether the failure is offline (serializer) or live (Google response)

## Code of conduct

Be kind. Assume good intent. The maintainers reserve the right to close
discussions that are not constructive.
