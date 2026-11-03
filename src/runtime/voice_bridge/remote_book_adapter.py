"""Opt-in PC OCR backend for the existing DeskService book.find worker."""
import json
import math
from pathlib import Path
import subprocess
import sys
import time
import uuid

try:
    from ocr_link.client import MAX_IMAGE, ClientError, OCRClient, make_request, read_token
except ModuleNotFoundError as exc:
    if exc.name != 'ocr_link':
        raise
    # Preserve the existing direct-script service invocation as well as -m.
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from ocr_link.client import MAX_IMAGE, ClientError, OCRClient, make_request, read_token

ROOT = Path(__file__).resolve().parents[1]


class RemoteBookAdapter:
    def __init__(self, server, token_file, *, camera=None, runtime_path=None,
                 output_root='output/remote-book', request_timeout=10,
                 total_timeout=180, capture_timeout=15, client=None, capture=None):
        self.client = client if client is not None else OCRClient(
            server, read_token(token_file), request_timeout, total_timeout)
        self.camera, self.runtime_path = camera, runtime_path
        self.output_root = Path(output_root).expanduser().resolve()
        if not math.isfinite(capture_timeout) or not 0 < capture_timeout <= 120:
            raise ValueError('invalid_capture_timeout')
        self.capture_timeout = capture_timeout
        self.capture = capture if capture is not None else self._capture

    def _capture(self, output):
        image_path = output / 'capture.jpg'
        command = [sys.executable, '-m', 'ocr_link.board_cli', '--capture-worker',
                   '--camera', str(self.camera), '--capture-file', str(image_path)]
        if self.runtime_path:
            command += ['--runtime-path', str(self.runtime_path)]
        try:
            subprocess.run(command, check=True, timeout=self.capture_timeout,
                           stdout=subprocess.PIPE, stderr=subprocess.PIPE, cwd=ROOT)
        except subprocess.TimeoutExpired as exc:
            raise ValueError('book_camera_timeout') from exc
        except (subprocess.CalledProcessError, OSError) as exc:
            raise ValueError('book_camera_unavailable') from exc
        info = json.loads(image_path.with_suffix('.json').read_text(encoding='utf-8'))
        with image_path.open('rb') as image_file:
            data = image_file.read(MAX_IMAGE + 1)
        return data, dict(kind='camera', capture_id=uuid.uuid4().hex,
                          captured_at=info['captured_at'], live=True,
                          age_seconds=max(0.0, time.monotonic() - info['captured_monotonic']),
                          clock='client_read_completion')

    def find(self, title, image_path=None, uart_request_id=None):
        if not isinstance(title, str) or not 1 <= len(title.strip()) <= 200:
            raise ValueError('invalid_book_title')
        # UART IDs are not the HTTP identifier: their character set differs and
        # they can recur after a board restart. DeskService handles UART retries.
        http_id = uuid.uuid4().hex
        output = self.output_root / http_id
        output.mkdir(parents=True, exist_ok=False)
        try:
            if self.camera is not None:
                if image_path:
                    raise ValueError('book_source_conflict')
                data, source = self.capture(output)
            else:
                if not image_path:
                    raise ValueError('book_image_or_camera_required')
                try:
                    with Path(image_path).open('rb') as image_file:
                        data = image_file.read(MAX_IMAGE + 1)
                except OSError as exc:
                    raise ValueError('image_not_found') from exc
                source = dict(kind='image', capture_id=uuid.uuid4().hex,
                              captured_at=None, live=False, age_seconds=0.0, clock='unknown')
            payload = make_request(data, http_id, 'book.find', title, source)
            state = self.client.run(payload, output)
        except TimeoutError as exc:
            raise ValueError('remote_book_timeout') from exc
        except ClientError as exc:
            raise ValueError('remote_book_unavailable') from exc
        if state.get('request_id') != http_id:
            raise ValueError('remote_book_result_invalid')
        if state.get('status') != 'succeeded':
            raise ValueError('remote_book_failed')
        result = state.get('result')
        if (not isinstance(result, dict) or result.get('image_sha256') != payload['image']['sha256']
                or result.get('request_id') != http_id or result.get('action') != 'book.find'
                or result.get('source') != source):
            raise ValueError('remote_book_result_invalid')
        matches = result.get('matches')
        if not isinstance(matches, list) or type(result.get('found')) is not bool or result['found'] != bool(matches):
            raise ValueError('remote_book_result_invalid')
        for match in matches:
            if not isinstance(match, dict) or not isinstance(match.get('text'), str):
                raise ValueError('remote_book_result_invalid')
            score = match.get('match_score')
            if score is not None and (type(score) not in (int, float) or not math.isfinite(score) or not 0 <= score <= 1):
                raise ValueError('remote_book_result_invalid')
            for key, length in (('book_box', 4), ('normalized_center', 2)):
                values = match.get(key)
                if values is not None and (not isinstance(values, list) or len(values) != length
                        or any(type(v) not in (int, float) or not math.isfinite(v) for v in values)):
                    raise ValueError('remote_book_result_invalid')
            centers = match.get('normalized_center', [])
            if any(not 0 <= value <= 1 for value in centers):
                raise ValueError('remote_book_result_invalid')
        timing = result.get('timing', {})
        if not isinstance(timing, dict):
            raise ValueError('remote_book_result_invalid')
        age = timing.get('capture_age_at_result_seconds')
        if age is not None and (type(age) not in (int, float) or not math.isfinite(age) or age < 0):
            raise ValueError('remote_book_result_invalid')
        # Use our capture source, never a server-provided path or live flag.
        evidence_source = dict(source, freshness='snapshot', path=str(output.resolve()))
        if self.camera is not None:evidence_source['camera_id']=str(self.camera)
        if age is not None:
            evidence_source['age_at_result_seconds'] = age
        evidence = dict(title=title.strip(), found=result['found'], matches=matches,
                    source=evidence_source, remote_request_id=http_id,
                    image_sha256=payload['image']['sha256'], inference_location='local_pc_gpu',
                    indicator_lit=False, motor_action=False, shelf_slot=None,
                    message='此次图像的识别结果；未确认实时书架位置，未点亮指示灯。')
        if 'image_size' in result:
            size=result['image_size']
            if not isinstance(size,list) or len(size)!=2 or any(type(v) is not int or not 1<=v<=10000 for v in size):
                raise ValueError('remote_book_result_invalid')
            evidence['image_size']=size
        if 'spine_count' in result:
            count = result['spine_count']
            if type(count) is not int or not 0 <= count <= len(matches):
                raise ValueError('remote_book_result_invalid')
            evidence.update(spine_count=count, spine_count_semantics='OCR_anchored_spine_hypotheses')
        if 'geometry_quality_evaluated' in result:
            evaluated=result['geometry_quality_evaluated']
            review_count=result.get('geometry_review_required_count')
            if type(evaluated) is not bool:
                raise ValueError('remote_book_result_invalid')
            if evaluated:
                if ('spine_count' not in evidence or type(review_count) is not int
                        or not 0<=review_count<=evidence['spine_count']):
                    raise ValueError('remote_book_result_invalid')
                evidence.update(geometry_quality_evaluated=True,geometry_review_required_count=review_count)
                if review_count:
                    evidence['message']='文字已识别；部分书脊边界待检查，未确认完整裁剪或实时书架位置。'
            elif review_count is not None:
                raise ValueError('remote_book_result_invalid')
        return evidence
