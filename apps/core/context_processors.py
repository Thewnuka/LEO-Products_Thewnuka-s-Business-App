from django.conf import settings


def brand(request):
    """
    Make brand identity available to every template as {{ brand.* }}.

    This is the one place templates get the name, tagline and logo from.
    When Business Settings are built, only this function needs to change
    to read the values from the database instead of settings.
    """
    config = settings.BRAND
    return {
        "brand": {
            "name": config["NAME"],
            "tagline": config["TAGLINE"],
            "logo": config["LOGO"],
            "logo_is_placeholder": config["LOGO_IS_PLACEHOLDER"],
            "version": settings.APP_VERSION,
        }
    }
