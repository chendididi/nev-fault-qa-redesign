from pathlib import Path
from uuid import uuid4
import boto3
from botocore.exceptions import ClientError
from app.core.config import get_settings


class ObjectStorage:
    def __init__(self) -> None:
        self.settings = get_settings()
        self.client = boto3.client(
            "s3",
            endpoint_url=self.settings.s3_endpoint,
            aws_access_key_id=self.settings.s3_access_key,
            aws_secret_access_key=self.settings.s3_secret_key,
            region_name=self.settings.s3_region,
        )
        self.local_dir = Path("uploads")
        self.local_dir.mkdir(exist_ok=True)

    def ensure_bucket(self) -> None:
        try:
            self.client.head_bucket(Bucket=self.settings.s3_bucket)
        except ClientError:
            self.client.create_bucket(Bucket=self.settings.s3_bucket)

    def put(self, filename: str, content_type: str, data: bytes) -> str:
        key = f"{uuid4()}-{filename}"
        try:
            self.ensure_bucket()
            self.client.put_object(Bucket=self.settings.s3_bucket, Key=key, Body=data, ContentType=content_type)
        except Exception:
            (self.local_dir / key).write_bytes(data)
        return key

    def get(self, key: str) -> bytes:
        local = self.local_dir / key
        if local.exists():
            return local.read_bytes()
        response = self.client.get_object(Bucket=self.settings.s3_bucket, Key=key)
        return response["Body"].read()
