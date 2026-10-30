"""
Simple brute-force protection for the login forms.

After LOGIN_RATE_LIMIT_ATTEMPTS failed attempts for the same account name
from the same IP address, further attempts are refused for
LOGIN_RATE_LIMIT_WINDOW seconds. Uses Django's cache (see CACHES setting).
"""
import hashlib

from django.conf import settings
from django.core.cache import cache

from .audit import client_ip


def _key(request, username):
    raw = f"{client_ip(request)}|{(username or '').strip().lower()}"
    return "login-fail:" + hashlib.sha256(raw.encode()).hexdigest()


def is_locked(request, username):
    return cache.get(_key(request, username), 0) >= settings.LOGIN_RATE_LIMIT_ATTEMPTS


def register_failure(request, username):
    key = _key(request, username)
    if cache.add(key, 1, timeout=settings.LOGIN_RATE_LIMIT_WINDOW):
        return
    try:
        cache.incr(key)
    except ValueError:  # expired between add() and incr()
        cache.add(key, 1, timeout=settings.LOGIN_RATE_LIMIT_WINDOW)


def reset(request, username):
    cache.delete(_key(request, username))
