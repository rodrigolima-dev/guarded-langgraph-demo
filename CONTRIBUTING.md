# Contributing

Keep examples offline and fictional. Changes to authorization, retrieval, or response routing need tests for both an allowed path and a denied or failure path.

Before opening a pull request:

```sh
uv sync --locked
uv run --locked ruff check .
uv run --locked mypy --strict src
uv run --locked python -m unittest discover -s tests -v
uv pip check
uv run --locked python -m compileall -q src
```

Review the source, fixtures, documentation, screenshots, and commit history for private material. Do not include real tenant names, customer records, credentials, prompts, service URLs, or operational rules. Explain any new external dependency or network behavior in the pull request.
