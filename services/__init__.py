"""
Services package for CelestiOS Backend
Contains email, OpenAI, and other service integrations
"""

# Import service modules to make them available from services package
from . import email_sendgrid
from . import email_service
from . import openai_service

# Export modules so they can be imported as:
# from services import email_sendgrid
__all__ = [
    'email_sendgrid',
    'email_service',
    'openai_service',
]
