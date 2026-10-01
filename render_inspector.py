#!/usr/bin/env python3
"""Compatibility entry point for saved-scene inspector rendering."""
import sys

from ctrlc.rendering import render, render_scene
from ctrlc.cli import legacy_main

__all__ = ["render", "render_scene"]


if __name__ == "__main__":
    raise SystemExit(legacy_main("render", sys.argv[1:]))
