#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

if [[ "${1:-}" != "--force" && -f ca.key && -f ca.crt ]]; then
    echo "Keeping existing $PWD/ca.crt (use --force to regenerate)"
    exit 0
fi

rm -f ca.key ca.crt

if command -v openssl >/dev/null 2>&1; then
    openssl req -x509 -newkey rsa:2048 -nodes -days 3650 \
        -keyout ca.key -out ca.crt \
        -subj "/CN=twin-local-ca" \
        -addext "basicConstraints=critical,CA:TRUE" \
        -addext "keyUsage=critical,keyCertSign,cRLSign"
else
    docker run --rm --user "$(id -u):$(id -g)" -v "$PWD:/certs" -w /certs alpine/openssl:3.5.9 \
        req -x509 -newkey rsa:2048 -nodes -days 3650 \
        -keyout ca.key -out ca.crt \
        -subj "/CN=twin-local-ca" \
        -addext "basicConstraints=critical,CA:TRUE" \
        -addext "keyUsage=critical,keyCertSign,cRLSign"
fi

chmod 600 ca.key
echo "Created $PWD/ca.crt"
