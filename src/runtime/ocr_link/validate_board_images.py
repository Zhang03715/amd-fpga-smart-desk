"""Repeatable static-image LAN checks; run on Z2, no peripheral actions."""
import argparse
import hashlib
import json
from pathlib import Path
import time

from .client import OCRClient, make_request, read_token, save_json


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--server', required=True)
    parser.add_argument('--token-file', type=Path, required=True)
    parser.add_argument('--image', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    data = args.image.read_bytes()
    client = OCRClient(args.server, read_token(args.token_file))
    reports = []
    for rid, title, expected in [('z2-find-d-20261013-01', '大学物理实验', True),
                                 ('z2-absent-d-20261013-01', '高等数学', False)]:
        source = dict(kind='image', capture_id=rid+'-static', live=False,
                      captured_at=None, age_seconds=0.0, clock='unknown')
        payload = make_request(data, rid, 'book.find', title, source)
        state = client.run(payload, args.output/rid)
        result = state.get('result', {})
        passed = (state['status'] == 'succeeded' and result.get('found') is expected
                  and result.get('image_sha256') == hashlib.sha256(data).hexdigest()
                  and result.get('source') == source and result.get('indicator_lit') is False
                  and result.get('motor_action') is False)
        reports.append(dict(request_id=rid, title=title, expected_found=expected, passed=passed,
                            status=state['status'], found=result.get('found'),
                            matches=result.get('matches'), timing=result.get('timing'),
                            transport=json.loads((args.output/rid/'transport.json').read_text(encoding='utf-8'))))
        save_json(args.output/'checks.json', reports)
        print(json.dumps(dict(request_id=rid, passed=passed, found=result.get('found')), ensure_ascii=True), flush=True)
    if not all(r['passed'] for r in reports):
        raise SystemExit(2)


if __name__ == '__main__':
    main()
