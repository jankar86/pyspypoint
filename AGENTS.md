# Project handoff

## What this repository does

`spypoint/` is an unofficial Python client for the SPYPOINT Cloud API. It can log
in, list cameras, query photos with filters, list species tags, and build signed
image URLs. SPYPOINT does not provide an API schema in this repository; use the
client code and a safely redacted live response when checking behavior.

The Docker image uses Python 3.12 Alpine and starts `poller.py` by default for
Unraid. Compose provides two one-shot jobs and an optional poller:

- `spypoint-smoke-test` lists cameras and recent photo URLs.
- `spypoint-archive` downloads the best image variant currently available and
  stores a JSON sidecar under `archive/<camera-id>/`.
- `spypoint-poller` runs the archive immediately and then every six hours by
  default. Start it with `docker compose --profile poller up -d spypoint-poller`.
- `spypoint-gallery` optionally runs FileBrowser Quantum against the archive
  mounted read-only. Its account database persists in `gallery-data/`.

See `README.md` for setup, commands, configuration, and scheduling.

## Current archive behavior

- Image preference is HD, then large, medium, small. The job does not request
  new Full-HD uploads from SPYPOINT.
- The sidecar keeps photo metadata, available variants, chosen image filename,
  byte count, SHA-256 hash, and download time. Signed URLs and access paths are
  excluded.
- A rerun skips downloading when the sidecar points to a nonempty file for the
  current best variant. It still refreshes metadata. A later HD variant is
  downloaded and the older image is retained. Images under distinct photo IDs
  are not deduplicated by content.
- The first successful uncapped run writes `archive/_state.json`. Later runs
  inspect a seven-day overlap window; a full scan runs every 30 days or when
  the camera list changes. Failed and capped runs do not advance the checkpoint.
  The one-shot job is designed to be invoked by a host scheduler, such as cron.

## Local status (2026-10-23)

- A live one-photo trial saved a JPEG and JSON sidecar; a repeat run skipped its
  download. Only one photo has been archived locally so far.
- `archive/_state.json` does not exist yet because no uncapped full archive has
  completed. The next uncapped run will scan the available history and may
  download many photos. Run it with `docker compose run --rm spypoint-archive`
  when the user wants to initialize the full archive.
- The source is forked to `jankar86/pyspypoint`; the local `origin` remote points
  there and `upstream` points to `hstern/pyspypoint`.
- The Linux x86-64 image is published publicly on Docker Hub as
  `jankar/pyspypoint:0.1.0` and `jankar/pyspypoint:latest`.
- The optional gallery uses `gtstef/filebrowser:stable` with `archive/` mounted
  read-only and `gallery-data/` mounted at `/data` for its SQLite database.
  `gallery-config.yaml` disables built-in authentication; the user plans to put
  authentication on a proxy. Keep direct access to the gallery port restricted.

## Verification and handling notes

- Run `python3 -m unittest test.test_archive -v`, `docker compose config --quiet`,
  and `git diff --check` after archive changes. Existing `test/test_client.py`
  needs the optional `requests-mock` dependency.
- `.env` contains local SPYPOINT credentials. `archive/` contains private photos
  and metadata. Both are Git ignored and excluded from the Docker build context.
  Do not print credentials, bearer tokens, or signed image URLs in logs or chat
  unless the user explicitly requests a URL.
- SPYPOINT serves tested JPEG downloads as `binary/octet-stream`; `archive.py`
  identifies supported images by file signature rather than HTTP content type.
- Photo pagination uses `originDate` and the API's `date_end` parameter. The
  seven-day overlap catches many delayed uploads, while the periodic full scan
  catches older ones and older HD upgrades.
