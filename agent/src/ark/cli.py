"""CLI stub. Extract / stage / sync land in later milestones."""

from __future__ import annotations

import click

from ark import __version__


@click.group()
@click.version_option(__version__, prog_name="ark")
def main() -> None:
    """ark — personal archive agent."""


@main.command()
def status() -> None:
    """Show agent scaffold status."""
    click.echo("ark agent scaffold — extract/stage/sync not wired yet")


if __name__ == "__main__":
    main()
