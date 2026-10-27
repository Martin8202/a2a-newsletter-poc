"""SMTP 寄信（SPEC §3 步驟 8）。"""
import os
import smtplib
import time
from email.mime.text import MIMEText


class MailError(Exception):
    pass


def send_mail(mail_cfg, subject, html, user=None, password=None, sleep=time.sleep):
    """失敗重試 mail_cfg['retries'] 次（間隔 retry_interval_seconds），仍失敗拋 MailError。"""
    user = user or os.environ.get("SMTP_USER", "")
    password = password or os.environ.get("SMTP_PASSWORD", "")
    msg = MIMEText(html, "html", "utf-8")
    msg["Subject"], msg["From"], msg["To"] = subject, user, mail_cfg["to"]
    last = None
    for attempt in range(mail_cfg["retries"] + 1):
        if attempt:
            sleep(mail_cfg.get("retry_interval_seconds", 60))
        try:
            with smtplib.SMTP(mail_cfg["smtp_host"], mail_cfg["smtp_port"], timeout=30) as s:
                s.starttls()
                s.login(user, password)
                s.sendmail(user, [mail_cfg["to"]], msg.as_string())
            return
        except (smtplib.SMTPException, OSError) as e:
            last = e
    raise MailError(f"寄信失敗: {last}")
