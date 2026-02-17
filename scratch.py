import sys
import os
import re
import io
import zipfile
import requests
import html
from urllib.parse import urlparse
from packaging.tags import Tag
from packaging.utils import parse_wheel_filename
from packaging.requirements import Requirement
from packaging.version import Version

# Configuration
PYPI_SIMPLE_URL = "https://pypi.org/simple/"
TIMEOUT = 10
MIRROR_ROOT = "./offline_mirror"  # Where to save the files

class RemoteWheelInspector:
    def __init__(self, platform_tag: str, python_version: str, implementation: str = "cp"):
        self.session = requests.Session()
        self.target_tags = self._generate_tags(platform_tag, python_version, implementation)
        self.env_context = {
            "python_version": f"{python_version[0]}.{python_version[1:]}",
            "sys_platform": "linux" if "linux" in platform_tag else "win32" if "win" in platform_tag else "darwin",
            "platform_machine": "x86_64" if "x86_64" in platform_tag or "amd64" in platform_tag else "arm64",
            "implementation_name": "cpython" if implementation == "cp" else "pypy",
        }
        self.visited = set()

    def _generate_tags(self, plat, py_ver, impl):
        tags = []
        tags.append(Tag(f"{impl}{py_ver}", f"{impl}{py_ver}", plat))
        tags.append(Tag(f"{impl}{py_ver}", "abi3", plat))
        tags.append(Tag(f"{impl}{py_ver}", "none", plat))
        tags.append(Tag("py3", "none", "any"))
        tags.append(Tag("py2.py3", "none", "any"))
        return tags

    def _fetch_simple_links(self, package_name):
        url = f"{PYPI_SIMPLE_URL}{package_name}/"
        headers = {"Accept": "application/vnd.pypi.simple.v1+json"}
        try:
            resp = self.session.get(url, headers=headers, timeout=TIMEOUT)
            if resp.status_code == 404:
                return None
            return resp.json().get("files", [])
        except Exception as e:
            print(f"Error fetching {package_name}: {e}")
            return None

    def _get_remote_metadata(self, url):
        # Optimized: Falls back to full download if Range requests are tricky
        # In a robust production script, use the 'remotezip' library here.
        try:
            head = self.session.head(url, allow_redirects=True)
            size = int(head.headers.get('Content-Length', 0))
            
            # Download full wheel into memory (buffer)
            # NOTE: For very large wheels (pytorch), you MUST use 'remotezip' or
            # increase system RAM. This is the simple in-memory approach.
            print(f"  [Metadata] Fetching {url.split('/')[-1]} ({size/1024/1024:.2f} MB)...")
            full_resp = self.session.get(url)
            zip_ref = zipfile.ZipFile(io.BytesIO(full_resp.content))
            
            for name in zip_ref.namelist():
                if name.endswith(".dist-info/METADATA"):
                    return zip_ref.read(name).decode("utf-8")
        except Exception as e:
            print(f"  [Error] Reading metadata from {url}: {e}")
        return None

    def _parse_deps(self, metadata_str):
        deps = []
        for line in metadata_str.splitlines():
            if line.startswith("Requires-Dist:"):
                req_str = line.split(":", 1)[1].strip()
                try:
                    req = Requirement(req_str)
                    if req.marker and not req.marker.evaluate(self.env_context):
                        continue
                    deps.append(req)
                except:
                    continue
        return deps

    def resolve(self, package_name):
        package_name = package_name.lower()
        # Handle "visited" to prevent infinite recursion
        if package_name in self.visited:
            return []
        
        print(f"Inspecting: {package_name}")
        self.visited.add(package_name)
        
        files = self._fetch_simple_links(package_name)
        if not files:
            print(f"  [Warn] Package not found: {package_name}")
            return []

        best_candidate = None
        best_candidate_version = Version("0.0.0")

        for file in files:
            filename = file["filename"]
            if not filename.endswith(".whl"): continue
            
            try:
                _, version, _, file_tags = parse_wheel_filename(filename)
            except: continue

            # Check compatibility
            matched = any(ft in self.target_tags for ft in file_tags)
            
            if matched and version > best_candidate_version:
                best_candidate_version = version
                best_candidate = {"url": file["url"], "filename": filename}

        if not best_candidate:
            print(f"  [Warn] No binary for {package_name} compatible with {self.target_tags[0]}")
            return []

        results = [best_candidate["url"]]

        metadata = self._get_remote_metadata(best_candidate["url"])
        if metadata:
            dependencies = self._parse_deps(metadata)
            for dep in dependencies:
                # We extend results with dependencies
                results.extend(self.resolve(dep.name))
        
        return results

# --- PEP 503 Builder ---

def normalize_name(name):
    """Normalize per PEP 503 (e.g. 'My_Package' -> 'my-package')."""
    return re.sub(r"[-_.]+", "-", name).lower()

def download_and_structure(urls, root_dir):
    """
    Downloads files and arranges them: root_dir/normalized-name/file.whl
    Also generates the index.html
    """
    if not os.path.exists(root_dir):
        os.makedirs(root_dir)

    session = requests.Session()
    # Map normalized_name -> list of filenames
    index_map = {}

    print(f"\n--- Downloading {len(urls)} binaries ---")
    
    for url in urls:
        filename = os.path.basename(urlparse(url).path)
        
        # 1. Parse name to find folder
        try:
            name, _, _, _ = parse_wheel_filename(filename)
            norm_name = normalize_name(name)
        except:
            print(f"Skipping non-compliant filename: {filename}")
            continue

        package_dir = os.path.join(root_dir, norm_name)
        if not os.path.exists(package_dir):
            os.makedirs(package_dir)

        # 2. Download File
        filepath = os.path.join(package_dir, filename)
        if not os.path.exists(filepath):
            print(f"Downloading: {filename} -> {norm_name}/")
            with session.get(url, stream=True) as r:
                r.raise_for_status()
                with open(filepath, 'wb') as f:
                    for chunk in r.iter_content(chunk_size=8192):
                        f.write(chunk)
        else:
            print(f"Cached: {filename}")

        # Add to map for index generation
        if norm_name not in index_map:
            index_map[norm_name] = []
        index_map[norm_name].append(filename)

    # 3. Generate HTML Indices (PEP 503)
    print("\n--- Generating PEP 503 Indices ---")
    
    # Generate /simple/project/index.html
    for norm_name, files in index_map.items():
        package_dir = os.path.join(root_dir, norm_name)
        index_path = os.path.join(package_dir, "index.html")
        
        links = []
        for f in files:
            links.append(f'<a href="{f}">{f}</a><br>')
        
        html_content = f"<html><body><h1>Links for {norm_name}</h1>{''.join(links)}</body></html>"
        
        with open(index_path, "w") as f:
            f.write(html_content)

    # Generate root /simple/index.html (Optional, but nice for browsing)
    root_links = []
    for norm_name in sorted(index_map.keys()):
        root_links.append(f'<a href="{norm_name}/">{norm_name}</a><br>')
    
    root_html = f"<html><body><h1>Simple Index</h1>{''.join(root_links)}</body></html>"
    with open(os.path.join(root_dir, "index.html"), "w") as f:
        f.write(root_html)

    print(f"\nSuccess! Mirror built at: {os.path.abspath(root_dir)}")
    print(f"Usage: pip install --no-index --find-links={os.path.abspath(root_dir)} <package>")

# --- Main Execution ---

if __name__ == "__main__":
    # 1. Setup Inspector
    # Change these to match your TARGET offline environment
    TARGET_PLATFORM = "manylinux_2_17_x86_64" 
    TARGET_PYTHON = "311" # Python 3.11
    
    inspector = RemoteWheelInspector(TARGET_PLATFORM, TARGET_PYTHON)
    
    # 2. Read Wishlist
    # Assume wishlist.txt exists in current dir
    wishlist_file = "wishlist.txt"
    if not os.path.exists(wishlist_file):
        with open(wishlist_file, "w") as f:
            f.write("pandas\nrequests\n") # Default example
    
    with open(wishlist_file, "r") as f:
        # Filter empty lines and comments
        packages = [line.strip() for line in f if line.strip() and not line.startswith("#")]

    print(f"Processing wishlist: {packages}")

    # 3. Collect URLs
    all_urls = []
    for pkg in packages:
        resolved_links = inspector.resolve(pkg)
        if resolved_links:
            all_urls.extend(resolved_links)

    # 4. Deduplicate
    unique_urls = list(set(all_urls))

    # 5. Download and Structure
    download_and_structure(unique_urls, MIRROR_ROOT)
