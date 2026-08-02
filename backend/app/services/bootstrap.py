from __future__ import annotations

import logging

from app.config import get_settings
from app.services.auth_repository import auth_repository
from app.services.baidu_oauth_repository import baidu_oauth_repository
from app.services.bot_repository import bot_repository

logger = logging.getLogger(__name__)


def bootstrap_auth_and_ownership() -> None:
    """Create bootstrap admin when empty, assign orphan bots, migrate shared Baidu token."""
    settings = get_settings()
    if auth_repository.count_users() == 0:
        email = settings.bootstrap_admin_email.strip().lower()
        password = settings.bootstrap_admin_password
        if email and password:
            auth_repository.create_user(email=email, password=password, role="admin")
            logger.info("Created bootstrap admin user %s", email)
        else:
            logger.warning(
                "Auth user table is empty but BOOTSTRAP_ADMIN_EMAIL/PASSWORD are unset; "
                "register a user via /api/auth/register"
            )

    admin = auth_repository.get_first_admin()
    if admin is None:
        return

    admin_id = str(admin["id"])
    assigned = bot_repository.assign_missing_owners(admin_id)
    if assigned:
        logger.info("Assigned %s orphan bot(s) to admin %s", assigned, admin.get("email"))

    migrated = baidu_oauth_repository.migrate_legacy_shared_token(admin_id)
    if migrated:
        logger.info("Migrated legacy shared Baidu OAuth token to admin %s", admin.get("email"))
