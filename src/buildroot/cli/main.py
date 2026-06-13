"""CLI entry point for the buildroot reconstructor."""

import click

from buildroot import __version__
from buildroot.cli.commands.agent_cmd import agent_cmd
from buildroot.cli.commands.compare import compare
from buildroot.cli.commands.inspect_cmd import inspect_cmd
from buildroot.cli.commands.reconstruct import reconstruct
from buildroot.cli.commands.verify import verify


@click.group()
@click.version_option(version=__version__, prog_name="buildroot")
def cli():
    """Reconstruct Maven artifact build environments as Containerfiles."""


cli.add_command(agent_cmd, name="agent")
cli.add_command(compare)
cli.add_command(reconstruct)
cli.add_command(verify)
cli.add_command(inspect_cmd, name="inspect")
