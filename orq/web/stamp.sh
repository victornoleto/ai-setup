#!/bin/sh
# Impressão digital da fonte da tela. O build grava em dist/src.hash; o doctor.sh compara e acusa dist/ velho.
cd "$(dirname "$0")" || exit 1
find src index.html package.json vite.config.ts -type f | LC_ALL=C sort | xargs cat | sha256sum | cut -d' ' -f1
