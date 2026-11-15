# ark agent

Python CLI: extract from an encrypted iPhone backup → local staging archive → (later) batch sync to the ark server.

## Commands

```sh
ark status
ark --backup /path/to/MobileSync/Backup/<udid> --out ./staging all
ark --backup … messages|contacts|voicemail|voicememos|whatsapp|wifi
ark view --root ./staging
ark sync   # not implemented yet
```

Backup encryption password: `--password-file`, `--password`, or interactive prompt. It never leaves this machine.

## Config (planned for sync)

```yaml
ark:
  url: https://ark.example.com
  api_key: "…"   # or env ARK_API_KEY
```

See `config.example.yml` for the local staging viewer settings.

## Dev

```sh
cd agent
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -e .
ark status
```

Optional: `ffmpeg` on `PATH` for on-demand media conversion in the local viewer.

## Windows release

GitHub Actions builds `ark-agent-<version>-windows-amd64.exe` (PyInstaller) and attaches it to the GitHub Release with the server compose assets.
