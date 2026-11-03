"""Data source connectors for Deep Research."""

from vortis.connectors._stubs import (
    Attachment,
    BaseConnector,
    Document,
    SyncStatus,
)
from vortis.connectors.store import KnowledgeStore

__all__ = ["Attachment", "BaseConnector", "Document", "KnowledgeStore", "SyncStatus"]

import vortis.connectors.obsidian  # noqa: F401

try:
    import vortis.connectors.gmail  # noqa: F401
except ImportError:
    pass

try:
    import vortis.connectors.gmail_imap  # noqa: F401
except ImportError:
    pass

try:
    import vortis.connectors.gdrive  # noqa: F401
except ImportError:
    pass

try:
    import vortis.connectors.notion  # noqa: F401
except ImportError:
    pass

try:
    import vortis.connectors.granola  # noqa: F401
except ImportError:
    pass

try:
    import vortis.connectors.gcontacts  # noqa: F401
except ImportError:
    pass

try:
    import vortis.connectors.imessage  # noqa: F401
except ImportError:
    pass

try:
    import vortis.connectors.apple_notes  # noqa: F401
except ImportError:
    pass

try:
    import vortis.connectors.apple_music  # noqa: F401
except ImportError:
    pass

try:
    import vortis.connectors.apple_contacts  # noqa: F401
except ImportError:
    pass

try:
    import vortis.connectors.apple_calendar  # noqa: F401
except ImportError:
    pass

try:
    import vortis.connectors.slack_connector  # noqa: F401
except ImportError:
    pass

try:
    import vortis.connectors.outlook  # noqa: F401
except ImportError:
    pass

try:
    import vortis.connectors.imap  # noqa: F401
except ImportError:
    pass

try:
    import vortis.connectors.gcalendar  # noqa: F401
except ImportError:
    pass

try:
    import vortis.connectors.dropbox  # noqa: F401
except ImportError:
    pass

try:
    import vortis.connectors.whatsapp  # noqa: F401
except ImportError:
    pass

try:
    import vortis.connectors.oura  # noqa: F401
except ImportError:
    pass

try:
    import vortis.connectors.apple_health  # noqa: F401
except ImportError:
    pass

try:
    import vortis.connectors.strava  # noqa: F401
except ImportError:
    pass

try:
    import vortis.connectors.spotify  # noqa: F401
except ImportError:
    pass

try:
    import vortis.connectors.google_tasks  # noqa: F401
except ImportError:
    pass

try:
    import vortis.connectors.weather  # noqa: F401
except ImportError:
    pass

try:
    import vortis.connectors.github_notifications  # noqa: F401
except ImportError:
    pass

try:
    import vortis.connectors.hackernews  # noqa: F401
except ImportError:
    pass

try:
    import vortis.connectors.news_rss  # noqa: F401
except ImportError:
    pass
