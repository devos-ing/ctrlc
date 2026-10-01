#!/usr/bin/env python3
"""Compatibility entry point for the localhost inspector preview."""
import sys

from ctrlc.preview import create_preview_server
from ctrlc.cli import legacy_main

__all__ = ["create_preview_server"]


if __name__ == "__main__":
    raise SystemExit(legacy_main("serve", sys.argv[1:]))
