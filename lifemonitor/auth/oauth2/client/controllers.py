from __future__ import annotations

import logging

from authlib.integrations.base_client import RemoteApp
from loginpass import create_flask_blueprint

from lifemonitor.auth.oauth2.client.providers.github import GitHub
from lifemonitor.auth.oauth2.client.providers.seek import Seek
from .models import OAuthUserProfile
from .services import oauth2_registry

# Config a module level logger
logger = logging.getLogger(__name__)

#: you can customize this part
backends = [GitHub, Seek]


def create_blueprint(handle_authorize):
    def _handle_authorize(provider: RemoteApp, token, user_info):
        return handle_authorize(provider, token, OAuthUserProfile.from_dict(user_info))

    return create_flask_blueprint(backends, oauth2_registry, _handle_authorize)
