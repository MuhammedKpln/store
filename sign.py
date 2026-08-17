#!/usr/bin/env python3
"""Compute the signature and digest Nextcloud needs for a release archive.

Nextcloud verifies a store release with:
    openssl_verify($archive, base64_decode($signature), $appCertificate, OPENSSL_ALGO_SHA512)

So `signature` = base64( SHA512-signature of the archive bytes with the app's
private key ), and this script outputs exactly that, ready to paste into
`apps.yaml` or to feed `build.py`.

Usage:
    python3 sign.py dist/demoapp-0.4.2.tar.gz dist/demoapp.key

Output:
    <base64 SHA512 signature>   paste this into `apps.yaml` under `signature:`
"""

import base64
import subprocess
import sys
from pathlib import Path


def openssl(args: list[str], data: bytes) -> bytes:
    return subprocess.run(
        ["openssl", *args],
        input=data,
        capture_output=True,
        check=True,
    ).stdout


def main() -> None:
    if len(sys.argv) != 3:
        print(__doc__)
        sys.exit(2)
    archive, key = Path(sys.argv[1]), Path(sys.argv[2])
    if not archive.exists():
        print(f"error: archive not found: {archive}", file=sys.stderr)
        sys.exit(1)
    if not key.exists():
        print(f"error: key not found: {key}", file=sys.stderr)
        sys.exit(1)

    data = archive.read_bytes()
    signature = openssl(["dgst", "-sha512", "-sign", str(key)], data)
    print(base64.b64encode(signature).decode())


if __name__ == "__main__":
    main()