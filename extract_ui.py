#!/usr/bin/env python3
"""Compatibility entry point for the packaged screenshot extractor."""
from pathlib import Path
import sys

from ctrlc.extraction import (VERSION, compact, components, contains, dominant, extract,
                              hex_color, label, native_ocr, packet, parse_roi, union,
                              validate_ocr, run_extraction)
from ctrlc.cli import legacy_main

HERE = Path(__file__).resolve().parent


if __name__ == "__main__":
    raise SystemExit(legacy_main("extract", sys.argv[1:]))
