"""Command-line interface for the reusable local workflows."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess
import sys
from typing import Sequence

from . import __version__
from .extraction import InvalidOCRDataError, compact, parse_roi, run_extraction
from .hierarchy import InvalidHierarchyError
from .preview import InvalidPreviewDocumentError, create_preview_server
from .rendering import InvalidSceneError, render_scene
from .workflows import refine_scene


COMMANDS = {"extract", "refine", "render", "serve"}


class ArgumentFailure(Exception):
    pass


class JsonArgumentParser(argparse.ArgumentParser):
    def error(self, message):
        raise ArgumentFailure(message)


def _argument_parser() -> JsonArgumentParser:
    parser = JsonArgumentParser(prog="ctrlc", description="Extract and inspect screenshot UI locally.")
    parser.add_argument("--version", action="version", version=f"ctrlc {__version__}")
    commands = parser.add_subparsers(dest="command", required=True, parser_class=JsonArgumentParser)

    extract = commands.add_parser("extract", help="measure a screenshot and save its scene")
    extract.add_argument("image", type=Path, help="PNG, JPEG or WebP screenshot")
    extract.add_argument("--out", type=Path, required=True, help="directory for saved results")
    extract.add_argument("--roi", type=parse_roi,
                         help="x,y,width,height in upright screenshot pixels")
    extract.add_argument("--languages", default="en-US", help="Vision OCR language list")
    extract.add_argument("--ocr-json", type=Path, help="use saved OCR instead of native Vision")
    extract.add_argument("--refresh", action="store_true", help="recompute this image/configuration")
    extract.add_argument("--inspector", action="store_true", help="also render a local inspector")
    extract.add_argument("--depth", type=int, choices=(1, 2, 3),
                         help="maximum hierarchy depth; omitted keeps legacy output")

    refine = commands.add_parser("refine", help="refine a saved scene without running OCR")
    refine.add_argument("scene", type=Path, help="saved scene with a measurement artifact")
    refine.add_argument("image", type=Path, help="matching source screenshot")
    refine.add_argument("--out", type=Path, required=True, help="directory for saved results")
    refine.add_argument("--depth", type=int, choices=(1, 2, 3), required=True,
                        help="maximum hierarchy depth to save")
    refine.add_argument("--inspector", action="store_true", help="also render a local inspector")

    render = commands.add_parser("render", help="render an existing scene without extraction")
    render.add_argument("scene", type=Path, help="saved scene JSON")
    render.add_argument("image", type=Path, help="matching source screenshot")
    render.add_argument("--out", type=Path, required=True, help="HTML output file")
    render.add_argument("--fragment", action="store_true", help="write the embeddable fragment")

    serve = commands.add_parser("serve", help="serve one inspector on localhost")
    serve.add_argument("document", type=Path, help="generated inspector HTML")
    serve.add_argument("--port", type=_port, default=8767, help="localhost port, or 0 for any free port")
    return parser


def _port(value: str) -> int:
    try:
        port = int(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError("port must be an integer from 0 to 65535") from error
    if not 0 <= port <= 65535:
        raise argparse.ArgumentTypeError("port must be an integer from 0 to 65535")
    return port


def _envelope(command: str | None, result: dict) -> dict:
    return {"schemaVersion": 1, "command": command, "ok": True, "result": result}


def _error_envelope(command: str | None, code: str, message: str) -> dict:
    return {"schemaVersion": 1, "command": command, "ok": False,
            "error": {"code": code, "message": message}}


def _error_details(error: Exception) -> tuple[str, str]:
    if isinstance(error, InvalidSceneError):
        return "invalid_scene", str(error)
    if isinstance(error, InvalidHierarchyError):
        return "invalid_scene", str(error)
    if isinstance(error, InvalidOCRDataError):
        return "invalid_ocr", str(error)
    if isinstance(error, InvalidPreviewDocumentError):
        return "invalid_preview_document", str(error)
    if isinstance(error, FileNotFoundError):
        return "file_not_found", str(error)
    if isinstance(error, json.JSONDecodeError):
        return "invalid_json", str(error)
    if isinstance(error, subprocess.CalledProcessError):
        details = (error.stderr or "").strip() or str(error)
        return "native_ocr_failed", details
    if isinstance(error, subprocess.TimeoutExpired):
        return "native_ocr_timeout", str(error)
    if isinstance(error, ValueError):
        message = str(error)
        lowered = message.lower()
        if "does not match" in lowered or "source hash" in lowered:
            return "source_mismatch", message
        if "native ocr needs" in lowered:
            return "native_ocr_unavailable", message
        return "invalid_input", message
    if isinstance(error, KeyError):
        return "invalid_scene", f"Scene is missing required field {error}"
    if isinstance(error, OSError):
        return "io_error", str(error)
    return "operation_failed", str(error)


def _run(args) -> dict:
    if args.command == "extract":
        return run_extraction(args.image, args.out, roi=args.roi, languages=args.languages,
                              ocr_json_path=args.ocr_json, refresh=args.refresh,
                              inspector=args.inspector, depth=args.depth)
    if args.command == "refine":
        return refine_scene(args.scene, args.image, args.out, depth=args.depth,
                            inspector=args.inspector)
    if args.command == "render":
        return render_scene(args.scene, args.image, args.out, fragment=args.fragment)
    if args.command == "serve":
        server = create_preview_server(args.document, args.port)
        address, port = server.server_address[:2]
        result = {"document": str(args.document.resolve()),
                  "url": f"http://{address}:{port}/sample/inspector.html"}
        try:
            print(json.dumps(_envelope("serve", result), ensure_ascii=False, separators=(",", ":")),
                  flush=True)
            try:
                server.serve_forever()
            except KeyboardInterrupt:
                return {}
        finally:
            server.server_close()
        return result
    raise ValueError(f"Unsupported command: {args.command}")


def main(argv: Sequence[str] | None = None) -> int:
    """Run the agent CLI, writing one JSON result or error envelope."""
    raw_args = list(sys.argv[1:] if argv is None else argv)
    command = raw_args[0] if raw_args and raw_args[0] in COMMANDS else None
    parser = _argument_parser()
    try:
        args = parser.parse_args(raw_args)
    except ArgumentFailure as error:
        print(json.dumps(_error_envelope(command, "invalid_arguments", str(error)),
                         ensure_ascii=False, separators=(",", ":")), file=sys.stderr)
        return 2
    if args.command == "serve":
        try:
            _run(args)
            return 0
        except KeyboardInterrupt:
            return 0
        except (ValueError, OSError, KeyError, json.JSONDecodeError,
                subprocess.SubprocessError) as error:
            code, message = _error_details(error)
            print(json.dumps(_error_envelope(args.command, code, message),
                             ensure_ascii=False, separators=(",", ":")), file=sys.stderr)
            return 1
    try:
        result = _run(args)
    except (ValueError, OSError, KeyError, json.JSONDecodeError,
            subprocess.SubprocessError) as error:
        code, message = _error_details(error)
        print(json.dumps(_error_envelope(args.command, code, message),
                         ensure_ascii=False, separators=(",", ":")), file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 130
    except Exception as error:
        code, message = _error_details(error)
        print(json.dumps(_error_envelope(args.command, code, message),
                         ensure_ascii=False, separators=(",", ":")), file=sys.stderr)
        return 1
    print(json.dumps(_envelope(args.command, result), ensure_ascii=False, separators=(",", ":")))
    return 0


def _legacy_parser(command: str) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Legacy compatibility adapter for ctrlc.")
    if command == "extract":
        parser.add_argument("image", type=Path)
        parser.add_argument("--out", type=Path, required=True)
        parser.add_argument("--roi", type=parse_roi)
        parser.add_argument("--languages", default="en-US")
        parser.add_argument("--ocr-json", type=Path)
        parser.add_argument("--refresh", action="store_true")
        parser.add_argument("--inspector", action="store_true")
    elif command == "render":
        parser.add_argument("scene", type=Path)
        parser.add_argument("image", type=Path)
        parser.add_argument("--out", type=Path, required=True)
        parser.add_argument("--fragment", action="store_true")
    elif command == "serve":
        parser.add_argument("inspector", type=Path)
        parser.add_argument("--port", type=int, default=8767)
    return parser


def legacy_main(command: str, argv: Sequence[str] | None = None) -> int:
    """Retain the original script commands as thin workflow adapters."""
    parser = _legacy_parser(command)
    args = parser.parse_args(argv)
    try:
        if command == "extract":
            result = run_extraction(args.image, args.out, roi=args.roi, languages=args.languages,
                                    ocr_json_path=args.ocr_json, refresh=args.refresh,
                                    inspector=args.inspector)
            result = {key: result[key] for key in ("cacheHit", "llmCalls", "modelTokens",
                                                    "components", "packetBytes", "elapsedSeconds", "output")}
            print(compact(result))
        elif command == "render":
            result = render_scene(args.scene, args.image, args.out, fragment=args.fragment)
            print(json.dumps({"output": result["html"], "bytes": result["bytes"],
                              "llmCalls": result["llmCalls"]}, separators=(",", ":")))
        else:
            server = create_preview_server(args.inspector, args.port)
            actual_port = server.server_address[1]
            print(f"Inspector: http://127.0.0.1:{actual_port}/sample/inspector.html", flush=True)
            try:
                server.serve_forever()
            except KeyboardInterrupt:
                pass
            finally:
                server.server_close()
    except (ValueError, OSError, KeyError, json.JSONDecodeError,
            subprocess.SubprocessError) as error:
        details = getattr(error, "stderr", None) or str(error)
        print(f"{command.capitalize()} failed: {details}", file=sys.stderr)
        return 1
    return 0
