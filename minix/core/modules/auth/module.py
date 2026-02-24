from minix.core.module import Module, BusinessModule
from minix.core.modules.auth.entities import ApiKeyEntity
from minix.core.modules.auth.repositories import ApiKeyRepository
from minix.core.modules.auth.services import ApiKeyService
from minix.core.registry import Registry
from minix.core.connectors.sql_connector import SqlConnector

AuthModule = (
    BusinessModule('auth_module')
        .add_entity(ApiKeyEntity)
        .add_repository(ApiKeyRepository)
        .add_service(ApiKeyService)
    )


