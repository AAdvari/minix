import pytest
from unittest.mock import MagicMock, patch
from datetime import datetime, timedelta

from minix.core.auth.entities import ApiKeyEntity, UserRole
from minix.core.auth.services import ApiKeyService
from minix.core.auth.repositories import ApiKeyRepository


class TestApiKeyService:
    @pytest.fixture
    def service(self, mock_repository):
        """Create ApiKeyService with mock repository."""
        return ApiKeyService(mock_repository)

    def test_get_repository(self, service, mock_repository):
        """Test get_repository returns the repository."""
        assert service.get_repository() is mock_repository

    def test_validate_key_success(self, service, mock_repository, mock_api_key_entity):
        """Test validate_key returns entity for valid key."""
        entity = mock_api_key_entity()
        mock_repository.get_by_key.return_value = entity
        
        result = service.validate_key("valid_key")
        
        assert result is entity
        mock_repository.get_by_key.assert_called_once_with("valid_key")
        mock_repository.update_last_used.assert_called_once_with(entity.id)

    def test_validate_key_not_found(self, service, mock_repository):
        """Test validate_key returns None for invalid key."""
        mock_repository.get_by_key.return_value = None
        
        result = service.validate_key("invalid_key")
        
        assert result is None
        mock_repository.update_last_used.assert_not_called()

    def test_create_key(self, service, mock_repository, mock_api_key_entity):
        """Test create_key delegates to repository."""
        entity = mock_api_key_entity()
        mock_repository.create_key.return_value = (entity, "full_key")
        
        result = service.create_key(
            user_id="user123",
            role=UserRole.ADMIN,
            name="My Key",
            expires_at=datetime(2025, 12, 31),
        )
        
        assert result == (entity, "full_key")
        mock_repository.create_key.assert_called_once_with(
            user_id="user123",
            role=UserRole.ADMIN,
            name="My Key",
            expires_at=datetime(2025, 12, 31),
        )

    def test_create_key_defaults(self, service, mock_repository, mock_api_key_entity):
        """Test create_key with default values."""
        entity = mock_api_key_entity()
        mock_repository.create_key.return_value = (entity, "full_key")
        
        service.create_key(user_id="user123")
        
        mock_repository.create_key.assert_called_once_with(
            user_id="user123",
            role=UserRole.USER,
            name=None,
            expires_at=None,
        )

    def test_revoke_key_success(self, service, mock_repository):
        """Test revoke_key returns True on success."""
        mock_repository.revoke_key.return_value = True
        
        result = service.revoke_key(key_id=1)
        
        assert result is True
        mock_repository.revoke_key.assert_called_once_with(1)

    def test_revoke_key_not_found(self, service, mock_repository):
        """Test revoke_key returns False when key not found."""
        mock_repository.revoke_key.return_value = False
        
        result = service.revoke_key(key_id=999)
        
        assert result is False

    def test_get_user_keys(self, service, mock_repository, mock_api_key_entity):
        """Test get_user_keys returns list of keys."""
        entities = [mock_api_key_entity(id=1), mock_api_key_entity(id=2)]
        mock_repository.get_keys_for_user.return_value = entities
        
        result = service.get_user_keys("user123")
        
        assert result == entities
        mock_repository.get_keys_for_user.assert_called_once_with("user123")

    def test_get_user_keys_empty(self, service, mock_repository):
        """Test get_user_keys returns empty list when no keys."""
        mock_repository.get_keys_for_user.return_value = []
        
        result = service.get_user_keys("user_no_keys")
        
        assert result == []
