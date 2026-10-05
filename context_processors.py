"""Template context processors registered in settings.TEMPLATES."""

from .models import Cart
from .models import Category, Brand


def cart_context(request):
    """Makes cart available globally in all templates (e.g. badge count in navbar)."""
    return {
        'cart': Cart(request)
    }


def categories_processor(request):
    """Makes categories and brands available to all templates for the header nav."""
    return {
        'nav_categories': Category.objects.all()[:15],
        'nav_brands': Brand.objects.all()[:12],
    }
