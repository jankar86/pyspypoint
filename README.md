# pyspypoint

This is a fork of [hstern/pyspypoint](https://github.com/hstern/pyspypoint).
The archiver source is at [jankar86/pyspypoint](https://github.com/jankar86/pyspypoint),
and the deployable image is at [jankar/pyspypoint on Docker Hub](https://hub.docker.com/r/jankar/pyspypoint).

`pyspypoint` is an unofficial Python client for the SPYPOINT Cloud API. It logs in
with a SPYPOINT account, lists the account's cameras, retrieves recent photo
metadata, and builds download URLs from the photo data. It can also list the
species tags available to the account. This repository is a client library; the
container below is a one-shot check of the library, not a web service or a
continuous photo downloader.

## Use the Python library

Install it from this checkout with `python -m pip install .`, then:

```python
import spypoint

client = spypoint.Client(username, password)
cameras = client.cameras()
photos = client.photos(cameras, limit=1)
for photo in photos:
    print(photo.url())  # large image URL by default
```

`Client.cameras()` lists cameras, `Client.photos(cameras, limit=100)` retrieves
photo metadata, and `Client.tags()` lists species tag identifiers. The photo
query also accepts `date_end`, `hd`, `favorite`, and `tags`. `Photo.url(size)`
builds a URL for an available size such as `small`, `medium`, or `large`.
The client does not save images locally. Photo URLs can contain signed access
parameters and may expire; treat them as sensitive.

## Run the container check

Docker with Compose is required. The image uses Python 3.12 on Alpine and runs
as an unprivileged user. From this directory:

```sh
cp .env.example .env
# Edit .env with your SPYPOINT username and password.
docker compose run --build --rm spypoint-smoke-test
```

The command builds the image, logs in once, prints camera IDs and
up to `SPYPOINT_PHOTO_LIMIT` recent photo URLs, then exits. The default limit is
1. The URL output may grant access to a photo until it expires, so avoid sharing
the output. If the account has no cameras or photos, it reports that and exits
successfully. A failed request exits with a nonzero status.

For later runs, omit `--build`: `docker compose run --rm spypoint-smoke-test`.
The container needs no open ports or persistent storage.

To check the API without printing signed photo URLs, run
`docker compose run --build --rm -e SPYPOINT_SHOW_URLS=0 spypoint-smoke-test`.

The credentials stay in the local `.env` file, which Git and the Docker build
context ignore. The image contains the client code and `requests`, but no
account credentials. Network access to `restapi.spypoint.com` is needed for a
live check.

## Archive photos and metadata

The archive job downloads the highest resolution **currently available** for
each photo: HD when the response includes an HD file, otherwise large, medium,
or small. It saves images and JSON metadata sidecars under `./archive/<camera-id>/`.
For example, a photo may produce `<photo-id>.large.jpg` and `<photo-id>.json`.
The JSON contains the photo ID, camera ID, timestamps, original filename and
size, tags, available image variants, and the saved file's SHA-256 hash and byte
count. Signed download paths are omitted from the JSON because they expire.

Start with a small trial:

```sh
mkdir -p archive
docker compose run --build --rm -e SPYPOINT_MAX_PHOTOS=10 spypoint-archive
```

Then run the full archive:

```sh
docker compose run --rm spypoint-archive
```

`SPYPOINT_MAX_PHOTOS=0` (the default) means no cap. The job requests pages of
100 photos by default; set `SPYPOINT_PAGE_SIZE` to a value of at least 2 if
needed. On a rerun, the job skips a download when that photo's JSON sidecar
records the best currently available variant and the referenced image file
exists and is nonempty. It still refreshes the JSON metadata. It also skips a
photo ID encountered more than once while paging through a single run. If an
HD version becomes available later, it downloads the HD image and retains the
earlier file.

The skip check is based on photo ID and variant, not image content: identical
images with different photo IDs are saved separately. If a sidecar is missing,
the image may be downloaded again. The stored SHA-256 hash is for reference;
reruns do not use it to verify an existing file. The job does not request new
Full-HD uploads. SPYPOINT describes [requesting a
Full-HD upload](https://www.spypoint.com/ca/en/support/article-detail?folder=hdPhotoAndVideoPackages&id=s131&topic=how-to-request-a-full-hd-photos-and-videos)
as a separate action in its app or web gallery.

### Poll for new photos

The first uncapped run scans all photo history available through the API. After
it finishes without errors, it saves a checkpoint in `archive/_state.json`.
Later runs query only recent pages, stopping once they reach photos older than
the overlap window. The default overlap is seven days
(`SPYPOINT_LOOKBACK_DAYS=7`). Already saved photos in that window are checked
for metadata changes and newly available HD versions without downloading the
same image again. A typical quiet poll makes one login request, one camera-list
request, and one photo-page request.

The job performs a full scan every 30 days by default
(`SPYPOINT_FULL_SCAN_DAYS=30`), or when the set of cameras changes. This can
find older delayed uploads and HD upgrades outside the overlap window. Run a
full scan immediately with
`docker compose run --rm -e SPYPOINT_FULL_SCAN=1 spypoint-archive`. A failed
run or a run capped by `SPYPOINT_MAX_PHOTOS` does not advance the checkpoint.
Keep `archive/_state.json` with the archived files when moving the archive.

The `spypoint-archive` Compose job runs once and exits. To poll automatically
from this checkout, either start the long-running poller with
`docker compose --profile poller up -d spypoint-poller`, or schedule the normal
archive command on the host. For example, this cron entry runs every six hours
and prevents overlapping jobs (replace the directory with your checkout path):

```cron
0 */6 * * * cd /absolute/path/to/pyspypoint && flock -n archive/.poll.lock docker compose run --rm spypoint-archive >> archive/poll.log 2>&1
```

Choose the interval based on your cameras' transfer settings; [SPYPOINT lists
transfer schedules ranging from daily to every two hours or each detection](https://www.spypoint.com/en/support/camera-model-support/articles/114/how-to-verify-if-my-cellular-device-is-communicating.html).
Photos transmitted more than seven days after their original timestamp may not
appear until the next full scan. The poller starts an archive run immediately,
then waits `SPYPOINT_POLL_HOURS` hours (default: 6) between runs. The published
image uses the poller as its default command; the one-shot Compose jobs override
that command.

The archive directory and `.env` are ignored by Git and excluded from the Docker
build context. The archive container writes as UID/GID 1000 by default. On a
host with a different account ID, set `ARCHIVE_UID` and `ARCHIVE_GID` in `.env`
to the values from `id -u` and `id -g` before running it. Photo downloads need
network access to the signed image hosts in addition to the SPYPOINT API.

## Deploy the image on Unraid

Add a container in Unraid's Docker page with these settings:

| Setting | Value |
| --- | --- |
| Repository | `jankar/pyspypoint:0.1.0` ([Docker Hub](https://hub.docker.com/r/jankar/pyspypoint)) |
| Network | Bridge; no port mappings |
| Host path | `/mnt/user/appdata/pyspypoint/archive` |
| Container path | `/archive` (read/write) |
| Environment | `SPYPOINT_USERNAME`, `SPYPOINT_PASSWORD` |
| Optional environment | `SPYPOINT_POLL_HOURS=6`, `SPYPOINT_LOOKBACK_DAYS=7`, `SPYPOINT_FULL_SCAN_DAYS=30` |

Create the host directory first and give the container's user write access.
For an Unraid share owned by `nobody:users`, set **Extra Parameters** to
`--user 99:100`. The image starts the poller automatically, runs the first
archive immediately, and keeps the checkpoint in `/archive/_state.json`. Set
the container to auto-start to resume polling after a reboot. The initial
uncapped run can download the whole history currently exposed by SPYPOINT.
The published image currently targets Linux x86-64, which is the usual Unraid
platform. The `latest` tag points to the same image as `0.1.0`.

Unraid supports these volume and environment mappings in its [container
settings](https://docs.unraid.net/unraid-os/using-unraid-to/run-docker-containers/managing-and-customizing-containers/).
