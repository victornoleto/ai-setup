#!/usr/bin/env bash
# Testes locais sem rede, credenciais ou escrita no checkout; nenhum download.
set -euo pipefail
orq_root=$(cd -- "$(dirname -- "$0")/.." && pwd)
orq_python=$(readlink -f "$orq_root/.venv/bin/python")
orq_runtime=$(dirname -- "$(dirname -- "$orq_python")")
orq_linkroot=$(dirname -- "$(dirname -- "$(readlink "$orq_root/.venv/bin/python")")")
exec timeout 110s bwrap --unshare-all --die-with-parent --new-session --clearenv \
  --ro-bind /usr /usr --symlink usr/bin /bin --symlink usr/lib /lib --symlink usr/lib64 /lib64 \
  --ro-bind "$orq_runtime" "$orq_runtime" --ro-bind "$orq_runtime" "$orq_linkroot" --ro-bind "$orq_root" /app \
  --proc /proc --dev /dev --size 268435456 --tmpfs /scratch --symlink /scratch /tmp \
  --setenv PATH /app/.venv/bin:/usr/bin:/bin --setenv HOME /scratch --setenv TMPDIR /scratch \
  --setenv PYTHONPATH /app/src --setenv PYTHONDONTWRITEBYTECODE 1 --setenv ORQ_HOME /app \
  --setenv GIT_CONFIG_NOSYSTEM 1 --setenv LC_ALL C.UTF-8 --chdir /app \
  /usr/bin/prlimit --cpu=90 --as=2147483648 --nproc=128 --fsize=33554432 --nofile=256 -- \
  /app/.venv/bin/python -m pytest -p no:cacheprovider "$@"
