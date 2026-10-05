"""Django admin registrations for the single `store` app."""

from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.contrib.auth.models import User

from .models import (
    Category, Brand, Product, ProductSpecification, Review, ProductView,
    Order, OrderItem, Coupon, Banner, StoreSetting,
    UserProfile,  # Customer profile model linked to User
)


# =========================================================================
# 0. CUSTOM USER ADMIN (Displays & Edits Phone Number)
# =========================================================================

class UserProfileInline(admin.StackedInline):
    """
    Inline form allowing administrators to edit customer profile details
    (including phone number) directly on the User change page.
    """
    model = UserProfile
    can_delete = False
    verbose_name_plural = 'Customer Profile & Contact Details'


class CustomUserAdmin(BaseUserAdmin):
    """
    Customized UserAdmin that integrates the UserProfile inline form
    and displays the customer's phone number as a dedicated table column.
    """
    inlines = [UserProfileInline]
    list_display = ['username', 'email', 'get_phone', 'first_name', 'last_name', 'is_staff']

    def get_phone(self, obj):
        """
        Retrieves the phone number from UserProfile.
        If not found on the profile, it automatically falls back
        to the phone number used in the customer's most recent order.
        """
        # 1. Check phone on linked UserProfile
        if hasattr(obj, 'profile'):
            phone = getattr(obj.profile, 'phone_number', None) or getattr(obj.profile, 'phone', None)
            if phone:
                return phone

        # 2. Fallback: check phone from their latest order
        latest_order = obj.orders.first()
        if latest_order and latest_order.phone:
            return f"{latest_order.phone} (Order)"

        return "-"

    get_phone.short_description = 'Phone Number'


# Unregister standard User and register CustomUserAdmin
admin.site.unregister(User)
admin.site.register(User, CustomUserAdmin)


# =========================================================================
# 1. CATALOG (Category, Brand, Product, Reviews)
# =========================================================================

class ProductSpecificationInline(admin.TabularInline):
    """Inline specifications editor within the product form."""
    model = ProductSpecification
    extra = 3


@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ['name', 'slug', 'icon']
    prepopulated_fields = {'slug': ('name',)}
    search_fields = ['name']


@admin.register(Brand)
class BrandAdmin(admin.ModelAdmin):
    list_display = ['name', 'slug', 'origin_country']
    prepopulated_fields = {'slug': ('name',)}
    search_fields = ['name']


@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = [
        'title', 'brand', 'category', 'current_price_display', 
        'energy_rating', 'stock', 'is_available', 'is_featured', 'is_deal_of_the_day'
    ]
    list_filter = ['category', 'brand', 'energy_rating', 'is_available', 'is_featured', 'is_deal_of_the_day']
    list_editable = ['stock', 'is_available', 'is_featured', 'is_deal_of_the_day']
    search_fields = ['title', 'sku', 'model_number', 'description']
    prepopulated_fields = {'slug': ('title',)}
    inlines = [ProductSpecificationInline]

    fieldsets = (
        ('Basic Information', {
            'fields': ('title', 'slug', 'sku', 'model_number', 'category', 'brand')
        }),
        ('Pricing & Inventory', {
            'fields': ('price', 'discount_price', 'stock', 'is_available', 'is_featured', 'is_deal_of_the_day')
        }),
        ('Technical Appliance Specifications', {
            'fields': ('energy_rating', 'capacity', 'warranty', 'color', 'power_consumption', 'dimensions')
        }),
        ('Descriptions & Media', {
            'fields': ('summary', 'description', 'image', 'image_url')
        }),
    )

    def current_price_display(self, obj):
        return f"₹{obj.current_price:.2f}"
    current_price_display.short_description = 'Price'


@admin.register(Review)
class ReviewAdmin(admin.ModelAdmin):
    list_display = ['product', 'user', 'rating', 'headline', 'created_at']
    list_filter = ['rating', 'created_at']
    search_fields = ['headline', 'comment', 'user__username', 'product__title']


# =========================================================================
# 2. ORDERS & CUSTOMER PHONE NUMBERS
# =========================================================================

class OrderItemInline(admin.TabularInline):
    """Inline view of purchased products inside the Order change form."""
    model = OrderItem
    raw_id_fields = ['product']
    extra = 0
    readonly_fields = ['product', 'price', 'quantity']


@admin.register(Order)
class OrderAdmin(admin.ModelAdmin):
    # Customer phone number is shown directly in the Order list table
    list_display = [
        'order_number', 'full_name', 'email', 'phone', 
        'total_amount', 'status', 'payment_method', 'is_paid', 'created_at'
    ]
    list_filter = ['status', 'payment_method', 'is_paid', 'created_at']
    list_editable = ['status', 'is_paid']
    search_fields = ['order_number', 'first_name', 'last_name', 'email', 'phone', 'city']
    inlines = [OrderItemInline]
    readonly_fields = ['order_number', 'subtotal', 'shipping_fee', 'total_amount', 'created_at', 'updated_at']

    fieldsets = (
        ('Order Identification', {
            'fields': ('order_number', 'user', 'status', 'created_at')
        }),
        ('Customer & Delivery Information', {
            'fields': (
                ('first_name', 'last_name'),
                ('email', 'phone'),
                'address_line1', 'address_line2',
                ('city', 'state', 'postal_code', 'country'),
                'delivery_instructions',
            )
        }),
        ('Payment & Totals', {
            'fields': (
                'payment_method', 'is_paid',
                'subtotal', 'shipping_fee', 'total_amount'
            )
        }),
    )


# =========================================================================
# 3. MARKETING & STORE CONFIGURATION
# =========================================================================

@admin.register(Coupon)
class CouponAdmin(admin.ModelAdmin):
    list_display = ['code', 'discount_percent', 'min_purchase_amount',
                    'valid_from', 'valid_until', 'times_used', 'usage_limit', 'is_active']
    list_filter = ['is_active', 'valid_until']
    search_fields = ['code']


@admin.register(Banner)
class BannerAdmin(admin.ModelAdmin):
    list_display = ['title', 'badge_text', 'order', 'is_active']
    list_editable = ['order', 'is_active']


@admin.register(StoreSetting)
class StoreSettingAdmin(admin.ModelAdmin):
    list_display = ['store_name', 'support_email', 'currency_symbol', 'maintenance_mode']


@admin.register(ProductView)
class ProductViewAdmin(admin.ModelAdmin):
    list_display = ['product', 'user', 'session_key', 'viewed_at']
    list_filter = ['viewed_at']
    search_fields = ['product__title', 'user__username', 'session_key']
    readonly_fields = ['product', 'user', 'session_key', 'viewed_at']