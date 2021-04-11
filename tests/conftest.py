from pathlib import Path

from pytest import fixture


DATA_PATH = Path(__file__).parent.joinpath('data')


@fixture
def db1():
    return DATA_PATH.joinpath('testdb_1')


@fixture()
def pid_file(tmpdir_factory):
    f = tmpdir_factory.mktemp('pid').join('f1')
    return str(f)

