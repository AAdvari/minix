from minix.core.auth.entities import ApiKeyEntity
from minix.core.auth.repositories import ApiKeyRepository
from minix.core.auth.services import ApiKeyService
from minix.core.registry import Registry
from minix.core.connectors.sql_connector import SqlConnector


def install_auth_module():
    sql_connector = Registry().get(SqlConnector)

    repo = ApiKeyRepository(ApiKeyEntity, sql_connector)
    Registry().register(ApiKeyRepository, repo)

    service = ApiKeyService(repo)
    Registry().register(ApiKeyService, service)
