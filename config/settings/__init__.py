"""
Settings package for LEO PRODUCTS.

    base.py         shared settings used everywhere
    development.py  local development (SQLite, DEBUG on)
    production.py   live server (PostgreSQL, DEBUG off, HTTPS hardening)

Choose one with the DJANGO_SETTINGS_MODULE environment variable.
"""
