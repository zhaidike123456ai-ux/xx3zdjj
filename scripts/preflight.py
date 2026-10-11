#!/usr/bin/env python3
"""Read-only runtime and input preflight; execution uses the same selected tools."""
import argparse
import json
from pathlib import Path
from runtime_manager import RuntimeManager, add_runtime_arguments


def main(argv=None):
    parser = argparse.ArgumentParser(description='只读检查环境与输入，不安装、不上传。')
    add_runtime_arguments(parser)
    parser.add_argument('--source')
    parser.add_argument('--font')
    args = parser.parse_args(argv)
    report = RuntimeManager(args).check()
    report['inputs'] = {}
    for name in ('source', 'font'):
        value = getattr(args, name)
        if value:
            path = Path(value).expanduser().absolute()
            report['inputs'][name] = {'path': str(path), 'status': 'available' if path.is_file() else 'missing'}
    report['not_verified'] += ['font_rendering', 'jianying_native_project']
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report['ready'] and all(i['status'] == 'available' for i in report['inputs'].values()) else 1


if __name__ == '__main__':
    raise SystemExit(main())
