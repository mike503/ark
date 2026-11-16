#!/usr/bin/env python3
"""CLI for ark agent: encrypted backup -> local staging -> sync to server."""

from __future__ import annotations

import argparse
import getpass
import os
import shutil
import sys
from pathlib import Path

from ark.agent_config import load_agent_config
from ark.archive import Archive
from ark.backup_io import open_backup
from ark.dates import utc_now_iso
from ark.extractors import contacts as contacts_ex
from ark.extractors import messages as messages_ex
from ark.extractors import voicemail as voicemail_ex
from ark.extractors import voicememos as voicememos_ex
from ark.extractors import whatsapp as whatsapp_ex
from ark.extractors import wifi as wifi_ex
from ark.report import CategoryReport, RunReport
from ark.sync import sync_staging
from ark.versioning import SCHEMA_VERSION, __version__

_ROOT = Path(__file__).resolve().parents[2]


def _cleanup_work(work_dir: Path) -> None:
    if not work_dir.exists():
        return
    shutil.rmtree(work_dir, ignore_errors=True)
    if work_dir.exists():
        print(f"Warning: could not fully remove work dir: {work_dir}", file=sys.stderr)
    else:
        print(f"Cleaned work: {work_dir}")


CORE_COMMANDS = (
    "messages",
    "voicemail",
    "voicememos",
    "contacts",
    "whatsapp",
    "wifi",
)


def _password_from_file(path: Path) -> str:
    lines = [
        ln.strip()
        for ln in path.read_text(encoding="utf-8").splitlines()
        if ln.strip() and not ln.strip().startswith("#")
    ]
    if not lines:
        raise SystemExit(f"Password file empty: {path}")
    return lines[0]


def resolve_password(args: argparse.Namespace, agent_cfg: dict) -> str:
    """CLI > agent.yml / env > prompt. Never leaves this machine."""
    if args.password:
        return args.password
    if args.password_file:
        path = Path(args.password_file)
        if not path.is_file():
            raise SystemExit(f"Password file not found: {path}")
        return _password_from_file(path)
    if agent_cfg.get("password"):
        return str(agent_cfg["password"])
    cfg_file = agent_cfg.get("password_file")
    if cfg_file:
        path = Path(cfg_file)
        if not path.is_file():
            raise SystemExit(f"Password file not found (agent.yml): {path}")
        return _password_from_file(path)
    return getpass.getpass("Backup encryption password: ")


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="ark",
        description=(
            "Extract from an encrypted iPhone backup into a local staging archive, "
            "then sync to the ark server (auto_sync: true by default in agent.yml)."
        ),
    )
    p.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {__version__} (schema {SCHEMA_VERSION})",
    )
    p.add_argument(
        "--config",
        type=Path,
        default=None,
        help="Path to agent.yml (default: ./agent.yml)",
    )
    p.add_argument(
        "--backup",
        type=Path,
        required=False,
        default=None,
        help="Path to encrypted MobileSync backup folder (required for extract commands)",
    )
    p.add_argument(
        "--out",
        type=Path,
        default=None,
        help="Local staging archive root (default: agent.yml out, else ./out)",
    )
    p.add_argument(
        "--work",
        type=Path,
        default=None,
        help="Scratch decrypt dir (default: <out>/work). Removed after each run unless --keep-work.",
    )
    p.add_argument(
        "--keep-work",
        action="store_true",
        help="Leave --work contents after the run (debug).",
    )
    p.add_argument(
        "--diagnostic",
        action="store_true",
        help="Write human-readable JSON dumps under <out>/export/ (off by default).",
    )
    p.add_argument(
        "--password-file",
        type=Path,
        default=None,
        help="File containing the backup encryption password (first non-comment line)",
    )
    p.add_argument(
        "--password",
        help="Backup encryption password (also: agent.yml password / ARK_BACKUP_PASSWORD)",
    )
    sync_group = p.add_mutually_exclusive_group()
    sync_group.add_argument(
        "--sync",
        dest="sync_override",
        action="store_true",
        default=None,
        help="After extract, sync even if agent.yml has auto_sync: false",
    )
    sync_group.add_argument(
        "--no-sync",
        dest="sync_override",
        action="store_false",
        help="Skip sync after extract even if auto_sync: true",
    )
    sub = p.add_subparsers(dest="cmd", required=True)
    for name in CORE_COMMANDS:
        sub.add_parser(name)
    sub.add_parser(
        "all",
        help="Run messages, voicemail, voicememos, contacts, whatsapp, wifi; then sync if enabled",
    )
    sync_p = sub.add_parser(
        "sync",
        help="Upload local staging archive to the ark server (without extracting)",
    )
    sync_p.add_argument(
        "--out",
        type=Path,
        default=None,
        dest="sync_out",
        help="Staging archive root (same as global --out)",
    )
    sub.add_parser("status", help="Show agent version and readiness")
    return p


def _resolve_paths(args: argparse.Namespace, agent_cfg: dict) -> tuple[Path | None, Path]:
    backup = args.backup or agent_cfg.get("backup")
    out = args.out or agent_cfg.get("out") or (_ROOT / "out")
    return backup, Path(out)


def _want_sync(args: argparse.Namespace, agent_cfg: dict) -> bool:
    if args.sync_override is not None:
        return bool(args.sync_override)
    return bool(agent_cfg.get("auto_sync", True))


def run_extract(args: argparse.Namespace, agent_cfg: dict) -> int:
    backup, out = _resolve_paths(args, agent_cfg)
    if backup is None:
        raise SystemExit("--backup is required (or set backup: in agent.yml)")
    backup = Path(backup)
    if not backup.is_dir():
        raise SystemExit(f"Backup not found: {backup}")

    work_dir: Path = args.work if args.work is not None else out / "work"
    archive_path = out / "archive" / "archive.sqlite"
    export_dir: Path | None = (out / "export") if args.diagnostic else None
    blobs_dir = out / "blobs"
    messages_dir = out / "messages"
    for d in (blobs_dir, messages_dir, work_dir, archive_path.parent):
        d.mkdir(parents=True, exist_ok=True)
    if export_dir is not None:
        export_dir.mkdir(parents=True, exist_ok=True)

    passphrase = resolve_password(args, agent_cfg)
    print(f"Opening backup {backup.name} (key derivation may take 10-30s)...")
    try:
        backup_obj = open_backup(backup, passphrase)
    except ValueError as exc:
        raise SystemExit(f"Password rejected / cannot decrypt: {exc}") from exc
    print("Password OK.")

    archive = Archive(archive_path)
    started_at = utc_now_iso()
    cmds = list(CORE_COMMANDS) if args.cmd == "all" else [args.cmd]
    archive.set_meta("backup_id", backup.name)
    archive.set_meta("last_run", started_at)
    archive.set_meta("last_run_tool_version", __version__)
    archive.set_meta("last_run_schema_version", str(SCHEMA_VERSION))
    archive.set_meta("tool_version", __version__)
    archive.set_meta("schema_version", str(SCHEMA_VERSION))
    run_id = archive.begin_run(
        started_at=started_at,
        tool_version=__version__,
        schema_version=SCHEMA_VERSION,
        backup_id=backup.name,
        commands=cmds,
        diagnostic=bool(args.diagnostic),
    )
    try:
        from ark.backup_meta import read_backup_info

        info = read_backup_info(backup)
        for key in (
            "backup_finished_at",
            "backup_started_at",
            "snapshot_state",
            "device_name",
            "product_name",
            "product_type",
            "product_version",
            "build_version",
            "serial_number",
            "phone_number",
        ):
            val = info.get(key)
            if val is not None and val != "":
                archive.set_meta(key, str(val))
        archive.set_meta("is_full_backup", "1" if info.get("is_full_backup") else "0")
    except Exception as exc:  # noqa: BLE001
        print(f"Warning: could not read backup Info/Status.plist: {exc}")

    print(f"Tool {__version__} · schema {SCHEMA_VERSION}")
    report = RunReport(
        started_at=started_at,
        backup_id=backup.name,
        tool_version=__version__,
        schema_version=SCHEMA_VERSION,
    )
    exit_ok = False

    try:
        for cmd in cmds:
            print(f"\n=== {cmd} ===")
            try:
                if cmd == "messages":
                    r = messages_ex.extract_messages(
                        backup_obj,
                        archive=archive,
                        work=work_dir,
                        export_dir=export_dir,
                        messages_dir=messages_dir,
                        backup_id=backup.name,
                    )
                elif cmd == "voicemail":
                    r = voicemail_ex.extract_voicemail(
                        backup_obj,
                        archive=archive,
                        work=work_dir,
                        export_dir=export_dir,
                        blobs_dir=blobs_dir,
                    )
                elif cmd == "voicememos":
                    r = voicememos_ex.extract_voicememos(
                        backup_obj,
                        archive=archive,
                        work=work_dir,
                        export_dir=export_dir,
                        blobs_dir=blobs_dir,
                    )
                elif cmd == "contacts":
                    r = contacts_ex.extract_contacts(
                        backup_obj,
                        archive=archive,
                        work=work_dir,
                        export_dir=export_dir,
                    )
                elif cmd == "whatsapp":
                    r = whatsapp_ex.extract_whatsapp(
                        backup_obj,
                        archive=archive,
                        work=work_dir,
                        export_dir=export_dir,
                        blobs_dir=blobs_dir,
                        backup_id=backup.name,
                    )
                elif cmd == "wifi":
                    r = wifi_ex.extract_wifi(
                        backup_obj,
                        archive=archive,
                        work=work_dir,
                        export_dir=export_dir,
                    )
                else:
                    raise SystemExit(f"Unknown command {cmd}")
            except Exception as exc:  # noqa: BLE001
                r = CategoryReport(category=cmd, status="failed")
                r.note(f"Unhandled error: {exc}")
                print(f"ERROR: {exc}")
            report.add(r)
            print(
                f"-> {r.category}: {r.status} "
                f"(ok={r.items_ok} partial={r.items_partial} failed={r.items_failed})"
            )
            for note in r.notes:
                print(f"   - {note}")

        report.finished_at = utc_now_iso()
        status = report.overall_status()
        archive.set_meta("last_run_status", status)
        archive.set_meta("last_run_finished", report.finished_at)
        archive.finish_run(run_id, finished_at=report.finished_at, status=status)
        archive.close()
        print(f"\nOverall: {status}")
        print(f"Archive: {archive_path}")
        if export_dir is not None:
            report_path = export_dir / "run_report.json"
            report.write(report_path)
            print(f"Export:  {export_dir}")
            print(f"Report:  {report_path}")
        exit_ok = status in {"ok", "partial"}
    finally:
        if not args.keep_work:
            _cleanup_work(work_dir)

    if not exit_ok:
        return 1

    if _want_sync(args, agent_cfg):
        sync_code = sync_staging(out, agent_cfg)
        # Sync not-implemented (2) does not fail a successful extract.
        if sync_code == 1:
            return 1
    else:
        print("\nSkipping sync (auto_sync disabled; use --sync or ark sync).")

    return 0


def run_sync(args: argparse.Namespace, agent_cfg: dict) -> int:
    if getattr(args, "sync_out", None) is not None and args.out is None:
        args.out = args.sync_out
    _backup, out = _resolve_paths(args, agent_cfg)
    return sync_staging(out, agent_cfg)


def run_status(agent_cfg: dict) -> int:
    print(f"ark agent {__version__} (schema {SCHEMA_VERSION})")
    print("extract: ready (messages, voicemail, voicememos, contacts, whatsapp, wifi, all)")
    print("sync:    stub (auto after extract when auto_sync: true; API not wired yet)")
    cfg_path = agent_cfg.get("path")
    print(f"config:  {cfg_path if cfg_path else '(none — using defaults / env)'}")
    print(f"auto_sync: {agent_cfg.get('auto_sync', True)}")
    print(f"server:  {agent_cfg.get('url') or '(not set)'}")
    has_pw = bool(
        agent_cfg.get("password")
        or agent_cfg.get("password_file")
        or os.environ.get("ARK_BACKUP_PASSWORD")
    )
    print(f"backup password: {'set' if has_pw else '(prompt / --password / --password-file)'}")
    return 0


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    agent_cfg = load_agent_config(args.config)
    if args.cmd == "status":
        return run_status(agent_cfg)
    if args.cmd == "sync":
        return run_sync(args, agent_cfg)
    return run_extract(args, agent_cfg)


if __name__ == "__main__":
    raise SystemExit(main())
