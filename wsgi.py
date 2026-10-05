"""
WSGI config for appliances_core project.
"""
import os
from django.core.wsgi import get_wsgi_application

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'appliances_core.settings')

application = get_wsgi_application()
