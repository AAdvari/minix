from minix.core.module import BusinessModule
from minix.core.modules.auth.entities import ApiKeyEntity
from minix.core.modules.auth.repositories import ApiKeyRepository
from minix.core.modules.auth.services import ApiKeyService

AuthModule = (
    BusinessModule('auth_module')
        .add_binding(ApiKeyEntity, ApiKeyRepository, ApiKeyService)
    )


