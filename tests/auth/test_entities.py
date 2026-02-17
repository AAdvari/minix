import pytest
from minix.core.auth.entities import ApiKeyEntity, UserRole


class TestUserRole:
    def test_user_role_values(self):
        """Test that UserRole enum has expected values."""
        assert UserRole.ADMIN.value == "admin"
        assert UserRole.USER.value == "user"
        assert UserRole.SERVICE.value == "service"
        assert UserRole.READONLY.value == "readonly"

    def test_user_role_membership(self):
        """Test UserRole enum membership."""
        assert UserRole.ADMIN in UserRole
        assert UserRole.USER in UserRole
        assert UserRole.SERVICE in UserRole
        assert UserRole.READONLY in UserRole


class TestApiKeyEntity:
    def test_generate_key_returns_tuple(self):
        """Test that generate_key returns a tuple of 3 strings."""
        result = ApiKeyEntity.generate_key()
        assert isinstance(result, tuple)
        assert len(result) == 3

    def test_generate_key_format(self):
        """Test the format of generated key components."""
        full_key, prefix, key_hash = ApiKeyEntity.generate_key()
        
        assert full_key.startswith("minix_")
        assert len(full_key) == 70  # "minix_" (6) + 64 hex chars
        assert prefix == full_key[:12]
        assert len(key_hash) == 64  # SHA256 hex digest

    def test_generate_key_uniqueness(self):
        """Test that generated keys are unique."""
        keys = [ApiKeyEntity.generate_key() for _ in range(10)]
        full_keys = [k[0] for k in keys]
        hashes = [k[2] for k in keys]
        
        assert len(set(full_keys)) == 10
        assert len(set(hashes)) == 10

    def test_generate_key_hash_consistency(self):
        """Test that the hash is consistent with the full key."""
        import hashlib
        full_key, prefix, key_hash = ApiKeyEntity.generate_key()
        
        expected_hash = hashlib.sha256(full_key.encode()).hexdigest()
        assert key_hash == expected_hash
