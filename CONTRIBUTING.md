# Contributing to stays

Thanks for your interest! This project is a lightweight, maintainable wrapper
around Google Hotels — PRs are welcome.

## Quick dev setup

```bash
git clone https://github.com/victoriawei/stays.git
cd stays
make install-dev
make test
```

## Before you submit a PR

1. `make format` — apply ruff formatting
2. `make lint` — fix any lint findings
3. `make test` — all offline tests must pass
4. If you changed the MCP tool surface, run `make test-live` locally
   against the real Google API to confirm the serializer is still correct.

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
