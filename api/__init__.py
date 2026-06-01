"""
API routes package for CelestiOS Backend
Contains all API endpoint routers
"""

from . import auth
from . import calendar
from . import checkin
from . import recommendations
from . import visualization

__all__ = [
    'auth',
    'calendar',
    'checkin',
    'recommendations',
    'visualization',
]
