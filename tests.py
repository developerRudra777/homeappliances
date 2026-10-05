import datetime
from decimal import Decimal
from django.test import TestCase, Client
from django.urls import reverse
from django.contrib.auth.models import User
from django.utils import timezone
from django.core import mail

from store.models import (
    Category, Brand, Product, ProductSpecification, Review, ProductView,
    Coupon, Banner, StoreSetting, Order, OrderItem, UserProfile, Cart
)


class ModelUnitTests(TestCase):
    """Unit tests for models, methods, signals, and properties."""

    def setUp(self):
        self.category = Category.objects.create(name='Refrigerators', icon='bi-snow')
        self.brand = Brand.objects.create(name='Samsung', origin_country='South Korea')
        self.product = Product.objects.create(
            title='Samsung 300L Frost Free Fridge',
            sku='SAM-REF-300',
            category=self.category,
            brand=self.brand,
            price=Decimal('30000.00'),
            discount_price=Decimal('27000.00'),
            stock=10,
            is_available=True,
        )

    def test_category_slug_and_display_image(self):
        self.assertEqual(self.category.slug, 'refrigerators')
        self.assertTrue('unsplash.com' in self.category.display_image or self.category.display_image.startswith('http'))
        self.assertEqual(self.category.min_price, Decimal('27000.00'))

    def test_brand_slug(self):
        self.assertEqual(self.brand.slug, 'samsung')

    def test_product_price_and_discount_properties(self):
        self.assertEqual(self.product.current_price, Decimal('27000.00'))
        self.assertEqual(self.product.savings, Decimal('3000.00'))
        self.assertEqual(self.product.discount_percent, 10)
        self.assertTrue(self.product.in_stock)

        # Test product without discount
        self.product.discount_price = None
        self.product.save()
        self.assertEqual(self.product.current_price, Decimal('30000.00'))
        self.assertEqual(self.product.savings, Decimal('0.00'))
        self.assertEqual(self.product.discount_percent, 0)

    def test_coupon_validity_and_redemption(self):
        today = timezone.localdate()
        coupon = Coupon.objects.create(
            code='SAVE20',
            discount_percent=20,
            min_purchase_amount=Decimal('5000.00'),
            valid_from=today - datetime.timedelta(days=1),
            valid_until=today + datetime.timedelta(days=10),
            usage_limit=2,
            times_used=0,
            is_active=True
        )
        self.assertTrue(coupon.is_valid())
        self.assertEqual(coupon.code, 'SAVE20')

        # First redemption
        self.assertTrue(coupon.redeem())
        coupon.refresh_from_db()
        self.assertEqual(coupon.times_used, 1)
        self.assertTrue(coupon.is_valid())

        # Second redemption
        self.assertTrue(coupon.redeem())
        coupon.refresh_from_db()
        self.assertEqual(coupon.times_used, 2)
        # Reached usage limit
        self.assertFalse(coupon.is_valid())
        self.assertFalse(coupon.redeem())

    def test_user_profile_creation_signal(self):
        user = User.objects.create_user(username='testcustomer', password='PassWord123!')
        self.assertTrue(hasattr(user, 'profile'))
        self.assertIsInstance(user.profile, UserProfile)
        self.assertEqual(user.profile.reward_points, 120)

    def test_order_number_auto_generation(self):
        order = Order.objects.create(
            first_name='John', last_name='Doe', email='john@example.com',
            phone='9876543210', address_line1='123 Main St', city='Kolkata',
            state='West Bengal', postal_code='700001', country='India'
        )
        self.assertTrue(order.order_number.startswith('HA-'))
        self.assertEqual(order.full_name, 'John Doe')


class CartTests(TestCase):
    """Comprehensive tests for session-based Cart operations."""

    def setUp(self):
        self.client = Client()
        self.category = Category.objects.create(name='Air Conditioners')
        self.brand = Brand.objects.create(name='Daikin')
        self.product = Product.objects.create(
            title='Daikin 1.5 Ton AC',
            sku='DAI-AC-15',
            category=self.category,
            brand=self.brand,
            price=Decimal('40000.00'),
            discount_price=Decimal('36000.00'),
            stock=5,
            is_available=True,
        )
        self.settings = StoreSetting.get_settings()
        self.settings.free_shipping_threshold = Decimal('50000.00')
        self.settings.standard_shipping_fee = Decimal('500.00')
        self.settings.save()

    def test_add_to_cart_and_totals(self):
        # Add 1 Daikin AC via POST
        response = self.client.post(reverse('cart:cart_add', args=[self.product.id]), {'quantity': 2})
        self.assertEqual(response.status_code, 302)

        # Inspect Cart via request session
        session = self.client.session
        cart_data = session.get('appliance_cart')
        self.assertIsNotNone(cart_data)
        self.assertEqual(cart_data[str(self.product.id)]['quantity'], 2)

        # Verify Cart detail view
        resp = self.client.get(reverse('cart:cart_detail'))
        self.assertEqual(resp.status_code, 200)
        cart = resp.context['cart']
        self.assertEqual(len(cart), 2)
        self.assertEqual(cart.get_subtotal(), Decimal('72000.00'))  # 36000 * 2
        # Subtotal 72000 >= threshold 50000 => Shipping free (0)
        self.assertEqual(cart.get_shipping(), Decimal('0.00'))
        self.assertEqual(cart.get_total(), Decimal('72000.00'))

    def test_stock_capping_in_cart(self):
        # Product stock is 5; attempt to add 10
        self.client.post(reverse('cart:cart_add', args=[self.product.id]), {'quantity': 10})
        session = self.client.session
        self.assertEqual(session['appliance_cart'][str(self.product.id)]['quantity'], 5)

    def test_cart_decrement_and_remove(self):
        self.client.post(reverse('cart:cart_add', args=[self.product.id]), {'quantity': 2})
        # Decrement by 1
        self.client.post(reverse('cart:cart_decrement', args=[self.product.id]))
        session = self.client.session
        self.assertEqual(session['appliance_cart'][str(self.product.id)]['quantity'], 1)

        # Decrement again (reaches 0 -> removed)
        self.client.post(reverse('cart:cart_decrement', args=[self.product.id]))
        session = self.client.session
        self.assertNotIn(str(self.product.id), session.get('appliance_cart', {}))

    def test_cart_coupon_application(self):
        today = timezone.localdate()
        Coupon.objects.create(
            code='DISC10',
            discount_percent=10,
            min_purchase_amount=Decimal('20000.00'),
            valid_from=today - datetime.timedelta(days=1),
            valid_until=today + datetime.timedelta(days=10),
            usage_limit=10,
            is_active=True
        )
        self.client.post(reverse('cart:cart_add', args=[self.product.id]), {'quantity': 1})
        # Subtotal: 36000, Shipping: 500 (since 36000 < 50000)
        # Apply coupon
        resp = self.client.post(reverse('cart:cart_apply_coupon'), {'coupon_code': 'disc10'}, follow=True)
        self.assertEqual(resp.status_code, 200)

        cart = resp.context['cart']
        self.assertEqual(cart.coupon_code, 'DISC10')
        self.assertEqual(cart.get_discount(), Decimal('3600.00'))  # 10% of 36000
        # Subtotal 36000 + Shipping 500 - Discount 3600 = 32900
        self.assertEqual(cart.get_total(), Decimal('32900.00'))

        # Remove coupon
        self.client.post(reverse('cart:cart_remove_coupon'))
        resp = self.client.get(reverse('cart:cart_detail'))
        self.assertIsNone(resp.context['cart'].coupon_code)


class StorefrontViewTests(TestCase):
    """Tests for public storefront catalog, search, and reviews."""

    def setUp(self):
        self.client = Client()
        self.category = Category.objects.create(name='Microwaves', slug='microwaves')
        self.brand = Brand.objects.create(name='LG', slug='lg')
        self.product = Product.objects.create(
            title='LG 28L Convection Microwave',
            slug='lg-28l-convection-microwave',
            sku='LG-MC-28',
            category=self.category,
            brand=self.brand,
            price=Decimal('18000.00'),
            discount_price=Decimal('15990.00'),
            stock=8,
            is_available=True,
            is_featured=True,
            energy_rating='4-Star'
        )
        self.user = User.objects.create_user(username='buyer', password='BuyerPassword123!')

    def test_home_page(self):
        resp = self.client.get(reverse('store:home'))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'LG 28L Convection Microwave')

    def test_product_list_search_and_filters(self):
        # Search by title
        resp = self.client.get(reverse('store:product_list') + '?q=Microwave')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.context['total_count'], 1)

        # Filter by category
        resp = self.client.get(reverse('store:product_list') + '?category=microwaves')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.context['total_count'], 1)

        # Filter by non-existent category
        resp = self.client.get(reverse('store:product_list') + '?category=dishwashers')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.context['total_count'], 0)

        # Filter by energy rating
        resp = self.client.get(reverse('store:product_list') + '?energy_rating=4-Star')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.context['total_count'], 1)

        # Filter by price range
        resp = self.client.get(reverse('store:product_list') + '?min_price=20000')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.context['total_count'], 0)

    def test_product_detail_page(self):
        resp = self.client.get(reverse('store:product_detail', args=[self.product.slug]))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'LG 28L Convection Microwave')

        # Invalid slug returns 404
        resp = self.client.get(reverse('store:product_detail', args=['non-existent-product']))
        self.assertEqual(resp.status_code, 404)

    def test_add_review_authenticated(self):
        self.client.login(username='buyer', password='BuyerPassword123!')
        url = reverse('store:add_review', args=[self.product.id])
        resp = self.client.post(url, {
            'rating': 5,
            'headline': 'Excellent Microwave!',
            'comment': 'Heats food evenly and looks great.'
        }, follow=True)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(Review.objects.count(), 1)
        review = Review.objects.first()
        self.assertEqual(review.rating, 5)
        self.assertEqual(review.headline, 'Excellent Microwave!')

        # Submitting again updates the existing review without error
        self.client.post(url, {
            'rating': 4,
            'headline': 'Updated review headline',
            'comment': 'Still good after a month.'
        }, follow=True)
        self.assertEqual(Review.objects.count(), 1)
        review.refresh_from_db()
        self.assertEqual(review.rating, 4)
        self.assertEqual(review.headline, 'Updated review headline')


class AccountsAndAuthTests(TestCase):
    """Tests for customer registration, login, logout, and password reset."""

    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(
            username='existinguser',
            email='existing@example.com',
            password='ExistingPassword123!',
            first_name='Existing',
            last_name='User'
        )

    def test_user_registration_success(self):
        resp = self.client.post(reverse('accounts:register'), {
            'username': 'newuser',
            'full_name': 'New Customer',
            'email': 'newcustomer@example.com',
            'phone': '9876543210',
            'password1': 'NewSecretPassword123!',
            'password2': 'NewSecretPassword123!',
        }, follow=True)
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(User.objects.filter(username='newuser').exists())
        new_user = User.objects.get(username='newuser')
        self.assertEqual(new_user.first_name, 'New')
        self.assertEqual(new_user.last_name, 'Customer')
        self.assertEqual(new_user.profile.phone, '9876543210')

    def test_user_registration_duplicate_email(self):
        resp = self.client.post(reverse('accounts:register'), {
            'username': 'anotheruser',
            'full_name': 'Another User',
            'email': 'existing@example.com',  # duplicate
            'password1': 'Secret123456!',
            'password2': 'Secret123456!',
        })
        self.assertFalse(User.objects.filter(username='anotheruser').exists())

    def test_login_with_username_and_email(self):
        # Login with username
        resp = self.client.post(reverse('accounts:login'), {
            'username': 'existinguser',
            'password': 'ExistingPassword123!'
        })
        self.assertEqual(resp.status_code, 302)
        self.client.logout()

        # Login with email
        resp = self.client.post(reverse('accounts:login'), {
            'username': 'existing@example.com',
            'password': 'ExistingPassword123!'
        })
        self.assertEqual(resp.status_code, 302)

    def test_logout_requires_post(self):
        self.client.login(username='existinguser', password='ExistingPassword123!')
        # GET should be rejected (405 Method Not Allowed)
        resp = self.client.get(reverse('accounts:logout'))
        self.assertEqual(resp.status_code, 405)

        # POST succeeds
        resp = self.client.post(reverse('accounts:logout'))
        self.assertEqual(resp.status_code, 302)

    def test_profile_update(self):
        self.client.login(username='existinguser', password='ExistingPassword123!')
        resp = self.client.post(reverse('accounts:profile'), {
            'first_name': 'UpdatedFirst',
            'last_name': 'UpdatedLast',
            'email': 'existing@example.com',
            'phone': '9988776655',
            'city': 'Mumbai',
            'state': 'Maharashtra',
            'postal_code': '400001'
        }, follow=True)
        self.assertEqual(resp.status_code, 200)
        self.user.refresh_from_db()
        self.assertEqual(self.user.first_name, 'UpdatedFirst')
        self.assertEqual(self.user.profile.phone, '9988776655')
        self.assertEqual(self.user.profile.city, 'Mumbai')

    def test_forgot_password_and_otp_verification(self):
        self.user.profile.phone = '9876543210'
        self.user.profile.save()

        # Request OTP
        resp = self.client.post(reverse('accounts:forgot_password'), {
            'email': 'existing@example.com',
            'phone': '9876543210'
        })
        self.assertEqual(resp.status_code, 302)

        session = self.client.session
        otp = session.get('reset_otp')
        self.assertIsNotNone(otp)
        self.assertEqual(len(otp), 6)

        # Test invalid OTP attempts
        self.client.post(reverse('accounts:reset_password_verify'), {
            'otp': '000000',
            'new_password': 'BrandNewPassword123!',
            'confirm_password': 'BrandNewPassword123!'
        })
        session = self.client.session
        self.assertEqual(session.get('reset_otp_attempts'), 1)

        # Test valid OTP
        resp = self.client.post(reverse('accounts:reset_password_verify'), {
            'otp': otp,
            'new_password': 'BrandNewPassword123!',
            'confirm_password': 'BrandNewPassword123!'
        }, follow=True)
        self.assertEqual(resp.status_code, 200)

        # Check login with new password
        login_success = self.client.login(username='existinguser', password='BrandNewPassword123!')
        self.assertTrue(login_success)


class CheckoutAndOrderTests(TestCase):
    """Tests for checkout flow, concurrency, stock decrement, and authorization."""

    def setUp(self):
        self.client = Client()
        self.customer = User.objects.create_user(
            username='shopper', email='shopper@example.com', password='ShopperPass123!'
        )
        self.other_customer = User.objects.create_user(
            username='other', email='other@example.com', password='OtherPass123!'
        )
        self.staff_user = User.objects.create_user(
            username='staffadmin', email='staff@example.com', password='StaffPass123!', is_staff=True
        )
        self.category = Category.objects.create(name='Washing Machines')
        self.brand = Brand.objects.create(name='Bosch')
        self.product = Product.objects.create(
            title='Bosch 8kg Front Load Washer',
            sku='BOS-WM-8KG',
            category=self.category,
            brand=self.brand,
            price=Decimal('35000.00'),
            discount_price=Decimal('32000.00'),
            stock=3,
            is_available=True,
        )

    def test_unauthenticated_checkout_redirects_to_login(self):
        resp = self.client.get(reverse('orders:checkout'))
        self.assertEqual(resp.status_code, 302)
        self.assertIn(reverse('accounts:login'), resp.url)

    def test_empty_cart_checkout_redirects(self):
        self.client.login(username='shopper', password='ShopperPass123!')
        resp = self.client.get(reverse('orders:checkout'))
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(resp.url, reverse('store:product_list'))

    def test_successful_checkout_flow(self):
        self.client.login(username='shopper', password='ShopperPass123!')
        # Add 2 items to cart
        self.client.post(reverse('cart:cart_add', args=[self.product.id]), {'quantity': 2})

        # Submit checkout with UPI
        checkout_data = {
            'first_name': 'Rahul',
            'last_name': 'Sharma',
            'email': 'shopper@example.com',
            'phone': '9876543210',
            'address_line1': 'Flat 402, Green Heights',
            'city': 'Kolkata',
            'state': 'West Bengal',
            'postal_code': '700001',
            'country': 'India',
            'payment_method': 'COD',
        }
        resp = self.client.post(reverse('orders:checkout'), checkout_data)
        self.assertEqual(resp.status_code, 302)

        # Verify order created
        self.assertEqual(Order.objects.count(), 1)
        order = Order.objects.first()
        self.assertEqual(order.user, self.customer)
        self.assertEqual(order.payment_method, 'COD')
        self.assertFalse(order.is_paid)
        self.assertEqual(order.subtotal, Decimal('64000.00'))  # 32000 * 2
        self.assertEqual(order.items.count(), 1)

        # Verify stock decremented: 3 - 2 = 1
        self.product.refresh_from_db()
        self.assertEqual(self.product.stock, 1)

        # Verify cart emptied
        session = self.client.session
        self.assertTrue(session.get('appliance_cart') in ({}, None))

    def test_order_idor_access_control(self):
        # Create order owned by self.customer
        order = Order.objects.create(
            user=self.customer, first_name='Rahul', last_name='Sharma',
            email='shopper@example.com', phone='9876543210',
            address_line1='Flat 402', city='Kolkata', state='WB', postal_code='700001'
        )

        # Owner can view
        self.client.login(username='shopper', password='ShopperPass123!')
        resp = self.client.get(reverse('orders:order_detail', args=[order.order_number]))
        self.assertEqual(resp.status_code, 200)

        # Another user is forbidden (redirects to home)
        self.client.login(username='other', password='OtherPass123!')
        resp = self.client.get(reverse('orders:order_detail', args=[order.order_number]))
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(resp.url, reverse('store:home'))

        # Staff user can view
        self.client.login(username='staffadmin', password='StaffPass123!')
        resp = self.client.get(reverse('orders:order_detail', args=[order.order_number]))
        self.assertEqual(resp.status_code, 200)


class AdminPortalSecurityAndCRUDTests(TestCase):
    """Tests for staff admin portal permissions and management operations."""

    def setUp(self):
        self.client = Client()
        self.customer = User.objects.create_user(
            username='regularuser', email='reg@example.com', password='UserPass123!'
        )
        self.staff_admin = User.objects.create_user(
            username='adminuser', email='admin@example.com', password='AdminPass123!', is_staff=True
        )
        self.category = Category.objects.create(name='Dishwashers')
        self.brand = Brand.objects.create(name='Siemens')
        self.product = Product.objects.create(
            title='Siemens 14 Place Dishwasher',
            sku='SIE-DW-14',
            category=self.category,
            brand=self.brand,
            price=Decimal('55000.00'),
            stock=4,
            is_available=True,
        )

    def test_unauthenticated_portal_redirects_to_portal_login(self):
        resp = self.client.get(reverse('admin_portal:dashboard'))
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(resp.url, reverse('admin_portal:login'))

    def test_customer_portal_access_strictly_denied(self):
        self.client.login(username='regularuser', password='UserPass123!')
        resp = self.client.get(reverse('admin_portal:dashboard'))
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(resp.url, reverse('store:home'))

    def test_staff_portal_dashboard_access(self):
        self.client.login(username='adminuser', password='AdminPass123!')
        resp = self.client.get(reverse('admin_portal:dashboard'))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Dashboard')

    def test_product_create_and_edit_in_portal(self):
        self.client.login(username='adminuser', password='AdminPass123!')
        # Create product
        resp = self.client.post(reverse('admin_portal:product_create'), {
            'title': 'New Inverter Refrigerator',
            'brand': self.brand.id,
            'category': self.category.id,
            'sku': 'NEW-REF-01',
            'price': '45000.00',
            'stock': 12,
            'energy_rating': '5-Star',
            'summary': 'Energy efficient smart inverter model',
            'description': 'Full description with complete appliance details.',
            'warranty': '1 Year Comprehensive + 10 Years on Compressor',
            'is_available': True,
        })
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(Product.objects.filter(sku='NEW-REF-01').exists())

        # Edit product
        created_p = Product.objects.get(sku='NEW-REF-01')
        resp = self.client.post(reverse('admin_portal:product_edit', args=[created_p.id]), {
            'title': 'Updated Inverter Refrigerator',
            'brand': self.brand.id,
            'category': self.category.id,
            'sku': 'NEW-REF-01',
            'price': '42000.00',
            'stock': 15,
            'energy_rating': '5-Star',
            'summary': 'Updated summary description',
            'description': 'Updated complete description text.',
            'warranty': '2 Years Comprehensive',
            'is_available': True,
        })
        self.assertEqual(resp.status_code, 302)
        created_p.refresh_from_db()
        self.assertEqual(created_p.title, 'Updated Inverter Refrigerator')
        self.assertEqual(created_p.price, Decimal('42000.00'))

    def test_protected_product_cannot_be_deleted(self):
        # Attach product to an order item
        order = Order.objects.create(
            first_name='A', last_name='B', email='a@b.com', phone='123',
            address_line1='C', city='D', state='E', postal_code='F'
        )
        OrderItem.objects.create(order=order, product=self.product, price=self.product.price, quantity=1)

        self.client.login(username='adminuser', password='AdminPass123!')
        resp = self.client.post(reverse('admin_portal:product_delete', args=[self.product.id]))
        self.assertEqual(resp.status_code, 302)
        # Verify product was NOT deleted due to ProtectedError handling
        self.assertTrue(Product.objects.filter(id=self.product.id).exists())

    def test_coupon_toggle_and_delete(self):
        today = timezone.localdate()
        coupon = Coupon.objects.create(
            code='TOGGLE10', discount_percent=10,
            valid_from=today, valid_until=today + datetime.timedelta(days=5)
        )
        self.client.login(username='adminuser', password='AdminPass123!')

        # Toggle inactive
        self.client.post(reverse('admin_portal:coupon_toggle', args=[coupon.id]))
        coupon.refresh_from_db()
        self.assertFalse(coupon.is_active)

        # Toggle active
        self.client.post(reverse('admin_portal:coupon_toggle', args=[coupon.id]))
        coupon.refresh_from_db()
        self.assertTrue(coupon.is_active)

        # Delete coupon
        self.client.post(reverse('admin_portal:coupon_delete', args=[coupon.id]))
        self.assertFalse(Coupon.objects.filter(id=coupon.id).exists())

    def test_quick_inventory_update(self):
        self.client.login(username='adminuser', password='AdminPass123!')
        resp = self.client.post(
            reverse('admin_portal:inventory_quick_update', args=[self.product.id]),
            {'stock': 25}
        )
        self.assertEqual(resp.status_code, 302)
        self.product.refresh_from_db()
        self.assertEqual(self.product.stock, 25)


class SecurityAndEdgeCaseTests(TestCase):
    """Tests covering security boundaries, open redirects, input validation, and edge cases."""

    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(
            username='secuser', email='secuser@example.com', password='SecUserPass123!'
        )
        self.user.profile.phone = '9876543219'  # Ends with 9
        self.user.profile.save()

        self.category = Category.objects.create(name='Heaters')
        self.brand = Brand.objects.create(name='Havells')
        self.product = Product.objects.create(
            title='Havells 25L Storage Geyser',
            sku='HAV-GEY-25',
            category=self.category,
            brand=self.brand,
            price=Decimal('12000.00'),
            stock=2,
            is_available=True,
        )

    def test_login_open_redirect_protection(self):
        # Open redirect attempt with external domain
        resp = self.client.post(reverse('accounts:login') + '?next=https://attacker.com/evil', {
            'username': 'secuser',
            'password': 'SecUserPass123!'
        })
        self.assertEqual(resp.status_code, 302)
        # Should redirect to safe fallback home, NOT attacker.com
        self.assertEqual(resp.url, reverse('store:home'))

        # Protocol-relative open redirect attempt
        self.client.logout()
        resp = self.client.post(reverse('accounts:login') + '?next=//attacker.com/evil', {
            'username': 'secuser',
            'password': 'SecUserPass123!'
        })
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(resp.url, reverse('store:home'))

    def test_cart_add_open_redirect_protection(self):
        # Open redirect attempt via next parameter in cart_add
        resp = self.client.post(
            reverse('cart:cart_add', args=[self.product.id]),
            {'quantity': 1, 'next': 'https://evil-phishing.com'}
        )
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(resp.url, reverse('cart:cart_detail'))

    def test_password_reset_phone_suffix_validation_flaw(self):
        """Documents the vulnerability where entering only the last digit ('9') bypasses phone check."""
        resp = self.client.post(reverse('accounts:forgot_password'), {
            'email': 'secuser@example.com',
            'phone': '9'  # Attacker guessing only 1 single digit!
        })
        # Due to clean_db.endswith(clean_input[-10:]) with len < 10, '9876543219'.endswith('9') is True!
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(resp.url, reverse('accounts:reset_password_verify'))
        # An OTP was generated despite only 1 digit entered!
        self.assertIn('reset_otp', self.client.session)

    def test_coupon_edge_cases(self):
        today = timezone.localdate()
        expired_coupon = Coupon.objects.create(
            code='EXPIRED20', discount_percent=20,
            valid_from=today - datetime.timedelta(days=10),
            valid_until=today - datetime.timedelta(days=1),
            is_active=True
        )
        inactive_coupon = Coupon.objects.create(
            code='INACTIVE20', discount_percent=20,
            valid_from=today, valid_until=today + datetime.timedelta(days=10),
            is_active=False
        )
        min_spend_coupon = Coupon.objects.create(
            code='BIGSPENDER', discount_percent=30,
            min_purchase_amount=Decimal('50000.00'),
            valid_from=today, valid_until=today + datetime.timedelta(days=10),
            is_active=True
        )

        # Add 1 item (value 12000)
        self.client.post(reverse('cart:cart_add', args=[self.product.id]), {'quantity': 1})

        # Test expired coupon
        resp = self.client.post(reverse('cart:cart_apply_coupon'), {'coupon_code': 'EXPIRED20'}, follow=True)
        self.assertContains(resp, 'expired or is no longer available')

        # Test inactive coupon
        resp = self.client.post(reverse('cart:cart_apply_coupon'), {'coupon_code': 'INACTIVE20'}, follow=True)
        self.assertContains(resp, 'expired or is no longer available')

        # Test minimum purchase amount not met (12000 < 50000)
        resp = self.client.post(reverse('cart:cart_apply_coupon'), {'coupon_code': 'BIGSPENDER'}, follow=True)
        self.assertContains(resp, 'requires a minimum purchase of')

    def test_checkout_validation_failures(self):
        self.client.login(username='secuser', password='SecUserPass123!')
        self.client.post(reverse('cart:cart_add', args=[self.product.id]), {'quantity': 1})

        base_data = {
            'first_name': 'Test', 'last_name': 'User', 'email': 'secuser@example.com',
            'phone': '9876543210', 'address_line1': '101 Street', 'city': 'Delhi',
            'state': 'Delhi', 'postal_code': '110001', 'country': 'India',
        }

        # 1. Missing First Name
        data_no_name = dict(base_data, payment_method='COD', first_name='')
        resp = self.client.post(reverse('orders:checkout'), data_no_name)
        self.assertContains(resp, 'First Name: This field is required')

        # 2. Missing Street Address
        data_no_addr = dict(base_data, payment_method='COD', address_line1='')
        resp = self.client.post(reverse('orders:checkout'), data_no_addr)
        self.assertContains(resp, 'Address Line1: This field is required')

        # 3. Invalid Email Format
        data_bad_email = dict(base_data, payment_method='COD', email='not-an-email')
        resp = self.client.post(reverse('orders:checkout'), data_bad_email)
        self.assertContains(resp, 'Email: Enter a valid email address')

    def test_guest_cart_cleared_on_customer_login(self):
        """Verify that when an anonymous visitor adds items to cart and then logs in, the guest cart is cleared."""
        # 1. Anonymous visitor adds product to cart
        self.client.post(reverse('cart:cart_add', args=[self.product.id]), {'quantity': 1})
        session = self.client.session
        self.assertEqual(session.get('appliance_cart', {}).get(str(self.product.id), {}).get('quantity'), 1)

        # 2. Customer logs in
        resp = self.client.post(reverse('accounts:login'), {
            'username': 'secuser',
            'password': 'SecUserPass123!'
        })
        self.assertEqual(resp.status_code, 302)

        # 3. Verify cart is now completely empty
        session = self.client.session
        self.assertTrue(session.get('appliance_cart') in ({}, None))
        resp_cart = self.client.get(reverse('cart:cart_detail'))
        self.assertEqual(len(resp_cart.context['cart']), 0)

    def test_guest_cart_cleared_on_staff_portal_login(self):
        """Verify that when an anonymous visitor carts items and staff logs in to portal, cart is cleared."""
        staff = User.objects.create_user(
            username='portalstaff', email='staffp@example.com', password='StaffPortalPass123!', is_staff=True
        )
        # 1. Anonymous visitor adds product to cart
        self.client.post(reverse('cart:cart_add', args=[self.product.id]), {'quantity': 1})
        self.assertIn('appliance_cart', self.client.session)

        # 2. Staff logs in to portal
        resp = self.client.post(reverse('admin_portal:login'), {
            'username': 'portalstaff',
            'password': 'StaffPortalPass123!'
        })
        self.assertEqual(resp.status_code, 302)

        # 3. Verify cart is cleared
        session = self.client.session
        self.assertTrue(session.get('appliance_cart') in ({}, None))


class AIMLRecommendationTests(TestCase):
    """Automated tests for AI / Machine Learning Recommendation and Search Engine."""

    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(
            username='aiuser', email='aiuser@example.com', password='AIPassword123!'
        )
        self.cat_fridge = Category.objects.create(name='Refrigerators')
        self.cat_microwave = Category.objects.create(name='Microwaves')
        self.brand_samsung = Brand.objects.create(name='Samsung')
        self.brand_lg = Brand.objects.create(name='LG')
        self.brand_panasonic = Brand.objects.create(name='Panasonic')

        # Appliance 1: Samsung Inverter Refrigerator
        self.fridge1 = Product.objects.create(
            title='Samsung 253L Double Door Inverter Refrigerator',
            sku='SAM-REF-253',
            category=self.cat_fridge,
            brand=self.brand_samsung,
            price=Decimal('28000.00'),
            capacity='253 Litres',
            energy_rating='4-Star',
            summary='Frost free smart digital inverter refrigerator with deep cooling',
            description='Energy efficient frost free refrigerator with stabilizer free operation',
            stock=10,
            is_available=True,
        )

        # Appliance 2: LG Inverter Refrigerator (very similar to fridge1)
        self.fridge2 = Product.objects.create(
            title='LG 260L Frost Free Smart Inverter Refrigerator',
            sku='LG-REF-260',
            category=self.cat_fridge,
            brand=self.brand_lg,
            price=Decimal('29500.00'),
            capacity='260 Litres',
            energy_rating='4-Star',
            summary='Double door inverter refrigerator with linear cooling',
            description='Smart inverter double door refrigerator for family home kitchen',
            stock=8,
            is_available=True,
        )

        # Appliance 3: Panasonic Microwave (different appliance type)
        self.microwave = Product.objects.create(
            title='Panasonic 27L Convection Microwave Oven',
            sku='PAN-MC-27',
            category=self.cat_microwave,
            brand=self.brand_panasonic,
            price=Decimal('15000.00'),
            capacity='27 Litres',
            energy_rating='N/A',
            summary='Convection microwave with 360 degree heat wave technology',
            description='Countertop baking and defrosting microwave oven for snacks and grill',
            stock=5,
            is_available=True,
        )

    def test_similar_appliances_ml_ranking(self):
        from store.recommendation import get_similar_appliances
        similar = get_similar_appliances(self.fridge1.id, limit=2)
        self.assertGreater(len(similar), 0)
        # The top recommendation for Samsung fridge should be the LG fridge, not microwave!
        self.assertEqual(similar[0].id, self.fridge2.id)

    def test_personalized_recommendation_from_browsing_history(self):
        from store.recommendation import get_personalized_recommendations
        # User views fridge1
        ProductView.objects.create(user=self.user, product=self.fridge1)

        recommendations = get_personalized_recommendations(user=self.user, limit=2)
        self.assertGreater(len(recommendations), 0)
        # Recommended list should contain appliances tailored to user's browsing
        self.assertIn(self.fridge2, recommendations)

    def test_smart_semantic_search(self):
        from store.recommendation import smart_semantic_search
        # Search query without exact match: "linear cooling double door"
        results = smart_semantic_search("linear cooling double door", limit=5)
        self.assertGreater(len(results), 0)
        self.assertEqual(results[0].id, self.fridge2.id)

    def test_product_detail_view_records_product_view(self):
        # Authenticated user visits fridge1 page
        self.client.login(username='aiuser', password='AIPassword123!')
        resp = self.client.get(reverse('store:product_detail', args=[self.fridge1.slug]))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Similar Appliances')
        # Check ProductView created
        self.assertTrue(ProductView.objects.filter(user=self.user, product=self.fridge1).exists())

    def test_home_page_renders_ai_recommendations(self):
        resp = self.client.get(reverse('store:home'))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Recommended For You')
        self.assertIn('ai_recommendations', resp.context)


class ProductViewSystemTests(TestCase):
    """Automated tests for customer recently viewed appliances and staff view analytics."""

    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(
            username='viewuser', email='viewuser@example.com', password='ViewPass123!'
        )
        self.staff_user = User.objects.create_user(
            username='staffviewuser', email='staffview@example.com', password='StaffViewPass123!', is_staff=True
        )
        self.category = Category.objects.create(name='Microwaves')
        self.brand = Brand.objects.create(name='IFB')
        self.product = Product.objects.create(
            title='IFB 30L Convection Microwave',
            sku='IFB-MW-30',
            category=self.category,
            brand=self.brand,
            price=Decimal('18500.00'),
            stock=8,
            is_available=True,
        )

    def test_recently_viewed_page_renders_for_authenticated_user(self):
        self.client.login(username='viewuser', password='ViewPass123!')
        # View product via detail page
        self.client.get(reverse('store:product_detail', args=[self.product.slug]))
        self.assertTrue(ProductView.objects.filter(user=self.user, product=self.product).exists())

        # Visit recently viewed page
        resp = self.client.get(reverse('store:recently_viewed'))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Recently Viewed Appliances')
        self.assertContains(resp, self.product.title)

    def test_clear_recently_viewed_history(self):
        self.client.login(username='viewuser', password='ViewPass123!')
        ProductView.objects.create(user=self.user, product=self.product)
        self.assertEqual(ProductView.objects.filter(user=self.user).count(), 1)

        resp = self.client.post(reverse('store:clear_recently_viewed'))
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(resp.url, reverse('store:recently_viewed'))
        self.assertEqual(ProductView.objects.filter(user=self.user).count(), 0)

    def test_anonymous_visitor_view_tracking(self):
        # Anonymous user views the product
        resp = self.client.get(reverse('store:product_detail', args=[self.product.slug]))
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(ProductView.objects.filter(user__isnull=True, product=self.product).count(), 1)

        # Anonymous user views browsing history
        resp = self.client.get(reverse('store:recently_viewed'))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, self.product.title)

    def test_customer_profile_includes_recently_viewed(self):
        self.client.login(username='viewuser', password='ViewPass123!')
        ProductView.objects.create(user=self.user, product=self.product)

        resp = self.client.get(reverse('accounts:profile'))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Recently Viewed Appliances')
        self.assertContains(resp, self.product.title)

    def test_portal_product_views_permissions_and_metrics(self):
        # Non-staff redirect
        self.client.login(username='viewuser', password='ViewPass123!')
        resp = self.client.get(reverse('admin_portal:product_views'))
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(resp.url, reverse('store:home'))

        # Staff access
        self.client.login(username='staffviewuser', password='StaffViewPass123!')
        ProductView.objects.create(user=self.user, product=self.product)
        resp = self.client.get(reverse('admin_portal:product_views'))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Product Views & Traffic Analytics')
        self.assertContains(resp, self.product.title)

    def test_portal_clear_views_logs(self):
        self.client.login(username='staffviewuser', password='StaffViewPass123!')
        ProductView.objects.create(user=self.user, product=self.product)
        self.assertEqual(ProductView.objects.count(), 1)

        resp = self.client.post(reverse('admin_portal:product_views_clear'))
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(resp.url, reverse('admin_portal:product_views'))
        self.assertEqual(ProductView.objects.count(), 0)


class CancelOrderSystemTests(TestCase):
    """Automated tests for customer order cancellation and stock restoration."""

    def setUp(self):
        self.client = Client()
        self.customer = User.objects.create_user(
            username='ordercustomer', email='cust@example.com', password='CustPass123!'
        )
        self.other_user = User.objects.create_user(
            username='othercust', email='other@example.com', password='OtherPass123!'
        )
        self.staff_user = User.objects.create_user(
            username='staffmgr', email='staffmgr@example.com', password='StaffPass123!', is_staff=True
        )
        self.category = Category.objects.create(name='Dishwashers')
        self.brand = Brand.objects.create(name='Bosch')
        self.product = Product.objects.create(
            title='Bosch Series 4 Dishwasher',
            sku='BOS-DW-04',
            category=self.category,
            brand=self.brand,
            price=Decimal('45000.00'),
            stock=10,
            is_available=True,
        )
        self.order = Order.objects.create(
            user=self.customer,
            first_name='Rahul',
            last_name='Roy',
            email='cust@example.com',
            phone='9876543210',
            address_line1='123 Lake View Apt',
            city='Kolkata',
            state='West Bengal',
            postal_code='700001',
            status='PENDING',
            total_amount=Decimal('45000.00'),
            is_paid=True,
        )
        self.order_item = OrderItem.objects.create(
            order=self.order,
            product=self.product,
            price=self.product.price,
            quantity=2
        )
        # Emulate post-checkout inventory: stock was decremented by 2 (10 - 2 = 8)
        self.product.stock = 8
        self.product.save()

    def test_customer_can_cancel_pending_order_and_restore_stock(self):
        self.client.login(username='ordercustomer', password='CustPass123!')
        resp = self.client.post(reverse('orders:order_cancel', args=[self.order.order_number]), {
            'cancellation_reason': 'Ordered by mistake',
            'cancellation_comment': 'Accidentally ordered two units instead of one.'
        })
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(resp.url, reverse('orders:order_detail', args=[self.order.order_number]))

        self.order.refresh_from_db()
        self.assertEqual(self.order.status, 'CANCELLED')
        self.assertIn('Ordered by mistake', self.order.cancellation_reason)
        self.assertIsNotNone(self.order.cancelled_at)

        # Verify product stock restored from 8 back to 10
        self.product.refresh_from_db()
        self.assertEqual(self.product.stock, 10)

    def test_coupon_usage_restored_on_order_cancellation(self):
        today = timezone.localdate()
        coupon = Coupon.objects.create(
            code='CANCELTEST',
            discount_percent=10,
            valid_from=today,
            valid_until=today + datetime.timedelta(days=5),
            times_used=1,
            usage_limit=50,
        )
        self.order.coupon_code = 'CANCELTEST'
        self.order.save()

        self.client.login(username='ordercustomer', password='CustPass123!')
        self.client.post(reverse('orders:order_cancel', args=[self.order.order_number]), {
            'cancellation_reason': 'Changed my mind',
        })
        coupon.refresh_from_db()
        self.assertEqual(coupon.times_used, 0)

    def test_customer_cannot_cancel_others_order(self):
        self.client.login(username='othercust', password='OtherPass123!')
        resp = self.client.post(reverse('orders:order_cancel', args=[self.order.order_number]), {
            'cancellation_reason': 'Unauthorized try',
        })
        self.assertEqual(resp.status_code, 302)
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, 'PENDING')
        self.product.refresh_from_db()
        self.assertEqual(self.product.stock, 8)

    def test_cannot_cancel_delivered_order(self):
        self.order.status = 'DELIVERED'
        self.order.save()

        self.client.login(username='ordercustomer', password='CustPass123!')
        resp = self.client.post(reverse('orders:order_cancel', args=[self.order.order_number]), {
            'cancellation_reason': 'Too late',
        })
        self.assertEqual(resp.status_code, 302)
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, 'DELIVERED')
        self.product.refresh_from_db()
        self.assertEqual(self.product.stock, 8)

    def test_portal_staff_can_cancel_and_restore_stock(self):
        self.client.login(username='staffmgr', password='StaffPass123!')
        resp = self.client.post(reverse('admin_portal:order_detail', args=[self.order.order_number]), {
            'status': 'CANCELLED',
            'cancellation_reason': 'Customer requested cancellation via phone call',
            'is_paid': 'on',
        })
        self.assertEqual(resp.status_code, 302)
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, 'CANCELLED')
        self.assertIn('via phone call', self.order.cancellation_reason)

        # Verify stock restored
        self.product.refresh_from_db()
        self.assertEqual(self.product.stock, 10)


class RazorpayIntegrationTests(TestCase):
    """Integration tests for Razorpay payment view and callback."""

    def setUp(self):
        self.user = User.objects.create_user(username='rzpuser', password='RzpPassword123!')
        self.category = Category.objects.create(name='Microwaves', icon='bi-cpu')
        self.brand = Brand.objects.create(name='IFB', origin_country='India')
        self.product = Product.objects.create(
            title='IFB 30L Convection Microwave',
            sku='IFB-MIC-30',
            category=self.category,
            brand=self.brand,
            price=Decimal('15000.00'),
            stock=5,
            is_available=True,
        )
        self.order = Order.objects.create(
            user=self.user,
            first_name='Rudra',
            last_name='Saha',
            email='rudra@example.com',
            phone='9876543210',
            address_line1='Santipur, Nadia',
            city='Santipur',
            state='West Bengal',
            postal_code='741404',
            total_amount=Decimal('15000.00'),
            payment_method='RAZORPAY',
            razorpay_order_id='order_mock_12345',
        )

    def test_razorpay_payment_view_requires_login(self):
        resp = self.client.get(reverse('orders:razorpay_payment', args=[self.order.order_number]))
        self.assertEqual(resp.status_code, 302)

    def test_razorpay_payment_view_renders_for_owner(self):
        self.client.login(username='rzpuser', password='RzpPassword123!')
        resp = self.client.get(reverse('orders:razorpay_payment', args=[self.order.order_number]))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Razorpay Secure Checkout')
        self.assertContains(resp, 'order_mock_12345')

    def test_razorpay_callback_missing_payload(self):
        resp = self.client.post(reverse('orders:razorpay_callback'), {})
        self.assertEqual(resp.status_code, 302)






