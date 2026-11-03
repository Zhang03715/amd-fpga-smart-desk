"""Actual DeskService -> LAN PC GPU -> asynchronous result, without UART/GPIO."""
import argparse
import json
from pathlib import Path
import time

from .client import save_json
from voice_bridge.pynq_service import DeskService, encode
from voice_bridge.remote_book_adapter import RemoteBookAdapter


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--server', required=True)
    parser.add_argument('--token-file', type=Path, required=True)
    parser.add_argument('--image', required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    remote = RemoteBookAdapter(args.server, args.token_file, output_root=args.output/'full')
    service = DeskService(book_image=args.image, book_adapter=remote)
    request = dict(v=1, type='request', id='board-service-validation-01',
                   action='book.find', params={'title':'大学物理实验'})
    started = time.monotonic()
    try:
        features = service.features
        pending = service.handle(request)
        first_return_seconds = time.monotonic()-started
        repeated = service.handle(request)
        status = service.handle(dict(v=1,type='request',id='status-while-ocr',action='status',params={}))
        final = None
        deadline = started+185
        while time.monotonic() < deadline:
            for event in service.poll_events():
                if event.get('id') == request['id']:
                    final = event
            if final:
                break
            time.sleep(.05)
        if final is None:
            raise TimeoutError('no DeskService result')
        queried = service.handle(dict(v=1,type='request',id='get-after-ocr',action='job.get',
                                      params={'request_id':request['id']}))
        evidence = dict(pending=pending, repeated=repeated, status_while_processing=status,
                        final=final, queried=queried, same_feature_service=features is service.features,
                        initial_return_seconds=first_return_seconds,
                        total_seconds=time.monotonic()-started, uart_frame_bytes=len(encode(final)))
        evidence['passed'] = (pending['status']=='pending' and repeated==pending and
                              final['status']=='success' and final['data']['found'] and
                              final['data']['indicator_lit'] is False and final['data']['motor_action'] is False
                              and evidence['same_feature_service'] and evidence['uart_frame_bytes'] <= 2049)
        save_json(args.output/'checks.json', evidence)
        print(json.dumps({'passed':evidence['passed'], 'total_seconds':evidence['total_seconds'],
                          'initial_return_seconds':first_return_seconds}, ensure_ascii=True))
        if not evidence['passed']:
            raise SystemExit(2)
        # A similar, wrong title must not inherit the recognized correct title.
        absent = remote.find('大学物理实骏', args.image)
        save_json(args.output/'near-title.json', absent)
        if absent['found']:
            raise AssertionError('similar wrong title was accepted')
        print('similar wrong title rejected', flush=True)
    finally:
        service.close()


if __name__ == '__main__':
    main()
