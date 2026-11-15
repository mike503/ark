# ark agent

Python CLI: extract from an encrypted iPhone backup → local staging → batch sync to the ark server.

## Status

Scaffold only. Extract, local staging, and `ark sync` are the next agent milestones.

## Config (planned)

```yaml
ark:
  url: https://ark.example.com
  api_key: "…"   # or env ARK_API_KEY
```

Backup encryption password never leaves the extract machine.

## Dev

```sh
cd agent
python -m venv .venv
source .venv/bin/activate
pip install -e .
ark status
```
