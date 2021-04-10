import os
import socket
import sys
from configparser import ConfigParser
from pathlib import Path
from subprocess import Popen
from time import sleep

import click

from server import OPEN, QUIT, FILTERED_ENTRIES, DEFAULT_PID_PATH


class Client:
    GET_ATTRIBUTE = 'get '

    def __init__(self, db, pid_file, key_file, yubikey, timeout, no_prompt):
        self.pid_file = pid_file
        self.server = None
        self.timeout = timeout
        self.no_prompt = no_prompt
        self.db = db
        self.key_file = key_file
        self.yubikey = yubikey

    def run_command(self, cmd):
        if cmd.startswith(OPEN):
            self.call_server(QUIT)
            self.prepare_server()
            return self.call_server('db-info')
        else:
            return self.call_server(cmd)

    def get_attribute(self, entry, show, attribute):

        entry = entry.replace(' ', r'\ ')
        if show:
            cmd = ['show']
            if attribute == 'password':
                cmd.append('-s')
        else:
            cmd = ['clip']

        cmd.extend(['-a', attribute, entry])

        return self.call_server(' '.join(cmd))

    def prepare_server(self):
        if not self.db:
            self.db = click.prompt("Open database: ", type=click.Path(exists=True))
        server_script = Path(__file__).parent.joinpath('server.py')
        ppn = [sys.executable, server_script, self.db, '-pf', self.pid_file, '-t', str(self.timeout)]
        if self.key_file:
            ppn.extend(['-kf', self.key_file])
        if self.yubikey:
            ppn.extend(['-yk', self.yubikey])
        Popen(ppn)

        sleep(1)
        connection = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        try:
            connection.connect(self.pid_file)
        except (FileNotFoundError, ConnectionRefusedError):
            connection.close()
            raise RuntimeError("Cant create server for database.")

        password = click.prompt("Password :", hide_input=True)

        connection.send(password.encode() + b'\n')

        success = connection.recv(1024).decode().strip().startswith('SUCCESS')

        connection.close()

        return success

    def call_server(self, cmd, try_prepare=True):
        connection = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        try:
            connection.connect(self.pid_file)
        except (FileNotFoundError, ConnectionRefusedError):
            connection.close()
            if try_prepare and not self.no_prompt:
                prepared = self.prepare_server()
                if prepared:
                    return self.call_server(cmd, False)
            raise RuntimeError("Can't create db and connect to server")

        connection.send(cmd.encode() + b'\n')
        result = []
        while new_data := connection.recv(4028):
            result.append(new_data)

        connection.close()

        return b''.join(result).decode()

    def __del__(self):
        if self.server:
            self.server.run_in_background()


def choose_entry(names, no_prompt=False):
    if len(names) == 0 or (no_prompt and len(names) > 1):
        print("No entry found.")
        return None

    if len(names) == 1:
        return names[0]

    for i, name in enumerate(names):
        print(f'[{i + 1}] {name}')

    res = click.prompt(f'\nChoose entry 1 - {len(names)} (default 1)',
                       default=1,
                       show_choices=False,
                       show_default=False,
                       type=click.Choice(map(str, range(1, len(names) + 1))))
    return names[int(res) - 1]


KEEPASSXCCLI2_CONFIG_FILE_NAME = '.keepassxccli2.ini'
KEEPASSXCCLI2_CONFIG_FILE_PATH = str(Path.home().joinpath(KEEPASSXCCLI2_CONFIG_FILE_NAME))
KEEPASSXCCLI2_CONFIG_ENV_PREFIX = 'KEEPASSXCCLI2'
KEEPASSXCCLI2_ITEMS = ['db', 'pid_file', 'key_file', 'yubikey', 'timeout']
KEEPASSXCCLI2_CONFIG_NONAME_SECTION = 'noname'
KEEPASSXCCLI2_CONFIG_NONAME = {
    'db': None,
    'pid_file': DEFAULT_PID_PATH,
    'key_file': None,
    'yubikey': None,
    'timeout': None,
}


def load_config(name, config_file):
    c = ConfigParser()
    files = [
        Path.home().joinpath('.config', KEEPASSXCCLI2_CONFIG_FILE_NAME),
        KEEPASSXCCLI2_CONFIG_FILE_PATH
    ]
    if config_file and config_file not in files:
        files.append(config_file)
    c.read(files)

    if c.has_section(name):
        d = {}
        for key in KEEPASSXCCLI2_ITEMS:
            d[key] = (
                os.getenv(f'{KEEPASSXCCLI2_CONFIG_ENV_PREFIX}_{name.upper()}_{key.upper()}', None)
                or c.get(name, key, fallback=None)
            )
        if not d['pid_file']:
            raise ValueError(f"Set pid_file for section {name}")
    elif name == KEEPASSXCCLI2_CONFIG_NONAME_SECTION:
        d = {**KEEPASSXCCLI2_CONFIG_NONAME}
        for key in d:
            if val := os.getenv(f'{KEEPASSXCCLI2_CONFIG_ENV_PREFIX}_{key.upper()}', None):
                d[key] = val
    else:
        raise ValueError(f"Section {name} does not exists in config files {', '.join(files)}")

    d['timeout'] = d['timeout'] or 0.3
    return d


HELP = """
"""


@click.command(context_settings={'ignore_unknown_options': True})
@click.option('-n', '--name', type=str, help="name for config section", default=KEEPASSXCCLI2_CONFIG_NONAME_SECTION, show_default=True)
@click.option('-cf', '--config-file', type=click.Path(exists=True), help=f"[default: {KEEPASSXCCLI2_CONFIG_FILE_PATH}]")
@click.option('-np', '--no-prompt', is_flag=True, help="No prompt will be invoked. Useful for use in scripts.")
@click.argument('cmd', nargs=-1, required=True)
def raw(name, config_file, cmd, no_prompt):
    """
    Simple wrapper around keepassxc-cli open. CMD is passed to keepassxc interactive shell.

    If database is not opened yet, you will be asked about
    the password. If no config is provided you will be also asked
    about the database path.

    Examples:
    \b
    # same as keepassxc-cli help
    kpowr help

    \b
    # same as keepassxc-cli db-info
    kpowr -n mydb db-info

    \b
    # same as keepassxc-cli edit -t "new title" /path/to/mydb google
    kpowr -n mydb edit -t "new title" google
    """
    config = load_config(name, config_file)
    c = Client(no_prompt=no_prompt, **config)
    res = c.run_command(" ".join(cmd))
    print(res, end="" if cmd[0] == 'show' else "\n")


ATTRIBUTE_OPTIONS = ['password', 'username', 'url', 'notes', 'title']


@click.command()
@click.option('-n', '--name', type=str, help="name for config section", default=KEEPASSXCCLI2_CONFIG_NONAME_SECTION, show_default=True)
@click.option('-cf', '--config-file', type=click.Path(exists=True), help=f"[default: {KEEPASSXCCLI2_CONFIG_FILE_PATH}]")
@click.option('-s', '--show', is_flag=True, help="Instead of copying it just write the attribute to console.")
@click.option('-np', '--no-prompt', is_flag=True, help="No prompt will be invoked. Useful for use in scripts.")
@click.argument('entry', nargs=1)
@click.argument('attribute', nargs=1, default='password', type=click.Choice(ATTRIBUTE_OPTIONS))
def attr(show, entry, attribute, no_prompt, name, config_file):
    """
    Copy ATTRIBUTE [default: password] from ENTRY to clipboard.

    If database is not opened yet, you will be asked about
    the password. If no config is provided you will be also asked
    about the database path.

    Examples:

    \b
    # copy google password to clipboard
    kpowg google

    \b
    # copy username from ssh entry from workdb (section defined in config)
    kpowg -n workdb ssh username

    \b
    # print password for gmail entry without waiting for prompt
    kpowg --np -s gmail
    """
    config = load_config(name, config_file)
    c = Client(no_prompt=no_prompt, **config)
    entries = c.call_server(f'{FILTERED_ENTRIES} {entry}').splitlines()
    entry = choose_entry(entries, no_prompt)
    if entry:
        res = c.get_attribute(entry, show, attribute)
        if show:
            print(res, end='')
        else:
            print(f'{attribute} for entry {entry} has been clipped')
    else:
        print("no entry was found")


if __name__ == '__main__':
    attr()