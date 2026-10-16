import subprocess

import pytest

from orq import config
from orq.engine import block_push_env
from orq.store import RunStore
from tests.test_engine import make_queue, engine, PLAN, EXEC_OK, APPROVED


def second_repo(tmp_path):
    repo = tmp_path / 'second'
    subprocess.run(['git', 'init', '-q', str(repo)], check=True)
    subprocess.run(['git', '-C', str(repo), '-c', 'user.name=t', '-c', 'user.email=t@t',
                    'commit', '-qm', 'second', '--allow-empty'], check=True)
    return repo


async def test_task_repo_rules_verify_and_delivery(tmp_path):
    repo = second_repo(tmp_path)
    cfg = make_queue(tmp_path, {'plan': [PLAN], 'execute': [EXEC_OK], 'review': [APPROVED]},
                     tasks=('01-a', '02-b'), extra_toml='''
[tasks."02-b"]
repo = "../second"
rules_file = "second.md"
[tasks."02-b".verify]
command = "test -f a.txt && test \\\"$ORQ_TASK_ID\\\" = 02-b"
''')
    (cfg.queue_dir / 'second.md').write_text('SECOND RULES')
    e = engine(tmp_path, cfg)
    assert await e.run()
    assert (cfg.repo / 'a.txt').read_text() == 'a\n'
    assert (repo / 'a.txt').read_text() == 'a\n'
    calls = list((e.s.dir / '02-b' / 'calls').glob('*.prompt.md'))
    assert all('SECOND RULES' in p.read_text() for p in calls)
    assert e.s.get('02-b', 'repo') == str(repo)
    assert e.s.get('02-b', 'result') == 'ok'
    assert next(x for x in e.s.events() if x['type'] == 'task_end' and x['task'] == '02-b')['delivery']['commits']


def test_config_rejects_unknown_override(tmp_path):
    with pytest.raises(config.ConfigError, match='tasks'):
        make_queue(tmp_path, {}, extra_toml='[tasks."01-a"]\nreop = "oops"')


def test_lock_all_repositories(tmp_path):
    cfg = make_queue(tmp_path, {})
    repo = second_repo(tmp_path)
    first, second = RunStore(tmp_path / 'one'), RunStore(tmp_path / 'two')
    first.dir.mkdir(); second.dir.mkdir()
    with first.engine_lock([cfg.repo, repo]):
        with pytest.raises(RuntimeError, match='motor'):
            with second.engine_lock(repo):
                pass
    with second.engine_lock(repo):
        pass


def test_push_block_covers_all_remote_names(tmp_path):
    cfg = make_queue(tmp_path, {})
    repo = second_repo(tmp_path)
    for path, name in ((cfg.repo, 'origin'), (repo, 'upstream')):
        subprocess.run(['git', '-C', str(path), 'remote', 'add', name, '/unused'], check=True)
    env = block_push_env([cfg.repo, repo])
    assert {v for k, v in env.items() if k.startswith('GIT_CONFIG_KEY_')} == {
        'remote.origin.pushurl', 'remote.upstream.pushurl'}


def test_resume_keeps_task_overrides(tmp_path, monkeypatch):
    from argparse import Namespace
    from orq import cli
    repo = second_repo(tmp_path)
    cfg = make_queue(tmp_path, {}, extra_toml='[tasks."01-a"]\nrepo = "../second"')
    e = engine(tmp_path, cfg)
    (cfg.queue_dir / 'orq.toml').write_text('[run]\nrepo = "/wrong"')
    received = []
    monkeypatch.setattr(cli, 'start', lambda store, actual, args: received.append(actual) or 0)
    cli.cmd_resume(Namespace(run_dir=str(e.s.dir), account=None, retry=[], headless=True))
    assert received[0].task_config('01-a').repo == repo
    assert received[0].task_config('unconfigured').repo == cfg.repo


async def test_dirty_secondary_repo_blocks_without_touching_default(tmp_path):
    repo = second_repo(tmp_path)
    (repo / 'uncommitted').write_text('user work')
    cfg = make_queue(tmp_path, {}, extra_toml='[tasks."01-a"]\nrepo = "../second"')
    e = engine(tmp_path, cfg)
    assert not await e.run()
    assert e.s.get('01-a', 'result') == 'blocked'
    assert all(r.name.startswith('summary') and r.read_only for r in e.harness('fake').calls)
    assert (repo / 'uncommitted').read_text() == 'user work'


async def test_council_uses_task_repo_and_rules(tmp_path):
    from tests.test_engine import Q, vote
    repo = second_repo(tmp_path)
    cfg = make_queue(tmp_path, {'plan': [{'summary': 's', 'questions': [Q]}, PLAN],
                               'execute': [EXEC_OK], 'review': [APPROVED],
                               'voter:vote': [vote('a')]},
                     extra_toml='[tasks."01-a"]\nrepo = "../second"\nrules_file = "second.md"')
    (cfg.queue_dir / 'second.md').write_text('SECOND RULES')
    e = engine(tmp_path, cfg)
    assert await e.run()
    calls = e.harness('fake').calls
    assert all(r.cwd == repo for r in calls if r.role.name != 'planner' or not r.name.startswith('summary'))
    votes = [r for r in calls if r.role.name == 'voter']
    assert votes and all('SECOND RULES' in r.prompt for r in votes)


def test_changed_repo_is_rejected_for_existing_task(tmp_path):
    cfg = make_queue(tmp_path, {})
    e = engine(tmp_path, cfg)
    e.s.set('01-a', 'repo', '/old/worktree')
    with pytest.raises(config.ConfigError, match='mudou'):
        e.make_task(e.task_files()[0])
