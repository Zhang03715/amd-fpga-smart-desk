"""Restore original tool-required source paths into an isolated worktree."""
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main():
    target = ROOT / 'build' / 'worktree'
    entries = json.loads((ROOT / 'build/source_map.json').read_text(encoding='utf-8'))
    for entry in entries:
        source = (ROOT / entry['stored']).resolve()
        output = (target / entry['original']).resolve()
        if not source.is_relative_to(ROOT) or not output.is_relative_to(target.resolve()):
            raise ValueError('Unsafe source map path')
        content = source.read_bytes()
        if hashlib.sha256(content).hexdigest() != entry['sha256']:
            raise ValueError('Source hash mismatch: ' + entry['stored'])
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(content)
    print('Restored', len(entries), 'files to', target)


if __name__ == '__main__':
    main()
