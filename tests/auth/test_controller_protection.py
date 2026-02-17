import pytest
from unittest.mock import MagicMock, patch
from fastapi import Depends

from minix.core.auth.entities import UserRole
from minix.core.auth.dependencies import protected, protected_controller, RoleChecker
from minix.core.controller import Controller


class TestControllerProtection:
    """Test Controller class protection features."""

    def test_controller_get_protection_dependencies_no_protection(self):
        """Test _get_protection_dependencies returns empty list when no protection."""
        class UnprotectedController(Controller):
            def get_prefix(self):
                return "/unprotected"
            
            def define_routes(self):
                pass
        
        controller = UnprotectedController()
        
        def my_endpoint():
            pass
        
        deps = controller._get_protection_dependencies(my_endpoint)
        assert deps == []

    def test_controller_get_protection_dependencies_route_level(self):
        """Test _get_protection_dependencies returns route-level protection."""
        class MyController(Controller):
            def get_prefix(self):
                return "/test"
            
            def define_routes(self):
                pass
        
        controller = MyController()
        
        @protected[UserRole.ADMIN]
        def protected_endpoint():
            pass
        
        deps = controller._get_protection_dependencies(protected_endpoint)
        assert len(deps) == 1

    def test_controller_get_protection_dependencies_controller_level(self):
        """Test _get_protection_dependencies returns controller-level protection."""
        @protected_controller[UserRole.SERVICE]
        class ProtectedController(Controller):
            def get_prefix(self):
                return "/protected"
            
            def define_routes(self):
                pass
        
        controller = ProtectedController()
        
        def undecorated_endpoint():
            pass
        
        deps = controller._get_protection_dependencies(undecorated_endpoint)
        assert len(deps) == 1

    def test_controller_route_protection_overrides_controller(self):
        """Test route-level protection takes precedence over controller-level."""
        @protected_controller[UserRole.USER]
        class MyController(Controller):
            def get_prefix(self):
                return "/test"
            
            def define_routes(self):
                pass
        
        controller = MyController()
        
        @protected[UserRole.ADMIN]
        def admin_only_endpoint():
            pass
        
        deps = controller._get_protection_dependencies(admin_only_endpoint)
        assert len(deps) == 1

    def test_controller_add_api_route_applies_protection(self):
        """Test add_api_route applies protection dependencies."""
        @protected_controller[UserRole.USER]
        class MyController(Controller):
            def get_prefix(self):
                return "/test"
            
            def define_routes(self):
                pass
        
        controller = MyController()
        
        def my_endpoint():
            return {"message": "hello"}
        
        controller.add_api_route("/hello", my_endpoint, methods=["GET"])
        
        routes = controller._actual_router.routes
        assert len(routes) == 1
        assert len(routes[0].dependencies) == 1

    def test_controller_add_api_route_preserves_existing_deps(self):
        """Test add_api_route preserves existing dependencies."""
        class MyController(Controller):
            def get_prefix(self):
                return "/test"
            
            def define_routes(self):
                pass
        
        controller = MyController()
        
        def custom_dep():
            return "custom"
        
        @protected[UserRole.ADMIN]
        def my_endpoint():
            return {"message": "hello"}
        
        controller.add_api_route(
            "/hello", 
            my_endpoint, 
            methods=["GET"],
            dependencies=[Depends(custom_dep)]
        )
        
        routes = controller._actual_router.routes
        assert len(routes) == 1
        assert len(routes[0].dependencies) == 2

    def test_controller_router_property(self):
        """Test get_router property returns the actual router."""
        class MyController(Controller):
            def get_prefix(self):
                return "/test"
            
            def define_routes(self):
                pass
        
        controller = MyController()
        assert controller.get_router is controller._actual_router

    def test_controller_prefix_applied(self):
        """Test controller prefix is applied to router."""
        class MyController(Controller):
            def get_prefix(self):
                return "/api/v1"
            
            def define_routes(self):
                pass
        
        controller = MyController()
        assert controller._actual_router.prefix == "/api/v1"

    def test_controller_tags_applied(self):
        """Test controller tags are applied to router."""
        class MyController(Controller):
            def get_prefix(self):
                return "/test"
            
            def define_routes(self):
                pass
        
        controller = MyController(tags=["users", "auth"])
        assert controller._actual_router.tags == ["users", "auth"]
