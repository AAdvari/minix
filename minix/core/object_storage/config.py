from pydantic import BaseModel

class ObjectStorageConfig(BaseModel):
    """Configuration for object storage connection."""
    endpoint_url: str
    access_key: str
    secret_key: str
    bucket_name: str
    use_ssl: bool = True
    verify_ssl: bool = True

