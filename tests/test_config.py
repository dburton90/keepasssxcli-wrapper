import os
from configparser import ConfigParser
from pathlib import Path
from tempfile import NamedTemporaryFile
from time import time

import pytest
from pytest import fixture

from keepasxcli_wrapper import client


def create_config():
    return ConfigParser()


def add_section(cfg, name, db, pid_file, key_file=None, yubikey=None, timeout=None):
    cfg[name] = {}
    cfg[name]['db'] = db
    cfg[name]['pid_file'] = pid_file
    if key_file:
        cfg[name]['key_file'] = key_file
    if yubikey:
        cfg[name]['yubikey'] = yubikey
    if timeout:
        cfg[name]['timeout'] = timeout


@fixture
def base_config(tmpdir_factory, db1, pid_file):
    cf = tmpdir_factory.mktemp('config').join('base.ini')
    c = create_config()
    add_section(c, client.KEEPASSXCCLI2_CONFIG_NONAME_SECTION, str(db1), pid_file)
    add_section(c, 'custom', str(db1), pid_file + 'custom')
    with open(cf, 'w') as f:
        c.write(f)

    return str(cf), c


@fixture
def home_config(tmpdir_factory, db1, pid_file, monkeypatch):
    fakehome = tmpdir_factory.mktemp('fake_home')
    monkeypatch.setattr(client.Path, "home", lambda: Path(str(fakehome)))

    ff = fakehome.join(client.KEEPASSXCCLI2_CONFIG_FILE_NAME)
    c = create_config()
    add_section(c, client.KEEPASSXCCLI2_CONFIG_NONAME_SECTION, str(db1) + 'home', pid_file + 'home', timeout=str(4))
    with open(ff, 'w') as f:
        c.write(f)

    return str(ff), c


@fixture
def db_noname_in_env():
    cdb = '/custom_db'
    key = f'{client.KEEPASSXCCLI2_CONFIG_ENV_PREFIX}_{client.KEEPASSXCCLI2_CONFIG_NONAME_SECTION.upper()}_DB'
    os.environ[key] = cdb
    yield cdb
    del os.environ[key]


def test_get_config_from_home(home_config, db1, pid_file):
    cfg = client.load_config(client.KEEPASSXCCLI2_CONFIG_NONAME_SECTION, None)
    assert cfg == {
        'db':  str(db1) + 'home',
        'pid_file': str(pid_file) + 'home',
        'key_file': None,
        'yubikey': None,
        'timeout': 4
    }


def test_home_config_override_by_explicit(home_config, base_config, db1, pid_file):
    cfg = client.load_config(client.KEEPASSXCCLI2_CONFIG_NONAME_SECTION, base_config[0])
    assert cfg == {
        'db':  str(db1),
        'pid_file': str(pid_file),
        'key_file': None,
        'yubikey': None,
        'timeout': 4
    }


def test_explicit_config_override_by_env(base_config, db1, pid_file, db_noname_in_env):
    cfg = client.load_config(client.KEEPASSXCCLI2_CONFIG_NONAME_SECTION, base_config[0])
    assert cfg == {
        'db':  db_noname_in_env,
        'pid_file': str(pid_file),
        'key_file': None,
        'yubikey': None,
        'timeout': 0.3
    }


def test_no_config():
    cfg = client.load_config(client.KEEPASSXCCLI2_CONFIG_NONAME_SECTION, None)
    assert cfg == {
        'db': None,
        'pid_file': str(client.DEFAULT_PID_PATH),
        'key_file': None,
        'yubikey': None,
        'timeout': 0.3
    }


def test_config_set_by_env(db_noname_in_env):
    cfg = client.load_config(client.KEEPASSXCCLI2_CONFIG_NONAME_SECTION, None)
    assert cfg == {
        'db':  db_noname_in_env,
        'pid_file': str(client.DEFAULT_PID_PATH),
        'key_file': None,
        'yubikey': None,
        'timeout': 0.3
    }


def test_custom_config(base_config, db1, pid_file):
    cfg = client.load_config('custom', base_config[0])
    assert cfg == {
        'db':  str(db1),
        'pid_file': str(pid_file) + 'custom',
        'key_file': None,
        'yubikey': None,
        'timeout': 0.3
    }


def test_section_does_not_exists(base_config, db1, pid_file):
    with pytest.raises(ValueError):
        client.load_config('custom2', base_config[0])
