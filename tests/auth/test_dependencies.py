import pytest
from unittest.mock import MagicMock, AsyncMock, patch
from fastapi import HTTPException

from minix.core.auth.entities import UserRole
from minix.core.auth.dependencies import (
    AuthContext,
    RoleChecker,
    get_auth_context,
    require_roles,
    protected,
    protected_controller,
    RequireAdmin,
    RequireUser,
    RequireService,
    RequireReadonly,
)
from minix.core.auth.services import ApiKeyService
from minix.core.registry import Registry


class TestAuthContext:
    def test_auth_context_creation(self):
        """Test AuthContext dataclass creation."""
        ctx = AuthContext(user_id="user123", role=UserRole.USER, api_key_id=1)
        
        assert ctx.user_id == "user123"
        assert ctx.role == UserRole.USER
        assert ctx.api_key_id == 1

    def test_has_role_single(self):
        """Test has_role with single role."""
        ctx = AuthContext(user_id="user123", role=UserRole.ADMIN, api_key_id=1)
        
        assert ctx.has_role(UserRole.ADMIN) is True
        assert ctx.has_role(UserRole.USER) is False

    def test_has_role_multiple(self):
        """Test has_role with multiple roles."""
        ctx = AuthContext(user_id="user123", role=UserRole.USER, api_key_id=1)
        
        assert ctx.has_role(UserRole.USER, UserRole.ADMIN) is True
        assert ctx.has_role(UserRole.SERVICE, UserRole.READONLY) is False

    def test_is_admin(self):
        """Test is_admin method."""
        admin_ctx = AuthContext(user_id="admin", role=UserRole.ADMIN, api_key_id=1)
        user_ctx = AuthContext(user_id="user", role=UserRole.USER, api_key_id=2)
        
        assert admin_ctx.is_admin() is True
        assert user_ctx.is_admin() is False


class TestRoleChecker:
    @pytest.mark.asyncio
    async def test_role_checker_allows_valid_role(self, mock_api_key_entity, setup_registry_with_mock_service):
        """Test RoleChecker allows access for valid role."""
        entity = mock_api_key_entity(role=UserRole.ADMIN)
        
        service = Registry().get(ApiKeyService)
        service.validate_key.return_value = entity
        
        checker = RoleChecker([UserRole.ADMIN])
        result = await checker(api_key="test_key")
        
        assert isinstance(result, AuthContext)
        assert result.role == UserRole.ADMIN

    @pytest.mark.asyncio
    async def test_role_checker_denies_invalid_role(self, mock_api_key_entity, setup_registry_with_mock_service):
        """Test RoleChecker denies access for invalid role."""
        entity = mock_api_key_entity(role=UserRole.READONLY)
        
        service = Registry().get(ApiKeyService)
        service.validate_key.return_value = entity
        
        checker = RoleChecker([UserRole.ADMIN])
        
        with pytest.raises(HTTPException) as exc_info:
            await checker(api_key="test_key")
        
        assert exc_info.value.status_code == 403

    @pytest.mark.asyncio
    async def test_role_checker_no_api_key(self, setup_registry_with_mock_service):
        """Test RoleChecker raises 401 when no API key provided."""
        checker = RoleChecker([UserRole.USER])
        
        with pytest.raises(HTTPException) as exc_info:
            await checker(api_key=None)
        
        assert exc_info.value.status_code == 401
        assert "API key required" in exc_info.value.detail

    @pytest.mark.asyncio
    async def test_role_checker_invalid_api_key(self, setup_registry_with_mock_service):
        """Test RoleChecker raises 401 for invalid API key."""
        service = Registry().get(ApiKeyService)
        service.validate_key.return_value = None
        
        checker = RoleChecker([UserRole.USER])
        
        with pytest.raises(HTTPException) as exc_info:
            await checker(api_key="invalid_key")
        
        assert exc_info.value.status_code == 401


class TestGetAuthContext:
    @pytest.mark.asyncio
    async def test_get_auth_context_success(self, mock_api_key_entity, setup_registry_with_mock_service):
        """Test get_auth_context returns AuthContext for valid key."""
        entity = mock_api_key_entity(user_id="user123", role=UserRole.USER)
        
        service = Registry().get(ApiKeyService)
        service.validate_key.return_value = entity
        
        result = await get_auth_context(api_key="valid_key")
        
        assert isinstance(result, AuthContext)
        assert result.user_id == "user123"
        assert result.role == UserRole.USER

    @pytest.mark.asyncio
    async def test_get_auth_context_no_key(self, setup_registry_with_mock_service):
        """Test get_auth_context raises 401 when no key provided."""
        with pytest.raises(HTTPException) as exc_info:
            await get_auth_context(api_key=None)
        
        assert exc_info.value.status_code == 401

    @pytest.mark.asyncio
    async def test_get_auth_context_invalid_key(self, setup_registry_with_mock_service):
        """Test get_auth_context raises 401 for invalid key."""
        service = Registry().get(ApiKeyService)
        service.validate_key.return_value = None
        
        with pytest.raises(HTTPException) as exc_info:
            await get_auth_context(api_key="invalid")
        
        assert exc_info.value.status_code == 401


class TestRequireRolesHelpers:
    def test_require_roles_returns_role_checker(self):
        """Test require_roles returns a RoleChecker instance."""
        checker = require_roles([UserRole.ADMIN, UserRole.USER])
        
        assert isinstance(checker, RoleChecker)
        assert checker.allowed_roles == [UserRole.ADMIN, UserRole.USER]

    def test_require_admin(self):
        """Test RequireAdmin helper."""
        checker = RequireAdmin()
        assert isinstance(checker, RoleChecker)
        assert UserRole.ADMIN in checker.allowed_roles

    def test_require_user(self):
        """Test RequireUser helper."""
        checker = RequireUser()
        assert isinstance(checker, RoleChecker)
        assert UserRole.USER in checker.allowed_roles
        assert UserRole.ADMIN in checker.allowed_roles

    def test_require_service(self):
        """Test RequireService helper."""
        checker = RequireService()
        assert isinstance(checker, RoleChecker)
        assert UserRole.SERVICE in checker.allowed_roles
        assert UserRole.ADMIN in checker.allowed_roles


class TestProtectedDecorator:
    def test_protected_single_role(self):
        """Test @protected decorator with single role."""
        @protected[UserRole.ADMIN]
        def my_endpoint():
            pass
        
        assert hasattr(my_endpoint, '_protected_roles')
        assert my_endpoint._protected_roles == [UserRole.ADMIN]

    def test_protected_multiple_roles(self):
        """Test @protected decorator with multiple roles."""
        @protected[UserRole.ADMIN, UserRole.USER]
        def my_endpoint():
            pass
        
        assert my_endpoint._protected_roles == [UserRole.ADMIN, UserRole.USER]

    def test_protected_preserves_function(self):
        """Test @protected decorator preserves function behavior."""
        @protected[UserRole.USER]
        def my_endpoint(x: int) -> int:
            return x * 2
        
        assert my_endpoint(5) == 10


class TestProtectedControllerDecorator:
    def test_protected_controller_single_role(self):
        """Test @protected_controller decorator with single role."""
        @protected_controller[UserRole.ADMIN]
        class MyController:
            def __init__(self):
                pass
        
        assert hasattr(MyController, '_controller_protected_roles')
        assert MyController._controller_protected_roles == [UserRole.ADMIN]

    def test_protected_controller_multiple_roles(self):
        """Test @protected_controller decorator with multiple roles."""
        @protected_controller[UserRole.ADMIN, UserRole.SERVICE]
        class MyController:
            def __init__(self):
                pass
        
        assert MyController._controller_protected_roles == [UserRole.ADMIN, UserRole.SERVICE]

    def test_protected_controller_instance_has_roles(self):
        """Test that instances of protected controller have _protected_roles."""
        @protected_controller[UserRole.USER]
        class MyController:
            def __init__(self):
                pass
        
        instance = MyController()
        assert hasattr(instance, '_protected_roles')
        assert instance._protected_roles == [UserRole.USER]
