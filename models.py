"""
Data models for the single `store` app.

Everything the storefront needs lives here: catalogue (Category, Brand,
Product, ProductSpecification, Review), marketing (Coupon, Banner,
StoreSetting), checkout (Order, OrderItem) and customer data (UserProfile).

`db_table` is pinned on the models that used to live in the old
orders/accounts/admin_portal apps so the existing db.sqlite3 keeps working.

The session-based shopping Cart (a plain class, not a DB model) is at the
bottom of this file.
"""

import re
import uuid
from decimal import Decimal

from django.conf import settings
from django.contrib.auth.models import User
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.db.models import Avg, Case, DecimalField, F, Min, When
from django.db.models.signals import post_save
from django.dispatch import receiver
from django.urls import reverse
from django.utils import timezone
from django.utils.text import slugify


# ===========================================================================
# 0. HELPERS
# ===========================================================================

def make_unique_slug(instance, source_text, fallback):
    """Build a unique slug for `instance` from `source_text`.

    Falls back to `fallback` if the text slugifies to an empty string, and
    keeps the result inside the field's max_length even after a "-N" suffix.
    """
    model = instance.__class__
    max_length = model._meta.get_field('slug').max_length
    base = (slugify(source_text) or fallback)[: max_length - 8]
    slug = base
    counter = 1
    while model.objects.filter(slug=slug).exclude(pk=instance.pk).exists():
        slug = f"{base}-{counter}"
        counter += 1
    return slug


def effective_price_expr():
    """SQL expression for the price a customer actually pays.

    Mirrors Product.current_price: the discount price when it is set,
    greater than 0 and lower than the regular price, otherwise the price.
    """
    return Case(
        When(discount_price__gt=0, discount_price__lt=F('price'), then=F('discount_price')),
        default=F('price'),
        output_field=DecimalField(max_digits=10, decimal_places=2),
    )


def _unsplash(photo_id):
    return f"https://images.unsplash.com/{photo_id}?w=600&auto=format&fit=crop&q=80"


# Order matters: the first matching rule wins, so more specific words
# (dishwasher, water heater, water purifier) come before generic ones.
# Short tokens (ac, ro, tv, fan) use word boundaries so they don't match
# inside words like "Washing Machines" or "Vacuum".
CATEGORY_IMAGE_RULES = [
    (re.compile(r'dish'), _unsplash('photo-1585829365295-ab7cd400c167')),
    (re.compile(r'geyser|heater'), _unsplash('photo-1585338107529-13afc5f02586')),
    (re.compile(r'water|\bro\b'), _unsplash('photo-1581092160607-ee22621dd758')),
    (re.compile(r'\bacs?\b|air[\s-]?condition'), _unsplash('photo-1628177142898-93e36e4e3a50')),
    (re.compile(r'fridge|refrigerat'), _unsplash('photo-1584992236310-6edddc08acff')),
    (re.compile(r'wash|laundry'), _unsplash('photo-1626806787461-102c1bfaaea1')),
    (re.compile(r'microwave|oven'), _unsplash('photo-1574269909862-7e1d70bb8078')),
    (re.compile(r'vacuum|purifier|clean'), _unsplash('photo-1558317374-067fb5f30001')),
    (re.compile(r'chimney|hob|cook'), _unsplash('photo-1556911220-e15b29be8c8f')),
    (re.compile(r'cooler|\bfans?\b'), _unsplash('photo-1545259741-2ea3ebf61fa3')),
    (re.compile(r'\btvs?\b|televis|audio'), _unsplash('photo-1593359677879-a4bb92f829d1')),
    (re.compile(r'mixer|grind|blender'), _unsplash('photo-1570222094114-d054a817e56b')),
]
CATEGORY_FALLBACK_IMAGE = _unsplash('photo-1556911220-e15b29be8c8f')


# ===========================================================================
# 1. CATALOGUE
# ===========================================================================

class Category(models.Model):
    name = models.CharField(max_length=120, unique=True)
    slug = models.SlugField(max_length=140, unique=True, blank=True)
    icon = models.CharField(max_length=60, default='bi-cpu', help_text="Bootstrap icon class name, e.g. bi-snow, bi-fan, bi-tv")
    description = models.TextField(blank=True)
    image = models.ImageField(upload_to='categories/', blank=True, null=True)

    class Meta:
        verbose_name_plural = 'Categories'
        ordering = ['name']

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = make_unique_slug(self, self.name, 'category')
        super().save(*args, **kwargs)

    def get_absolute_url(self):
        return reverse('store:category_detail', args=[self.slug])

    @property
    def display_image(self):
        if self.image:
            return self.image.url
        name = self.name.lower()
        for pattern, url in CATEGORY_IMAGE_RULES:
            if pattern.search(name):
                return url
        return CATEGORY_FALLBACK_IMAGE

    @property
    def min_price(self):
        """Lowest price a customer would actually pay in this category."""
        return self.products.filter(is_available=True).aggregate(
            lowest=Min(effective_price_expr())
        )['lowest']

    def __str__(self):
        return self.name


class Brand(models.Model):
    name = models.CharField(max_length=100, unique=True)
    slug = models.SlugField(max_length=120, unique=True, blank=True)
    logo = models.ImageField(upload_to='brands/', blank=True, null=True)
    origin_country = models.CharField(max_length=80, blank=True, default='Global')
    description = models.TextField(blank=True)

    class Meta:
        ordering = ['name']

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = make_unique_slug(self, self.name, 'brand')
        super().save(*args, **kwargs)

    def get_absolute_url(self):
        return reverse('store:brand_detail', args=[self.slug])

    def __str__(self):
        return self.name


class Product(models.Model):
    ENERGY_RATING_CHOICES = [
        ('5-Star', '5-Star Energy Saver'),
        ('4-Star', '4-Star Inverter'),
        ('3-Star', '3-Star Standard'),
        ('2-Star', '2-Star Economy'),
        ('1-Star', '1-Star Entry'),
        ('Inverter', 'Smart Dual Inverter'),
        ('A+++', 'European A+++ Rated'),
        ('N/A', 'Not Applicable'),
    ]

    title = models.CharField(max_length=255)
    slug = models.SlugField(max_length=280, unique=True, blank=True)
    sku = models.CharField(max_length=64, unique=True, help_text="Stock Keeping Unit / Product Code")
    model_number = models.CharField(max_length=100, blank=True, help_text="Manufacturer Model Number")

    # PROTECT: a category/brand with products (and therefore order history)
    # cannot be deleted by accident.
    category = models.ForeignKey(Category, related_name='products', on_delete=models.PROTECT)
    brand = models.ForeignKey(Brand, related_name='products', on_delete=models.PROTECT)

    price = models.DecimalField(max_digits=10, decimal_places=2, help_text="Original / Regular price in INR (₹)")
    discount_price = models.DecimalField(max_digits=10, decimal_places=2, blank=True, null=True, help_text="Discounted sale price in INR (₹)")

    summary = models.CharField(max_length=300, help_text="Short highlight, e.g. Frost Free Double Door with Twin Inverter")
    description = models.TextField(help_text="Detailed product overview and key selling points")

    # Appliance Specific Technical Attributes
    energy_rating = models.CharField(max_length=30, choices=ENERGY_RATING_CHOICES, default='5-Star')
    capacity = models.CharField(max_length=100, blank=True, help_text="e.g. 450 Litres, 9 kg, 1.5 Ton, 28 Litres")
    warranty = models.CharField(max_length=150, default='1 Year Comprehensive + 10 Years on Motor/Compressor')
    color = models.CharField(max_length=80, blank=True, default='Stainless Steel')
    power_consumption = models.CharField(max_length=100, blank=True, default='230V / 50Hz')
    dimensions = models.CharField(max_length=120, blank=True, help_text="e.g. 70 x 68 x 178 cm")

    # Inventory & Status
    stock = models.PositiveIntegerField(default=15)
    is_available = models.BooleanField(default=True)
    is_featured = models.BooleanField(default=False)
    is_deal_of_the_day = models.BooleanField(default=False)

    # Visuals
    image = models.ImageField(upload_to='products/', blank=True, null=True)
    image_url = models.URLField(max_length=500, blank=True, null=True, help_text="External image link or CDN fallback")

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = make_unique_slug(self, self.title, 'product')
        super().save(*args, **kwargs)

    @property
    def current_price(self):
        """Returns discount price if available, otherwise regular price."""
        if self.discount_price and 0 < self.discount_price < self.price:
            return self.discount_price
        return self.price

    @property
    def savings(self):
        if self.discount_price and self.discount_price < self.price:
            return self.price - self.discount_price
        return Decimal('0.00')

    @property
    def discount_percent(self):
        if self.discount_price and self.discount_price < self.price:
            pct = ((self.price - self.discount_price) / self.price) * 100
            return int(round(pct))
        return 0

    def get_image_url(self):
        if self.image:
            return self.image.url
        if self.image_url:
            return self.image_url
        return 'https://images.unsplash.com/photo-1584269600464-37b1b58a9fe7?w=800&auto=format&fit=crop&q=60'

    @property
    def in_stock(self):
        return self.stock > 0 and self.is_available

    def average_rating(self):
        """Average star rating (1 decimal), or 0 when there are no reviews."""
        avg = self.reviews.aggregate(avg=Avg('rating'))['avg']
        return round(avg, 1) if avg else 0

    def review_count(self):
        return self.reviews.count()

    def get_absolute_url(self):
        return reverse('store:product_detail', args=[self.slug])

    def __str__(self):
        return f"{self.brand.name} {self.title}"


class ProductSpecification(models.Model):
    product = models.ForeignKey(Product, related_name='specifications', on_delete=models.CASCADE)
    spec_key = models.CharField(max_length=120, help_text="e.g. Compressor Type, Noise Level, Defrosting Type")
    spec_value = models.CharField(max_length=255, help_text="e.g. Smart Inverter, 38 dB, Frost Free")

    class Meta:
        verbose_name = 'Product Specification'
        verbose_name_plural = 'Product Specifications'

    def __str__(self):
        return f"{self.spec_key}: {self.spec_value}"


class Review(models.Model):
    product = models.ForeignKey(Product, related_name='reviews', on_delete=models.CASCADE)
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    rating = models.IntegerField(validators=[MinValueValidator(1), MaxValueValidator(5)], default=5)
    headline = models.CharField(max_length=150)
    comment = models.TextField()
    # Calculated automatically in save() from the user's real orders.
    is_verified_purchase = models.BooleanField(default=False, editable=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        # One review per user per product.
        unique_together = ('product', 'user')

    def save(self, *args, **kwargs):
        if self._state.adding:
            self.is_verified_purchase = OrderItem.objects.filter(
                order__user_id=self.user_id,
                product_id=self.product_id,
            ).exclude(order__status='CANCELLED').exists()
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.rating}★ by {self.user.username} for {self.product.title}"


class ProductView(models.Model):
    """Tracks customer browsing history for AI-driven personalized recommendations."""
    user = models.ForeignKey(User, on_delete=models.CASCADE, null=True, blank=True, related_name='product_views')
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name='views_history')
    session_key = models.CharField(max_length=40, blank=True, null=True, help_text="Session key for guest view tracking")
    viewed_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-viewed_at']
        indexes = [
            models.Index(fields=['user', '-viewed_at']),
            models.Index(fields=['session_key', '-viewed_at']),
        ]

    def __str__(self):
        user_name = self.user.username if self.user else f"Guest ({self.session_key})"
        return f"{user_name} viewed {self.product.title}"


class CustomerFeedback(models.Model):
    FEEDBACK_TYPES = [
        ('GENERAL', 'General Store Experience'),
        ('PRODUCT', 'Product Quality & Variety'),
        ('DELIVERY', 'Delivery & Installation Service'),
        ('SUPPORT', 'Customer Service & Support'),
        ('SUGGESTION', 'Suggestion / Improvement Idea'),
        ('COMPLAINT', 'Issue / Complaint'),
    ]

    user = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='feedbacks')
    name = models.CharField(max_length=120)
    email = models.EmailField()
    phone = models.CharField(max_length=20, blank=True)
    order_number = models.CharField(max_length=50, blank=True, help_text="Optional order reference ID")
    feedback_type = models.CharField(max_length=20, choices=FEEDBACK_TYPES, default='GENERAL')
    rating = models.IntegerField(validators=[MinValueValidator(1), MaxValueValidator(5)], default=5)
    subject = models.CharField(max_length=200)
    message = models.TextField()
    is_approved = models.BooleanField(default=True, help_text="Visible on public feedback page")
    is_featured = models.BooleanField(default=False, help_text="Highlight on testimonials")
    admin_reply = models.TextField(blank=True, help_text="Staff reply to customer feedback")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name = 'Customer Feedback'
        verbose_name_plural = 'Customer Feedbacks'

    def __str__(self):
        return f"{self.rating}★ Feedback from {self.name} - {self.subject[:30]}"


# ===========================================================================
# 2. MARKETING & STORE CONFIGURATION (was the admin_portal app)
# ===========================================================================

class Coupon(models.Model):
    code = models.CharField(max_length=50, unique=True, help_text="e.g. SUMMER20, WELCOME10")
    discount_percent = models.PositiveIntegerField(
        validators=[MinValueValidator(1), MaxValueValidator(100)],
        help_text="Percentage off, e.g. 15 for 15% discount"
    )
    min_purchase_amount = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'))
    valid_from = models.DateField(default=timezone.localdate)
    valid_until = models.DateField()
    usage_limit = models.PositiveIntegerField(default=100)
    times_used = models.PositiveIntegerField(default=0)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'admin_portal_coupon'
        ordering = ['-created_at']

    def is_valid(self):
        # localdate() = the store's local calendar day (not UTC)
        today = timezone.localdate()
        return (
            self.is_active
            and self.valid_from <= today <= self.valid_until
            and self.times_used < self.usage_limit
        )

    def redeem(self):
        """Atomically count one use of this coupon.

        Call this when an order is actually placed. Returns True on success,
        False if the coupon just hit its usage limit (or was deactivated).
        Uses an F() expression so two simultaneous orders can't overshoot
        `usage_limit`.
        """
        updated = Coupon.objects.filter(
            pk=self.pk,
            is_active=True,
            times_used__lt=F('usage_limit'),
        ).update(times_used=F('times_used') + 1)
        return updated == 1

    def save(self, *args, **kwargs):
        self.code = self.code.upper().strip()
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.code} ({self.discount_percent}% OFF)"


class Banner(models.Model):
    title = models.CharField(max_length=200, help_text="Main headline on banner")
    subtitle = models.CharField(max_length=300, blank=True, help_text="Subheading details")
    badge_text = models.CharField(max_length=80, default="Flash Appliance Sale")
    image_url = models.URLField(max_length=500, default="https://images.unsplash.com/photo-1584269600464-37b1b58a9fe7?w=1200&auto=format&fit=crop&q=80")
    link_url = models.CharField(max_length=255, default="/catalog/")
    button_text = models.CharField(max_length=50, default="Shop Appliance Deals")
    is_active = models.BooleanField(default=True)
    order = models.PositiveIntegerField(default=1)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'admin_portal_banner'
        ordering = ['order', '-created_at']

    def __str__(self):
        return self.title


class StoreSetting(models.Model):
    store_name = models.CharField(max_length=150, default="VoltCraft Appliances")
    tagline = models.CharField(max_length=255, default="Smart, Energy-Saving Home Appliances")
    support_email = models.EmailField(default="support@voltcraft.com")
    support_phone = models.CharField(max_length=50, default="1-800-VOLT-HOME")
    currency_symbol = models.CharField(max_length=10, default="₹")
    free_shipping_threshold = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('10000.00'))
    standard_shipping_fee = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('499.00'))
    order_email_notifications = models.BooleanField(default=True)
    maintenance_mode = models.BooleanField(default=False)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'admin_portal_storesetting'

    @classmethod
    def get_settings(cls):
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj

    def __str__(self):
        return f"{self.store_name} Configuration"


# ===========================================================================
# 3. ORDERS & CHECKOUT (was the orders app)
# ===========================================================================

class Order(models.Model):
    STATUS_CHOICES = [
        ('PENDING', 'Order Placed (Pending Processing)'),
        ('CONFIRMED', 'Order Confirmed & Scheduled for Dispatch'),
        ('SHIPPED', 'Dispatched / In Transit (Appliance Logistics)'),
        ('DELIVERED', 'Delivered & Installed'),
        ('CANCELLED', 'Cancelled'),
    ]

    PAYMENT_METHODS = [
        ('RAZORPAY', 'Razorpay Online (UPI, QR Code, Cards, NetBanking)'),
        ('COD', 'Cash on Delivery (Pay on Delivery / QR Scan)'),
    ]

    order_number = models.CharField(max_length=32, unique=True, editable=False)
    user = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='orders')

    # Customer Details
    first_name = models.CharField(max_length=60)
    last_name = models.CharField(max_length=60)
    email = models.EmailField()
    phone = models.CharField(max_length=20)

    # Shipping Address
    address_line1 = models.CharField(max_length=255)
    address_line2 = models.CharField(max_length=255, blank=True)
    city = models.CharField(max_length=100)
    state = models.CharField(max_length=100)
    postal_code = models.CharField(max_length=20)
    country = models.CharField(max_length=60, default='India')
    delivery_instructions = models.TextField(blank=True, help_text="e.g. Elevator access, ground floor, call before arrival")

    # Monetary fields (in INR Rupees)
    subtotal = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'))
    shipping_fee = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'))
    coupon_code = models.CharField(max_length=50, blank=True, null=True, help_text="Applied coupon code, if any")
    discount_amount = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'))
    total_amount = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'))

    # Status & Payment
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='PENDING')
    payment_method = models.CharField(max_length=20, choices=PAYMENT_METHODS, default='RAZORPAY')
    upi_id = models.CharField(max_length=100, blank=True, null=True, help_text="e.g. yourname@okhdfcbank or phonepe")
    card_last_digits = models.CharField(max_length=4, blank=True, null=True, help_text="Last 4 digits of card")
    bank_name = models.CharField(max_length=100, blank=True, null=True, help_text="Net Banking bank, e.g. HDFC Bank, SBI, ICICI")
    razorpay_order_id = models.CharField(max_length=100, blank=True, null=True, help_text="Razorpay Order ID")
    razorpay_payment_id = models.CharField(max_length=100, blank=True, null=True, help_text="Razorpay Payment ID")
    razorpay_signature = models.CharField(max_length=255, blank=True, null=True, help_text="Razorpay Payment Signature")
    is_paid = models.BooleanField(default=False)
    cancellation_reason = models.TextField(blank=True, null=True, help_text="Reason provided if the order was cancelled")
    cancelled_at = models.DateTimeField(blank=True, null=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    @property
    def can_cancel(self):
        """Returns True if the order is in a cancellable status."""
        return self.status in ['PENDING', 'CONFIRMED']

    def cancel_order(self, reason="Cancelled by customer"):
        """Atomically cancel order, restore inventory stock, and return coupon usage."""
        if self.status == 'CANCELLED':
            return False

        self.status = 'CANCELLED'
        self.cancellation_reason = reason
        self.cancelled_at = timezone.now()
        self.save(update_fields=['status', 'cancellation_reason', 'cancelled_at', 'updated_at'])

        # Restore product stock
        for item in self.items.select_related('product'):
            Product.objects.filter(id=item.product_id).update(stock=F('stock') + item.quantity)

        # Restore coupon usage count if used
        if self.coupon_code:
            Coupon.objects.filter(code=self.coupon_code, times_used__gt=0).update(times_used=F('times_used') - 1)

        return True

    class Meta:
        db_table = 'orders_order'
        ordering = ['-created_at']

    @classmethod
    def _generate_order_number(cls):
        """Return an order number that is guaranteed not to exist yet."""
        while True:
            number = 'HA-' + uuid.uuid4().hex[:12].upper()
            if not cls.objects.filter(order_number=number).exists():
                return number

    def save(self, *args, **kwargs):
        if not self.order_number:
            self.order_number = self._generate_order_number()
        super().save(*args, **kwargs)

    @property
    def full_name(self):
        return f"{self.first_name} {self.last_name}"

    def __str__(self):
        return f"Order #{self.order_number} - {self.full_name}"


class OrderItem(models.Model):
    order = models.ForeignKey(Order, related_name='items', on_delete=models.CASCADE)
    # PROTECT: a product that appears in any order cannot be deleted, so past
    # orders and their totals stay intact. Set is_available=False instead.
    product = models.ForeignKey(Product, on_delete=models.PROTECT)
    price = models.DecimalField(max_digits=10, decimal_places=2)
    quantity = models.PositiveIntegerField(default=1)

    class Meta:
        db_table = 'orders_orderitem'

    def __str__(self):
        return f"{self.quantity}x {self.product.title} in Order #{self.order.order_number}"

    @property
    def total_price(self):
        return self.price * self.quantity


# ===========================================================================
# 4. CUSTOMER PROFILES (was the accounts app)
# ===========================================================================

class UserProfile(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='profile')
    phone = models.CharField(max_length=20, blank=True, default='')
    avatar = models.ImageField(upload_to='profiles/', blank=True, null=True)
    address = models.CharField(max_length=255, blank=True, default='')
    city = models.CharField(max_length=100, blank=True, default='')
    state = models.CharField(max_length=100, blank=True, default='')
    postal_code = models.CharField(max_length=10, blank=True, default='')
    reward_points = models.PositiveIntegerField(default=120)

    class Meta:
        db_table = 'accounts_userprofile'

    def __str__(self):
        return f"Profile for {self.user.username}"

    @property
    def avatar_url(self):
        if self.avatar and hasattr(self.avatar, 'url'):
            return self.avatar.url
        return None


@receiver(post_save, sender=User)
def ensure_user_profile(sender, instance, raw=False, **kwargs):
    """Make sure every user has a profile.

    Only a cheap lookup on normal saves (e.g. login updating last_login),
    instead of re-saving the profile every time.
    """
    if raw:  # loading fixtures
        return
    UserProfile.objects.get_or_create(user=instance)


# ===========================================================================
# 5. SHOPPING CART (session based, not a database model)
#
# The session only stores {product_id: {'quantity': n}}.  Prices are NEVER
# stored in the session: they are read from the database every time, so a
# price / discount change in the admin shows up immediately.
# Deleted, unavailable or out-of-stock products are dropped automatically,
# so the badge count, subtotal and displayed items always agree.
# ===========================================================================

CART_SESSION_ID = getattr(settings, 'CART_SESSION_ID', 'appliance_cart')
COUPON_SESSION_ID = 'appliance_cart_coupon'


class Cart:
    def __init__(self, request):
        """Initialize the session cart."""
        self.session = request.session
        self.cart = self.session.setdefault(CART_SESSION_ID, {})
        self.coupon_code = self.session.get(COUPON_SESSION_ID)
        self._products = None  # lazy cache: {"product_id": Product}

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------
    def _load(self):
        """Fetch cart products with ONE query and clean up invalid entries."""
        if self._products is not None:
            return self._products

        ids = [int(pid) for pid in self.cart if str(pid).isdigit()]
        queryset = Product.objects.filter(
            id__in=ids, is_available=True, stock__gt=0
        ).select_related('brand', 'category')
        self._products = {str(p.id): p for p in queryset}

        changed = False
        for pid in list(self.cart):
            product = self._products.get(pid)
            entry = self.cart[pid]

            try:
                quantity = int(entry.get('quantity', 0))
            except (AttributeError, TypeError, ValueError):
                quantity = 0

            if product is not None:
                quantity = min(quantity, product.stock)

            if product is None or quantity <= 0:
                del self.cart[pid]
                self._products.pop(pid, None)
                changed = True
            elif entry != {'quantity': quantity}:
                # also strips the old 'price' key from legacy sessions
                self.cart[pid] = {'quantity': quantity}
                changed = True

        if changed:
            self.save()
        return self._products

    def _invalidate(self):
        self._products = None

    def _quantity(self, pid):
        return self.cart[pid]['quantity']

    # ------------------------------------------------------------------
    # Cart operations
    # ------------------------------------------------------------------
    def add(self, product, quantity=1, override_quantity=False):
        """Add a product to the cart or update its quantity.

        Returns True if the product is in the cart afterwards.
        """
        if not product.is_available or product.stock <= 0:
            self.remove(product)
            return False

        pid = str(product.id)
        current = self.cart.get(pid, {}).get('quantity', 0)
        new_quantity = quantity if override_quantity else current + quantity
        new_quantity = min(new_quantity, product.stock)  # stock limit

        if new_quantity <= 0:
            self.remove(product)
            return False

        self.cart[pid] = {'quantity': new_quantity}
        self._invalidate()
        self.save()
        return True

    def update(self, product, quantity):
        """Directly update product quantity in cart."""
        if str(product.id) in self.cart:
            self.add(product, quantity, override_quantity=True)

    def save(self):
        """Mark session as modified to ensure persistence."""
        self.session.modified = True

    def remove(self, product):
        """Remove a product from the cart."""
        pid = str(product.id)
        if pid in self.cart:
            del self.cart[pid]
            self._invalidate()
            self.save()

    def __iter__(self):
        """Yield one dict per cart line, always using live database prices."""
        products = self._load()
        for pid, entry in self.cart.items():
            product = products[pid]
            price = product.current_price
            quantity = entry['quantity']
            yield {
                'product': product,
                'quantity': quantity,
                'price': price,
                'total_price': price * quantity,
            }

    def __len__(self):
        """Count all appliance units in the cart."""
        self._load()
        return sum(entry['quantity'] for entry in self.cart.values())

    # ------------------------------------------------------------------
    # Money
    # ------------------------------------------------------------------
    def get_subtotal(self):
        """Total price of all items before shipping and discounts."""
        products = self._load()
        return sum(
            (products[pid].current_price * entry['quantity']
             for pid, entry in self.cart.items()),
            Decimal('0.00'),
        )

    def get_shipping(self):
        """Shipping fee, driven by the values set in StoreSetting (admin)."""
        subtotal = self.get_subtotal()
        if subtotal == 0:
            return Decimal('0.00')
        store = StoreSetting.get_settings()
        if subtotal >= store.free_shipping_threshold:
            return Decimal('0.00')
        return store.standard_shipping_fee

    def get_coupon(self):
        """Return the active, still-valid Coupon applied to this cart, if any."""
        if not self.coupon_code:
            return None
        try:
            coupon = Coupon.objects.get(code=self.coupon_code.upper().strip())
        except Coupon.DoesNotExist:
            self.remove_coupon()
            return None

        if not coupon.is_valid():
            self.remove_coupon()
            return None
        return coupon

    @property
    def coupon(self):
        return self.get_coupon()

    def apply_coupon(self, code):
        """Validate and attach a coupon code to the cart session."""
        code = (code or '').upper().strip()
        if not code:
            return False, "Please enter a coupon code."
        try:
            coupon = Coupon.objects.get(code=code)
        except Coupon.DoesNotExist:
            return False, f'Coupon code "{code}" is not valid.'

        if not coupon.is_valid():
            return False, f'Coupon "{code}" has expired or is no longer available.'

        if self.get_subtotal() < coupon.min_purchase_amount:
            return False, (
                f'Coupon "{code}" requires a minimum purchase of '
                f'₹{coupon.min_purchase_amount}.'
            )

        self.coupon_code = coupon.code
        self.session[COUPON_SESSION_ID] = coupon.code
        self.save()
        return True, f'Coupon "{coupon.code}" applied! {coupon.discount_percent}% OFF.'

    def remove_coupon(self):
        """Remove any applied coupon from the cart session."""
        self.coupon_code = None
        if COUPON_SESSION_ID in self.session:
            del self.session[COUPON_SESSION_ID]
            self.save()

    def get_discount(self):
        """Discount amount (in ₹) granted by the currently applied coupon."""
        coupon = self.get_coupon()
        if not coupon:
            return Decimal('0.00')
        subtotal = self.get_subtotal()
        if subtotal < coupon.min_purchase_amount:
            return Decimal('0.00')
        discount = (subtotal * Decimal(coupon.discount_percent)) / Decimal('100')
        return min(discount, subtotal).quantize(Decimal('0.01'))

    def get_total(self):
        """Total = Subtotal + Shipping - Discount."""
        total = self.get_subtotal() + self.get_shipping() - self.get_discount()
        return max(total, Decimal('0.00'))

    def clear(self):
        """Empty the cart session and remove applied coupons."""
        self.session.pop(CART_SESSION_ID, None)
        self.session.pop(COUPON_SESSION_ID, None)
        self.cart = {}
        self.coupon_code = None
        self._invalidate()
        self.save()