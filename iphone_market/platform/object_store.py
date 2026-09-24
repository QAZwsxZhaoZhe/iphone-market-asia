from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from .settings import PlatformSettings, ensure_storage_dirs


@dataclass(frozen=True)
class StoredObject:
    uri: str
    sha256: str
    size_bytes: int
    content_type: str


class ObjectStore(Protocol):
    def put_json(self, key: str, payload: Any) -> StoredObject:
        ...

    def delete(self, uri: str) -> None:
        ...


class LocalObjectStore:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)

    def put_json(self, key: str, payload: Any) -> StoredObject:
        body = json.dumps(
            payload,
            ensure_ascii=False,
            separators=(",", ":"),
            default=str,
        ).encode("utf-8")
        path = self.root / key
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(body)
        return StoredObject(
            uri=f"file://{path.resolve().as_posix()}",
            sha256=hashlib.sha256(body).hexdigest(),
            size_bytes=len(body),
            content_type="application/json",
        )

    def delete(self, uri: str) -> None:
        if not uri.startswith("file://"):
            return
        path = Path(uri[7:])
        if path.is_file():
            path.unlink()


class S3ObjectStore:
    def __init__(
        self,
        *,
        bucket: str,
        endpoint_url: str = "",
        access_key: str = "",
        secret_key: str = "",
        server_side_encryption: str = "AES256",
    ) -> None:
        if not bucket:
            raise ValueError("OBJECT_STORE_BUCKET 未配置")
        try:
            import boto3
        except ImportError as exc:
            raise RuntimeError("使用 S3 存储需要安装 boto3") from exc

        kwargs: dict[str, Any] = {}
        if endpoint_url:
            kwargs["endpoint_url"] = endpoint_url
        if access_key:
            kwargs["aws_access_key_id"] = access_key
            kwargs["aws_secret_access_key"] = secret_key
        self.bucket = bucket
        self.server_side_encryption = server_side_encryption
        self.client = boto3.client("s3", **kwargs)

    def put_json(self, key: str, payload: Any) -> StoredObject:
        body = json.dumps(
            payload,
            ensure_ascii=False,
            separators=(",", ":"),
            default=str,
        ).encode("utf-8")
        put_options: dict[str, Any] = {
            "Bucket": self.bucket,
            "Key": key,
            "Body": body,
            "ContentType": "application/json",
        }
        if self.server_side_encryption:
            put_options["ServerSideEncryption"] = self.server_side_encryption
        self.client.put_object(
            **put_options,
        )
        return StoredObject(
            uri=f"s3://{self.bucket}/{key}",
            sha256=hashlib.sha256(body).hexdigest(),
            size_bytes=len(body),
            content_type="application/json",
        )

    def delete(self, uri: str) -> None:
        prefix = f"s3://{self.bucket}/"
        if not uri.startswith(prefix):
            return
        self.client.delete_object(Bucket=self.bucket, Key=uri[len(prefix) :])


def get_object_store(settings: PlatformSettings) -> ObjectStore:
    ensure_storage_dirs(settings)
    if settings.object_store_backend == "s3":
        return S3ObjectStore(
            bucket=settings.object_store_bucket,
            endpoint_url=settings.object_store_endpoint_url,
            access_key=settings.object_store_access_key,
            secret_key=settings.object_store_secret_key,
            server_side_encryption=settings.object_store_sse,
        )
    return LocalObjectStore(Path(settings.object_store_local_dir))
