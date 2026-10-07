# Contributing

Keep examples offline and fictional. Changes to authorization, retrieval, or response routing need tests for both an allowed path and a denied or failure path.

Before opening a pull request:

```sh
python -m pip install -e . ruff==0.16.10 mypy==2.4.0
ruff check .
mypy --strict src
python -m unittest discover -s tests -v
python -m pip check
python -m compileall -q src
```

Review the source, fixtures, documentation, screenshots, and commit history for private material. Do not include real tenant names, customer records, credentials, prompts, service URLs, or operational rules. Explain any new external dependency or network behavior in the pull request.
