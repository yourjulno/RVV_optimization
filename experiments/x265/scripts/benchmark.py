"""Measure the same x265 workload under two QEMUs, inside Linux container."""
import argparse
import csv
import hashlib
import json
import os
from pathlib import Path
import re
import signal
import statistics
import subprocess
import time


def sha256(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def build_command(config, name, target, plugin=None):
    command = [config['qemus'][name]['path']]
    if plugin is not None:
        command.extend(['-plugin', str(plugin)])
    command.extend(['-cpu', config['cpu'], '-L', config['sysroot'],
                    config['binary'], '--input', config['input'], '--y4m',
                    '--frames', str(config['frames']), *config['encoder_args'],
                    '--output', str(target)])
    return command


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    config = json.loads(args.config.read_text())
    out = args.output
    out.mkdir(parents=True, exist_ok=False)
    (out / 'config.json').write_text(json.dumps(config, indent=2) + '\n')
    for path, expected in [(config['binary'], config['binary_sha256']),
                           (config['input'], config['input_sha256'])] + [
                               (q['path'], q['sha256']) for q in config['qemus'].values()]:
        if sha256(path) != expected:
            raise RuntimeError('Unexpected SHA-256: ' + path)
    metadata = {
        'uname': subprocess.check_output(['uname', '-a'], text=True).strip(),
        'qemu_versions': {name: subprocess.check_output([q['path'], '--version'], text=True)
                          for name, q in config['qemus'].items()},
        'cpuinfo': Path('/proc/cpuinfo').read_text(),
        'loadavg_before': Path('/proc/loadavg').read_text().strip(),
        'start_utc': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
        'clock': 'time.perf_counter around GNU time + QEMU process; excludes docker exec and SHA-256',
        'cache_policy': 'one full workload warmup per QEMU; no cache flush; outputs use distinct files',
        'internal_time': 'x265 stderr encoded line, rounded to 0.01 seconds',
    }
    (out / 'metadata.json').write_text(json.dumps(metadata, indent=2) + '\n')
    rows = []
    expected_output = None
    names = list(config['qemus'])
    assert len(names) == 2
    for iteration in range(config['repeats'] + 1):
        # Alternate AB / BA; the warmup pair is recorded but excluded from statistics.
        order = names if iteration % 2 == 0 else names[::-1]
        for name in order:
            tag = f'{iteration:02d}-{name}'
            target = out / (tag + '.hevc')
            resources = out / (tag + '.resources.txt')
            command = build_command(config, name, target)
            timed_command = ['/usr/bin/time', '-f', '%U %S %M', '-o', str(resources), *command]
            row = dict(variant=name, iteration=iteration, warmup=(iteration == 0),
                       command=command, timed_command=timed_command,
                       loadavg=Path('/proc/loadavg').read_text().strip())
            start = time.perf_counter()
            process = subprocess.Popen(timed_command, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                       text=True, start_new_session=True, env={**os.environ, 'LC_ALL': 'C'})
            try:
                stdout, stderr = process.communicate(timeout=config['timeout_seconds'])
                row['status'] = 'ok' if process.returncode == 0 else 'failed'
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
                stdout, stderr = process.communicate()
                row['status'] = 'timeout'
            row.update(wall_seconds=time.perf_counter() - start, returncode=process.returncode)
            (out / (tag + '.stdout')).write_text(stdout)
            (out / (tag + '.stderr')).write_text(stderr)
            match = re.search(r'encoded (\d+) frames in ([0-9.]+)s \(([0-9.]+) fps\)', stderr)
            if row['status'] == 'ok':
                if not match or int(match[1]) != config['frames']:
                    row['status'] = 'invalid_frame_count'
                elif config.get('expected_cpu_capabilities', 'RVV') != (re.search(r'using cpu capabilities: (.+)', stderr)[1].strip() if re.search(r'using cpu capabilities: (.+)', stderr) else None):
                    row['status'] = 'unexpected_cpu_capabilities'
                else:
                    row.update(internal_seconds=float(match[2]), internal_fps=float(match[3]),
                               wall_fps=config['frames'] / row['wall_seconds'],
                               output_sha256=sha256(target), output_bytes=target.stat().st_size)
                    user, system, rss = resources.read_text().split()
                    row.update(user_seconds=float(user), system_seconds=float(system), max_rss_kib=int(rss))
                    if expected_output is None:
                        expected_output = row['output_sha256']
                    elif row['output_sha256'] != expected_output:
                        row['status'] = 'output_mismatch'
            rows.append(row)
            (out / 'runs.json').write_text(json.dumps(rows, indent=2) + '\n')
            print(f'{tag}: {row["status"]}, wall={row["wall_seconds"]:.3f}s, '
                  f'x265={row.get("internal_seconds", "n/a")}s', flush=True)
            if row['status'] != 'ok':
                raise RuntimeError(f'{tag}: {row["status"]}; see saved logs')
    summary = []
    for name in names:
        subset = [r for r in rows if r['variant'] == name and not r['warmup']]
        values = [r['wall_seconds'] for r in subset]
        q1, _, q3 = statistics.quantiles(values, n=4, method='inclusive')
        summary.append(dict(variant=name, n=len(values), median_seconds=statistics.median(values),
                            mean_seconds=statistics.mean(values), stdev_seconds=statistics.stdev(values),
                            min_seconds=min(values), max_seconds=max(values), q1_seconds=q1, q3_seconds=q3,
                            wall_fps=config['frames'] / statistics.median(values),
                            internal_median_seconds=statistics.median(r['internal_seconds'] for r in subset),
                            internal_median_fps=statistics.median(r['internal_fps'] for r in subset)))
    base, patched = summary
    pairs = [next(r['wall_seconds'] for r in rows if r['iteration'] == i and r['variant'] == names[0]) /
             next(r['wall_seconds'] for r in rows if r['iteration'] == i and r['variant'] == names[1])
             for i in range(1, config['repeats'] + 1)]
    report = dict(summary=summary, median_speedup=base['median_seconds']/patched['median_seconds'],
                  time_reduction_percent=100*(1-patched['median_seconds']/base['median_seconds']),
                  paired_speedups=pairs, paired_median_speedup=statistics.median(pairs),
                  output_sha256=expected_output, successful_measured_runs=2*config['repeats'])
    (out / 'summary.json').write_text(json.dumps(report, indent=2) + '\n')
    with (out / 'measurements.csv').open('w', newline='') as stream:
        fields = ['variant', 'iteration', 'warmup', 'status', 'wall_seconds', 'internal_seconds',
                  'internal_fps', 'wall_fps', 'user_seconds', 'system_seconds', 'max_rss_kib',
                  'output_bytes', 'output_sha256']
        writer = csv.DictWriter(stream, fieldnames=fields, extrasaction='ignore')
        writer.writeheader()
        writer.writerows(rows)
    metadata['loadavg_after'] = Path('/proc/loadavg').read_text().strip()
    metadata['end_utc'] = time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())
    (out / 'metadata.json').write_text(json.dumps(metadata, indent=2) + '\n')
    (out / 'COMPLETE').write_text('All runs succeeded; output hashes match.\n')
    print(json.dumps(report, indent=2), flush=True)


if __name__ == '__main__':
    main()
