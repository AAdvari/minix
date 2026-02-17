from abc import abstractmethod
from typing import List, Callable
from fastapi import APIRouter, Depends


class Controller:
    _controller_protected_roles: List = None

    def __init__(self, tags: List[str] = None):
        self._actual_router = APIRouter(
            prefix=self.get_prefix(), 
            tags=tags
        )
        self.router = self
        self.define_routes()

    @property
    def get_router(self):
        return self._actual_router

    def _get_protection_dependencies(self, endpoint: Callable) -> List:
        """Get protection dependencies for a route.
        
        Route-level protection (@protected) takes precedence over controller-level.
        """
        func = getattr(endpoint, '__func__', endpoint)
        route_roles = getattr(func, '_protected_roles', None)
        
        if route_roles:
            from minix.core.auth.dependencies import RoleChecker
            return [Depends(RoleChecker(route_roles))]
        
        controller_roles = getattr(self.__class__, '_controller_protected_roles', None)
        if controller_roles:
            from minix.core.auth.dependencies import RoleChecker
            return [Depends(RoleChecker(controller_roles))]
        
        return []

    def add_api_route(self, path: str, endpoint: Callable, **kwargs):
        """Add a route with automatic protection applied."""
        protection_deps = self._get_protection_dependencies(endpoint)
        existing_deps = list(kwargs.get('dependencies', []))
        kwargs['dependencies'] = existing_deps + protection_deps
        self._actual_router.add_api_route(path, endpoint, **kwargs)

    @abstractmethod
    def get_prefix(self):
        """
        Returns the prefix for the controller's routes.
        This method should be implemented by subclasses.
        """
        raise NotImplementedError("Subclasses must implement this method.")

    @abstractmethod
    def define_routes(self):
        """
        Defines the routes for the controller.
        This method should be implemented by subclasses.
        """
        raise NotImplementedError("Subclasses must implement this method.")