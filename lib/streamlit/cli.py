# -*- coding: utf-8 -*-
# Copyright 2018-2019 Streamlit Inc.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""This is a script which is run when the Streamlit package is executed."""

# Python 2/3 compatibility
from __future__ import print_function, division, absolute_import

# Not importing unicode_literals from __future__ because click doesn't like it.
from streamlit.compatibility import setup_2_3_shims

setup_2_3_shims(globals())

from streamlit import config as _config

import os
import click

import streamlit
from streamlit.credentials import Credentials
from streamlit import version
import streamlit.bootstrap as bootstrap

LOG_LEVELS = ["error", "warning", "info", "debug"]

NEW_VERSION_TEXT = """
  %(new_version)s

  See what's new at https://discuss.streamlit.io/c/announcements

  Enter the following command to upgrade:
  %(prompt)s %(command)s
""" % {
    "new_version": click.style(
        "A new version of Streamlit is available.", fg="blue", bold=True
    ),
    "prompt": click.style("$", fg="blue"),
    "command": click.style("pip install streamlit --upgrade", bold=True),
}


@click.group(context_settings={"auto_envvar_prefix": "STREAMLIT"})
@click.option("--log_level", show_default=True, type=click.Choice(LOG_LEVELS))
@click.version_option(prog_name="Streamlit")
@click.pass_context
def main(ctx, log_level="info"):
    """Try out a demo with:

        $ streamlit hello

    Or use the line below to run your own script:

        $ streamlit run your_script.py
    """

    if log_level:
        import streamlit.logger

        streamlit.logger.set_log_level(log_level.upper())


@main.command("help")
@click.pass_context
def help(ctx):
    """Print this help message."""
    # Pretend user typed 'streamlit --help' instead of 'streamlit help'.
    import sys

    assert len(sys.argv) == 2  # This is always true, but let's assert anyway.
    sys.argv[1] = "--help"
    main()


@main.command("version")
@click.pass_context
def main_version(ctx):
    """Print Streamlit's version number."""
    # Pretend user typed 'streamlit --version' instead of 'streamlit version'
    import sys

    assert len(sys.argv) == 2  # This is always true, but let's assert anyway.
    sys.argv[1] = "--version"
    main()


@main.command("docs")
def main_docs():
    """Show help in browser."""
    print("Showing help page in browser...")
    from streamlit import util

    util.open_browser("https://streamlit.io/docs")


@main.command("hello")
def main_hello():
    """Runs the Hello World script."""
    from streamlit.hello import hello

    filename = hello.__file__

    # For Python 2 when Streamlit is actually installed (make install rather
    # than make develop).
    if filename.endswith(".pyc"):
        filename = "%s.py" % filename[:-4]

    _main_run(filename)


def _convert_config_option_to_click_option(config_option):
    """Composes given config option options as options for click lib."""
    option = "--{}".format(config_option.key)
    param = config_option.key.replace(".", "_")
    description = config_option.description
    if config_option.deprecated:
        description += "\n {} - {}".format(
            config_option.deprecation_text, config_option.deprecation_date
        )
    envvar = "STREAMLIT_CONFIG_{}".format(param.upper())

    return {
        "param": param,
        "description": description,
        "type": config_option.type,
        "option": option,
        "envvar": envvar,
    }


def configurator_options(func):
    """Decorator that adds config param keys to click dynamically."""
    for _, value in reversed(_config._config_options.items()):
        parsed_parameter = _convert_config_option_to_click_option(value)
        config_option = click.option(
            parsed_parameter["option"],
            parsed_parameter["param"],
            help=parsed_parameter["description"],
            type=parsed_parameter["type"],
            envvar=parsed_parameter["envvar"],
        )
        func = config_option(func)
    return func


def _apply_config_options_from_cli(kwargs):
    """The "streamlit run" command supports passing Streamlit's config options
    as flags.

    This function reads through all config flags, massage them, and
    pass them to _set_config() overriding default values and values set via
    config.toml file

    """
    for config_option in kwargs:
        if kwargs[config_option] is not None:
            config_option_def_key = config_option.replace("_", ".")

            _config._set_option(
                config_option_def_key, kwargs[config_option], "cli call option"
            )


# Fetch remote file at url_path to script_path
def _download_remote(script_path, url_path):
    import requests

    with open(script_path, "wb") as fp:
        try:
            resp = requests.get(url_path)
            resp.raise_for_status()
            fp.write(resp.content)
        except requests.exceptions.RequestException as e:
            raise click.BadParameter(("Unable to fetch {}.\n{}".format(url_path, e)))


@main.command("run")
@configurator_options
@click.argument("target", required=True, envvar="STREAMLIT_RUN_TARGET")
@click.argument("args", nargs=-1)
def main_run(target, args=None, **kwargs):
    """Run a Python script, piping stderr to Streamlit.

    The script can be local or it can be an url. In the latter case, Streamlit
    will download the script to a temporary file and runs this file.

    """
    from validators import url

    _apply_config_options_from_cli(kwargs)

    if url(target):
        from streamlit.temporary_directory import TemporaryDirectory
        with TemporaryDirectory() as temp_dir:
            from urllib.parse import urlparse
            path = urlparse(target).path
            script_path = os.path.join(temp_dir, path.strip('/').rsplit('/', 1)[-1])
            _download_remote(script_path, target)
            _main_run(script_path, args)
    else:
        if not os.path.exists(target):
            raise click.BadParameter("File does not exist: {}".format(target))
        _main_run(target, args)


# Utility function to compute the command line as a string
def _get_command_line_as_string():
    import subprocess

    cmd_line_as_list = [click.get_current_context().parent.command_path]
    cmd_line_as_list.extend(click.get_os_args())
    return subprocess.list2cmdline(cmd_line_as_list)


def _main_run(file, args=[]):
    command_line = _get_command_line_as_string()

    # Set a global flag indicating that we're "within" streamlit.
    streamlit._is_running_with_streamlit = True

    # Check credentials.
    Credentials.get_current().check_activated(auto_resolve=True)

    # Notify if streamlit is out of date.
    if version.should_show_new_version_notice():
        click.echo(NEW_VERSION_TEXT)

    bootstrap.run(file, command_line, args)


# DEPRECATED

# TODO: Remove after 2019-09-01
@main.command("clear_cache", deprecated=True, hidden=True)
@click.pass_context
def main_clear_cache(ctx):
    """Deprecated."""
    click.echo(click.style('Use "cache clear" instead.', fg="red"))
    ctx.invoke(cache_clear)


# TODO: Remove after 2019-09-01
@main.command("show_config", deprecated=True, hidden=True)
@click.pass_context
def main_show_config(ctx):
    """Deprecated."""
    click.echo(click.style('Use "config show" instead.', fg="red"))
    ctx.invoke(config_show)


# SUBCOMMAND: cache


@main.group("cache")
def cache():
    """Manage the Streamlit cache."""
    pass


@cache.command("clear")
def cache_clear():
    """Clear the Streamlit on-disk cache."""
    import streamlit.caching

    result = streamlit.caching.clear_cache()
    cache_path = streamlit.caching.get_cache_path()
    if result:
        print("Cleared directory %s." % cache_path)
    else:
        print("Nothing to clear at %s." % cache_path)


# SUBCOMMAND: config


@main.group("config")
def config():
    """Manage Streamlit's config settings."""
    pass


@config.command("show")
def config_show():
    """Show all of Streamlit's config settings."""
    _config.show_config()


# SUBCOMMAND: activate


@main.group("activate", invoke_without_command=True)
@click.pass_context
def activate(ctx):
    """Activate Streamlit by entering your email."""
    if not ctx.invoked_subcommand:
        Credentials.get_current().activate()


@activate.command("reset")
def activate_reset():
    """Reset Activation Credentials."""
    Credentials.get_current().reset()


if __name__ == "__main__":
    main()
