"""Create new owned synthetic sources only; never inspect an existing home."""
import ast
from contextlib import closing
import importlib.util
import json
from pathlib import Path
import sqlite3

from common import require, digest

QUERIES = {
    'sessions': 'SELECT COUNT(*) FROM sessions',
    'messages': 'SELECT COUNT(*) FROM messages',
    'usage_rows': 'SELECT COUNT(*) FROM session_model_usage',
    'active_sessions': 'SELECT COUNT(*) FROM sessions WHERE ended_at IS NULL',
    'ended_sessions': 'SELECT COUNT(*) FROM sessions WHERE ended_at IS NOT NULL',
    'tool_messages': "SELECT COUNT(*) FROM messages WHERE tool_name IS NOT NULL AND tool_name != ''",
}


def public_schema():
    # Static AST reads from the freshly installed public distribution, not execution
    # of schema modules (which could load configuration). No local fallback schema.
    for name in ('hermes_state_common', 'hermes_state'):
        spec = importlib.util.find_spec(name)
        if spec is None or spec.origin is None:
            continue
        source = Path(spec.origin).resolve()
        require(source.suffix == '.py', 'host_schema')
        for node in ast.parse(source.read_text()).body:
            if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == 'SCHEMA_SQL'
                                                   for t in node.targets):
                value = ast.literal_eval(node.value)
                require(type(value) is str, 'host_schema')
                return value, digest(source)
    raise ValueError('host_schema')


def source_hashes(home):
    return {name: digest(home/name) for name in ('state.db', 'job-ledger/jobs.jsonl')}


def counts(home):
    path = home/'state.db'
    require(path.resolve() == path and not path.is_symlink(), 'fixture_boundary')
    with closing(sqlite3.connect(path.as_uri()+'?mode=ro', uri=True)) as conn:
        conn.execute('PRAGMA query_only=ON')
        require(type(conn.execute('PRAGMA query_only').fetchone()[0]) is int
                and conn.execute('PRAGMA query_only').fetchone()[0] == 1, 'query_only')
        databases = conn.execute('PRAGMA database_list').fetchall()
        require(databases == [(0, 'main', str(path))], 'fixture_boundary')
        values = {name: conn.execute(q).fetchone()[0] for name, q in QUERIES.items()}
    values['skill_records'] = len((home/'job-ledger/jobs.jsonl').read_text().splitlines())
    require(all(type(v) is int and v >= 0 for v in values.values()), 'fixture_counts')
    return values


def build(home, repo, epoch, expected):
    require(not home.exists() and not home.is_symlink(), 'fixture_exists')
    home.mkdir()
    for name in ('plugins', 'cron', 'logs', 'memories', 'skills', 'job-ledger', 'bundled-skills',
                 'fake-user', 'tmp'):
        (home/name).mkdir()
    (home/'plugins/hermes-hud').symlink_to(repo, target_is_directory=True)
    schema, schema_source_hash = public_schema()
    # Absence of any required field is a feasibility failure; do not silently
    # extend the pinned host DDL to turn an unsupported fixture into success.
    with closing(sqlite3.connect(home/'state.db')) as conn:
        conn.executescript(schema)
        conn.executemany('INSERT INTO sessions(id,source,model,started_at,ended_at,title,input_tokens,output_tokens,estimated_cost_usd,cost_status,cwd) VALUES(?,?,?,?,?,?,?,?,?,?,?)',
            ((f'synthetic-{i:05d}', 'cli', 'synthetic-model', epoch+i,
              None if i < 20 else epoch+i+10, 'Synthetic session', 2000, 100, .02,
              'estimated', '/synthetic/workspace') for i in range(5000)))
        conn.executemany('INSERT INTO session_model_usage(session_id,model,input_tokens,output_tokens,estimated_cost_usd,cost_status,cost_source,first_seen,last_seen) VALUES(?,?,?,?,?,?,?,?,?)',
            ((f'synthetic-{i:05d}', 'synthetic-model', 2000, 100, .02, 'estimated',
              'official_docs_snapshot', epoch+i, epoch+i+10) for i in range(5000) if i % 50))
        conn.executemany('INSERT INTO messages(session_id,role,content,tool_name,tool_call_id,timestamp,finish_reason) VALUES(?,?,?,?,?,?,?)',
            ((f'synthetic-{i%5000:05d}', 'tool' if i%100 == 0 else 'assistant',
              'Synthetic test only', 'synthetic-tool' if i%100 == 0 else None,
              f'synthetic-call-{i}' if i%100 == 0 else None, epoch+i%3000, 'stop')
             for i in range(200000)))
        conn.commit()
    with (home/'job-ledger/jobs.jsonl').open('w') as stream:
        for i in range(1000):
            stream.write(json.dumps({'job_id': f'synthetic-job-{i}', 'skill': 'synthetic-skill',
                'task': 'Synthetic test only', 'finished_at': epoch+i,
                'event': 'failed' if i%20 == 0 else 'finished'}, sort_keys=True)+'\n')
    (home/'config.yaml').write_text('plugins:\n  enabled: [hermes-hud]\nmodel: synthetic-model\n')
    (home/'cron/jobs.json').write_text('{"jobs":[]}\n')
    (home/'logs/errors.log').write_text('')
    (home/'logs/agent.log').write_text('Synthetic test only\n')
    values = counts(home)
    require(values == expected, 'fixture_counts')
    return {'counts': values, 'schema_source_sha256': schema_source_hash,
            'source_hashes': source_hashes(home), 'query_only': True,
            'native_ddl': 'fresh pinned distribution SCHEMA_SQL; required fields not patched',
            'timeline_total': None}
