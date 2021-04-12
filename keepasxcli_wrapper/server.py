#!/usr/bin/env python3
import asyncio
import os
import tempfile
from difflib import SequenceMatcher
from functools import reduce
from operator import mul
from pathlib import Path

import click
from pexpect import spawn, TIMEOUT


def open_db(db, timeout, key_file, yubikey):
    db = Path(db).expanduser().absolute()
    if not db.exists():
        raise ValueError(f"database '{db}' does not exists")
    args = ['open']
    if key_file:
        args.extend(['-k', str(key_file)])
    if yubikey:
        args.extend(['-y', yubikey])
    args.append(str(db))
    p = spawn('keepassxc-cli', args, encoding='utf-8', timeout=timeout)
    return p


def get_db_name(first_line):
    db_name_end = first_line.find('>')
    return first_line[:db_name_end] if db_name_end != -1 else ''


QUIT = 'quit'
CLOSE = 'close'
OPEN = 'open'
FILTERED_ENTRIES = 'locate_cached'
DEFAULT_PID_PATH = os.path.join(tempfile.gettempdir(), 'kdbx.pid')


class Handler:

    def __init__(self, process, pid_file):
        self.process = process
        self.db_name = ''
        self.entries = []
        self.pid_file = pid_file
        self.waiting_for_password = True
        self.server = None

    def set_password(self, password):
        if self.waiting_for_password:
            self.process.sendline(password)
            self.result()
            self._update_db_name()
            if self.db_name != '':
                self.waiting_for_password = False
                return f"SUCCESS: Database {self.db_name} is now open"
            else:
                self.quit()

                return "Database could not be opened. Probably wrong password."

    def call_command(self, cmd):
        self.process.sendline(cmd)
        _, data = self.result()
        return self.process.crlf.join(data)

    def _update_db_name(self):
        self.process.sendline('')
        self.db_name, _ = self.result()

    def result(self, timeout=None):
        timeout = timeout if timeout is not None else self.process.timeout
        res = [self.process.crlf, self.process.delimiter]

        lines = []
        try:
            while True:
                self.process.expect(res, timeout=timeout)
                lines.append(self.process.before)
        except TIMEOUT:
            pass

        if lines and (split_by := lines[0].rfind('>')) > -1:
            db = lines[0][:split_by]
        else:
            db = ''

        return db, lines[1:]

    async def async_server(self):
        server = await asyncio.start_unix_server(self._handler, self.pid_file)
        async with server:
            self.server = asyncio.Task(server.serve_forever())
            try:
                await self.server
            except asyncio.CancelledError:
                print(f"Serving database {self.db_name} stopped.")

    def quit(self):
        self.process.sendline('quit')
        self.process.close()
        self.process = None
        return 'Database is closed'

    def get_filtered_entries(self, term):
        response = self.call_command('locate ' + term)
        return response

    async def _handler(self, reader, writer):
        data = (await reader.readuntil()).decode().strip()

        if self.process:
            if self.waiting_for_password:
                response = self.set_password(data)
            elif data.startswith(OPEN):
                response = "Open is not supported. Close or quit database instead."
            elif data.startswith(QUIT) or data.startswith(CLOSE):
                response = self.quit()
            elif data.startswith(FILTERED_ENTRIES):
                term = data[len(FILTERED_ENTRIES):].strip().lower()
                response = self.get_filtered_entries(term)
            else:
                response = self.call_command(data)

            writer.write(response.encode())
        else:
            writer.write(b"Database is closed.")
        await writer.drain()
        writer.close()

        if self.process:
            self._update_db_name()
        if not self.process and self.server:
            self.server.cancel()


@click.command()
@click.option('-pf', '--pid-file', type=click.Path(), default=DEFAULT_PID_PATH)
@click.option('-t', '--timeout', type=float, default=0.5)
@click.option('-kf', '--key-file', type=click.Path())
@click.option('-yk', '--yubikey', type=str)
@click.option('-pp', '--password-prompt', is_flag=True)
@click.argument('database')
def run_server(pid_file, timeout, database, key_file, yubikey, password_prompt):
    p = open_db(database, timeout, key_file, yubikey)
    h = Handler(p, pid_file)
    if password_prompt:
        p = click.prompt("Password", hide_input=True)
        print(f'"{p}"')
        print(h.set_password(p))
        if h.process is None:
            return
    asyncio.run(h.async_server())


if __name__ == '__main__':
    run_server()
