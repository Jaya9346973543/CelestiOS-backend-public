"""
SendGrid Email Service for CelestiOS
Handles sending transactional emails via SendGrid API
"""

from sendgrid import SendGridAPIClient
from sendgrid.helpers.mail import Mail, Email, To, Content
from core.config import settings
import logging

logger = logging.getLogger(__name__)


def send_password_reset_email(to_email: str, reset_token: str) -> bool:
    """
    Send password reset email with reset link.

    Args:
        to_email: Recipient email address
        reset_token: Password reset token

    Returns:
        True if email sent successfully, False otherwise
    """
    if not settings.ENABLE_EMAIL_SENDING:
        logger.info(f"[Email Disabled] Skipping password reset email to {to_email}")
        return True  # Return True to not break flows

    if not settings.SENDGRID_API_KEY:
        logger.warning("SendGrid API key not configured. Reset token logged to console instead.")
        reset_link = f"{settings.FRONTEND_URL}/reset-password?token={reset_token}"
        logger.info(f"[Password Reset] Reset link for {to_email}: {reset_link}")
        print(f"\n{'='*60}")
        print(f"PASSWORD RESET REQUEST")
        print(f"{'='*60}")
        print(f"Email: {to_email}")
        print(f"Reset Link: {reset_link}")
        print(f"{'='*60}\n")
        return False

    try:
        # Build reset link
        reset_link = f"{settings.FRONTEND_URL}/reset-password?token={reset_token}"

        # Create email message
        from_email = Email(settings.SENDGRID_FROM_EMAIL, settings.SENDGRID_FROM_NAME)
        to_email_obj = To(to_email)
        subject = "Reset your Celesti password"

        # HTML content
        html_content = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <style>
                body {{
                    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Arial, sans-serif;
                    line-height: 1.6;
                    color: #1f2937;
                    max-width: 600px;
                    margin: 0 auto;
                    padding: 20px;
                }}
                .header {{
                    text-align: center;
                    padding: 30px 0;
                    border-bottom: 2px solid #f3f4f6;
                }}
                .logo {{
                    font-size: 24px;
                    font-weight: 600;
                    color: #111827;
                }}
                .content {{
                    padding: 40px 20px;
                }}
                .button {{
                    display: inline-block;
                    background-color: #111827;
                    color: white;
                    padding: 14px 28px;
                    text-decoration: none;
                    border-radius: 8px;
                    font-weight: 600;
                    margin: 20px 0;
                }}
                .footer {{
                    text-align: center;
                    padding: 20px;
                    color: #6b7280;
                    font-size: 14px;
                    border-top: 1px solid #f3f4f6;
                }}
                .security-note {{
                    background-color: #f3f4f6;
                    padding: 15px;
                    border-radius: 8px;
                    margin-top: 20px;
                    font-size: 14px;
                    color: #6b7280;
                }}
            </style>
        </head>
        <body>
            <div class="header">
                <div class="logo">celesti</div>
            </div>
            <div class="content">
                <h2>Reset your password</h2>
                <p>We received a request to reset your password for your Celesti account.</p>
                <p>Click the button below to choose a new password:</p>
                <a href="{reset_link}" class="button">Reset Password</a>
                <p>Or copy and paste this link into your browser:</p>
                <p style="color: #6b7280; font-size: 14px; word-break: break-all;">{reset_link}</p>
                <div class="security-note">
                    <strong>Security note:</strong> This link will expire in 1 hour. If you didn't request a password reset, you can safely ignore this email.
                </div>
            </div>
            <div class="footer">
                <p>&copy; 2026 celesti. All rights reserved.</p>
                <p>This is an automated message, please do not reply.</p>
            </div>
        </body>
        </html>
        """

        # Plain text fallback
        plain_text_content = f"""
        Reset your password

        We received a request to reset your password for your Celesti account.

        Click the link below to reset your password:
        {reset_link}

        This link will expire in 1 hour.

        If you didn't request a password reset, you can safely ignore this email.

        ---
        celesti - Your intelligent daily companion
        This is an automated message, please do not reply.
        """

        message = Mail(
            from_email=from_email,
            to_emails=to_email_obj,
            subject=subject,
            plain_text_content=Content("text/plain", plain_text_content),
            html_content=Content("text/html", html_content)
        )

        # Send email
        sg = SendGridAPIClient(settings.SENDGRID_API_KEY)
        response = sg.send(message)

        logger.info(f"Password reset email sent to {to_email}. Status: {response.status_code}")
        return response.status_code == 202

    except Exception as e:
        logger.error(f"Failed to send password reset email to {to_email}: {e}")
        return False


def send_daily_insights_email(
    to_email: str,
    name: str,
    meeting_count: int,
    readiness_score: int = None,
    user_id: str = None,
    email_token: str = None,
    unsubscribe_token: str = None
) -> bool:
    """
    Send energy-aware daily check-in email (simple, actionable).

    Args:
        to_email: Recipient email address
        name: User's name
        meeting_count: Number of meetings scheduled today
        readiness_score: Health readiness score 0-100 (from Oura/Fitbit), optional
        user_id: User ID (for logging)
        email_token: Optional one-time authentication token for dashboard access

    Returns:
        True if email sent successfully, False otherwise
    """
    from core.config import settings
    from sendgrid import SendGridAPIClient
    from sendgrid.helpers.mail import Mail, Email, To, Content
    import logging

    logger = logging.getLogger(__name__)

    if not settings.ENABLE_EMAIL_SENDING:
        logger.info(f"[Email Disabled] Skipping daily insights email to {to_email}")
        return True  # Return True to not break flows

    if not settings.SENDGRID_API_KEY:
        logger.warning("SendGrid API key not configured. Email not sent.")
        return False

    try:
        # Use first name only, title case
        first_name = name.split()[0].title() if name else "there"

        # Build email subject
        subject = f"{first_name}, ready to fix your day?"

        # Dashboard link with optional email auth token for one-click access
        if email_token:
            dashboard_url = f"{settings.FRONTEND_URL}/daily_checkin?email_token={email_token}"
        else:
            dashboard_url = f"{settings.FRONTEND_URL}/daily_checkin"

        # Energy-aware message logic
        energy_message = ""
        if readiness_score is not None:
            if readiness_score >= 85:
                energy_message = "You're in a strong state today — protect time for deep work."
            elif readiness_score >= 70:
                if meeting_count == 0:
                    energy_message = "Your energy looks good — great opportunity for focused work."
                elif meeting_count == 1:
                    energy_message = "Your energy looks good — you can get meaningful work done."
                else:
                    energy_message = "Your energy looks good — this is a strong day for focused work."
            elif readiness_score >= 50:
                energy_message = "Your energy is moderate today — pace yourself wisely."
            else:
                if meeting_count == 0:
                    energy_message = "Your energy is low today — this is a good day for lighter tasks."
                else:
                    energy_message = "Your energy is low today — avoid overloading yourself."

        # Meeting count message
        if meeting_count == 0:
            meetings_msg = "Your schedule is clear today — great opportunity to use your energy well."
        elif meeting_count == 1:
            meetings_msg = f"You have 1 meeting today."
        else:
            meetings_msg = f"You have {meeting_count} meetings today."

        # Build final email body
        if energy_message:
            # With health data
            email_body = f"""{meetings_msg}
{energy_message}

Take 30 seconds to plan your day around your energy."""
        else:
            # Without health data
            if meeting_count == 0:
                email_body = f"""{meetings_msg}

Take 30 seconds to plan your day."""
            else:
                email_body = f"""{meetings_msg}

Take 30 seconds to check in and plan your day around your energy."""

        # Email preheader (shows in inbox preview)
        preheader = f"{meeting_count} meeting{'s' if meeting_count != 1 else ''} today" if meeting_count > 0 else "Clear schedule today"

        html_content = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset="UTF-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <style>
                body {{
                    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Arial, sans-serif;
                    line-height: 1.6;
                    color: #1f2937;
                    max-width: 600px;
                    margin: 0 auto;
                    padding: 20px;
                    background-color: #f9fafb;
                }}
                .header {{
                    text-align: center;
                    padding: 30px 0 20px 0;
                    border-bottom: 1px solid #e5e7eb;
                }}
                .logo {{
                    font-size: 28px;
                    font-weight: 700;
                    color: #111827;
                    letter-spacing: -0.5px;
                }}
                .content {{
                    padding: 30px 24px;
                    background: white;
                    border-radius: 16px;
                    margin: 20px 0;
                    box-shadow: 0 4px 6px rgba(0, 0, 0, 0.05);
                }}
                .message {{
                    font-size: 16px;
                    color: #374151;
                    line-height: 1.8;
                    margin: 20px 0;
                    white-space: pre-line;
                }}
                .button {{
                    display: inline-block;
                    background: #111827;
                    color: white !important;
                    padding: 16px 40px;
                    text-decoration: none;
                    border-radius: 12px;
                    font-weight: 600;
                    margin: 24px 0;
                    box-shadow: 0 4px 12px rgba(0, 0, 0, 0.2);
                }}
                .footer {{
                    text-align: center;
                    padding: 20px;
                    color: #6b7280;
                    font-size: 13px;
                }}
                .footer a {{
                    color: #374151;
                    text-decoration: none;
                }}
            </style>
        </head>
        <body>
            <!-- Preheader text (hidden, shows in inbox preview) -->
            <div style="display:none;font-size:1px;color:#fefefe;line-height:1px;max-height:0px;max-width:0px;opacity:0;overflow:hidden;">
                {preheader}
            </div>

            <div class="header">
                <div class="logo">celesti</div>
            </div>
            <div class="content">
                <h2 style="color:#111827;margin:0 0 10px 0;font-size:24px;">Hey {first_name},</h2>

                <div class="message">
{email_body}
                </div>

                <div style="text-align:center;margin-top:32px;">
                    <a href="{dashboard_url}" class="button">👉 Start Daily Check-in</a>
                </div>
            </div>
            <div class="footer">
                <p>&copy; 2026 celesti. Your energy-aware daily companion.</p>
                <p style="font-size:12px;color:#9ca3af;margin-top:12px;">
                    <a href="{settings.FRONTEND_URL}/unsubscribe?action=preferences&user_id={user_id}" style="color:#111827;">Manage preferences</a> ·
                    <a href="{settings.FRONTEND_URL}/unsubscribe?action=unsubscribe&token={unsubscribe_token if unsubscribe_token else ''}" style="color:#111827;">Unsubscribe</a>
                </p>
            </div>
        </body>
        </html>
        """

        # Plain text fallback
        plain_text = f"""
Hey {first_name},

{email_body}

Start Daily Check-in: {dashboard_url}

---
© 2026 celesti - Your energy-aware daily companion
Manage preferences: {settings.FRONTEND_URL}/unsubscribe?action=preferences&user_id={user_id}
Unsubscribe: {settings.FRONTEND_URL}/unsubscribe?action=unsubscribe&token={unsubscribe_token if unsubscribe_token else ''}
        """

        from_email = Email(settings.SENDGRID_FROM_EMAIL, settings.SENDGRID_FROM_NAME)
        to_email_obj = To(to_email)

        message = Mail(
            from_email=from_email,
            to_emails=to_email_obj,
            subject=subject,
            plain_text_content=Content("text/plain", plain_text),
            html_content=Content("text/html", html_content)
        )

        sg = SendGridAPIClient(settings.SENDGRID_API_KEY)
        response = sg.send(message)

        logger.info(f"Daily check-in email sent to {to_email}. Status: {response.status_code}")
        return response.status_code == 202

    except Exception as e:
        logger.error(f"Failed to send daily check-in email to {to_email}: {e}")
        return False

def send_evening_checkin_email(
    to_email: str,
    name: str,
    priority: str,
    user_id: str,
    email_token: str = None,
    unsubscribe_token: str = None
) -> bool:
    """
    Send evening check-in reminder email.

    Args:
        to_email: Recipient email address
        name: User's name
        priority: Today's priority task they set in the morning
        user_id: User ID for dashboard link
        email_token: Optional one-time authentication token for dashboard access

    Returns:
        True if email sent successfully, False otherwise
    """
    if not settings.ENABLE_EMAIL_SENDING:
        logger.info(f"[Email Disabled] Skipping evening check-in email to {to_email}")
        return True  # Return True to not break flows

    if not settings.SENDGRID_API_KEY:
        logger.warning("SendGrid API key not configured. Evening check-in email not sent.")
        return False

    try:
        first_name = name.split()[0].title() if name else "there"

        from_email = Email(settings.SENDGRID_FROM_EMAIL, settings.SENDGRID_FROM_NAME)
        to_email_obj = To(to_email)
        subject = f"{first_name}, how did your day go?"

        # Dashboard link with optional email auth token for one-click access
        if email_token:
            dashboard_url = f"{settings.FRONTEND_URL}/daily_checkin?email_token={email_token}"
        else:
            dashboard_url = f"{settings.FRONTEND_URL}/daily_checkin"

        html_content = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset="UTF-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <style>
                body {{
                    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Arial, sans-serif;
                    line-height: 1.6;
                    color: #1f2937;
                    max-width: 600px;
                    margin: 0 auto;
                    padding: 20px;
                    background-color: #f9fafb;
                }}
                .header {{
                    text-align: center;
                    padding: 30px 0 20px 0;
                    border-bottom: 1px solid #e5e7eb;
                }}
                .logo {{
                    font-size: 28px;
                    font-weight: 700;
                    color: #111827;
                    letter-spacing: -0.5px;
                }}
                .content {{
                    padding: 30px 24px;
                    background: white;
                    border-radius: 16px;
                    margin: 20px 0;
                    box-shadow: 0 4px 6px rgba(0, 0, 0, 0.05);
                }}
                .priority-box {{
                    background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                    color: white;
                    padding: 20px;
                    border-radius: 12px;
                    margin: 20px 0;
                    text-align: center;
                }}
                .button {{
                    display: inline-block;
                    background: #111827;
                    color: white !important;
                    padding: 16px 40px;
                    text-decoration: none;
                    border-radius: 12px;
                    font-weight: 600;
                    margin: 24px 0;
                    box-shadow: 0 4px 12px rgba(0, 0, 0, 0.2);
                }}
                .footer {{
                    text-align: center;
                    padding: 20px;
                    color: #6b7280;
                    font-size: 13px;
                }}
            </style>
        </head>
        <body>
            <div class="header">
                <div class="logo">celesti</div>
            </div>
            <div class="content">
                <h2 style="color:#111827;margin:0 0 10px 0;font-size:24px;">Evening Check-in 🌆</h2>
                <p style="color:#374151;font-size:16px;">Hi {first_name}, let's wrap up your day!</p>

                <div class="priority-box">
                    <p style="margin:0;font-size:14px;opacity:0.9;">Today's priority:</p>
                    <h3 style="margin:8px 0 0 0;font-size:20px;">"{priority}"</h3>
                </div>

                <p style="color:#374151;">Quick question: Did you complete it?</p>
                <p style="color:#6b7280;font-size:14px;">Your answer helps us understand your progress and adapt tomorrow's plan.</p>

                <div style="text-align:center;margin-top:32px;">
                    <a href="{dashboard_url}" class="button">Complete Check-in</a>
                </div>
            </div>
            <div class="footer">
                <p>&copy; 2026 celesti. Your intelligent daily companion.</p>
                <p style="font-size:12px;color:#9ca3af;margin-top:12px;">
                    <a href="{settings.FRONTEND_URL}/unsubscribe?action=preferences&user_id={user_id}" style="color:#111827;">Manage preferences</a> ·
                    <a href="{settings.FRONTEND_URL}/unsubscribe?action=unsubscribe&token={unsubscribe_token if unsubscribe_token else ''}" style="color:#111827;">Unsubscribe</a>
                </p>
            </div>
        </body>
        </html>
        """

        plain_text = f"""
        Evening Check-in

        Hi {first_name}, let's wrap up your day!

        Today's priority: "{priority}"

        Did you complete it? Click below to answer:
        {dashboard_url}

        ---
        © 2026 celesti - Your intelligent daily companion
        Manage preferences: {settings.FRONTEND_URL}/unsubscribe?action=preferences&user_id={user_id}
        Unsubscribe: {settings.FRONTEND_URL}/unsubscribe?action=unsubscribe&token={unsubscribe_token if unsubscribe_token else ''}
        """

        message = Mail(
            from_email=from_email,
            to_emails=to_email_obj,
            subject=subject,
            plain_text_content=Content("text/plain", plain_text),
            html_content=Content("text/html", html_content)
        )

        sg = SendGridAPIClient(settings.SENDGRID_API_KEY)
        response = sg.send(message)

        logger.info(f"Evening check-in email sent to {to_email}. Status: {response.status_code}")
        return response.status_code == 202

    except Exception as e:
        logger.error(f"Failed to send evening check-in email to {to_email}: {e}")
        return False


def send_welcome_email(to_email: str, name: str) -> bool:
    """
    Send welcome email to new users with energy-aware value proposition.

    Args:
        to_email: Recipient email address
        name: User's name

    Returns:
        True if email sent successfully, False otherwise
    """
    if not settings.ENABLE_EMAIL_SENDING:
        logger.info(f"[Email Disabled] Skipping welcome email to {to_email}")
        return True  # Return True to not break flows

    if not settings.SENDGRID_API_KEY:
        logger.warning("SendGrid API key not configured. Welcome email not sent.")
        return False

    try:
        first_name = name.split()[0].title() if name else "there"

        from_email = Email(settings.SENDGRID_FROM_EMAIL, settings.SENDGRID_FROM_NAME)
        to_email_obj = To(to_email)
        subject = f"👉 Welcome to Celesti — let's fix your day"

        html_content = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset="UTF-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <style>
                body {{
                    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Arial, sans-serif;
                    line-height: 1.6;
                    color: #1f2937;
                    max-width: 600px;
                    margin: 0 auto;
                    padding: 20px;
                    background-color: #f9fafb;
                }}
                .header {{
                    text-align: center;
                    padding: 30px 0 20px 0;
                    border-bottom: 1px solid #e5e7eb;
                }}
                .logo {{
                    font-size: 28px;
                    font-weight: 700;
                    color: #111827;
                    letter-spacing: -0.5px;
                }}
                .content {{
                    padding: 30px 24px;
                    background: white;
                    border-radius: 16px;
                    margin: 20px 0;
                    box-shadow: 0 4px 6px rgba(0, 0, 0, 0.05);
                }}
                .message {{
                    font-size: 16px;
                    color: #374151;
                    line-height: 1.8;
                    margin: 20px 0;
                }}
                .highlight {{
                    background-color: #fef3c7;
                    padding: 2px 6px;
                    border-radius: 4px;
                    font-weight: 600;
                }}
                .button {{
                    display: inline-block;
                    background: #111827;
                    color: white !important;
                    padding: 16px 40px;
                    text-decoration: none;
                    border-radius: 12px;
                    font-weight: 600;
                    margin: 24px 0;
                    box-shadow: 0 4px 12px rgba(0, 0, 0, 0.2);
                }}
                .feature-list {{
                    list-style: none;
                    padding: 0;
                    margin: 20px 0;
                }}
                .feature-list li {{
                    padding: 8px 0;
                    padding-left: 24px;
                    position: relative;
                }}
                .feature-list li:before {{
                    content: "•";
                    position: absolute;
                    left: 0;
                    font-weight: bold;
                    font-size: 20px;
                }}
                .footer {{
                    text-align: center;
                    padding: 20px;
                    color: #6b7280;
                    font-size: 13px;
                }}
                .footer a {{
                    color: #374151;
                    text-decoration: none;
                }}
            </style>
        </head>
        <body>
            <div class="header">
                <div class="logo">celesti</div>
            </div>
            <div class="content">
                <h2 style="color:#111827;margin:0 0 20px 0;font-size:24px;">Hey {first_name},</h2>

                <div class="message">
                    <p>Most people plan their day based on <strong>time</strong> — and end up overloaded or unfocused.</p>

                    <p>Celesti helps you fix that by aligning your day with your <span class="highlight">ENERGY</span>.</p>

                    <p><strong>👉 Take 30 seconds to check in and see what your day should actually look like.</strong></p>
                </div>

                <div style="text-align:center;margin:32px 0;">
                    <a href="{settings.FRONTEND_URL}/daily_checkin" class="button">Start Your Check-in</a>
                </div>

                <div class="message">
                    <p style="margin-top:32px;"><strong>Where you can:</strong></p>
                    <ul class="feature-list">
                        <li>Connect your calendar</li>
                        <li>Optionally add Oura, Fitbit, or Apple Health for deeper energy insights</li>
                    </ul>
                </div>

                <p style="margin-top:32px;color:#6b7280;font-size:14px;">— Celesti</p>
            </div>
            <div class="footer">
                <p>&copy; 2026 celesti. Your energy-aware daily companion.</p>
            </div>
        </body>
        </html>
        """

        # Plain text fallback
        plain_text = f"""
        Hey {first_name},

        Most people plan their day based on TIME — and end up overloaded or unfocused.

        Celesti helps you fix that by aligning your day with your ENERGY.

        👉 Take 30 seconds to check in and see what your day should actually look like.

        Start Your Check-in: {settings.FRONTEND_URL}/daily_checkin

        Where you can:
        • Connect your calendar
        • Optionally add Oura, Fitbit, or Apple Health for deeper energy insights

        — Celesti

        ---
        © 2026 celesti - Your energy-aware daily companion
        """

        message = Mail(
            from_email=from_email,
            to_emails=to_email_obj,
            subject=subject,
            plain_text_content=Content("text/plain", plain_text),
            html_content=Content("text/html", html_content)
        )

        sg = SendGridAPIClient(settings.SENDGRID_API_KEY)
        response = sg.send(message)

        logger.info(f"Welcome email sent to {to_email}. Status: {response.status_code}")
        return response.status_code == 202

    except Exception as e:
        logger.error(f"Failed to send welcome email to {to_email}: {e}")
        return False


def send_welcome_email_post_checkin(to_email: str, name: str) -> bool:
    """
    Send welcome email to users who completed their first check-in during signup.
    More generic version that doesn't prompt them to check in.

    Args:
        to_email: Recipient email address
        name: User's name

    Returns:
        True if email sent successfully, False otherwise
    """
    if not settings.ENABLE_EMAIL_SENDING:
        logger.info(f"[Email Disabled] Skipping post-checkin welcome email to {to_email}")
        return True  # Return True to not break flows

    if not settings.SENDGRID_API_KEY:
        logger.warning("SendGrid API key not configured. Welcome email not sent.")
        return False

    try:
        first_name = name.split()[0].title() if name else "there"

        from_email = Email(settings.SENDGRID_FROM_EMAIL, settings.SENDGRID_FROM_NAME)
        to_email_obj = To(to_email)
        subject = f"👉 Nice start, {first_name} — here's your day"

        html_content = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset="UTF-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <style>
                body {{
                    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Arial, sans-serif;
                    line-height: 1.6;
                    color: #1f2937;
                    max-width: 600px;
                    margin: 0 auto;
                    padding: 20px;
                    background-color: #f9fafb;
                }}
                .header {{
                    text-align: center;
                    padding: 30px 0 20px 0;
                    border-bottom: 1px solid #e5e7eb;
                }}
                .logo {{
                    font-size: 28px;
                    font-weight: 700;
                    color: #111827;
                    letter-spacing: -0.5px;
                }}
                .content {{
                    padding: 30px 24px;
                    background: white;
                    border-radius: 16px;
                    margin: 20px 0;
                    box-shadow: 0 4px 6px rgba(0, 0, 0, 0.05);
                }}
                .message {{
                    font-size: 16px;
                    color: #374151;
                    line-height: 1.8;
                    margin: 20px 0;
                }}
                .highlight {{
                    background-color: #fef3c7;
                    padding: 2px 6px;
                    border-radius: 4px;
                    font-weight: 600;
                }}
                .button {{
                    display: inline-block;
                    background: #111827;
                    color: white !important;
                    padding: 16px 40px;
                    text-decoration: none;
                    border-radius: 12px;
                    font-weight: 600;
                    margin: 24px 0;
                    box-shadow: 0 4px 12px rgba(0, 0, 0, 0.2);
                }}
                .feature-list {{
                    list-style: none;
                    padding: 0;
                    margin: 20px 0;
                }}
                .feature-list li {{
                    padding: 8px 0;
                    padding-left: 24px;
                    position: relative;
                }}
                .feature-list li:before {{
                    content: "•";
                    position: absolute;
                    left: 0;
                    font-weight: bold;
                    font-size: 20px;
                }}
                .footer {{
                    text-align: center;
                    padding: 20px;
                    color: #6b7280;
                    font-size: 13px;
                }}
                .footer a {{
                    color: #374151;
                    text-decoration: none;
                }}
            </style>
        </head>
        <body>
            <div class="header">
                <div class="logo">celesti</div>
            </div>
            <div class="content">
                <h2 style="color:#111827;margin:0 0 20px 0;font-size:24px;">Hey {first_name},</h2>

                <div class="message">
                    <p><strong>Nice start — your first check-in is done.</strong></p>

                    <p>Most people plan their day based on time and end up overloaded or unfocused.<br>
                    You've just taken the first step to fixing that.</p>

                    <p>Celesti now understands your energy and priorities — your day can start to adapt around you.</p>

                    <p><strong>To get better results over time:</strong></p>
                    <ul class="feature-list">
                        <li><strong>connect your calendar</strong> → see how meetings affect your energy</li>
                        <li><strong>optionally add Oura, Fitbit, or Apple Health</strong> → improve energy accuracy</li>
                        <li><strong>keep doing daily check-ins</strong> → your system gets smarter every day</li>
                    </ul>

                    <p>We'll remind you to check in daily so your schedule keeps improving.</p>
                </div>

                <div style="text-align:center;margin:32px 0;">
                    <a href="{settings.FRONTEND_URL}/dashboard" class="button">Go to Dashboard</a>
                </div>

                <p style="margin-top:32px;color:#6b7280;font-size:14px;">— Celesti</p>
            </div>
            <div class="footer">
                <p>&copy; 2026 celesti. Your energy-aware daily companion.</p>
            </div>
        </body>
        </html>
        """

        # Plain text fallback
        plain_text = f"""
        Hey {first_name},

        Nice start — your first check-in is done.

        Most people plan their day based on time and end up overloaded or unfocused.
        You've just taken the first step to fixing that.

        Celesti now understands your energy and priorities — your day can start to adapt around you.

        To get better results over time:
        • connect your calendar → see how meetings affect your energy
        • optionally add Oura, Fitbit, or Apple Health → improve energy accuracy
        • keep doing daily check-ins → your system gets smarter every day

        We'll remind you to check in daily so your schedule keeps improving.

        Go to Dashboard: {settings.FRONTEND_URL}/dashboard

        — Celesti

        ---
        © 2026 celesti - Your energy-aware daily companion
        """

        message = Mail(
            from_email=from_email,
            to_emails=to_email_obj,
            subject=subject,
            plain_text_content=Content("text/plain", plain_text),
            html_content=Content("text/html", html_content)
        )

        sg = SendGridAPIClient(settings.SENDGRID_API_KEY)
        response = sg.send(message)

        logger.info(f"Post-checkin welcome email sent to {to_email}. Status: {response.status_code}")
        return response.status_code == 202

    except Exception as e:
        logger.error(f"Failed to send post-checkin welcome email to {to_email}: {e}")
        return False
