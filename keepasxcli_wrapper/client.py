import os
import socket
import sys
from configparser import ConfigParser
from pathlib import Path
from subprocess import Popen
from time import sleep

import click

from .gui import get_password_with_dialog
from .server import OPEN, QUIT, FILTERED_ENTRIES, DEFAULT_PID_PATH


class Client:
    GET_ATTRIBUTE = 'get '

    def __init__(self, db, pid_file, key_file, yubikey, timeout, no_prompt, window_for_password):
        self.pid_file = pid_file
        self.server = None
        self.timeout = timeout

        self.no_prompt = no_prompt
        self.window_for_password = window_for_password

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

        entry = '"' + entry.replace('"', '\"') + '"'
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
            if self.no_prompt:
                return False
            self.db = click.prompt("Open database", type=click.Path(exists=True))
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

        if self.window_for_password:
            password = get_password_with_dialog(self.db)
        elif not self.no_prompt:
            password = click.prompt("Password", hide_input=True)
        else:
            return False

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
            if try_prepare:
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
KEEPASSXCCLI2_CONFIG_FILE_PATH = lambda: str(Path.home().joinpath(KEEPASSXCCLI2_CONFIG_FILE_NAME))
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
        KEEPASSXCCLI2_CONFIG_FILE_PATH()
    ]
    if config_file and config_file not in files:
        files.append(config_file)
    c.read(files)

    # if name == KEEPASSXCCLI2_CONFIG_NONAME_SECTION and not c.has_section(name):
    #     d = {**KEEPASSXCCLI2_CONFIG_NONAME}
    #     prefix = f'{KEEPASSXCCLI2_CONFIG_ENV_PREFIX}_{KEEPASSXCCLI2_CONFIG_NONAME_SECTION.upper()}_'
    #     for key in d:
    #         if val := os.getenv(prefix + key.upper(), None):
    #             d[key] = val
    # else:
    result = {}
    default = {
        KEEPASSXCCLI2_CONFIG_NONAME_SECTION: KEEPASSXCCLI2_CONFIG_NONAME
    }.get(name, {})
    for key in KEEPASSXCCLI2_ITEMS:
        os_env = os.getenv(f'{KEEPASSXCCLI2_CONFIG_ENV_PREFIX}_{name.upper()}_{key.upper()}', None)
        config = c.get(name, key, fallback=None)
        default_value = default.get(key, None)
        result[key] = os_env or config or default_value
    if not result['pid_file']:
        raise ValueError(f"Set pid_file for section {name}")

    result['timeout'] = float(result['timeout']) if result['timeout'] else 0.3
    return result


@click.command(context_settings={'ignore_unknown_options': True})
@click.option('-n', '--name', type=str, help="name for config section", default=KEEPASSXCCLI2_CONFIG_NONAME_SECTION, show_default=True)
@click.option('-cf', '--config-file', type=click.Path(exists=True), help=f"[default: {KEEPASSXCCLI2_CONFIG_FILE_PATH()}]")
@click.option('-np', '--no-prompt', is_flag=True, help="No prompt will be invoked. Useful for use in scripts.")
@click.option('-wfp', '--window-for-password', is_flag=True, help="Window dialog for open database password.")
@click.argument('cmd', nargs=-1, required=True)
def raw(name, config_file, cmd, no_prompt, window_for_password):
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
    c = Client(no_prompt=no_prompt, window_for_password=window_for_password, **config)
    res = c.run_command(" ".join(cmd))
    print(res, end="" if cmd[0] == 'show' else "\n")


ATTRIBUTE_OPTIONS = ['password', 'username', 'url', 'notes', 'title']


@click.command()
@click.option('-n', '--name', type=str, help="name for config section", default=KEEPASSXCCLI2_CONFIG_NONAME_SECTION, show_default=True)
@click.option('-cf', '--config-file', type=click.Path(exists=True), help=f"[default: {KEEPASSXCCLI2_CONFIG_FILE_PATH()}]")
@click.option('-s', '--show', is_flag=True, help="Instead of copying it just write the attribute to console.")
@click.option('-np', '--no-prompt', is_flag=True, help="No prompt will be invoked. Useful for use in scripts.")
@click.option('-wfp', '--window-for-password', is_flag=True, help="Window dialog for open database password.")
@click.argument('entry', nargs=1)
@click.argument('attribute', nargs=1, default='password', type=click.Choice(ATTRIBUTE_OPTIONS))
def attr(show, entry, attribute, no_prompt, name, config_file, window_for_password):
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
    c = Client(no_prompt=no_prompt, window_for_password=window_for_password, **config)
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
