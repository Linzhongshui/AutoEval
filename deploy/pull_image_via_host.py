"""Download official Docker Hub images via host networking, then docker load.

Useful when Desktop daemon proxy fails but the host HTTPS proxy works. No daemon
settings are changed. Verifies compressed and uncompressed layer hashes. Dev only.
"""
import argparse
import gzip
import hashlib
import io
import json
from pathlib import Path
import subprocess
import tarfile
import tempfile
import urllib.parse
import urllib.request


def download_image(image: str, docker: str):
    name, tag = image.rsplit(":", 1)
    repository = name if "/" in name else "library/" + name
    auth_url = "https://auth.docker.io/token?" + urllib.parse.urlencode({
        "service": "registry.docker.io", "scope": f"repository:{repository}:pull"})
    with urllib.request.urlopen(auth_url, timeout=30) as response:
        token = json.load(response)["token"]
    headers = {"Authorization": "Bearer " + token,
               "Accept": ", ".join(["application/vnd.oci.image.index.v1+json",
                 "application/vnd.docker.distribution.manifest.list.v2+json",
                 "application/vnd.oci.image.manifest.v1+json",
                 "application/vnd.docker.distribution.manifest.v2+json"])}
    prefix = f"https://registry-1.docker.io/v2/{repository}/"

    def fetch(path):
        with urllib.request.urlopen(urllib.request.Request(prefix + path, headers=headers), timeout=120) as response:
            return response.read()

    manifest = json.loads(fetch("manifests/" + tag))
    if "manifests" in manifest:
        descriptor = next(d for d in manifest["manifests"]
                          if d.get("platform", {}).get("os") == "linux"
                          and d.get("platform", {}).get("architecture") == "amd64")
        raw = fetch("manifests/" + descriptor["digest"])
        assert "sha256:" + hashlib.sha256(raw).hexdigest() == descriptor["digest"]
        manifest = json.loads(raw)

    def blob(descriptor):
        data = fetch("blobs/" + descriptor["digest"])
        if "sha256:" + hashlib.sha256(data).hexdigest() != descriptor["digest"]:
            raise ValueError("Image blob hash mismatch")
        return data

    config = blob(manifest["config"])
    diff_ids = json.loads(config)["rootfs"]["diff_ids"]
    with tempfile.TemporaryDirectory(prefix="autoeval-image-") as tmp:
        archive = Path(tmp) / "image.tar"
        with tarfile.open(archive, "w") as out:
            def add_bytes(name, data):
                info = tarfile.TarInfo(name); info.size = len(data)
                out.addfile(info, io.BytesIO(data))
            config_name = manifest["config"]["digest"].split(":")[1] + ".json"
            add_bytes(config_name, config)
            layers = []
            for index, descriptor in enumerate(manifest["layers"]):
                compressed = blob(descriptor)
                data = gzip.decompress(compressed) if compressed[:2] == b"\x1f\x8b" else compressed
                if "sha256:" + hashlib.sha256(data).hexdigest() != diff_ids[index]:
                    raise ValueError("Uncompressed image layer hash mismatch")
                path = f"layer-{index}/layer.tar"; add_bytes(path, data); layers.append(path)
                print(f"{image}: verified layer {index + 1}/{len(diff_ids)}", flush=True)
            add_bytes("manifest.json", json.dumps([{"Config": config_name,
                      "RepoTags": [image], "Layers": layers}]).encode())
        subprocess.run([docker, "load", "-i", str(archive)], check=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("image")
    parser.add_argument("--docker", default="docker")
    args = parser.parse_args()
    download_image(args.image, args.docker)
