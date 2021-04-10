#!/usr/bin/env python3
import asyncio
import os
import tempfile
from difflib import SequenceMatcher
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


def sort_entry_filter_key(term):
    def f(entry):
        if term == entry:
            return 1
        if entry.startswith(term):
            return 0.9 + (pow(len(entry), -1) / 10)
        return SequenceMatcher(None, term, entry).ratio()
    return f


class Handler:

    def __init__(self, process, pid_file):
        self.process = process
        self.db_name = ''
        self.entries = []
        self.pid_file = pid_file
        self.waiting_for_password = True

    def set_password(self, password):
        if self.waiting_for_password:
            self.process.sendline(password)
            self.result()
            self._refresh_cache()
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

    def _refresh_cache(self):
        self.process.sendline('ls')
        self.db_name, entries = self.result(max(1, self.process.timeout))  # increase timeout for listing
        self.entries = [e.strip().lower() for e in entries]

    def run_in_background(self):
        if os.fork():
            return
        asyncio.run(self.async_server())
        exit(os.EX_OK)

    async def async_server(self):
        server = await asyncio.start_unix_server(self._handler, self.pid_file)
        async with server:
            await server.serve_forever()

    def quit(self):
        self.process.sendline('quit')
        self.process.close()
        self.process = None
        return 'Database is closed'

    def get_filtered_entries(self, term):
        response = filter(lambda e: term in e, self.entries)
        response = sorted(response, key=sort_entry_filter_key(term), reverse=True)

        return self.process.crlf.join(response)

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
            writer.write("Database is closed.")
        await writer.drain()
        writer.close()

        if self.process:
            self._refresh_cache()
        else:
            exit(os.EX_OK)


@click.command()
@click.option('-pf', '--pid-file', type=click.Path(), default=DEFAULT_PID_PATH)
@click.option('-t', '--timeout', type=float, default=0.5)
@click.option('-kf', '--key-file', type=click.Path())
@click.option('-yk', '--yubikey', type=str)
@click.argument('database')
def run_server(pid_file, timeout, database, key_file, yubikey):
    p = open_db(database, timeout, key_file, yubikey)
    h = Handler(p, pid_file)
    asyncio.run(h.async_server())


if __name__ == '__main__':
    run_server()
