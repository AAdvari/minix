from dataclasses import dataclass
from typing import List
from fastapi import HTTPException, Security, Depends, Request
from fastapi.security import APIKeyHeader
from minix.core.auth.entities import UserRole
from minix.core.auth.services import ApiKeyService
from minix.core.registry import Registry

API_KEY_HEADER = APIKeyHeader(name="X-API-Key", scheme_name="ApiKeyAuth", auto_error=False)


@dataclass
class AuthContext:
    user_id: str
    role: UserRole
    api_key_id: int

    def has_role(self, *roles: UserRole) -> bool:
        return self.role in roles

    def is_admin(self) -> bool:
        return self.role == UserRole.ADMIN


async def get_auth_context(api_key: str = Security(API_KEY_HEADER)) -> AuthContext:
    if not api_key:
        raise HTTPException(status_code=401, detail="API key required")

    service = Registry().get(ApiKeyService)
    key_entity = service.validate_key(api_key)

    if not key_entity:
        raise HTTPException(status_code=401, detail=f"Invalid or expired API key {api_key}")

    return AuthContext(
        user_id=key_entity.user_id,
        role=key_entity.role,
        api_key_id=key_entity.id,
    )


class RoleChecker:
    def __init__(self, allowed_roles: List[UserRole]):
        self.allowed_roles = allowed_roles

    async def __call__(self, api_key: str = Security(API_KEY_HEADER)) -> AuthContext:
        if not api_key:
            raise HTTPException(status_code=401, detail="API key required")

        service = Registry().get(ApiKeyService)
        key_entity = service.validate_key(api_key)

        if not key_entity:
            raise HTTPException(status_code=401, detail=f"Invalid or expired API key api_key ")

        if key_entity.role not in self.allowed_roles:
            raise HTTPException(
                status_code=403,
                detail=f"Access denied."
            )

        return AuthContext(
            user_id=key_entity.user_id,
            role=key_entity.role,
            api_key_id=key_entity.id,
        )


def require_roles(allowed_roles: List[UserRole]):
    return RoleChecker(allowed_roles)


RequireAdmin = lambda: require_roles([UserRole.ADMIN])
RequireUser = lambda: require_roles([UserRole.USER, UserRole.ADMIN])
RequireService = lambda: require_roles([UserRole.SERVICE, UserRole.ADMIN])
RequireReadonly = lambda: require_roles([UserRole.READONLY, UserRole.USER, UserRole.SERVICE, UserRole.ADMIN])

import inspect
from functools import wraps


class ProtectedDecorator:
    def __getitem__(self, roles):
        if isinstance(roles, UserRole):
            roles = [roles]
        else:
            roles = list(roles)

        def decorator(func):
            func._protected_roles = roles
            return func

        return decorator


protected = ProtectedDecorator()


class ProtectedControllerDecorator:
    def __getitem__(self, roles):
        if isinstance(roles, UserRole):
            roles = [roles]
        else:
            roles = list(roles)

        def class_decorator(cls):
            original_init = cls.__init__

            @wraps(original_init)
            def new_init(self, *args, **kwargs):
                original_init(self, *args, **kwargs)
                self._protected_roles = roles

            cls.__init__ = new_init
            cls._controller_protected_roles = roles
            return cls

        return class_decorator


protected_controller = ProtectedControllerDecorator()
