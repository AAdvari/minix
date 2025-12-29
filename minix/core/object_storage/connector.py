import boto3
from botocore.exceptions import ClientError
from typing import Optional, BinaryIO, Dict, Any
import logging
from .config import ObjectStorageConfig

logger = logging.getLogger(__name__)


class ObjectStorageConnector:
    """Connector for object storage operations."""

    def __init__(self, config: ObjectStorageConfig):
        self.config = config
        self.client = self._create_client()
        self.bucket_name = config.bucket_name

    def _create_client(self) -> boto3.client:
        """Create and return an S3 client."""
        return boto3.client(
            's3',
            endpoint_url=self.config.endpoint_url,
            aws_access_key_id=self.config.access_key,
            aws_secret_access_key=self.config.secret_key,
            use_ssl=self.config.use_ssl,
            verify=self.config.verify_ssl
        )

    async def upload_file(self, file_obj: BinaryIO, object_key: str, metadata: Optional[Dict[str, str]] = None) -> bool:
        """Upload a file to object storage."""
        try:
            extra_args = {'Metadata': metadata} if metadata else {}
            self.client.upload_fileobj(
                file_obj,
                self.bucket_name,
                object_key,
                ExtraArgs=extra_args
            )
            return True
        except ClientError as e:
            logger.error(f"Error uploading file {object_key}: {str(e)}")
            return False

    async def download_file(self, object_key: str, file_obj: BinaryIO) -> bool:
        """Download a file from object storage."""
        try:
            self.client.download_fileobj(
                self.bucket_name,
                object_key,
                file_obj
            )
            return True
        except ClientError as e:
            logger.error(f"Error downloading file {object_key}: {str(e)}")
            return False

    async def download_to_dir(self, object_key: str, directory: str) -> bool:
        """Download a file to a specified directory."""
        try:
            file_path = f"{directory}/{object_key}"
            with open(file_path, 'wb') as file_obj:
                return await self.download_file(object_key, file_obj)
        except Exception as e:
            logger.error(f"Error downloading file {object_key} to {directory}: {str(e)}")
            return False

    async def delete_file(self, object_key: str) -> bool:
        """Delete a file from object storage."""
        try:
            self.client.delete_object(
                Bucket=self.bucket_name,
                Key=object_key
            )
            return True
        except ClientError as e:
            logger.error(f"Error deleting file {object_key}: {str(e)}")
            return False

    async def get_file_metadata(self, object_key: str) -> Optional[Dict[str, Any]]:
        """Get metadata for a file."""
        try:
            response = self.client.head_object(
                Bucket=self.bucket_name,
                Key=object_key
            )
            return {
                'content_type': response.get('ContentType'),
                'content_length': response.get('ContentLength'),
                'last_modified': response.get('LastModified'),
                'metadata': response.get('Metadata', {})
            }
        except ClientError as e:
            logger.error(f"Error getting metadata for file {object_key}: {str(e)}")
            return None

    async def list_files(self, prefix: str = "") -> list:
        """List files in the bucket with optional prefix."""
        try:
            response = self.client.list_objects_v2(
                Bucket=self.bucket_name,
                Prefix=prefix
            )
            return [item['Key'] for item in response.get('Contents', [])]
        except ClientError as e:
            logger.error(f"Error listing files with prefix {prefix}: {str(e)}")
            return []

    async def generate_presigned_url(self, object_key: str, expiration: int = 3600) -> Optional[str]:
        """Generate a presigned URL for temporary access to a file."""
        try:
            return self.client.generate_presigned_url(
                'get_object',
                Params={
                    'Bucket': self.bucket_name,
                    'Key': object_key
                },
                ExpiresIn=expiration
            )
        except ClientError as e:
            logger.error(f"Error generating presigned URL for {object_key}: {str(e)}")
            return None