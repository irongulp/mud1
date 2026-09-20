#!/bin/bash
set -euo pipefail
if [[ $(id -u) != 0 ]]; then
    printf '%s\n' 'Run with sudo: sudo bash setup.sh --domain mud.etimbo.com' >&2
    exit 1
fi
source /etc/os-release
if [[ "$ID" != almalinux || "${VERSION_ID%%.*}" != 9 ]]; then
    printf '%s\n' 'This installer targets AlmaLinux 9.' >&2
    exit 1
fi
dnf install -y python3.12 python3.12-pip
ROOT=$(dirname "$(readlink -f "$0")")
exec python3.12 "$ROOT/tools/deploy.py" "$@"
