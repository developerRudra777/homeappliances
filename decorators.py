from functools import wraps
from django.shortcuts import redirect
from django.contrib import messages


def admin_required(view_func):
    """Decorator strictly isolating the portal from regular customers.
    If a logged-in customer tries to access any portal URL, they are immediately redirected
    to the storefront homepage with an Access Denied message.
    """
    @wraps(view_func)
    def _wrapped_view(request, *args, **kwargs):
        if request.user.is_authenticated:
            if not request.user.is_staff:
                messages.error(request, "Access Denied: You do not have permission to access this area.")
                return redirect('store:home')
            return view_func(request, *args, **kwargs)
        else:
            return redirect('admin_portal:login')
    return _wrapped_view
