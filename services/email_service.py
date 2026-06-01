import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from core.config import settings


def send_morning_email(to_email: str, name: str, event_count: int, user_id: str):
    """Sends a morning wake-up email with a link to check in."""
    checkin_url = f"{settings.FRONTEND_URL.rstrip('/')}/checkin?user_id={user_id}"

    if not settings.SMTP_SERVER or not settings.SMTP_PASSWORD:
        print(f"MOCK EMAIL => Sent to {to_email}. Subject: Good morning, {name}!")
        print(f"MOCK EMAIL BODY => Events: {event_count} | Check-in: {checkin_url}")
        return

    msg = MIMEMultipart("alternative")
    msg["Subject"] = f"Good morning, {name}! Ready to plan your day?"
    msg["From"] = settings.SENDER_EMAIL
    msg["To"] = to_email

    events_word = "event" if event_count == 1 else "events"

    html = f"""
    <html>
      <head>
        <style>
          body {{ font-family: 'Inter', sans-serif; color: #333; background: #faf5ff; }}
          .container {{ max-width: 600px; margin: 0 auto; padding: 30px 20px; }}
          .header {{ color: #a855f7; margin-bottom: 5px; }}
          .subtext {{ color: #6b7280; font-size: 16px; }}
          .event-count {{ background: #f3e8ff; padding: 15px; border-radius: 8px; margin: 20px 0; }}
          .event-count span {{ font-size: 24px; font-weight: bold; color: #7c3aed; }}
          .cta-button {{
            display: inline-block;
            background: #a855f7;
            color: #ffffff;
            padding: 14px 32px;
            border-radius: 8px;
            text-decoration: none;
            font-weight: bold;
            font-size: 16px;
            margin-top: 10px;
          }}
          .footer {{ color: #9ca3af; font-size: 12px; margin-top: 30px; }}
        </style>
      </head>
      <body>
        <div class="container">
          <h2 class="header">Good Morning, {name}!</h2>
          <p class="subtext">Let's make today count.</p>
          <div class="event-count">
            <span>{event_count}</span> {events_word} on your calendar today.
          </div>
          <p>Answer a few quick questions and get personalized AI insights for your day.</p>
          <a href="{checkin_url}" class="cta-button">Start My Day</a>
          <p class="footer" style="text-align: center; padding-top: 20px; border-top: 1px solid #e5e7eb; margin-top: 30px;">
            © 2026 <span style="color: #111827; font-weight: 500;">celesti</span>. Your intelligent daily companion
            <br>
            <a href="{settings.FRONTEND_URL.rstrip('/')}/unsubscribe?action=preferences&email={to_email}" style="color: #111827; text-decoration: none; margin: 0 8px;">Manage preferences</a>
            |
            <a href="{settings.FRONTEND_URL.rstrip('/')}/unsubscribe?action=unsubscribe&email={to_email}" style="color: #111827; text-decoration: none; margin: 0 8px;">Unsubscribe</a>
          </p>
        </div>
      </body>
    </html>
    """

    part = MIMEText(html, "html")
    msg.attach(part)

    try:
        with smtplib.SMTP(settings.SMTP_SERVER, settings.SMTP_PORT) as server:
            server.starttls()
            server.login(settings.SMTP_USER, settings.SMTP_PASSWORD)
            server.sendmail(settings.SENDER_EMAIL, to_email, msg.as_string())
            print(f"Morning email sent to {to_email}")
    except Exception as e:
        print(f"Failed to send morning email to {to_email}: {e}")


def send_insights_email(to_email: str, name: str, detailed: str, quick: str, day_type: str, events: list):
    """Sends AI-generated insights email after user completes check-in."""
    dashboard_url = settings.FRONTEND_URL.rstrip("/") + "/dashboard"

    if not settings.SMTP_SERVER or not settings.SMTP_PASSWORD:
        print(f"MOCK INSIGHTS EMAIL => Sent to {to_email}")
        print(f"MOCK BODY => Detailed: {detailed}")
        print(f"MOCK BODY => Quick: {quick}")
        print(f"MOCK BODY => Day type: {day_type}")
        return

    # Convert plain text insights to HTML
    detailed_lines = [line.strip() for line in detailed.strip().split("\n") if line.strip()]
    detailed_html = "".join(f"<p style='margin:4px 0;color:#374151;'>{line}</p>" for line in detailed_lines)

    quick_lines = [line.strip() for line in quick.strip().split("\n") if line.strip()]
    quick_html = "".join(
        f"<li style='margin:6px 0;color:#374151;'>{line.lstrip('• ').strip()}</li>"
        for line in quick_lines
    )

    # Build events list HTML
    events_html = ""
    if events:
        event_items = ""
        for event in events:
            summary = event.get("summary", "Untitled")
            start = event.get("start_time", event.get("start", ""))
            event_items += f"<li style='margin:6px 0;color:#374151;'><strong>{summary}</strong> — {start}</li>"
        events_html = f"""
        <div style="margin-top:20px;">
          <h4 style="color:#7c3aed;margin-bottom:8px;">Today's Schedule</h4>
          <ul style="padding-left:20px;">{event_items}</ul>
        </div>
        """

    # Day type badge color
    day_colors = {
        "normal": "#10b981",
        "overloaded": "#ef4444",
        "recovery": "#f59e0b",
        "fragmented": "#f97316",
        "burnout": "#dc2626",
    }
    badge_color = day_colors.get(day_type, "#6b7280")

    msg = MIMEMultipart("alternative")
    msg["Subject"] = f"{name}, here are your AI insights for today!"
    msg["From"] = settings.SENDER_EMAIL
    msg["To"] = to_email

    html = f"""
    <html>
      <head>
        <style>
          body {{ font-family: 'Inter', sans-serif; color: #333; background: #faf5ff; }}
          .container {{ max-width: 600px; margin: 0 auto; padding: 30px 20px; }}
        </style>
      </head>
      <body>
        <div class="container">
          <h2 style="color:#a855f7;margin-bottom:5px;">Your Daily Insights</h2>

          <span style="
            display:inline-block;
            background:{badge_color};
            color:#fff;
            padding:4px 12px;
            border-radius:12px;
            font-size:13px;
            font-weight:bold;
            text-transform:uppercase;
            margin-bottom:15px;
          ">{day_type} day</span>

          <div style="background:#f3e8ff;padding:20px;border-radius:8px;margin:20px 0;">
            <h4 style="color:#7c3aed;margin-top:0;margin-bottom:10px;">Detailed Insights</h4>
            {detailed_html}
          </div>

          <div style="background:#ede9fe;padding:20px;border-radius:8px;margin:20px 0;">
            <h4 style="color:#7c3aed;margin-top:0;margin-bottom:10px;">Quick Glance</h4>
            <ul style="padding-left:20px;margin:0;">{quick_html}</ul>
          </div>

          {events_html}

          <a href="{dashboard_url}" style="
            display:inline-block;
            background:#a855f7;
            color:#ffffff;
            padding:14px 32px;
            border-radius:8px;
            text-decoration:none;
            font-weight:bold;
            font-size:16px;
            margin-top:15px;
          ">View Dashboard</a>

          <p style="color:#9ca3af;font-size:12px;margin-top:30px;text-align:center;padding-top:20px;border-top:1px solid #e5e7eb;">
            © 2026 <span style="color:#111827;font-weight:500;">celesti</span>. Your intelligent daily companion
            <br>
            <a href="{settings.FRONTEND_URL.rstrip('/')}/unsubscribe?action=preferences&email={to_email}" style="color:#111827;text-decoration:none;margin:0 8px;">Manage preferences</a>
            |
            <a href="{settings.FRONTEND_URL.rstrip('/')}/unsubscribe?action=unsubscribe&email={to_email}" style="color:#111827;text-decoration:none;margin:0 8px;">Unsubscribe</a>
          </p>
        </div>
      </body>
    </html>
    """

    part = MIMEText(html, "html")
    msg.attach(part)

    try:
        with smtplib.SMTP_SSL(settings.SMTP_SERVER, settings.SMTP_PORT) as server:
            server.login(settings.SMTP_USER, settings.SMTP_PASSWORD)
            server.sendmail(settings.SENDER_EMAIL, to_email, msg.as_string())
            print(f"Insights email sent to {to_email}")
    except Exception as e:
        print(f"Failed to send insights email to {to_email}: {e}")
