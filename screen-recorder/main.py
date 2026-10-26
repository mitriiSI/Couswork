"""Entry point: `python main.py` opens the window, `--selftest DIR` checks the build."""

import sys


def main():
    if len(sys.argv) >= 3 and sys.argv[1] == "--selftest":
        from screenrec.selftest import run_selftest
        sys.exit(run_selftest(sys.argv[2]))
    from screenrec.gui import run
    run()


if __name__ == "__main__":
    main()
