#!/usr/bin/env python3
"""Generate static Nextcloud app-store JSON from hand-written YAML manifests.

Reads `apps.yaml` and `categories.yaml`, validates them, optionally signs
release archives with a local private key, and writes the Nextcloud-compatible
files that a server fetches from the `appstoreurl`:

    api/v1/apps.json
    api/v1/categories.json

Usage:
    python3 build.py                  # validate + generate (no signing)
    python3 build.py --key app.key    # sign releases that have `file:` set
    python3 build.py --quiet          # only print errors
"""

import argparse
import base64
import json
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent
APPS_SRC = ROOT / "apps.yaml"
CATEGORIES_SRC = ROOT / "categories.yaml"
OUT_DIR = ROOT / "api" / "v1"

REQUIRED_APP_FIELDS = ("id", "name", "summary")
REQUIRED_RELEASE_FIELDS = ("version", "download")


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S+00:00")


def normalize_spec(spec: str) -> str:
    """Normalize a version spec to the form Nextcloud's VersionParser accepts.

    The parser only understands up to two space-separated tokens like `>=32 <=33`
    (minimum + maximum). This turns `>= 24, <= 30` and similar into `>=24 <=30`.
    """
    if not spec or spec.strip() == "*":
        return spec
    pairs = re.findall(r"([<>]=?)\s*([0-9]+(?:\.[0-9]+)*)", spec)
    if not pairs:
        return spec
    return " ".join(f"{op}{version}" for op, version in pairs)


def fail(message: str) -> None:
    print(f"error: {message}", file=sys.stderr)
    sys.exit(1)


def localize_name_summary(entry: dict) -> dict:
    """Build the `translations` map for an app entry (en default + overrides)."""
    translations = {"en": {
        "name": entry["name"],
        "summary": entry.get("summary", ""),
        "description": entry.get("description", ""),
    }}
    for locale, values in (entry.get("translations") or {}).items():
        translations[locale] = {
            "name": values.get("name", entry["name"]),
            "summary": values.get("summary", entry.get("summary", "")),
            "description": values.get("description", entry.get("description", "")),
        }
    return translations


def openssl(args: list[str], data: bytes | None = None) -> bytes | None:
    try:
        return subprocess.run(
            ["openssl", *args],
            input=data,
            capture_output=True,
            check=True,
        ).stdout
    except (FileNotFoundError, subprocess.CalledProcessError) as exc:
        print(f"warning: openssl failed ({exc} run with --quiet to hide)", file=sys.stderr)
        return None


def sign_archive(archive: Path, key: Path) -> str:
    """Return the base64 SHA512 signature Nextcloud verifies on install."""
    data = archive.read_bytes()
    sig = openssl(["dgst", "-sha512", "-sign", str(key)], data)
    if sig is None:
        fail(f"could not sign {archive.name}")
    return base64.b64encode(sig).decode()


def build_release(release: dict, app_id: str, index: int, key: Path | None) -> dict:
    missing = [f for f in REQUIRED_RELEASE_FIELDS if not release.get(f)]
    if missing:
        fail(f"app '{app_id}' release #{index + 1} is missing: {', '.join(missing)}")

    version = release["version"]
    signature = release.get("signature", "")

    # Auto-sign from a local archive when a private key is available.
    archive = release.get("file")
    if archive and (key or release.get("key")):
        key_path = Path(release.get("key")) if release.get("key") else key
        if not key_path.exists():
            fail(f"app '{app_id}' release {version}: key not found at {key_path}")
        archive_path = Path(archive)
        if not archive_path.exists():
            fail(f"app '{app_id}' release {version}: archive not found at {archive_path}")
        signature = sign_archive(archive_path, key_path)

    raw_php_spec = normalize_spec(release.get("phpVersionSpec", "*"))
    raw_platform_spec = normalize_spec(release.get("platformVersionSpec", "*"))

    last_modified = release.get("lastModified", now_iso())
    return {
        "version": version,
        "phpExtensions": release.get("phpExtensions", []),
        "databases": release.get("databases", []),
        "shellCommands": release.get("shellCommands", []),
        "phpVersionSpec": raw_php_spec,
        "platformVersionSpec": raw_platform_spec,
        "minIntSize": release.get("minIntSize", 32),
        "download": release["download"],
        "created": release.get("created", last_modified),
        "licenses": release.get("licences", release.get("licenses", [])),
        "lastModified": last_modified,
        "isNightly": bool(release.get("isNightly", False)),
        "rawPhpVersionSpec": raw_php_spec,
        "rawPlatformVersionSpec": raw_platform_spec,
        "signature": signature,
        "translations": {"en": {"changelog": release.get("changelog", "")}},
        "signatureDigest": "sha512",
    }


def build_app(app: dict, index: int, key: Path | None) -> dict:
    app_id = app.get("id")
    if not app_id:
        fail(f"entry #{index + 1} has no 'id'")
    missing = [f for f in REQUIRED_APP_FIELDS if not app.get(f)]
    if missing:
        fail(f"app '{app_id}' is missing: {', '.join(missing)}")
    if not app.get("categories"):
        fail(f"app '{app_id}' has no categories")
    if not app.get("releases"):
        fail(f"app '{app_id}' has no releases")

    last_modified = max(
        (r.get("lastModified", "") for r in app["releases"] if r.get("lastModified")),
        default=now_iso(),
    )

    return {
        "id": app_id,
        "authors": app.get("authors", []),
        "categories": app["categories"],
        "certificate": app.get("certificate", ""),
        "created": app.get("created", now_iso()),
        "lastModified": app.get("lastModified", last_modified),
        "translations": localize_name_summary(app),
        "releases": [
            build_release(r, app_id, i, key) for i, r in enumerate(app["releases"])
        ],
        "screenshots": app.get("screenshots", []),
        "adminDocs": app.get("docs", {}).get("admin", ""),
        "userDocs": app.get("docs", {}).get("user", ""),
        "developerDocs": app.get("docs", {}).get("developer", ""),
        "discussion": app.get("discussion", ""),
        "issueTracker": app.get("issueTracker", ""),
        "website": app.get("website", ""),
        "isFeatured": bool(app.get("isFeatured", False)),
        "ratingRecent": float(app.get("ratingRecent", 0.0)),
        "ratingOverall": float(app.get("ratingOverall", 0.0)),
        "ratingNumRecent": int(app.get("ratingNumRecent", 0)),
        "ratingNumOverall": int(app.get("ratingNumOverall", 0)),
    }


def build_category(category: dict, index: int) -> dict:
    cat_id = category.get("id")
    if not cat_id:
        fail(f"category #{index + 1} has no 'id'")
    translations = {"en": {
        "name": category.get("name", cat_id),
        "description": category.get("description", ""),
    }}
    for locale, values in (category.get("translations") or {}).items():
        translations[locale] = {
            "name": values.get("name", cat_id),
            "description": values.get("description", ""),
        }
    return {"id": cat_id, "translations": translations}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--key", type=Path, help="private key used to sign local release archives")
    parser.add_argument("--quiet", action="store_true", help="suppress warnings")
    args = parser.parse_args()

    if not APPS_SRC.exists():
        fail(f"missing {APPS_SRC.name}")
    if not CATEGORIES_SRC.exists():
        fail(f"missing {CATEGORIES_SRC.name}")
    if args.key and not args.key.exists():
        fail(f"key not found at {args.key}")

    apps = yaml.safe_load(APPS_SRC.read_text()) or []
    categories = yaml.safe_load(CATEGORIES_SRC.read_text()) or []

    OUT_DIR.mkdir(parents=True, exist_ok=True)

    apps_data = [build_app(app, i, args.key) for i, app in enumerate(apps)]
    with open(OUT_DIR / "apps.json", "w") as fh:
        json.dump(apps_data, fh, indent=2, ensure_ascii=False)
        fh.write("\n")

    categories_data = [build_category(cat, i) for i, cat in enumerate(categories)]
    with open(OUT_DIR / "categories.json", "w") as fh:
        json.dump(categories_data, fh, indent=2, ensure_ascii=False)
        fh.write("\n")

    if not args.quiet:
        print(f"wrote {OUT_DIR / 'apps.json'} ({len(apps)} apps, {sum(len(a['releases']) for a in apps)} releases)")
        print(f"wrote {OUT_DIR / 'categories.json'} ({len(categories)} categories)")
        unsigned = [
            f"{a['id']} v{r['version']}"
            for a in apps
            for r in a["releases"]
            if not r.get("signature")
        ]
        if unsigned:
            print("note: unsigned releases (install will be blocked):", ", ".join(unsigned))


if __name__ == "__main__":
    main()