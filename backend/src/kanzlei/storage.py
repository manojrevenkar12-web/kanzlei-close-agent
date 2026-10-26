"""Original documents, stored once and never overwritten (content-addressed by SHA-256).

GoBD: an e-invoice is kept in the format it arrived in (the XML), for the retention period
(8 years for Buchungsbelege since 2025). In production the bucket enforces that with S3 Object
Lock in compliance mode (deploy/terraform/storage.tf); locally a write-once directory stands in.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any, Protocol
from urllib.parse import urlsplit


class Store(Protocol):
    def put(self, key: str, data: bytes, media_type: str) -> None: ...

    def get(self, key: str) -> bytes: ...


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def key_for(client_id: str, digest: str, filename: str) -> str:
    ext = Path(filename).suffix.lower()[:8]
    return f"{client_id}/{digest[:2]}/{digest}{ext}"


class LocalStore:
    def __init__(self, root: Path) -> None:
        self.root = root

    def put(self, key: str, data: bytes, media_type: str) -> None:
        path = self.root / key
        if path.exists():
            if sha256(path.read_bytes()) != sha256(data):
                raise ValueError(f"{key} exists with other content; documents are write-once")
            return
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".part")
        tmp.write_bytes(data)
        tmp.replace(path)

    def get(self, key: str) -> bytes:
        return (self.root / key).read_bytes()


class S3Store:
    def __init__(self, bucket: str, prefix: str = "") -> None:
        import boto3  # optional dependency: pip install .[s3]

        self.bucket = bucket
        self.prefix = prefix.strip("/")
        self.client: Any = boto3.client("s3")

    def _k(self, key: str) -> str:
        return f"{self.prefix}/{key}" if self.prefix else key

    def put(self, key: str, data: bytes, media_type: str) -> None:
        self.client.put_object(
            Bucket=self.bucket,
            Key=self._k(key),
            Body=data,
            ContentType=media_type,
            ChecksumAlgorithm="SHA256",
            IfNoneMatch="*",
        )

    def get(self, key: str) -> bytes:
        body: bytes = self.client.get_object(Bucket=self.bucket, Key=self._k(key))["Body"].read()
        return body


def store_from_url(url: str) -> Store:
    u = urlsplit(url)
    if u.scheme == "file":
        return LocalStore(Path(u.path))
    if u.scheme == "s3":
        return S3Store(u.netloc, u.path)
    raise ValueError(f"unsupported storage url {url}")
