#!/usr/bin/env python3
"""
Run a fraqtoos bot module's run() and print what it returns.

The chia bots were invoked as a `python3.12 -c "import sys; sys.path.insert(...)
; from bots.x import run; print(run())"` one-liner. That is fine inside a
Python dict but hostile in a systemd ExecStart, where the embedded quotes and
semicolons have to survive another layer of parsing. A two-line wrapper is
cheaper than getting that escaping right once and re-deriving it every time
someone edits the unit.

Usage: run_bot_module.py bots.chia_health
"""
import importlib
import sys

sys.path.insert(0, "/home/work/fraqtoos")


def main() -> int:
    if len(sys.argv) < 2:
        print("usage: run_bot_module.py <module>", file=sys.stderr)
        return 2
    out = importlib.import_module(sys.argv[1]).run()
    if out:
        print(out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
