"""Redact identifiers in user-facing errors; retain structured data for details."""
import re

def redact(value,accounts=()):
    text=str(value)
    for account in accounts:
        if account and len(str(account))>3:text=text.replace(str(account),'[账号]')
    text=re.sub(r'wxid_[A-Za-z0-9_-]+','[微信账号]',text)
    text=re.sub(r'(?i)(?:[A-Z]:[\\/]|\\\\)[^\r\n\'"<>]+','[本机路径]',text)
    return text
