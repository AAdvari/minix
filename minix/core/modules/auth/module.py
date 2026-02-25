from minix.core.module import BusinessModule
from minix.core.modules.auth.entities import ApiKeyEntity
from minix.core.modules.auth.repositories import ApiKeyRepository
from minix.core.modules.auth.services import ApiKeyService

AuthModule = (
    BusinessModule('auth_module')
        .add_entity(ApiKeyEntity)
        .add_repository(ApiKeyRepository)
        .add_service(ApiKeyService)
    )


