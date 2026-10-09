from unittest.mock import patch

import pytest
from pydantic import SecretStr

from service import service as service_module


@pytest.mark.asyncio
async def test_refuses_to_start_exposed_without_auth_secret():
    with (
        patch.object(service_module.settings, "AUTH_SECRET", None),
        patch.object(service_module.settings, "HOST", "0.0.0.0"),
        patch.object(service_module, "initialize_database") as init_db,
    ):
        with pytest.raises(RuntimeError, match="AUTH_SECRET is required"):
            async with service_module.lifespan(service_module.app):
                pass
    init_db.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize(("secret", "host"), [(None, "127.0.0.1"), (SecretStr("s"), "0.0.0.0")])
async def test_auth_check_passes_when_local_or_secret_set(secret, host):
    with (
        patch.object(service_module.settings, "AUTH_SECRET", secret),
        patch.object(service_module.settings, "HOST", host),
        patch.object(service_module, "initialize_database", side_effect=RuntimeError("db reached")),
    ):
        with pytest.raises(RuntimeError, match="db reached"):
            async with service_module.lifespan(service_module.app):
                pass
