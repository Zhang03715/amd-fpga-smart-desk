"""Compare unchanged geometry against request-local reuse on saved OCR evidence.

No OCR model is run; these timings are NOT end-to-end OCR timings.
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
sys.path.insert(0, str(ROOT))


def load_rows(case):
    review = json.loads(Path(case['review']).read_text(encoding='utf8'))
    rows = [[d['points'], d['v4_text'], d['v4_confidence']]
            for d in review['decisions'] if d['accepted']]
    if case.get('geometry'):
        report = json.loads(Path(case['geometry']).read_text(encoding='utf8'))
        for record in report.get('title_refinement', []):
            if record.get('refined_points'):
                for row in rows:
                    if row[0] == record['original_points']:
                        row[0] = record['refined_points']
    return rows


def worker(args, case):
    from hybrid_book_locator import locate
    from tools.benchmark_static_ocr import peak_memory_mib
    rows = load_rows(case)
    destination = args.output
    destination.mkdir(parents=True, exist_ok=True)
    started = time.perf_counter()
    audit = {}
    if rows:
        locate(Path(case['image']), case['target'], destination, 0. if case.get('blind') else 1.,
               draw_labels=False, supplied_ocr=rows, flat_seam_extent=case.get('flat_seam_extent', False),
               geometry_cache=args.mode == 'cached', geometry_audit=audit)
    else:
        (destination / f"{Path(case['image']).stem}_hybrid.json").write_text('[]', encoding='utf8')
    report = dict(work_seconds=time.perf_counter()-started, peak_rss_mib=peak_memory_mib(),
                  accepted_text_regions=len(rows), cache=audit,
                  image_sha256=hashlib.sha256(Path(case['image']).read_bytes()).hexdigest(),
                  review_sha256=hashlib.sha256(Path(case['review']).read_bytes()).hexdigest(),
                  mode=args.mode, platform=platform.platform(), architecture=platform.machine(),
                  scope='Saved OCR evidence replay; geometry only; not total OCR or board timing unless executed on board')
    (destination/'metrics.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf8')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest', type=Path, default=Path(__file__).with_name('geometry_cases.json'))
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--repeat', type=int, default=3)
    parser.add_argument('--case')
    parser.add_argument('--mode', choices=('legacy', 'cached'))
    args = parser.parse_args()
    cases = json.loads(args.manifest.read_text(encoding='utf8'))
    if args.case:
        worker(args, next(case for case in cases if case['name'] == args.case))
        return
    if not 1 <= args.repeat <= 10:
        parser.error('repeat must be 1..10')
    args.output.mkdir(parents=True, exist_ok=True)
    all_reports = []
    for case in cases:
        metrics = {mode: [] for mode in ('legacy', 'cached')}
        for repeat in range(args.repeat):
            # Alternate execution order, isolating process peak-memory measurements.
            modes = ('legacy', 'cached') if repeat % 2 == 0 else ('cached', 'legacy')
            results = {}
            for mode in modes:
                destination = args.output/case['name']/f'{repeat}_{mode}'
                destination.mkdir(parents=True, exist_ok=True)
                command = [sys.executable, str(Path(__file__).resolve()), '--manifest', str(args.manifest),
                           '--output', str(destination), '--case', case['name'], '--mode', mode]
                started = time.perf_counter()
                with (destination/'worker.log').open('w', encoding='utf8') as log:
                    subprocess.run(command, check=True, stdout=log, stderr=subprocess.STDOUT, timeout=300)
                report = json.loads((destination/'metrics.json').read_text(encoding='utf8'))
                report['process_wall_seconds'] = time.perf_counter()-started
                metrics[mode].append(report)
                results[mode] = json.loads((destination/f"{Path(case['image']).stem}_hybrid.json").read_text(encoding='utf8'))
            if results['legacy'] != results['cached']:
                raise AssertionError(f"Geometry changed in {case['name']} repeat {repeat}")
        legacy = statistics.median(run['work_seconds'] for run in metrics['legacy'])
        cached = statistics.median(run['work_seconds'] for run in metrics['cached'])
        all_reports.append(dict(case=case['name'], exact_json_equal=True, runs=metrics,
                                median_geometry_seconds=dict(legacy=legacy, cached=cached),
                                median_reduction_percent=100*(1-cached/legacy)))
        print(case['name'], f'{legacy:.3f}s -> {cached:.3f}s', flush=True)
    (args.output/'comparison.json').write_text(json.dumps(dict(cases=all_reports,
        scope='Fresh-process geometry replay only; no new OCR, no new accuracy measurement',
        source_sha256=hashlib.sha256((ROOT/'hybrid_book_locator.py').read_bytes()).hexdigest()),
        ensure_ascii=False, indent=2), encoding='utf8')


if __name__ == '__main__':
    main()
