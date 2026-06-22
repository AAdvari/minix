from minix.core.module import BusinessModule
from minix.core.modules.oidc.entities import OidcUserEntity
from minix.core.modules.oidc.repositories import OidcUserRepository
from minix.core.modules.oidc.services import OidcUserService, OidcDiscovery
from minix.core.modules.oidc.controllers import OidcController

# OIDC single sign-on module. Include alongside the core `auth` module and set
# AUTH_PROVIDER=oidc to authenticate via an external IdP. Registers the OIDC
# user store, the discovery/JWKS helper, and the auth-code login controller.
# Depends on the `auth` module for the shared AuthProvider/AuthContext/UserRole.
OidcModule = (
    BusinessModule('oidc_module')
        .add_entity(OidcUserEntity)
        .add_repository(OidcUserRepository)
        .add_service(OidcUserService)
        .add_helper_service(OidcDiscovery)
        .add_controller(OidcController)
    )
