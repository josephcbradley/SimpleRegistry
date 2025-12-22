# SimpleRegistry

This repository provides a **simple, offline-capable private Python package index** backed by pre-downloaded wheels and served over HTTP.

It is designed to be:

- **Boring and robust**
- **uv / pip compatible**
- **Offline-friendly**
- **Fail-fast** (wheel-only; no source builds)
- **Low ceremony** (no auth, TLS, or caching)

Users can install packages transparently via `uv` without environment variables or admin access.

---

## How it works (conceptually)

1. A list of package *names* is provided (`package_wishlist.txt`)
2. Wheels are downloaded using `uv run pip download`
   - Python version is pinned (3.12)
   - Only published, binary wheels are allowed
3. The resulting `wheelhouse/` directory is served via a tiny HTTP server
4. uv users point at this index and install packages normally

---

## Requirements (build machine)

Only required for the **initial build**:

- Docker (with access to Docker Hub)
- Python 3.12
- uv
- Network access to PyPI

Runtime machines **do not need internet access**.

---

## Initial setup (one-time)

### 1. Populate the wheelhouse

Edit `package_wishlist.txt` and add package names, one per line.

Download wheels (Python 3.12, Linux and Windows)s:

```bash
chmod +x download_packages.sh
./download_packages
```

## Build

```bash
chmod +x build_wheelserver.sh
./build_wheelserver
```

## Copy

Copy ```wheelserver.tar```, ```wheelhouse``` (optionally compresssed) and ```docker_compose.yml``` to your transfer media.

## Deploy

```bash
docker load -i wheelserver_py312.tar
docker compose up -d --pull=never
```

## Use 

On Windows, the users's ```uv.toml``` in ```%PROGRAMDATA%\uv```:

```toml
[[tool.uv.index]]
url = "http://IP_ADDR/simple"
default = true
```

where ```IP_ADDR``` is the IP address of the index host.

In linux this is ```/etc/uv```.
