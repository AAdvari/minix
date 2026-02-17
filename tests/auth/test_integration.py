import pytest
import hashlib
from unittest.mock import MagicMock, patch
from fastapi import FastAPI
from fastapi.testclient import TestClient

from minix.core.auth.entities import ApiKeyEntity, UserRole
from minix.core.auth.dependencies import protected, protected_controller
from minix.core.auth.services import ApiKeyService
from minix.core.controller import Controller
from minix.core.registry import Registry


class TestProtectedControllerIntegration:
    """Integration tests for @protected_controller decorator with real HTTP requests."""

    @pytest.fixture
    def admin_api_key(self):
        """Generate a valid admin API key."""
        return "minix_admin_key_12345678901234567890123456789012345678901234"

    @pytest.fixture
    def user_api_key(self):
        """Generate a valid user API key."""
        return "minix_user_key_123456789012345678901234567890123456789012345"

    @pytest.fixture
    def service_api_key(self):
        """Generate a valid service API key."""
        return "minix_service_key_1234567890123456789012345678901234567890123"

    @pytest.fixture
    def mock_key_entity_factory(self):
        """Factory to create mock ApiKeyEntity objects."""
        def _create(api_key: str, role: UserRole, user_id: str = "test_user"):
            entity = MagicMock(spec=ApiKeyEntity)
            entity.id = 1
            entity.user_id = user_id
            entity.role = role
            entity.is_active = True
            entity.expires_at = None
            entity.key_hash = hashlib.sha256(api_key.encode()).hexdigest()
            entity.key_prefix = api_key[:12]
            return entity
        return _create

    @pytest.fixture
    def setup_mock_service(self, mock_key_entity_factory, admin_api_key, user_api_key, service_api_key):
        """Set up mock ApiKeyService that validates specific keys."""
        mock_service = MagicMock(spec=ApiKeyService)
        
        def validate_key(api_key: str):
            if api_key == admin_api_key:
                return mock_key_entity_factory(api_key, UserRole.ADMIN)
            elif api_key == user_api_key:
                return mock_key_entity_factory(api_key, UserRole.USER)
            elif api_key == service_api_key:
                return mock_key_entity_factory(api_key, UserRole.SERVICE)
            return None
        
        mock_service.validate_key.side_effect = validate_key
        Registry().register(ApiKeyService, mock_service)
        return mock_service

    @pytest.fixture
    def app_with_protected_controller(self, setup_mock_service):
        """Create FastAPI app with a protected controller (ADMIN role)."""
        app = FastAPI()

        @protected_controller[UserRole.ADMIN]
        class AdminController(Controller):
            def get_prefix(self):
                return "/admin"

            def define_routes(self):
                self.router.add_api_route("/dashboard", self.dashboard, methods=["GET"])
                self.router.add_api_route("/users", self.list_users, methods=["GET"])

            def dashboard(self):
                return {"message": "Admin Dashboard"}

            def list_users(self):
                return {"users": ["user1", "user2"]}

        controller = AdminController(tags=["admin"])
        app.include_router(controller.get_router)
        return app

    def test_protected_controller_allows_valid_admin_key(self, app_with_protected_controller, admin_api_key):
        """Test that valid admin API key grants access to protected controller."""
        client = TestClient(app_with_protected_controller)
        
        response = client.get("/admin/dashboard", headers={"X-API-Key": admin_api_key})
        
        assert response.status_code == 200
        assert response.json() == {"message": "Admin Dashboard"}

    def test_protected_controller_allows_access_to_all_routes(self, app_with_protected_controller, admin_api_key):
        """Test that valid key grants access to all routes in protected controller."""
        client = TestClient(app_with_protected_controller)
        
        response1 = client.get("/admin/dashboard", headers={"X-API-Key": admin_api_key})
        response2 = client.get("/admin/users", headers={"X-API-Key": admin_api_key})
        
        assert response1.status_code == 200
        assert response2.status_code == 200

    def test_protected_controller_denies_wrong_role(self, app_with_protected_controller, user_api_key):
        """Test that API key with wrong role is denied access."""
        client = TestClient(app_with_protected_controller)
        
        response = client.get("/admin/dashboard", headers={"X-API-Key": user_api_key})
        
        assert response.status_code == 403
        assert "Access denied" in response.json()["detail"]

    def test_protected_controller_denies_missing_key(self, app_with_protected_controller):
        """Test that missing API key returns 401."""
        client = TestClient(app_with_protected_controller)
        
        response = client.get("/admin/dashboard")
        
        assert response.status_code == 401
        assert "API key required" in response.json()["detail"]

    def test_protected_controller_denies_invalid_key(self, app_with_protected_controller):
        """Test that invalid API key returns 401."""
        client = TestClient(app_with_protected_controller)
        
        response = client.get("/admin/dashboard", headers={"X-API-Key": "invalid_key_12345"})
        
        assert response.status_code == 401
        assert "Invalid" in response.json()["detail"]


class TestProtectedRouteIntegration:
    """Integration tests for @protected decorator on individual routes."""

    @pytest.fixture
    def admin_api_key(self):
        return "minix_admin_key_12345678901234567890123456789012345678901234"

    @pytest.fixture
    def user_api_key(self):
        return "minix_user_key_123456789012345678901234567890123456789012345"

    @pytest.fixture
    def service_api_key(self):
        return "minix_service_key_1234567890123456789012345678901234567890123"

    @pytest.fixture
    def mock_key_entity_factory(self):
        def _create(api_key: str, role: UserRole, user_id: str = "test_user"):
            entity = MagicMock(spec=ApiKeyEntity)
            entity.id = 1
            entity.user_id = user_id
            entity.role = role
            entity.is_active = True
            entity.expires_at = None
            entity.key_hash = hashlib.sha256(api_key.encode()).hexdigest()
            entity.key_prefix = api_key[:12]
            return entity
        return _create

    @pytest.fixture
    def setup_mock_service(self, mock_key_entity_factory, admin_api_key, user_api_key, service_api_key):
        mock_service = MagicMock(spec=ApiKeyService)
        
        def validate_key(api_key: str):
            if api_key == admin_api_key:
                return mock_key_entity_factory(api_key, UserRole.ADMIN)
            elif api_key == user_api_key:
                return mock_key_entity_factory(api_key, UserRole.USER)
            elif api_key == service_api_key:
                return mock_key_entity_factory(api_key, UserRole.SERVICE)
            return None
        
        mock_service.validate_key.side_effect = validate_key
        Registry().register(ApiKeyService, mock_service)
        return mock_service

    @pytest.fixture
    def app_with_protected_routes(self, setup_mock_service):
        """Create FastAPI app with individual protected routes."""
        app = FastAPI()

        class MixedController(Controller):
            def get_prefix(self):
                return "/api"

            def define_routes(self):
                self.router.add_api_route("/public", self.public_endpoint, methods=["GET"])
                self.router.add_api_route("/admin-only", self.admin_only, methods=["GET"])
                self.router.add_api_route("/user-area", self.user_area, methods=["GET"])
                self.router.add_api_route("/service-endpoint", self.service_endpoint, methods=["GET"])

            def public_endpoint(self):
                return {"message": "Public data"}

            @protected[UserRole.ADMIN]
            def admin_only(self):
                return {"message": "Admin only data"}

            @protected[UserRole.USER, UserRole.ADMIN]
            def user_area(self):
                return {"message": "User area data"}

            @protected[UserRole.SERVICE]
            def service_endpoint(self):
                return {"message": "Service data"}

        controller = MixedController(tags=["api"])
        app.include_router(controller.get_router)
        return app

    def test_public_route_accessible_without_key(self, app_with_protected_routes):
        """Test that unprotected route is accessible without API key."""
        client = TestClient(app_with_protected_routes)
        
        response = client.get("/api/public")
        
        assert response.status_code == 200
        assert response.json() == {"message": "Public data"}

    def test_protected_route_allows_correct_role(self, app_with_protected_routes, admin_api_key):
        """Test that protected route allows access with correct role."""
        client = TestClient(app_with_protected_routes)
        
        response = client.get("/api/admin-only", headers={"X-API-Key": admin_api_key})
        
        assert response.status_code == 200
        assert response.json() == {"message": "Admin only data"}

    def test_protected_route_denies_wrong_role(self, app_with_protected_routes, user_api_key):
        """Test that protected route denies access with wrong role."""
        client = TestClient(app_with_protected_routes)
        
        response = client.get("/api/admin-only", headers={"X-API-Key": user_api_key})
        
        assert response.status_code == 403

    def test_protected_route_denies_missing_key(self, app_with_protected_routes):
        """Test that protected route denies access without API key."""
        client = TestClient(app_with_protected_routes)
        
        response = client.get("/api/admin-only")
        
        assert response.status_code == 401

    def test_protected_route_allows_multiple_roles(self, app_with_protected_routes, user_api_key, admin_api_key):
        """Test that route protected with multiple roles allows any of them."""
        client = TestClient(app_with_protected_routes)
        
        response_user = client.get("/api/user-area", headers={"X-API-Key": user_api_key})
        response_admin = client.get("/api/user-area", headers={"X-API-Key": admin_api_key})
        
        assert response_user.status_code == 200
        assert response_admin.status_code == 200

    def test_protected_route_denies_unlisted_role(self, app_with_protected_routes, service_api_key):
        """Test that route denies role not in allowed list."""
        client = TestClient(app_with_protected_routes)
        
        response = client.get("/api/user-area", headers={"X-API-Key": service_api_key})
        
        assert response.status_code == 403


class TestRouteOverridesControllerProtection:
    """Test that route-level @protected overrides controller-level @protected_controller."""

    @pytest.fixture
    def admin_api_key(self):
        return "minix_admin_key_12345678901234567890123456789012345678901234"

    @pytest.fixture
    def user_api_key(self):
        return "minix_user_key_123456789012345678901234567890123456789012345"

    @pytest.fixture
    def service_api_key(self):
        return "minix_service_key_1234567890123456789012345678901234567890123"

    @pytest.fixture
    def mock_key_entity_factory(self):
        def _create(api_key: str, role: UserRole, user_id: str = "test_user"):
            entity = MagicMock(spec=ApiKeyEntity)
            entity.id = 1
            entity.user_id = user_id
            entity.role = role
            entity.is_active = True
            entity.expires_at = None
            entity.key_hash = hashlib.sha256(api_key.encode()).hexdigest()
            entity.key_prefix = api_key[:12]
            return entity
        return _create

    @pytest.fixture
    def setup_mock_service(self, mock_key_entity_factory, admin_api_key, user_api_key, service_api_key):
        mock_service = MagicMock(spec=ApiKeyService)
        
        def validate_key(api_key: str):
            if api_key == admin_api_key:
                return mock_key_entity_factory(api_key, UserRole.ADMIN)
            elif api_key == user_api_key:
                return mock_key_entity_factory(api_key, UserRole.USER)
            elif api_key == service_api_key:
                return mock_key_entity_factory(api_key, UserRole.SERVICE)
            return None
        
        mock_service.validate_key.side_effect = validate_key
        Registry().register(ApiKeyService, mock_service)
        return mock_service

    @pytest.fixture
    def app_with_override(self, setup_mock_service):
        """
        Create FastAPI app where:
        - Controller is protected with Role A (ADMIN)
        - One route is protected with Role B (USER)
        - Route-level should override controller-level
        """
        app = FastAPI()

        @protected_controller[UserRole.ADMIN]
        class AdminControllerWithUserRoute(Controller):
            def get_prefix(self):
                return "/mixed"

            def define_routes(self):
                self.router.add_api_route("/admin-default", self.admin_default, methods=["GET"])
                self.router.add_api_route("/user-override", self.user_override, methods=["GET"])
                self.router.add_api_route("/service-override", self.service_override, methods=["GET"])

            def admin_default(self):
                """This route uses controller-level protection (ADMIN)."""
                return {"message": "Admin default route"}

            @protected[UserRole.USER]
            def user_override(self):
                """This route overrides to USER role."""
                return {"message": "User override route"}

            @protected[UserRole.SERVICE, UserRole.ADMIN]
            def service_override(self):
                """This route overrides to SERVICE or ADMIN role."""
                return {"message": "Service override route"}

        controller = AdminControllerWithUserRoute(tags=["mixed"])
        app.include_router(controller.get_router)
        return app

    def test_controller_default_requires_admin(self, app_with_override, admin_api_key, user_api_key):
        """Test that route without @protected uses controller-level ADMIN protection."""
        client = TestClient(app_with_override)
        
        response_admin = client.get("/mixed/admin-default", headers={"X-API-Key": admin_api_key})
        response_user = client.get("/mixed/admin-default", headers={"X-API-Key": user_api_key})
        
        assert response_admin.status_code == 200
        assert response_admin.json() == {"message": "Admin default route"}
        assert response_user.status_code == 403

    def test_route_override_allows_user_role(self, app_with_override, user_api_key):
        """Test that @protected[USER] on route allows USER role access."""
        client = TestClient(app_with_override)
        
        response = client.get("/mixed/user-override", headers={"X-API-Key": user_api_key})
        
        assert response.status_code == 200
        assert response.json() == {"message": "User override route"}

    def test_route_override_denies_admin_when_user_required(self, app_with_override, admin_api_key):
        """Test that @protected[USER] denies ADMIN (route-level overrides controller)."""
        client = TestClient(app_with_override)
        
        response = client.get("/mixed/user-override", headers={"X-API-Key": admin_api_key})
        
        assert response.status_code == 403

    def test_route_override_with_multiple_roles(self, app_with_override, service_api_key, admin_api_key, user_api_key):
        """Test that @protected[SERVICE, ADMIN] allows both roles."""
        client = TestClient(app_with_override)
        
        response_service = client.get("/mixed/service-override", headers={"X-API-Key": service_api_key})
        response_admin = client.get("/mixed/service-override", headers={"X-API-Key": admin_api_key})
        response_user = client.get("/mixed/service-override", headers={"X-API-Key": user_api_key})
        
        assert response_service.status_code == 200
        assert response_admin.status_code == 200
        assert response_user.status_code == 403

    def test_missing_key_still_returns_401(self, app_with_override):
        """Test that missing API key returns 401 regardless of protection level."""
        client = TestClient(app_with_override)
        
        response1 = client.get("/mixed/admin-default")
        response2 = client.get("/mixed/user-override")
        
        assert response1.status_code == 401
        assert response2.status_code == 401

    def test_invalid_key_still_returns_401(self, app_with_override):
        """Test that invalid API key returns 401 regardless of protection level."""
        client = TestClient(app_with_override)
        
        response1 = client.get("/mixed/admin-default", headers={"X-API-Key": "invalid"})
        response2 = client.get("/mixed/user-override", headers={"X-API-Key": "invalid"})
        
        assert response1.status_code == 401
        assert response2.status_code == 401
