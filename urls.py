"""
URL patterns for the single `store` app.

The app keeps five URL namespaces (store, cart, orders, accounts,
admin_portal) so every existing `{% url 'cart:cart_detail' %}` style tag in the
templates keeps working unchanged. The project's urls.py mounts each list under
its own prefix and namespace.
"""

from django.urls import path

from . import views


app_name = 'store'

# ---------------------------------------------------------------------------
# Storefront  ->  namespace "store"  (mounted at /)
# ---------------------------------------------------------------------------
urlpatterns = [
    path('', views.home, name='home'),
    path('catalog/', views.product_list, name='product_list'),
    path('categories/', views.categories_list, name='categories_list'),
    path('appliance/<slug:slug>/', views.product_detail, name='product_detail'),
    path('category/<str:slug>/', views.category_detail, name='category_detail'),
    path('brand/<str:slug>/', views.brand_detail, name='brand_detail'),
    path('appliance/<int:product_id>/review/', views.add_review, name='add_review'),
    path('recently-viewed/', views.recently_viewed_view, name='recently_viewed'),
    path('recently-viewed/clear/', views.clear_recently_viewed_view, name='clear_recently_viewed'),
    path('feedback/', views.customer_feedback_view, name='customer_feedback'),
    path('api/search-suggestions/', views.search_suggestions, name='search_suggestions'),
]

# ---------------------------------------------------------------------------
# Shopping cart  ->  namespace "cart"  (mounted at /cart/)
# ---------------------------------------------------------------------------
cart_patterns = [
    path('', views.cart_detail, name='cart_detail'),
    path('add/<int:product_id>/', views.cart_add, name='cart_add'),
    path('update/<int:product_id>/', views.cart_update, name='cart_update'),
    path('remove/<int:product_id>/', views.cart_remove, name='cart_remove'),
    path('coupon/apply/', views.cart_apply_coupon, name='cart_apply_coupon'),
    path('coupon/remove/', views.cart_remove_coupon, name='cart_remove_coupon'),
    path('decrement/<int:product_id>/', views.cart_decrement, name='cart_decrement'),
    path('add-one/<int:product_id>/', views.cart_add_one, name='cart_add_one'),
]

# ---------------------------------------------------------------------------
# Checkout & orders  ->  namespace "orders"  (mounted at /orders/)
# ---------------------------------------------------------------------------
order_patterns = [
    path('checkout/', views.checkout, name='checkout'),
    path('success/<str:order_number>/', views.order_success, name='order_success'),
    path('history/', views.order_history, name='order_history'),
    path('tracking/<str:order_number>/', views.order_detail, name='order_detail'),
    path('invoice/<str:order_number>/', views.order_invoice, name='order_invoice'),
    path('cancel/<str:order_number>/', views.order_cancel, name='order_cancel'),
    path('payment/razorpay/<str:order_number>/', views.razorpay_payment_view, name='razorpay_payment'),
    path('payment/razorpay/callback/', views.razorpay_callback_view, name='razorpay_callback'),
]

# ---------------------------------------------------------------------------
# Customer accounts  ->  namespace "accounts"  (mounted at /accounts/)
# ---------------------------------------------------------------------------
account_patterns = [
    path('register/', views.register_view, name='register'),
    path('login/', views.login_view, name='login'),
    path('logout/', views.logout_view, name='logout'),
    path('profile/', views.profile_view, name='profile'),
    path('forgot-password/', views.forgot_password_view, name='forgot_password'),
    path('reset-password-verify/', views.reset_password_verify_view, name='reset_password_verify'),
]

# ---------------------------------------------------------------------------
# Staff admin portal  ->  namespace "admin_portal"  (mounted at /portal/)
# ---------------------------------------------------------------------------
portal_patterns = [
    # Portal login
    path('login/', views.portal_login_view, name='login'),

    # Dashboard
    path('', views.dashboard_view, name='dashboard'),

    # Products
    path('products/', views.products_view, name='products'),
    path('products/add/', views.product_create_view, name='product_create'),
    path('products/<int:product_id>/edit/', views.product_edit_view, name='product_edit'),
    path('products/<int:product_id>/delete/', views.product_delete_view, name='product_delete'),
    path('products/delete-all/', views.product_delete_all_view, name='product_delete_all'),

    # Categories
    path('categories/', views.categories_view, name='categories'),
    path('categories/<int:category_id>/delete/', views.category_delete_view, name='category_delete'),

    # Brands
    path('brands/', views.brands_view, name='brands'),
    path('brands/<int:brand_id>/delete/', views.brand_delete_view, name='brand_delete'),

    # Orders
    path('orders/', views.orders_view, name='orders'),
    path('orders/delete-all/', views.order_delete_all_view, name='order_delete_all'),
    path('orders/<str:order_number>/', views.order_detail_view, name='order_detail'),
    path('orders/<str:order_number>/delete/', views.order_delete_view, name='order_delete'),

    # Customers
    path('customers/', views.customers_view, name='customers'),
    path('customers/<int:customer_id>/delete/', views.customer_delete_view, name='customer_delete'),

    # Inventory
    path('inventory/', views.inventory_view, name='inventory'),
    path('inventory/<int:product_id>/quick-update/', views.inventory_quick_update_view, name='inventory_quick_update'),

    # Coupons
    path('coupons/', views.coupons_view, name='coupons'),
    path('coupons/<int:coupon_id>/toggle/', views.coupon_toggle_view, name='coupon_toggle'),
    path('coupons/<int:coupon_id>/delete/', views.coupon_delete_view, name='coupon_delete'),

    # Banners
    path('banners/', views.banners_view, name='banners'),
    path('banners/<int:banner_id>/toggle/', views.banner_toggle_view, name='banner_toggle'),
    path('banners/<int:banner_id>/delete/', views.banner_delete_view, name='banner_delete'),

    # Reviews
    path('reviews/', views.reviews_view, name='reviews'),
    path('reviews/<int:review_id>/delete/', views.review_delete_view, name='review_delete'),

    # Customer Feedback & Ratings
    path('feedback/', views.portal_feedback_list, name='feedback_list'),
    path('feedback/<int:feedback_id>/toggle-approve/', views.portal_feedback_toggle_approve, name='feedback_toggle_approve'),
    path('feedback/<int:feedback_id>/reply/', views.portal_feedback_reply, name='feedback_reply'),
    path('feedback/<int:feedback_id>/delete/', views.portal_feedback_delete, name='feedback_delete'),

    # Product Views & Analytics
    path('product-views/', views.portal_product_views_view, name='product_views'),
    path('product-views/clear/', views.portal_clear_views_view, name='product_views_clear'),

    # Settings
    path('settings/', views.settings_view, name='settings'),
]
