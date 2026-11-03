"""Package a separate board experiment without replacing the old project/runtime."""
import argparse
import hashlib
import json
from pathlib import Path
import zipfile

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=HERE/'board-ocr-optimization-ready.zip')
    args = parser.parse_args()
    paths = [ROOT/name for name in ('hybrid_book_locator.py', 'offline_book_ocr.py',
        'offline_book_segmenter.py', 'spine_geometry.py', 'flat_spine_extent.py', 'spine_centerline.py',
        'verification_policy.py', 'expanded_title_review.py',
        'tools/run_verified_lookup.py', 'tools/benchmark_static_ocr.py',
        'test_spine_geometry.py', 'test_verification_policy.py',
        'test_expanded_title_review.py', 'test_flat_spine_extent.py', 'test_spine_centerline.py')]
    paths += [path for path in HERE.iterdir() if path.suffix in ('.py', '.json', '.md')
              and not path.name.endswith('.manifest.json') and path.name != 'options_board.json']
    for case in json.loads((HERE/'geometry_cases.json').read_text(encoding='utf8')):
        paths += [ROOT/case[field] for field in ('image', 'review', 'geometry')]
    paths = sorted(set(paths))
    manifest = dict(scope='Isolated project code and static verification evidence only; no runtime, no model installation',
                    files=[dict(path=str(path.relative_to(ROOT)).replace('\\','/'),
                        bytes=path.stat().st_size, sha256=hashlib.sha256(path.read_bytes()).hexdigest()) for path in paths])
    options = json.loads((ROOT/'board_ocr/paddle_lite_trial/v6_tiny/pc_options_flat_fix_v2.json').read_text(encoding='utf8'))
    options['rec_model_path'] = '/home/xilinx/book_ocr_validation/paddle_lite_trial/v6_tiny/inference.onnx'
    options['rec_keys_path'] = '/home/xilinx/book_ocr_validation/paddle_lite_trial/v6_tiny/ppocrv6_tiny_dict.txt'
    options_data = json.dumps(options, ensure_ascii=False, indent=2).encode('utf8')
    manifest['files'].append(dict(path='board_ocr/optimization_20261013/options_board.json',
        bytes=len(options_data), sha256=hashlib.sha256(options_data).hexdigest()))
    with zipfile.ZipFile(args.output, 'w', zipfile.ZIP_DEFLATED) as archive:
        for path in paths:
            archive.write(path, 'project/'+str(path.relative_to(ROOT)).replace('\\','/'))
        archive.writestr('project/board_ocr/optimization_20261013/options_board.json', options_data)
        archive.writestr('bundle_manifest.json', json.dumps(manifest, ensure_ascii=False, indent=2))
    with zipfile.ZipFile(args.output) as archive:
        if archive.testzip() is not None:
            raise RuntimeError('ZIP integrity failure')
        for item in manifest['files']:
            if hashlib.sha256(archive.read('project/'+item['path'])).hexdigest() != item['sha256']:
                raise RuntimeError('Package source hash mismatch')
    report = dict(archive=str(args.output), bytes=args.output.stat().st_size,
                  sha256=hashlib.sha256(args.output.read_bytes()).hexdigest(), files=len(paths),
                  source_manifest=manifest, board_tested=False,
                  scope='New archive SHA has not been redeployed; real board evidence is preserved separately')
    args.output.with_suffix('.manifest.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf8')
    print(json.dumps({key:value for key,value in report.items() if key!='source_manifest'}, ensure_ascii=False))


if __name__ == '__main__':
    main()
