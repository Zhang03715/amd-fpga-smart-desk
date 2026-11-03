"""Fresh-process full lookup comparison with exact evidence checks.

Run on the board with --device cpu, or on the existing GPU environment with
--device cuda. Host measurements never stand in for board measurements.
"""
import argparse
import hashlib
import json
from pathlib import Path
import platform
import statistics
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[2]


def read(path):
    return json.loads(path.read_text(encoding='utf8'))


def compare(case, legacy, optimized):
    a, b = read(legacy/'summary.json'), read(optimized/'summary.json')
    if (a['image_sha256'], a['v4_model_sha256']) != (b['image_sha256'], b['v4_model_sha256']):
        raise AssertionError('Input or reviewer model changed')
    old, new = read(legacy/'review.json')['decisions'], read(optimized/'review.json')['decisions']
    if len(old) != len(new):
        raise AssertionError('Candidate count changed')
    for previous, current in zip(old, new):
        for field in ('id', 'points', 'tiny_text', 'v4_text', 'accepted', 'status', 'reason'):
            if previous[field] != current[field]:
                raise AssertionError(f"Candidate {previous['id']} field {field} changed")
        if abs(previous['v4_confidence'] - current['v4_confidence']) > 1e-6:
            raise AssertionError('Reviewer confidence changed')
        for field in ('crop_file', 'expanded_crop_file'):
            if field in previous:
                if hashlib.sha256((legacy/previous[field]).read_bytes()).digest() != hashlib.sha256((optimized/current[field]).read_bytes()).digest():
                    raise AssertionError(f'{field} bytes changed')
    filename = f"{Path(case['image']).stem}_hybrid.json"
    if read(legacy/filename) != read(optimized/filename):
        raise AssertionError('Complete geometry output changed')
    if b['accepted_count'] != case['expected']:
        raise AssertionError('Historical accepted-text count not retained')
    return dict(exact_geometry_equal=True, exact_crops_equal=True, decisions_equal=True,
                original_expanded_inferences=sum('expanded_inference_seconds' in d for d in old),
                optimized_expanded_inferences=sum('expanded_inference_seconds' in d for d in new),
                skipped_expanded_inferences=sum('expanded_review_skipped' in d for d in new),
                original=a, optimized=b, crop_reuse=read(optimized/'scan.json')['crop_reuse'])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--options', type=Path, required=True)
    parser.add_argument('--v4-model', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--manifest', type=Path, default=Path(__file__).with_name('lookup_cases.json'))
    parser.add_argument('--repeat', type=int, default=1)
    parser.add_argument('--case')
    parser.add_argument('--device', choices=('cpu', 'cuda'), default='cpu')
    args = parser.parse_args()
    if not 1 <= args.repeat <= 10:
        parser.error('repeat must be 1..10')
    cases = read(args.manifest)
    if args.case:
        cases = [case for case in cases if case['name'] == args.case]
        if not cases:
            parser.error('Unknown case')
    args.output.mkdir(parents=True, exist_ok=True)
    reports = []
    for case in cases:
        records = []
        for repeat in range(args.repeat):
            modes = ('legacy', 'optimized') if repeat % 2 == 0 else ('optimized', 'legacy')
            outputs = {}
            for mode in modes:
                output = args.output/case['name']/f'{repeat}_{mode}'
                output.mkdir(parents=True, exist_ok=True)
                runner = ROOT/'tools/run_verified_lookup.py' if mode == 'legacy' else Path(__file__).with_name('run_optimized_lookup.py')
                command = [sys.executable, str(runner), case['image'], '--target', case['target'],
                           '--options', str(args.options), '--v4-model', str(args.v4_model),
                           '--output', str(output), '--device', args.device]
                if case.get('blind'):
                    command.append('--all-texts')
                with (output/'parent.log').open('w', encoding='utf8') as log:
                    subprocess.run(command, check=True, stdout=log, stderr=subprocess.STDOUT, timeout=1200)
                outputs[mode] = output
                print(case['name'], repeat, mode, read(output/'summary.json')['total_wall_seconds'], flush=True)
            records.append(compare(case, outputs['legacy'], outputs['optimized']))
            legacy = statistics.median(r['original']['total_wall_seconds'] for r in records)
            optimized = statistics.median(r['optimized']['total_wall_seconds'] for r in records)
        reports.append(dict(case=case['name'], runs=records,
                            median_wall_seconds=dict(legacy=legacy, optimized=optimized),
                            median_reduction_percent=100*(1-optimized/legacy)))
        (args.output/'comparison.json').write_text(json.dumps(dict(cases=reports,
            platform=platform.platform(), architecture=platform.machine(), device=args.device,
            options_sha256=hashlib.sha256(args.options.read_bytes()).hexdigest(),
            optimized_source_sha256=hashlib.sha256(Path(__file__).with_name('run_optimized_lookup.py').read_bytes()).hexdigest(),
            scope='Full lookup on this executing machine; model stages separate; single samples are not a general accuracy or speed guarantee'),
            ensure_ascii=False, indent=2), encoding='utf8')


if __name__ == '__main__':
    main()
