import argparse
import sys
from collections.abc import Sequence
from importlib.metadata import version


def main(argv: Sequence[str] | None = None) -> None:
    args = list(sys.argv[1:] if argv is None else argv)
    parser = argparse.ArgumentParser(prog="voice-sidecar")
    parser.add_argument("--version", action="version", version=version("voice-sidecar"))
    if not args:
        parser.error("a flag is required")
    parser.parse_args(args)
