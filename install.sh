#!/bin/sh
set -eu

if [ "$#" -ne 0 ]; then
    printf 'Usage: sh install.sh\n' >&2
    exit 2
fi

uv_bin=$(command -v uv || true)
if [ -z "$uv_bin" ]; then
    uv_install_dir=${UV_INSTALL_DIR:-"$HOME/.local/bin"}
    uv_bin="$uv_install_dir/uv"
    if [ ! -x "$uv_bin" ]; then
        if ! command -v curl >/dev/null 2>&1; then
            printf 'Install curl or uv, then run this script again.\n' >&2
            exit 1
        fi
        printf 'Installing uv...\n'
        uv_installer=$(mktemp)
        trap 'rm -f "$uv_installer"' 0
        curl -fsSL https://astral.sh/uv/install.sh -o "$uv_installer"
        UV_INSTALL_DIR="$uv_install_dir" UV_NO_MODIFY_PATH=1 sh "$uv_installer"
    fi
fi

wheel_url=https://github.com/devos-ing/ctrlc/releases/download/v0.1.0/ctrlc-0.1.0-py3-none-any.whl
printf 'Installing ctrlc 0.1.0...\n'
"$uv_bin" tool install --force "$wheel_url"

tool_bin=$("$uv_bin" tool dir --bin)
"$tool_bin/ctrlc" --version
printf 'Installed ctrlc at %s\n' "$tool_bin/ctrlc"

case ":${PATH:-}:" in
    *":$tool_bin:"*) ;;
    *)
        printf '\nAdd %s to your PATH to run ctrlc by name.\n' "$tool_bin"
        printf 'For now, you can run "%s/ctrlc" directly.\n' "$tool_bin"
        ;;
esac
