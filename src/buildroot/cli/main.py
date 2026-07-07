"""CLI entry point for the buildroot reconstructor."""

import click

from buildroot import __version__
from buildroot.utils.dotenv import load_dotenv

load_dotenv()
from buildroot.cli.commands.agent_cmd import agent_cmd
from buildroot.cli.commands.compare import compare
from buildroot.cli.commands.db_cmd import db_cmd
from buildroot.cli.commands.eval_cmd import eval_cmd
from buildroot.cli.commands.inspect_cmd import inspect_cmd
from buildroot.cli.commands.kb_cmd import kb_cmd
from buildroot.cli.commands.reconstruct import reconstruct
from buildroot.cli.commands.regression_cmd import regression_cmd
from buildroot.cli.commands.migrate_pinned import migrate_pinned_cmd
from buildroot.cli.commands.validate import validate
from buildroot.cli.commands.verify import verify


@click.group()
@click.version_option(version=__version__, prog_name="buildroot")
def cli():
    """Reconstruct Maven artifact build environments as Containerfiles."""


cli.add_command(agent_cmd, name="agent")
cli.add_command(compare)
cli.add_command(db_cmd, name="db")
cli.add_command(eval_cmd, name="eval")
cli.add_command(inspect_cmd, name="inspect")
cli.add_command(kb_cmd, name="kb")
cli.add_command(reconstruct)
cli.add_command(regression_cmd, name="regression")
cli.add_command(migrate_pinned_cmd)
cli.add_command(validate)
cli.add_command(verify)
