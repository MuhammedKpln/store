# Nextcloud Static App Store

A fully static, Nextcloud-compatible app store. You author app metadata in
hand-written YAML, run one command, and commit two generated JSON files. No
server, no database, no incoming data — Nextcloud fetches `apps.json` and
`categories.json` straight from a raw GitHub URL or GitHub Pages.

## Layout

```
apps.yaml          # hand-maintained app manifest (one entry per app)
categories.yaml    # hand-maintained categories
build.py           # YAML -> JSON generator + validation
sign.py            # helper: sign a release archive and print its signature
api/v1/apps.json       # generated output (commit this)
api/v1/categories.json # generated output (commit this)
dist/              # local release archives (gitignored)
```

## Quick start

1. Add your app entries to `apps.yaml` (see the `demoapp` example).
2. Generate:

   ```sh
   python3 build.py
   ```

3. Commit and push the generated `api/v1/*.json`.
4. Point Nextcloud at them — see [Hosting](#hosting).

## Manifest format

```yaml
- id: myapp                    # required, must match the app folder name
  name: My App                 # required
  summary: One-line pitch.     # required
  description: |
    Full description shown in the app store.
  certificate: ""              # public code-signing cert (PEM). See Signing.
  authors:
    - name: You
      mail: you@example.com
      homepage: https://example.com
  categories: [tools]          # required, must match an id in categories.yaml
  website: https://example.com
  docs:
    admin: https://example.com/docs
    user: ""
    developer: ""
  discussion: ""
  issueTracker: https://github.com/you/myapp/issues
  screenshots:
    - url: https://example.com/shot.png
      smallThumbnail: https://example.com/shot-thumb.png
  isFeatured: false
  ratingRecent: 4.5
  ratingOverall: 4.8
  ratingNumRecent: 12
  ratingNumOverall: 240
  releases:
    - version: 1.2.0           # required
      phpVersionSpec: ">= 8.0"
      platformVersionSpec: ">= 28, <= 30"   # required
      download: https://github.com/you/myapp/releases/download/v1.2.0/myapp-1.2.0.tar.gz  # required
      signature: ""            # required for install. See Signing.
      changelog: |
        - Fixed the thing
    - version: 1.1.0
      phpVersionSpec: ">= 7.4"
      platformVersionSpec: ">= 24"
      download: https://github.com/you/myapp/releases/download/v1.1.0/myapp-1.1.0.tar.gz
      signature: ""
```

### Version specs

Nextcloud's parser only accepts two space-separated tokens. `build.py`
normalizes human input automatically:

| You write                     | Stored as           |
| ----------------------------- | ------------------- |
| `*`                           | `*` (any version)   |
| `>= 28, <= 30`                | `>=28 <=30`         |
| `>= 24`                       | `>=24`              |

Use `>= X, <= Y` for a window and `>= X` or just `*` for an open or unrestricted
range.

## Building a signed release

Nextcloud refuses to install unsigned apps. Before install it:

1. checks the app's `certificate` was issued by the Nextcloud Code Signing
   **Authority** (the official one — see below),
2. verifies the released archive's `signature` against that certificate
   (`openssl_verify($archive, base64(signature), $cert, SHA512)`).

Steps:

1. Register your app id on https://apps.nextcloud.com/developer — this issues a
   certificate signed by the Nextcloud CA for your app id. Keep the private key
   secret.
2. Sign a release archive:

   ```sh
   python3 sign.py dist/myapp-1.2.0.tar.gz myapp.key
   ```

   Paste the printed base64 string into `signature:` for that release and the
   cert PEM into the app's `certificate:`.

   Or automate it in `build.py` by giving a local archive + key directly:

   ```yaml
   releases:
     - version: 1.2.0
       file: ./dist/myapp-1.2.0.tar.gz   # local archive gets signed + verified
       key:  ./dist/myapp.key            # or pass --key app.key to build.py
       download: https://github.com/you/myapp/releases/download/v1.2.0/myapp-1.2.0.tar.gz
   ```

   ```sh
   python3 build.py --key dist/myapp.key
   ```

   `build.py` computes and embeds the signature; `openssl` must be on your PATH.

> **Certificates for custom stores.** A self-signed certificate will NOT install
> on a stock Nextcloud, because the server validates the issuer chain against its
> bundled Nextcloud Code Signing Authority. Get the official per-app certificate
> from the developer registration flow, then host the releases yourself — the
> store data, downloads and distribution all stay fully static.

## Hosting

### Option A — raw GitHub URLs (no build/deploy step)

Push the repo, then set the store URL to the directory containing the JSON files:

```php
// config/config.php
'appstoreenabled' => true,
'appstoreurl' => 'https://raw.githubusercontent.com/USER/REPO/BRANCH/api/v1',
```

Nextcloud appends `/apps.json` and `/categories.json` to that base URL.

### Option B — GitHub Pages

Enable Pages in your repo settings (deploy from the default branch), then:

```php
'appstoreurl' => 'https://USER.github.io/REPO/api/v1',
```

## How it works

`build.py` validates the YAML, applies defaults, normalizes version specs and
optionally signs releases, then emits bare JSON arrays — the exact shape the
real `apps.nextcloud.com/api/v1/*.json` endpoints serve and the shape
Nextcloud's `AppFetcher`/`CategoryFetcher` expect. Everything is regenerated
locally; the committed JSON never changes on its own.

## Notes

- `isNightly: true` releases are only shown/offered on beta/daily/git channels.
- Releases whose version spec doesn't match the server version are filtered out
  server-side; you can carry multiple `platformVersionSpec` entries per app.
- The `appsallowlist` config restricts app listings to a fixed set of ids.