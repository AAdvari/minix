import pytest
from unittest.mock import MagicMock, patch
from datetime import datetime, timedelta

from minix.core.registry import Registry
from minix.core.auth.entities import ApiKeyEntity, UserRole
from minix.core.auth.services import ApiKeyService
from minix.core.auth.repositories import ApiKeyRepository


@pytest.fixture(autouse=True)
def reset_registry():
    """Reset the Registry singleton before each test."""
    Registry._instances = {}
    yield
    Registry._instances = {}


@pytest.fixture
def mock_api_key_entity():
    """Create a mock ApiKeyEntity for testing."""
    def _create(
        id: int = 1,
        user_id: str = "test_user",
        role: UserRole = UserRole.USER,
        is_active: bool = True,
        expires_at: datetime = None,
    ):
        entity = MagicMock(spec=ApiKeyEntity)
        entity.id = id
        entity.user_id = user_id
        entity.role = role
        entity.is_active = is_active
        entity.expires_at = expires_at
        entity.key_hash = "test_hash"
        entity.key_prefix = "minix_test_"
        entity.name = "Test Key"
        entity.last_used_at = None
        return entity
    return _create


@pytest.fixture
def mock_repository():
    """Create a mock ApiKeyRepository."""
    return MagicMock(spec=ApiKeyRepository)


@pytest.fixture
def mock_api_key_service(mock_repository):
    """Create a mock ApiKeyService with a mock repository."""
    service = MagicMock(spec=ApiKeyService)
    service.repository = mock_repository
    return service


@pytest.fixture
def setup_registry_with_mock_service(mock_api_key_service):
    """Set up Registry with a mock ApiKeyService."""
    registry = Registry()
    registry.register(ApiKeyService, mock_api_key_service)
    return registry
