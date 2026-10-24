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

See `README.md` for setup, commands, configuration, and scheduling.

## Current archive behavior

- Image preference is HD, then large, medium, small. The job does not request
  new Full-HD uploads from SPYPOINT.
- The sidecar keeps photo metadata, the current camera display name in
  `camera_name`, SPYPOINT labels in `photo.tag`, available variants, chosen
  image filename, byte count, SHA-256 hash, and download time. These are not
  embedded in image EXIF. Signed URLs and access paths are excluded.
- A rerun skips downloading when the sidecar points to a nonempty file for the
  current best variant. It still refreshes metadata. A later HD variant is
  downloaded and the older image is retained. Images under distinct photo IDs
  are not deduplicated by content.
- The first successful uncapped run writes `archive/_state.json`. Later runs
  inspect a seven-day overlap window; a full scan runs every 30 days or when
  the camera list or tag filter changes. Failed and capped runs do not advance
  the checkpoint. `SPYPOINT_TAGS=buck` archives only photos with that API tag.
  The one-shot job is designed to be invoked by a host scheduler, such as cron.

## Local status (2026-10-23)

- An earlier live one-photo trial saved a JPEG and JSON sidecar; a repeat run
  skipped its download. Later one-photo trials with `SPYPOINT_TAGS=buck` saved
  buck-tagged images. The older non-buck trial photo remains in `archive/`.
  The latest buck trial verified `camera_name` in its JSON sidecar.
- The account currently lists 13 cameras. A read-only date search on 2026-10-23
  found the oldest photo returned across them dated 2025-10-24 UTC. SPYPOINT's
  published Insiders Club benefit is 12 months of gallery history.
- `archive/_state.json` does not exist yet because no uncapped full archive has
  completed. The next uncapped run will scan the available history and may
  download many photos. Run it with `docker compose run --rm spypoint-archive`
  when the user wants to initialize the full archive.
- The source is forked to `jankar86/pyspypoint`; the local `origin` remote points
  there and `upstream` points to `hstern/pyspypoint`.
- The Linux x86-64 image with the tag filter and camera-name metadata is
  published publicly on Docker Hub as `jankar/pyspypoint:0.2.1` and
  `jankar/pyspypoint:latest`.

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
