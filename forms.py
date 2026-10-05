"""
All forms for the single `store` app: checkout, customer accounts and the
staff-facing admin portal.
"""

from django import forms
from django.contrib.auth.models import User
from django.contrib.auth.forms import UserCreationForm, AuthenticationForm

from .models import (
    Product, Category, Brand,
    Coupon, Banner, StoreSetting,
    Order, UserProfile, CustomerFeedback,
)


# =========================================================================
# 1. CHECKOUT
# =========================================================================

class OrderCreateForm(forms.ModelForm):
    class Meta:
        model = Order
        fields = [
            'first_name', 'last_name', 'email', 'phone',
            'address_line1', 'address_line2', 'city', 'state', 'postal_code', 'country',
            'delivery_instructions', 'payment_method'
        ]
        widgets = {
            'first_name': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'First name'}),
            'last_name': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Last name'}),
            'email': forms.EmailInput(attrs={'class': 'form-control', 'placeholder': 'Email address'}),
            'phone': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Mobile number'}),
            'address_line1': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Flat/House No., Street'}),
            'address_line2': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Landmark, Area (Optional)'}),
            'city': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'City'}),
            'state': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'State'}),
            'postal_code': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'PIN Code'}),
            'country': forms.TextInput(attrs={'class': 'form-control', 'value': 'India'}),
            'delivery_instructions': forms.Textarea(attrs={'class': 'form-control', 'rows': 2, 'placeholder': 'Delivery notes...'}),
            'payment_method': forms.HiddenInput(attrs={'id': 'id_payment_method', 'value': 'RAZORPAY'}),
        }

# =========================================================================
# 2. CUSTOMER ACCOUNTS
# =========================================================================

class UserRegisterForm(UserCreationForm):
    full_name = forms.CharField(
        max_length=80, 
        required=True, 
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Enter your full name'})
    )
    email = forms.EmailField(
        required=True, 
        widget=forms.EmailInput(attrs={'class': 'form-control', 'placeholder': 'Enter your email'})
    )
    phone = forms.CharField(
        max_length=20, 
        required=False, 
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Enter your mobile number'})
    )

    class Meta:
        model = User
        fields = ['username', 'full_name', 'email', 'phone']

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if 'username' in self.fields:
            self.fields['username'].widget.attrs.update({'class': 'form-control', 'placeholder': 'Choose a username'})
        self.fields['password1'].widget.attrs.update({'class': 'form-control', 'placeholder': 'Create a password'})
        self.fields['password2'].widget.attrs.update({'class': 'form-control', 'placeholder': 'Confirm your password'})

    def clean_email(self):
        email = self.cleaned_data.get('email', '').strip().lower()
        if User.objects.filter(email__iexact=email).exists():
            raise forms.ValidationError("This email is already registered. Please log in or use another email.")
        return email

    def save(self, commit=True):
        user = super().save(commit=False)
        full = self.cleaned_data.get('full_name', '').strip()
        parts = full.split(' ', 1)
        user.first_name = parts[0]
        user.last_name = parts[1] if len(parts) > 1 else ''
        user.email = self.cleaned_data.get('email')
        if commit:
            user.save()
            profile, _ = UserProfile.objects.get_or_create(user=user)
            profile.phone = self.cleaned_data.get('phone', '')
            profile.save()
        return user


class UserLoginForm(AuthenticationForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['username'].widget.attrs.update({
            'class': 'form-control', 
            'placeholder': 'Enter your email or username'
        })
        self.fields['password'].widget.attrs.update({
            'class': 'form-control', 
            'placeholder': 'Enter your password'
        })


class UserProfileForm(forms.ModelForm):
    phone = forms.CharField(max_length=20, required=False, widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': '+91 98765 43210'}))
    avatar = forms.ImageField(required=False, widget=forms.FileInput(attrs={'class': 'form-control', 'accept': 'image/*'}))
    address = forms.CharField(max_length=255, required=False, widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Street, Apartment, Landmark'}))
    city = forms.CharField(max_length=100, required=False, widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Kolkata'}))
    state = forms.CharField(max_length=100, required=False, widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'West Bengal'}))
    postal_code = forms.CharField(max_length=10, required=False, widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': '700001'}))

    class Meta:
        model = User
        fields = ['first_name', 'last_name', 'email']
        widgets = {
            'first_name': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'First name'}),
            'last_name': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Last name'}),
            'email': forms.EmailInput(attrs={'class': 'form-control', 'placeholder': 'Email address'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance and self.instance.pk:
            try:
                profile = self.instance.profile
                self.fields['phone'].initial = profile.phone
                self.fields['address'].initial = profile.address
                self.fields['city'].initial = profile.city
                self.fields['state'].initial = profile.state
                self.fields['postal_code'].initial = profile.postal_code
            except UserProfile.DoesNotExist:
                pass

    def save(self, commit=True):
        user = super().save(commit=commit)
        if commit:
            profile, _ = UserProfile.objects.get_or_create(user=user)
            profile.phone = self.cleaned_data.get('phone', '')
            profile.address = self.cleaned_data.get('address', '')
            profile.city = self.cleaned_data.get('city', '')
            profile.state = self.cleaned_data.get('state', '')
            profile.postal_code = self.cleaned_data.get('postal_code', '')
            if self.cleaned_data.get('avatar'):
                profile.avatar = self.cleaned_data.get('avatar')
            profile.save()
        return user


# =========================================================================
# 3. ADMIN PORTAL
# =========================================================================

class ProductAdminForm(forms.ModelForm):
    class Meta:
        model = Product
        fields = [
            'title', 'brand', 'category', 'sku', 'model_number',
            'price', 'discount_price', 'stock', 'energy_rating',
            'capacity', 'warranty', 'color', 'power_consumption',
            'dimensions', 'summary', 'description', 'image', 'image_url',
            'is_available', 'is_featured', 'is_deal_of_the_day'
        ]
        widgets = {
            'title': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'e.g. Samsung 653L French Door Refrigerator'}),
            'brand': forms.Select(attrs={'class': 'form-select'}),
            'category': forms.Select(attrs={'class': 'form-select'}),
            'sku': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'e.g. SM-REF-653'}),
            'model_number': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'e.g. RF28T5001SR'}),
            'price': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01', 'placeholder': '48990.00'}),
            'discount_price': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01', 'placeholder': '42990.00 (optional)'}),
            'stock': forms.NumberInput(attrs={'class': 'form-control', 'placeholder': '15'}),
            'energy_rating': forms.Select(attrs={'class': 'form-select'}),
            'capacity': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'e.g. 653 Litres, 9 kg, 1.5 Ton'}),
            'warranty': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'e.g. 2 Years + 10 Years on Motor'}),
            'color': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'e.g. Stainless Steel, Matte Black'}),
            'power_consumption': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'e.g. 220V / 1350W'}),
            'dimensions': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'e.g. 90 x 73 x 178 cm'}),
            'summary': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Short selling feature'}),
            'description': forms.Textarea(attrs={'class': 'form-control', 'rows': 4, 'placeholder': 'Full product overview...'}),
            'image': forms.FileInput(attrs={'class': 'form-control', 'accept': 'image/*'}),
            'image_url': forms.URLInput(attrs={'class': 'form-control', 'placeholder': 'https://images.unsplash.com/... (optional fallback)'}),
            'is_available': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'is_featured': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'is_deal_of_the_day': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['image'].required = False
        self.fields['image_url'].required = False



class CategoryAdminForm(forms.ModelForm):
    class Meta:
        model = Category
        fields = ['name', 'icon', 'image', 'description']
        widgets = {
            'name': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'e.g. Dishwashers'}),
            'icon': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'e.g. bi-cup-hot, bi-snow, bi-fan'}),
            'image': forms.FileInput(attrs={'class': 'form-control', 'accept': 'image/*'}),
            'description': forms.Textarea(attrs={'class': 'form-control', 'rows': 3, 'placeholder': 'Category description...'}),
        }


class BrandAdminForm(forms.ModelForm):
    class Meta:
        model = Brand
        fields = ['name', 'origin_country', 'description']
        widgets = {
            'name': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'e.g. Samsung, LG, Whirlpool, Bosch'}),
            'origin_country': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'e.g. South Korea, Germany, USA, India'}),
            'description': forms.Textarea(attrs={'class': 'form-control', 'rows': 3, 'placeholder': 'Brand heritage and warranty reputation...'}),
        }


class CouponAdminForm(forms.ModelForm):
    class Meta:
        model = Coupon
        fields = ['code', 'discount_percent', 'min_purchase_amount', 'valid_from', 'valid_until', 'usage_limit', 'is_active']
        widgets = {
            'code': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'e.g. FESTIVE20'}),
            'discount_percent': forms.NumberInput(attrs={'class': 'form-control', 'min': 1, 'max': 100, 'placeholder': '20'}),
            'min_purchase_amount': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01', 'placeholder': '0.00'}),
            'valid_from': forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
            'valid_until': forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
            'usage_limit': forms.NumberInput(attrs={'class': 'form-control', 'placeholder': '100'}),
            'is_active': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        }


class BannerAdminForm(forms.ModelForm):
    class Meta:
        model = Banner
        fields = ['title', 'subtitle', 'badge_text', 'image_url', 'link_url', 'button_text', 'order', 'is_active']
        widgets = {
            'title': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'e.g. Next-Gen Inverter Series'}),
            'subtitle': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'e.g. Upgrade to smart living'}),
            'badge_text': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'e.g. Up to 40% OFF'}),
            'image_url': forms.URLInput(attrs={'class': 'form-control', 'placeholder': 'Image URL'}),
            'link_url': forms.TextInput(attrs={'class': 'form-control', 'placeholder': '/catalog/?energy_rating=5-Star'}),
            'button_text': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Shop Deals'}),
            'order': forms.NumberInput(attrs={'class': 'form-control', 'placeholder': '1'}),
            'is_active': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        }


class StoreSettingForm(forms.ModelForm):
    class Meta:
        model = StoreSetting
        fields = [
            'store_name', 'tagline', 'support_email', 'support_phone',
            'currency_symbol', 'free_shipping_threshold', 'standard_shipping_fee',
            'order_email_notifications', 'maintenance_mode'
        ]
        widgets = {
            'store_name': forms.TextInput(attrs={'class': 'form-control'}),
            'tagline': forms.TextInput(attrs={'class': 'form-control'}),
            'support_email': forms.EmailInput(attrs={'class': 'form-control'}),
            'support_phone': forms.TextInput(attrs={'class': 'form-control'}),
            'currency_symbol': forms.TextInput(attrs={'class': 'form-control', 'style': 'max-width: 80px;'}),
            'free_shipping_threshold': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
            'standard_shipping_fee': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
            'order_email_notifications': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'maintenance_mode': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        }


# =========================================================================
# 5. CUSTOMER FEEDBACK
# =========================================================================

class CustomerFeedbackForm(forms.ModelForm):
    class Meta:
        model = CustomerFeedback
        fields = ['name', 'email', 'phone', 'order_number', 'feedback_type', 'rating', 'subject', 'message']
        widgets = {
            'name': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Your Full Name'}),
            'email': forms.EmailInput(attrs={'class': 'form-control', 'placeholder': 'Email Address'}),
            'phone': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Mobile Number (Optional)'}),
            'order_number': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'e.g. ORD-2026-XXXX (Optional)'}),
            'feedback_type': forms.Select(attrs={'class': 'form-select'}),
            'rating': forms.Select(attrs={'class': 'form-select'}, choices=[
                (5, '★★★★★ (5 Stars - Excellent)'),
                (4, '★★★★☆ (4 Stars - Good)'),
                (3, '★★★☆☆ (3 Stars - Average)'),
                (2, '★★☆☆☆ (2 Stars - Poor)'),
                (1, '★☆☆☆☆ (1 Star - Bad)'),
            ]),
            'subject': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Brief Subject / Headline'}),
            'message': forms.Textarea(attrs={'class': 'form-control', 'rows': 4, 'placeholder': 'Tell us in detail about your experience...'}),
        }


class CustomerFeedbackAdminReplyForm(forms.ModelForm):
    class Meta:
        model = CustomerFeedback
        fields = ['is_approved', 'is_featured', 'admin_reply']
        widgets = {
            'is_approved': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'is_featured': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'admin_reply': forms.Textarea(attrs={'class': 'form-control', 'rows': 3, 'placeholder': 'Official store response to this customer...'}),
        }

