"""Independent offline scalar analysis. Does not import runner or open any DB/home."""
import argparse
import hashlib
import json
import math
from pathlib import Path
import statistics
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import (require, read, digest, frozen, protocol, schedule, coverage,
                    METRICS, LABELS, number, SHA, HEX)


def slope(points):
    require(len(points) == 4 and all(number(x) and number(y) for x, y in points), 'slope')
    xs, ys = zip(*points)
    mx, my = statistics.mean(xs), statistics.mean(ys)
    den = sum((x-mx)**2 for x in xs)
    require(den > 0, 'slope')
    return sum((x-mx)*(y-my) for x, y in points)/den*3600


def samples_read(path):
    require(path.is_file() and not path.is_symlink() and path.stat().st_size <= 16*1024*1024,
            'samples_boundary')
    rows = [json.loads(line) for line in path.read_text().splitlines()]
    require(0 < len(rows) <= 2000, 'samples_count')
    for row in rows:
        require(set(row) == {'at', 'phase'} | set(METRICS) and number(row['at'])
                and type(row['phase']) is str and row['phase'] in
                {x[0] for x in schedule(protocol())} | {'startup', 'checkpoint'}
                and all(type(row[k]) is int and 0 <= row[k] < 2**63 for k in METRICS), 'sample_schema')
    require(all(b['at'] > a['at'] for a, b in zip(rows, rows[1:])), 'sample_order')
    return rows


def analyze_arm(root, arm, p, pair):
    out = root/arm/'evidence'
    r = read(out/'result.json')
    require(set(r) == {'schema', 'arm', 'result', 'error', 'phases', 'operations', 'cleanup',
                       'fixture', 'sources_end', 'counts_end', 'tool_end', 'start', 'seconds', 'identity'}
            and r['schema'] == 'hud_remote_arm_v1' and r['arm'] == arm
            and r['result'] == 'EXECUTION_COMPLETE_PENDING_ANALYSIS' and r['error'] is None
            and 0 < r['seconds'] < p['arm_seconds'] and r['tool_end'] == pair['tool_start'], 'arm')
    clean = r['cleanup']
    require(set(clean) == {'identity_matched', 'alive', 'exit_code', 'error'}
            and clean['identity_matched'] is True and clean['alive'] is False
            and type(clean['exit_code']) is int and clean['error'] is None, 'cleanup')
    identity = r['identity']
    expected_home = root/arm/'synthetic-home'
    require(set(identity) == {'pid', 'birth', 'cwd', 'argv'} and type(identity['pid']) is int
            and identity['pid'] > 0 and number(identity['birth'])
            and identity['cwd'] == str(expected_home), 'identity')
    # Explicit argv length is eleven; do not trust an extra shell/token argument.
    require(type(identity['argv']) is list and len(identity['argv']) == 11
            and identity['argv'][1:4] == ['-I', '-B', str(Path(__file__).resolve().parent/'observer.py')]
            and identity['argv'][4:8] == ['dashboard', '--host', '127.0.0.1', '--port']
            and identity['argv'][9:] == ['--no-open', '--skip-build']
            and identity['argv'][8].isdigit() and 1024 <= int(identity['argv'][8]) <= 65535
            and int(identity['argv'][8]) != 9119 and identity['argv'][0] == str(root/'venv/bin/python'),
            'identity_command')
    require(read(out/'identity.json') == identity, 'identity_binding')
    fixture = r['fixture']
    require(set(fixture) == {'counts', 'schema_source_sha256', 'source_hashes', 'query_only',
                            'native_ddl', 'timeline_total'} and fixture['counts'] == p['fixture_counts']
            and r['counts_end'] == p['fixture_counts'] and fixture['query_only'] is True
            and fixture['timeline_total'] is None
            and all(type(v) is int for v in fixture['counts'].values())
            and all(type(v) is int for v in r['counts_end'].values())
            and HEX.fullmatch(fixture['schema_source_sha256']) is not None
            and set(fixture['source_hashes']) == {'state.db', 'job-ledger/jobs.jsonl'}
            and all(HEX.fullmatch(v) is not None for v in fixture['source_hashes'].values())
            and r['sources_end'] == fixture['source_hashes'], 'fixture')
    phases = r['phases']
    require(len(phases) == len(schedule(p)), 'schedule')
    rows = samples_read(out/'samples.jsonl')
    means, qualities = {}, []
    last = r['start']
    for phase, (label, seconds, load) in zip(phases, schedule(p)):
        require(set(phase) == {'label', 'seconds', 'start', 'end', 'http', 'ws', 'handshakes'}
                and phase['label'] == label and phase['seconds'] == seconds
                and number(phase['start']) and number(phase['end'])
                and phase['start'] >= last and phase['end']-phase['start'] >= seconds
                and all(type(phase[k]) is int and phase[k] >= 0 for k in ('http', 'ws', 'handshakes'))
                and ((phase['http'] >= 4 and phase['ws'] > 0 and phase['handshakes'] == 1) if load
                     else phase['http'] == phase['ws'] == phase['handshakes'] == 0), 'phase')
        quality, tail = coverage(rows, phase, p)
        qualities.append(quality)
        means[label] = {k: statistics.mean(s[k] for s in tail) for k in METRICS}
        last = phase['end']
    require(len(r['operations']) == 5, 'operations')
    cp_summaries = []
    for seq, (label, operation) in enumerate(zip(LABELS, r['operations']), 1):
        require(set(operation) == {'sequence', 'label', 'at', 'observed_seconds', 'window_seconds'}
                and type(operation['sequence']) is int and operation['sequence'] == seq
                and operation['label'] == label and number(operation['at'])
                and number(operation['observed_seconds']) and number(operation['window_seconds'])
                and 0 <= operation['observed_seconds'] < 30 and operation['window_seconds'] >= 30,
                'operation')
        cp = read(out/f'checkpoint-{seq}.json')
        require(set(cp) == {'sequence', 'label', 'compare_to', 'snapshot_count', 'gc_count', 'seconds', 'values'}
                and type(cp['sequence']) is int and cp['sequence'] == seq and cp['label'] == label
                and (cp['compare_to'] is None if seq == 1 else type(cp['compare_to']) is int and cp['compare_to'] == 1)
                and type(cp['snapshot_count']) is int and cp['snapshot_count'] == int(arm == 'snapshot')
                and type(cp['gc_count']) is int and cp['gc_count'] == 0
                and number(cp['seconds']) and 0 <= cp['seconds'] < 30, 'checkpoint')
        v = cp['values']
        if arm == 'sham':
            require(v is None, 'sham_intervention')
        else:
            require(set(v) == {'trace_records', 'snapshot_bytes', 'delta_rows', 'net_delta_bytes',
                              'top', 'interpretation'} and v['interpretation'] == 'filename_provenance_only_not_ownership'
                    and all(type(v[k]) is int and v[k] >= 0 for k in ('trace_records', 'snapshot_bytes', 'delta_rows'))
                    and type(v['net_delta_bytes']) is int and type(v['top']) is list and len(v['top']) <= 25,
                    'allocation_schema')
            for t in v['top']:
                require(set(t) == {'file_sha256', 'line', 'bytes', 'blocks'}
                        and HEX.fullmatch(t['file_sha256']) is not None
                        and all(type(t[k]) is int and t[k] >= 0 for k in ('line', 'bytes', 'blocks')), 'allocation_privacy')
            require(sum(t['bytes'] for t in v['top']) <= v['snapshot_bytes'], 'allocation_bounds')
        cp_summaries.append({'sequence': seq, 'seconds': cp['seconds'], 'values': v})
    trends = {}
    for metric in METRICS:
        points = [(next(x['end'] for x in phases if x['label'] == f'cooldown-{n}'),
                   means[f'cooldown-{n}'][metric]) for n in range(1, 5)]
        trends[metric] = {'final_minus_baseline': means['final'][metric]-means['baseline'][metric],
                          'cooldown_ols_per_hour': slope(points)}
    return {'arm': arm, 'seconds': r['seconds'], 'coverage': qualities, 'phase_tail_means': means,
            'within_arm_changes': trends, 'checkpoints': cp_summaries,
            'http': sum(x['http'] for x in phases), 'ws': sum(x['ws'] for x in phases),
            'samples': rows, 'phases': phases,
            'cleanup_verified_from_record': True, 'live_pid_checked': False,
            'fixture': fixture, 'identity_digest': hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()}


def analyze(root):
    p = protocol()
    pair = read(root/'result.json')
    require(set(pair) == {'schema', 'sha', 'candidate', 'grant', 'run_id', 'result', 'arms',
                         'tool_start', 'tool_end', 'seconds', 'environment', 'memory_risk',
                         'public_release', 'public_source_start', 'public_source_end'}
            and pair['schema'] == 'hud_remote_pair_v1' and pair['candidate'] == p['candidate']
            and SHA.fullmatch(pair['sha']) is not None and pair['result'] == 'EXECUTION_COMPLETE_PENDING_ANALYSIS'
            and pair['memory_risk'] == 'WARN_NOT_ACCEPTED' and pair['public_release'] == 'BLOCK'
            and pair['arms'] == [{'arm': a, 'result': 'EXECUTION_COMPLETE_PENDING_ANALYSIS'} for a in p['arms']]
            and number(pair['seconds']) and 0 < pair['seconds'] < p['pair_seconds']
            and pair['tool_start'] == pair['tool_end'] == frozen()
            and pair['public_source_start'] == pair['public_source_end'], 'pair')
    source = pair['public_source_start']
    require(set(source) == {'count', 'sha256'} and type(source['count']) is int and source['count'] > 0
            and HEX.fullmatch(source['sha256']) is not None, 'public_source')
    env = pair['environment']
    require(set(env) == {'python', 'platform', 'distributions'} and env['platform'] == 'darwin'
            and type(env['python']) is str and env['python'].startswith('3.13.')
            and type(env['distributions']) is dict and len(env['distributions']) <= 512
            and env['distributions'].get('hermes-agent') == p['host_version'], 'environment')
    versions = {k: env['distributions'].get(k) for k in ('hermes-agent', 'psutil', 'websockets',
                                                       'fastapi', 'uvicorn', 'starlette')}
    import re
    require(all(type(v) is str and re.fullmatch(r'[a-zA-Z0-9.+_-]{1,64}', v) for v in versions.values()),
            'environment')
    arms = [analyze_arm(root, arm, p, pair) for arm in p['arms']]
    require(arms[0]['fixture'] == arms[1]['fixture'], 'paired_fixture')
    return {'result': 'VERIFIED_REMOTE_FINITE_EXECUTION_ONLY', 'sha': pair['sha'],
            'seconds': pair['seconds'], 'arms': arms, 'environment': {'python': env['python'],
                'platform': env['platform'], 'versions': versions, 'public_cli_source': source},
            'absolute_between_arm_memory_comparison': 'FORBIDDEN',
            'ols': 'four_cooldown_points_descriptive_only',
            'historical_cause': 'UNKNOWN', 'growth_acceptance_budget': None,
            'memory_risk': 'WARN_NOT_ACCEPTED', 'public_release': 'BLOCK',
            'limitations': ['Fresh macOS Python 3.13 Hermes 0.19.0; not historical host recreation.',
                'Sequential order and system pressure can confound trends.',
                'Snapshot instrumentation changes the observed object.',
                'Net traced bytes do not exclude product or native memory retention.',
                'Mach self scalars are not region ownership; RSS/compressed differences are not conservation.',
                'No raw transport fidelity reconstruction from aggregate records.',
                'No risk acceptance, long-term no-leak proof, final product SHA or public release PASS.']}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('root', type=Path)
    args = parser.parse_args()
    root = args.root.resolve()
    # Only this fixed CI-owned root is supported. No general DB/log/source reader.
    require(root.name == 'hud-finite-owned' and not args.root.is_symlink(), 'root')
    output = root/'aggregate-artifact'
    output.mkdir(exist_ok=True)
    try:
        summary = analyze(root)
        code = 0
    except BaseException:
        summary = {'result': 'DIAGNOSTIC_ONLY_NOT_VERIFIED', 'memory_risk': 'WARN_NOT_ACCEPTED',
                   'public_release': 'BLOCK', 'error': 'evidence_invalid_or_execution_failed'}
        code = 2
    (output/'analysis.json').write_text(json.dumps(summary, sort_keys=True, indent=2)+'\n')
    # Deliberately only validated/projection scalars, not homes, logs, HTML, config,
    # sample raw JSON, caller-defined extra fields or arbitrary failure payloads.
    print(json.dumps({k: summary[k] for k in ('result', 'memory_risk', 'public_release')}))
    return code


if __name__ == '__main__':
    raise SystemExit(main())
