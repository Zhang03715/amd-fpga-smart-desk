"""Package the standard-library Z2 uploader, excluding credentials and models."""
import argparse
import hashlib
import json
from pathlib import Path
import zipfile


ROOT = Path(__file__).resolve().parents[1]
FILES = ('ocr_link/client.py', 'ocr_link/board_cli.py', 'ocr_link/board_launch.sh',
         'ocr_link/snapshot.py', 'ocr_link/camera_daemon.py',
         'ocr_link/consensus.py',
         'ocr_link/validate_board_images.py', 'ocr_link/validate_board_service.py',
         'voice_bridge/desk_features.py',
         'voice_bridge/book_adapter.py', 'voice_bridge/pynq_service.py',
         'voice_bridge/remote_book_adapter.py', 'voice_bridge/usb_service.py',
         'voice_bridge/shelf_book_adapter.py', 'voice_bridge/shelf_calibration.py', 'adapter_control/__init__.py',
         'adapter_control/local_book_lights.py', 'adapter_control/hardware.py')
README = r"""# Z2 LAN OCR client

Extract this package to /home/xilinx/ocr-link-client. No pip installation is
required for existing JPEG/PNG uploads (Python 3.10+ standard library).
Camera capture additionally requires the board's existing OpenCV runtime.
This package contains no OCR models, GPU runtime, passwords or token.

Create a token file privately from the token prepared on the PC; do not put
the token in command-line arguments or source files:

    umask 077
    read -r -s -p 'OCR token: ' OCR_TOKEN; echo
    printf '%s\n' "$OCR_TOKEN" > ~/.ocr-link-token
    unset OCR_TOKEN
    chmod 600 ~/.ocr-link-token

The PC and Z2 must be on the same LAN, and PC TCP port 8765 must be reachable.
Replace PC_IP below with the actual PC address, not the board's address.

    cd /home/xilinx/ocr-link-client
    bash ocr_link/board_launch.sh --server http://PC_IP:8765 --token-file ~/.ocr-link-token --health
    bash ocr_link/board_launch.sh --server http://PC_IP:8765 --token-file ~/.ocr-link-token --image /path/to/shelf.jpg --action book.scan --output output
    bash ocr_link/board_launch.sh --server http://PC_IP:8765 --token-file ~/.ocr-link-token --image /path/to/shelf.jpg --action book.find --title '高等数学' --output output

One command = one explicit upload + OCR job. Each output directory contains
request.json, response.json, transport.json and preview.jpg when available.
A failure/timeout can be resumed with --resume output/REQUEST_ID. Resume
reuses the original request ID and exact payload; it does not recapture.
For a new capture or command use a new request ID and directory.

Camera example (requires an actual UVC camera and OpenCV; not guaranteed by
the standard-library package):

    bash ocr_link/board_launch.sh --server http://PC_IP:8765 --token-file ~/.ocr-link-token --camera /dev/video0 --width 1920 --height 1080 --runtime-path /home/xilinx/book_ocr_validation/runtime --output output

The existing DeskService supports an opt-in remote OCR book.find backend.
This package includes the standard-library service/remote adapter modules;
merely importing them does not load a board OCR model. The local legacy OCR
backend is not packaged and must not be selected when using this upload-only
deployment.

Run the real service in stdin protocol demonstration mode (same DeskService
instance, no physical UART or new peripheral wiring):

    python3 -m voice_bridge.pynq_service --book-image /path/to/shelf.jpg --book-ocr-server http://PC_IP:8765 --book-ocr-token-file ~/.ocr-link-token --book-ocr-output output/service-books --db-path output/desk-records.sqlite3

Then enter one complete JSON line:

    {"v":1,"type":"request","id":"find-1","action":"book.find","params":{"title":"大学物理实验"}}

The first reply is pending. Later, in the same running process, enter:

    {"v":1,"type":"request","id":"poll-1","action":"job.get","params":{"request_id":"find-1"}}

Use a new poll ID on each poll. If still pending, wait and poll again. For
camera capture, replace --book-image with --book-camera /dev/video0 and add
--book-camera-runtime-path /home/xilinx/book_ocr_validation/runtime.
Stdin demonstration is not a live UART/timer daemon. Physical S3 UART has
not been tested by the LAN image validation. A Linux serial port deployment
additionally needs pyserial and a verified device mapping; the existing
adapter_control PL UART deployment instead needs its matching overlay and
PYNQ/Pillow package and must use the same configured DeskService instance.
Do not guess /dev/ttyPS1 for the PL UART on physical header pins 35/36.

Returned UART/service evidence is compact and bounded; complete matches,
preview and source/timing remain in the HTTP client output directory. A
result says no lamp or motor was actuated. Importing the remote adapter does
not activate the local OCR fallback.

Static uploads are live=false. Camera timestamps are read-completion times,
not sensor exposure timestamps. The uploader never controls lights, motors
or posture reminders. HTTP bearer tokens protect LAN access; traffic is not
encrypted on HTTP. Keep the service within the trusted LAN and use HTTPS
through an appropriate reverse proxy when that property is required.

Full implementation and validation notes are maintained in the PC project:
docs/Z2与电脑OCR全链路验证.md.
"""


def package(output):
    payloads = {name: (ROOT / name).read_bytes() for name in FILES}
    payloads['ocr_link/__init__.py'] = b'"""Z2 LAN OCR upload client."""\n'
    payloads['voice_bridge/__init__.py'] = b'"""Existing desk service with opt-in remote OCR backend."""\n'
    payloads['README.md'] = README.encode('utf-8')
    manifest = {'format': 1, 'scope': 'Z2 uploader and opt-in DeskService remote backend; no credentials or models',
                'files': {name: {'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest()}
                          for name, data in payloads.items()}}
    payloads['manifest.json'] = json.dumps(manifest, ensure_ascii=False, indent=2).encode('utf-8')
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output, 'w', zipfile.ZIP_DEFLATED) as archive:
        for name, data in payloads.items():
            info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            archive.writestr(info, data)
    with zipfile.ZipFile(output) as archive:
        bad = archive.testzip()
        if bad:
            raise RuntimeError('ZIP CRC failure: ' + bad)
        for name, expected in manifest['files'].items():
            if hashlib.sha256(archive.read(name)).hexdigest() != expected['sha256']:
                raise RuntimeError('ZIP manifest failure: ' + name)
    result = {'path': str(output.resolve()), 'bytes': output.stat().st_size,
              'sha256': hashlib.sha256(output.read_bytes()).hexdigest(), 'files': len(payloads)}
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=ROOT / 'output/z2-ocr-link-client.zip')
    package(parser.parse_args().output)
