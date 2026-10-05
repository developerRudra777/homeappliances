"""
All views for the single `store` app.

Sections:
    1. Storefront   - home, catalogue, product / category / brand pages, reviews
    2. Cart         - session cart, coupons, quantity controls
    3. Checkout     - order placement, history, tracking, invoices
    4. Accounts     - register, login, logout, profile, forgot/reset password
    5. Admin portal - staff-only dashboard and management screens
"""

import re
from datetime import timedelta
import logging
import secrets
from decimal import Decimal
from smtplib import SMTPException
import razorpay
from django.conf import settings


from django.http import JsonResponse
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.contrib.auth import login, logout, authenticate
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.core.paginator import Paginator
from django.db import transaction, IntegrityError
from django.db.models import Q, Count, Sum, Value, IntegerField, F, ProtectedError, Avg
from django.db.models.functions import Coalesce
from django.urls import reverse
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST
from django.views.decorators.csrf import csrf_exempt
from django.core.mail import send_mail
from django.conf import settings

from .models import Cart
from .decorators import admin_required
from .models import (
    Product, Category, Brand, Review, ProductView,
    Coupon, Banner, StoreSetting,
    Order, OrderItem, UserProfile, CustomerFeedback,
)
try:
    from .recommendation import (
        get_similar_appliances,
        get_personalized_recommendations,
        smart_semantic_search,
    )
except Exception:
    def get_similar_appliances(product_id, limit=4):
        from .models import Product
        return list(Product.objects.filter(is_available=True).exclude(id=product_id)[:limit])

    def get_personalized_recommendations(user=None, session_key=None, limit=4):
        from .models import Product
        return list(Product.objects.filter(is_available=True)[:limit])

    def smart_semantic_search(query_text, limit=12):
        return []
from .forms import (
    OrderCreateForm,
    UserRegisterForm, UserLoginForm, UserProfileForm,
    ProductAdminForm, CategoryAdminForm, BrandAdminForm, CouponAdminForm,
    BannerAdminForm, StoreSettingForm,
    CustomerFeedbackForm, CustomerFeedbackAdminReplyForm,
)

logger = logging.getLogger(__name__)


# =========================================================================
# 1. STOREFRONT
# =========================================================================

CATEGORY_SEARCH_PATTERNS = [
    (re.compile(r'(\b(ac|acs|air[\s-]?condition(er)?s?|split[\s-]?ac|window[\s-]?ac|inverter[\s-]?ac)\b|\ba[./]c\b)', re.I), ['condition', 'ac']),
    (re.compile(r'\b(fridge|fridges|refrigerat(or)?s?|freezer?s?)\b', re.I), ['refrigerat', 'fridge']),
    (re.compile(r'\b(wash(er|ing)?[\s-]?machines?|dryers?|laundry)\b', re.I), ['wash', 'laundry']),
    (re.compile(r'\b(microwaves?|ovens?|otg)\b', re.I), ['micro', 'oven']),
    (re.compile(r'\b(dishwashers?|dish[\s-]?wash(er)?s?)\b', re.I), ['dish']),
    (re.compile(r'\b(chimneys?|hobs?|cooktops?)\b', re.I), ['chimney', 'hob']),
    (re.compile(r'\b(purifiers?|\bro\b|\buv\b|water[\s-]?purifiers?)\b', re.I), ['purif', 'water']),
    (re.compile(r'\b(geysers?|water[\s-]?heaters?)\b', re.I), ['geyser', 'heater']),
    (re.compile(r'\b(coolers?|\bfans?\b|bldc)\b', re.I), ['cooler', 'fan']),
    (re.compile(r'\b(\btvs?\b|televisions?|audios?|soundbars?)\b', re.I), ['tv', 'televis']),
    (re.compile(r'\b(mixers?|grinders?|blenders?|juicers?)\b', re.I), ['mixer', 'grind']),
    (re.compile(r'\b(vacuums?|cleaners?)\b', re.I), ['vacuum', 'clean']),
]


def get_category_by_slug_or_name(slug_or_name):
    """Find category by slug, id, name, or appliance keyword gracefully without 404."""
    if not slug_or_name:
        return None
    slug_str = str(slug_or_name).strip()

    cat = Category.objects.filter(slug__iexact=slug_str).first()
    if cat:
        return cat

    if slug_str.isdigit():
        cat = Category.objects.filter(id=int(slug_str)).first()
        if cat:
            return cat

    cat = Category.objects.filter(name__iexact=slug_str).first()
    if cat:
        return cat

    clean_name = slug_str.replace('-', ' ').replace('_', ' ').strip()
    cat = Category.objects.filter(name__icontains=clean_name).first()
    if cat:
        return cat

    cat = Category.objects.filter(slug__icontains=slug_str).first()
    if cat:
        return cat

    for pattern, keywords in CATEGORY_SEARCH_PATTERNS:
        if pattern.search(slug_str):
            q_obj = Q()
            for kw in keywords:
                q_obj |= Q(name__icontains=kw) | Q(slug__icontains=kw)
            matched = Category.objects.filter(q_obj).first()
            if matched:
                return matched

    return None


def home(request):
    """Home landing page with categories, deals of the day, and featured appliances."""
    categories = Category.objects.all()
    brands = Brand.objects.all()

    featured_products = Product.objects.filter(is_featured=True, is_available=True).select_related('brand')[:8]
    deals_of_the_day = Product.objects.filter(is_deal_of_the_day=True, is_available=True).select_related('brand')[:4]
    latest_products = Product.objects.filter(is_available=True).select_related('brand').order_by('-created_at')[:8]

    # AI & Machine Learning Personalized Recommendations
    session_key = request.session.session_key
    ai_recommendations = get_personalized_recommendations(
        user=request.user if request.user.is_authenticated else None,
        session_key=session_key,
        limit=4
    )

    context = {
        'categories': categories,
        'brands': brands,
        'featured_products': featured_products,
        'deals_of_the_day': deals_of_the_day,
        'latest_products': latest_products,
        'ai_recommendations': ai_recommendations,
    }
    return render(request, 'store/index.html', context)


def product_list(request):
    """Catalog view with multi-faceted filtering, search, and sorting."""
    products = Product.objects.filter(is_available=True).select_related('brand', 'category')
    categories = Category.objects.all()
    brands = Brand.objects.all()

    query = request.GET.get('q', '').strip()
    is_ai_search = False
    if query:
        # 1. Smart Category Intent: Match if user searched for an appliance category (e.g. "ac", "fridge", "tv")
        matched_cat = get_category_by_slug_or_name(query)
        if matched_cat:
            cat_products = products.filter(category=matched_cat)
            # Check for qualifying brand or model keywords (e.g. "Samsung AC")
            words = [
                w for w in re.findall(r'\b\w+\b', query)
                if not any(pat.search(w) for pat, _ in CATEGORY_SEARCH_PATTERNS)
            ]
            if words:
                sub_q = Q()
                for w in words:
                    sub_q &= (Q(title__icontains=w) | Q(brand__name__icontains=w) | Q(model_number__icontains=w))
                refined = cat_products.filter(sub_q)
                if refined.exists():
                    products = refined
                else:
                    products = cat_products
            else:
                products = cat_products
        else:
            # 2. General search: Use word boundary for short queries (<=3 chars) to avoid false substring matches
            if len(query) <= 3:
                exact_matches = products.filter(
                    Q(title__iregex=r'(?i)\b' + re.escape(query) + r'\b') |
                    Q(brand__name__icontains=query) |
                    Q(category__name__icontains=query) |
                    Q(sku__icontains=query) |
                    Q(model_number__icontains=query)
                )
            else:
                exact_matches = products.filter(
                    Q(title__icontains=query) |
                    Q(summary__icontains=query) |
                    Q(description__icontains=query) |
                    Q(model_number__icontains=query) |
                    Q(sku__icontains=query) |
                    Q(brand__name__icontains=query) |
                    Q(category__name__icontains=query)
                )

            if exact_matches.exists():
                products = exact_matches
            else:
                # Semantic AI Search via TF-IDF & Cosine Similarity
                ai_matches = smart_semantic_search(query, limit=12)
                if ai_matches:
                    match_ids = [p.id for p in ai_matches]
                    products = Product.objects.filter(id__in=match_ids, is_available=True).select_related('brand', 'category')
                    is_ai_search = True
                else:
                    products = exact_matches

    category_slug = request.GET.get('category', '').strip()
    selected_category = None
    if category_slug:
        selected_category = get_category_by_slug_or_name(category_slug)
        if selected_category:
            products = products.filter(category=selected_category)
        else:
            clean_term = category_slug.replace('-', ' ')
            products = products.filter(
                Q(category__name__icontains=clean_term) |
                Q(title__icontains=clean_term) |
                Q(summary__icontains=clean_term)
            )

    brand_slug = request.GET.get('brand', '').strip()
    selected_brand = None
    if brand_slug:
        selected_brand = Brand.objects.filter(Q(slug__iexact=brand_slug) | Q(name__icontains=brand_slug.replace('-', ' '))).first()
        if selected_brand:
            products = products.filter(brand=selected_brand)

    energy_rating = request.GET.get('energy_rating', '').strip()
    if energy_rating:
        products = products.filter(energy_rating=energy_rating)

    min_price = request.GET.get('min_price', '').strip()
    max_price = request.GET.get('max_price', '').strip()
    if min_price:
        try:
            products = products.filter(price__gte=Decimal(min_price))
        except (ValueError, ArithmeticError):
            pass
    if max_price:
        try:
            products = products.filter(price__lte=Decimal(max_price))
        except (ValueError, ArithmeticError):
            pass

    in_stock_only = request.GET.get('in_stock', '')
    if in_stock_only == '1':
        products = products.filter(stock__gt=0)

    sort_by = request.GET.get('sort', 'newest')
    if sort_by == 'price_asc':
        products = products.order_by('price')
    elif sort_by == 'price_desc':
        products = products.order_by('-price')
    elif sort_by == 'popular':
        products = products.order_by('-is_featured', '-created_at')
    else:
        products = products.order_by('-created_at')

    paginator = Paginator(products, 9)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)

    energy_ratings = [choice[0] for choice in Product.ENERGY_RATING_CHOICES if choice[0] != 'N/A']

    context = {
        'page_obj': page_obj,
        'total_count': paginator.count,
        'categories': categories,
        'brands': brands,
        'energy_ratings': energy_ratings,
        'query': query,
        'selected_category': selected_category,
        'selected_brand': selected_brand,
        'selected_energy': energy_rating,
        'min_price': min_price,
        'max_price': max_price,
        'sort_by': sort_by,
        'in_stock_only': in_stock_only,
        'is_ai_search': is_ai_search,
    }
    return render(request, 'store/product_list.html', context)


def search_suggestions(request):
    """Real-time autocomplete search suggestions API for navbar search bar.
    Returns matching appliances with product name, thumbnail image, brand, category, and price.
    """
    query = request.GET.get('q', '').strip()
    if not query:
        return JsonResponse({'results': [], 'total': 0, 'query': query})

    products = Product.objects.filter(is_available=True).select_related('brand', 'category')

    # 1. Smart Category Intent: Match if user typed e.g. "ac", "fridge", "tv", "cooler", etc.
    matched_cat = get_category_by_slug_or_name(query)
    if matched_cat:
        cat_products = products.filter(category=matched_cat)
        words = [
            w for w in re.findall(r'\b\w+\b', query)
            if not any(pat.search(w) for pat, _ in CATEGORY_SEARCH_PATTERNS)
        ]
        if words:
            sub_q = Q()
            for w in words:
                sub_q &= (Q(title__icontains=w) | Q(brand__name__icontains=w) | Q(model_number__icontains=w))
            refined = cat_products.filter(sub_q)
            matches = refined if refined.exists() else cat_products
        else:
            matches = cat_products
    else:
        if len(query) <= 3:
            matches = products.filter(
                Q(title__iregex=r'(?i)\b' + re.escape(query) + r'\b') |
                Q(brand__name__icontains=query) |
                Q(category__name__icontains=query) |
                Q(sku__icontains=query) |
                Q(model_number__icontains=query)
            )
        else:
            matches = products.filter(
                Q(title__icontains=query) |
                Q(brand__name__icontains=query) |
                Q(category__name__icontains=query) |
                Q(model_number__icontains=query) |
                Q(sku__icontains=query) |
                Q(summary__icontains=query)
            )

    # 2. Semantic AI fallback if no direct keyword matches
    if not matches.exists():
        ai_matches = smart_semantic_search(query, limit=6)
        if ai_matches:
            match_ids = [p.id for p in ai_matches]
            matches = Product.objects.filter(id__in=match_ids, is_available=True).select_related('brand', 'category')

    total_count = matches.count()
    top_items = matches.order_by('-is_featured', '-is_deal_of_the_day', '-created_at')[:6]

    results = []
    for p in top_items:
        results.append({
            'id': p.id,
            'title': p.title,
            'brand': p.brand.name if p.brand else '',
            'category': p.category.name if p.category else '',
            'price': f"₹{int(p.current_price):,}",
            'original_price': f"₹{int(p.price):,}" if (p.discount_price and p.discount_price < p.price) else None,
            'discount_percent': p.discount_percent if p.discount_percent > 0 else 0,
            'image_url': p.get_image_url(),
            'url': p.get_absolute_url(),
        })

    return JsonResponse({
        'results': results,
        'total': total_count,
        'query': query,
    })


def categories_list(request):
    """Dedicated showcase page for major appliance categories."""
    categories = Category.objects.all().order_by('name')
    categories_data = []
    for cat in categories:
        prods = cat.products.filter(is_available=True)
        count = prods.count()
        min_price = None
        if count > 0:
            cheapest = prods.order_by('price').first()
            min_price = cheapest.current_price

        categories_data.append({
            'category': cat,
            'count': count,
            'min_price': min_price,
            'featured_products': prods.order_by('-is_featured', '-created_at')[:4],
        })

    context = {
        'categories_data': categories_data,
        'total_categories': len(categories_data),
    }
    return render(request, 'store/categories.html', context)


def category_detail(request, slug):
    """Dynamic category showcase page."""
    category = get_category_by_slug_or_name(slug)
    if not category:
        messages.warning(request, f"Category '{slug}' was not found.")
        return redirect('store:categories_list')

    products = Product.objects.filter(category=category, is_available=True).select_related('brand')
    all_categories = Category.objects.all().order_by('name')
    brands = Brand.objects.filter(products__in=products).distinct()
    if not brands.exists():
        brands = Brand.objects.all()[:8]

    query = request.GET.get('q', '').strip()
    if query:
        products = products.filter(
            Q(title__icontains=query) |
            Q(summary__icontains=query) |
            Q(description__icontains=query) |
            Q(model_number__icontains=query) |
            Q(sku__icontains=query) |
            Q(brand__name__icontains=query)
        )

    brand_slug = request.GET.get('brand', '').strip()
    selected_brand = None
    if brand_slug:
        selected_brand = Brand.objects.filter(Q(slug__iexact=brand_slug) | Q(name__icontains=brand_slug.replace('-', ' '))).first()
        if selected_brand:
            products = products.filter(brand=selected_brand)

    energy_rating = request.GET.get('energy_rating', '').strip()
    if energy_rating:
        products = products.filter(energy_rating=energy_rating)

    min_price = request.GET.get('min_price', '').strip()
    max_price = request.GET.get('max_price', '').strip()
    if min_price:
        try:
            products = products.filter(price__gte=Decimal(min_price))
        except (ValueError, ArithmeticError):
            pass
    if max_price:
        try:
            products = products.filter(price__lte=Decimal(max_price))
        except (ValueError, ArithmeticError):
            pass

    sort_by = request.GET.get('sort', 'featured')
    if sort_by == 'price_low':
        products = products.order_by('discount_price', 'price')
    elif sort_by == 'price_high':
        products = products.order_by('-price')
    elif sort_by == 'newest':
        products = products.order_by('-created_at')
    else:
        products = products.order_by('-is_featured', '-created_at')

    paginator = Paginator(products, 9)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)

    context = {
        'category': category,
        'page_obj': page_obj,
        'products': page_obj.object_list,
        'total_count': products.count(),
        'brands': brands,
        'all_categories': all_categories,
        'selected_brand': selected_brand,
        'selected_energy_rating': energy_rating,
        'min_price': min_price,
        'max_price': max_price,
        'sort_by': sort_by,
        'query': query,
    }
    return render(request, 'store/category_detail.html', context)


def brand_detail(request, slug):
    """Shortcut to view products of a specific brand."""
    brand = Brand.objects.filter(Q(slug__iexact=slug) | Q(name__icontains=slug.replace('-', ' '))).first()
    if brand:
        return redirect(f"/catalog/?brand={brand.slug}")
    return redirect('store:product_list')


def get_recently_viewed_products(request, limit=6, exclude_id=None):
    """Retrieve distinct recently viewed appliances for current user or guest session."""
    try:
        qs = ProductView.objects.select_related('product__brand', 'product__category')
        if request.user.is_authenticated:
            qs = qs.filter(user=request.user)
        elif request.session.session_key:
            qs = qs.filter(session_key=request.session.session_key)
        else:
            return []

        if exclude_id:
            qs = qs.exclude(product_id=exclude_id)

        seen_ids = set()
        distinct_products = []
        for pv in qs.order_by('-viewed_at')[:40]:
            if pv.product_id not in seen_ids and pv.product.is_available:
                seen_ids.add(pv.product_id)
                distinct_products.append(pv.product)
                if len(distinct_products) >= limit:
                    break
        return distinct_products
    except Exception as exc:
        logger.debug("Error fetching recently viewed products: %s", exc)
        return []


def product_detail(request, slug):
    """Full appliance specifications, images, customer reviews, AI recommendations & recently viewed tracking."""
    product = get_object_or_404(Product, slug=slug, is_available=True)
    specifications = product.specifications.all()
    reviews = product.reviews.select_related('user').all()

    # Track user interaction for AI personalization & view product system
    try:
        if not request.session.session_key:
            request.session.save()
        ProductView.objects.create(
            user=request.user if request.user.is_authenticated else None,
            product=product,
            session_key=request.session.session_key
        )
    except Exception as exc:
        logger.debug("Failed to record ProductView: %s", exc)

    # AI / ML Content-Based Similarity Recommendations
    ai_similar_products = get_similar_appliances(product.id, limit=4)
    if not ai_similar_products:
        ai_similar_products = list(
            Product.objects.filter(category=product.category, is_available=True)
            .exclude(id=product.id)[:4]
        )

    # Recently Viewed Appliances (excluding currently viewed product)
    recently_viewed = get_recently_viewed_products(request, limit=4, exclude_id=product.id)

    context = {
        'product': product,
        'specifications': specifications,
        'reviews': reviews,
        'related_products': ai_similar_products,
        'ai_similar_products': ai_similar_products,
        'recently_viewed': recently_viewed,
    }
    return render(request, 'store/product_detail.html', context)


def recently_viewed_view(request):
    """Dedicated browsing history page showcasing all recently viewed appliances."""
    appliances = get_recently_viewed_products(request, limit=24)
    return render(request, 'store/recently_viewed.html', {
        'page_title': 'Recently Viewed Appliances',
        'appliances': appliances,
        'total_viewed': len(appliances),
    })


@require_POST
def clear_recently_viewed_view(request):
    """Clear browsing history for current user or guest session."""
    if request.user.is_authenticated:
        ProductView.objects.filter(user=request.user).delete()
    elif request.session.session_key:
        ProductView.objects.filter(session_key=request.session.session_key).delete()
    messages.info(request, "Your recently viewed browsing history has been cleared.")
    return redirect('store:recently_viewed')


@login_required
@require_POST
def add_review(request, product_id):
    """Customer submission of appliance review & star rating."""
    product = get_object_or_404(Product, id=product_id)
    try:
        rating = max(1, min(5, int(request.POST.get('rating', 5))))
    except (ValueError, TypeError):
        rating = 5

    headline = request.POST.get('headline', '').strip()
    comment = request.POST.get('comment', '').strip()

    if not headline or not comment:
        messages.error(request, 'Please provide both a headline and review comments.')
        return redirect(product.get_absolute_url())

    # Update or create to avoid IntegrityError on duplicates
    review, created = Review.objects.update_or_create(
        product=product,
        user=request.user,
        defaults={
            'rating': rating,
            'headline': headline,
            'comment': comment,
        }
    )
    if created:
        messages.success(request, 'Thank you! Your appliance review has been posted.')
    else:
        messages.info(request, 'Your existing review has been updated.')

    return redirect(product.get_absolute_url())


def customer_feedback_view(request):
    """Public customer feedback & reviews page.
    Displays all verified customer ratings & testimonials.
    Also accepts new feedback submissions from both customers and guests.
    """
    feedbacks = CustomerFeedback.objects.filter(is_approved=True)

    rating_filter = request.GET.get('rating', '').strip()
    if rating_filter in ['1', '2', '3', '4', '5']:
        feedbacks = feedbacks.filter(rating=int(rating_filter))

    type_filter = request.GET.get('type', '').strip()
    if type_filter:
        feedbacks = feedbacks.filter(feedback_type=type_filter)

    total_count = CustomerFeedback.objects.filter(is_approved=True).count()
    avg_aggregate = CustomerFeedback.objects.filter(is_approved=True).aggregate(avg=Avg('rating'))['avg']
    avg_rating = round(float(avg_aggregate), 1) if avg_aggregate else 5.0

    rating_counts = {
        5: CustomerFeedback.objects.filter(is_approved=True, rating=5).count(),
        4: CustomerFeedback.objects.filter(is_approved=True, rating=4).count(),
        3: CustomerFeedback.objects.filter(is_approved=True, rating=3).count(),
        2: CustomerFeedback.objects.filter(is_approved=True, rating=2).count(),
        1: CustomerFeedback.objects.filter(is_approved=True, rating=1).count(),
    }

    if request.method == 'POST':
        form = CustomerFeedbackForm(request.POST)
        if form.is_valid():
            fb = form.save(commit=False)
            if request.user.is_authenticated:
                fb.user = request.user
            fb.save()
            messages.success(request, "Thank you! Your feedback has been received and is greatly appreciated.")
            return redirect('store:customer_feedback')
        else:
            messages.error(request, "Please check the form and fill in all required fields correctly.")
    else:
        initial_data = {}
        if request.user.is_authenticated:
            initial_data['name'] = request.user.get_full_name() or request.user.username
            initial_data['email'] = request.user.email
            if hasattr(request.user, 'profile') and request.user.profile.phone:
                initial_data['phone'] = request.user.profile.phone
        form = CustomerFeedbackForm(initial=initial_data)

    paginator = Paginator(feedbacks, 10)
    page_obj = paginator.get_page(request.GET.get('page'))

    context = {
        'form': form,
        'page_obj': page_obj,
        'feedbacks': page_obj.object_list,
        'total_count': total_count,
        'avg_rating': avg_rating,
        'rating_counts': rating_counts,
        'selected_rating': rating_filter,
        'selected_type': type_filter,
    }
    return render(request, 'store/feedback.html', context)


# =========================================================================
# 2. SHOPPING CART
# =========================================================================

@require_POST
def cart_apply_coupon(request):
    """Apply a discount coupon code to the current shopping cart."""
    cart = Cart(request)
    code = request.POST.get('coupon_code', '')
    success, message = cart.apply_coupon(code)
    if success:
        messages.success(request, message)
    else:
        messages.error(request, message)
    return redirect('cart:cart_detail')


@require_POST
def cart_remove_coupon(request):
    """Remove the currently applied coupon from the cart."""
    cart = Cart(request)
    cart.remove_coupon()
    messages.info(request, "Coupon removed from your order.")
    return redirect('cart:cart_detail')


@require_POST
def cart_add(request, product_id):
    """Add an appliance to cart with desired quantity."""
    cart = Cart(request)
    product = get_object_or_404(Product, id=product_id)

    quantity = 1
    if request.method == 'POST':
        try:
            quantity = max(1, int(request.POST.get('quantity', 1)))
        except (ValueError, TypeError):
            quantity = 1

    if product.stock <= 0:
        messages.error(request, f"Sorry, {product.title} is currently out of stock.")
        return redirect(product.get_absolute_url())

    cart.add(product=product, quantity=quantity)
    messages.success(request, f"Added {product.title} to your shopping cart!")

    if request.POST.get('action') == 'buy_now':
        return redirect('orders:checkout')

    next_url = request.POST.get('next') or request.META.get('HTTP_REFERER')
    if next_url and url_has_allowed_host_and_scheme(next_url, allowed_hosts={request.get_host()}):
        return redirect(next_url)
    return redirect('cart:cart_detail')


@require_POST
def cart_update(request, product_id):
    """Update appliance quantity directly from cart page."""
    cart = Cart(request)
    product = get_object_or_404(Product, id=product_id)
    try:
        quantity = max(1, int(request.POST.get('quantity', 1)))
    except (ValueError, TypeError):
        quantity = 1

    cart.update(product=product, quantity=quantity)
    messages.info(request, f"Updated quantity for {product.title}.")
    return redirect('cart:cart_detail')


def cart_detail(request):
    """View shopping cart contents and order totals."""
    cart = Cart(request)
    return render(request, 'cart/cart_detail.html', {'cart': cart})


@require_POST
def cart_remove(request, product_id):
    """Remove an appliance from the cart entirely."""
    cart = Cart(request)
    product = get_object_or_404(Product, id=product_id)
    cart.remove(product)
    messages.success(request, f'"{product.title}" removed from your cart.')
    return redirect('cart:cart_detail')


@require_POST
def cart_decrement(request, product_id):
    """Decrease an item's quantity by one, removing it when it reaches zero."""
    cart = Cart(request)
    product = get_object_or_404(Product, id=product_id)
    product_id_str = str(product.id)
    if product_id_str in cart.cart:
        current_qty = cart.cart[product_id_str].get('quantity', 1)
        if current_qty > 1:
            cart.update(product=product, quantity=current_qty - 1)
            messages.info(request, f'"{product.title}" quantity decreased.')
        else:
            cart.remove(product)
            messages.warning(request, f'"{product.title}" removed from your cart.')
    return redirect('cart:cart_detail')


@require_POST
def cart_add_one(request, product_id):
    """Increase an item's quantity by one, respecting stock limits."""
    cart = Cart(request)
    product = get_object_or_404(Product, id=product_id)
    product_id_str = str(product.id)
    if product_id_str in cart.cart:
        current_qty = cart.cart[product_id_str].get('quantity', 0)
        if current_qty < product.stock:
            cart.add(product, quantity=1)
            messages.success(request, f'"{product.title}" quantity increased.')
        else:
            messages.error(request, f'Cannot add more of "{product.title}". Stock limit reached.')
    else:
        cart.add(product, quantity=1)
    return redirect('cart:cart_detail')


# =========================================================================
# 3. CHECKOUT & ORDERS
# =========================================================================

def checkout(request):
    """Checkout view with stock checks, atomic order creation, and payment simulation."""
    if not request.user.is_authenticated:
        messages.warning(request, "Please log in or sign up first to proceed to checkout.")
        login_url = reverse('accounts:login')
        return redirect(f"{login_url}?next={request.path}")

    cart = Cart(request)
    if len(cart) == 0:
        messages.warning(request, "Your shopping cart is empty! Add appliances before proceeding to checkout.")
        return redirect('store:product_list')

    applied_coupon = cart.get_coupon()

    context = {
        'cart': cart,
        'subtotal_display': cart.get_subtotal(),
        'shipping_display': cart.get_shipping(),
        'discount_display': cart.get_discount(),
        'applied_coupon': applied_coupon,
        'total_display': cart.get_total(),
    }

    if request.method == 'POST':
        post_data = request.POST.copy()
        if not post_data.get('country'):
            post_data['country'] = 'India'

        form = OrderCreateForm(post_data)
        context['form'] = form

        if form.is_valid():
            order = form.save(commit=False)

            selected_method = form.cleaned_data.get('payment_method') or request.POST.get('payment_method', 'RAZORPAY')
            if selected_method not in ['RAZORPAY', 'COD']:
                selected_method = 'RAZORPAY'
            order.payment_method = selected_method
            order.is_paid = False

            # Atomic transaction with concurrency locking
            try:
                with transaction.atomic():
                    order.status = 'PENDING'
                    order.user = request.user
                    order.subtotal = cart.get_subtotal()
                    order.shipping_fee = cart.get_shipping()
                    order.discount_amount = cart.get_discount()
                    order.total_amount = cart.get_total()

                    # Handle coupon redemption atomically
                    if applied_coupon and order.discount_amount > 0:
                        redeemed = applied_coupon.redeem()
                        if not redeemed:
                            messages.error(request, "The applied coupon has expired or reached its usage limit.")
                            transaction.set_rollback(True)
                            return render(request, 'orders/checkout.html', context)
                        order.coupon_code = applied_coupon.code

                    order.save()

                    # Create order items with row-level stock locks
                    for item in cart:
                        product_id = item['product'].id
                        quantity = item['quantity']

                        # Concurrency safety: select_for_update prevents overselling
                        locked_product = Product.objects.select_for_update().get(id=product_id)

                        if locked_product.stock < quantity:
                            messages.error(
                                request,
                                f"Sorry, {locked_product.title} only has {locked_product.stock} units left in stock."
                            )
                            transaction.set_rollback(True)
                            return redirect('cart:cart_detail')

                        OrderItem.objects.create(
                            order=order,
                            product=locked_product,
                            price=item['price'],
                            quantity=quantity
                        )

                        # Decrement inventory
                        Product.objects.filter(id=product_id).update(stock=F('stock') - quantity)

                    if order.payment_method == 'RAZORPAY':
                        if not settings.RAZORPAY_KEY_ID or not settings.RAZORPAY_KEY_SECRET:
                            messages.error(request, "Razorpay payment keys are not configured. Please contact support.")
                            transaction.set_rollback(True)
                            return render(request, 'orders/checkout.html', context)

                        try:
                            client = razorpay.Client(auth=(settings.RAZORPAY_KEY_ID, settings.RAZORPAY_KEY_SECRET))
                            amount_paise = int(order.total_amount * 100)
                            razorpay_order = client.order.create({
                                'amount': amount_paise,
                                'currency': 'INR',
                                'receipt': order.order_number,
                                'payment_capture': 1,
                                'notes': {
                                    'order_number': order.order_number,
                                    'email': order.email,
                                    'phone': order.phone,
                                }
                            })
                            order.razorpay_order_id = razorpay_order['id']
                            order.save(update_fields=['razorpay_order_id'])
                        except Exception as rz_err:
                            logger.exception("Failed to create Razorpay order: %s", rz_err)
                            messages.error(request, "Could not initialize Razorpay payment. Please try another payment method.")
                            transaction.set_rollback(True)
                            return render(request, 'orders/checkout.html', context)
                    else:
                        cart.clear()

            except (IntegrityError, ValueError) as exc:
                logger.exception("Unable to place order for user %s", request.user.pk, exc_info=exc)
                messages.error(request, "An error occurred while placing your order. Please try again.")
                return render(request, 'orders/checkout.html', context)

            if order.payment_method == 'RAZORPAY':
                return redirect('orders:razorpay_payment', order_number=order.order_number)

            messages.success(request, f"Order #{order.order_number} has been placed successfully!")
            return redirect('orders:order_success', order_number=order.order_number)

        else:
            error_list = [f"{field.replace('_', ' ').title()}: {', '.join(errors)}" for field, errors in form.errors.items()]
            messages.error(request, f"Please fix the errors in the form: {' | '.join(error_list)}")
    else:
        initial_data = {
            'first_name': request.user.first_name or request.user.username,
            'last_name': request.user.last_name or '',
            'email': request.user.email or '',
        }
        context['form'] = OrderCreateForm(initial=initial_data)

    return render(request, 'orders/checkout.html', context)


@login_required
def order_success(request, order_number):
    """Displays order confirmation invoice and logistics status."""
    order = get_object_or_404(Order, order_number=order_number)
    if order.user != request.user and not request.user.is_staff:
        messages.error(request, "You do not have permission to view this order confirmation.")
        return redirect('store:home')
    return render(request, 'orders/order_success.html', {'order': order})


@login_required
def order_history(request):
    """Customer dashboard view of all previous orders."""
    user_orders = Order.objects.filter(user=request.user).order_by('-created_at')
    return render(request, 'orders/order_history.html', {'orders': user_orders})


@login_required
def order_detail(request, order_number):
    """Detailed invoice and tracking for a specific order."""
    order = get_object_or_404(Order, order_number=order_number)
    if order.user != request.user and not request.user.is_staff:
        messages.error(request, "You do not have permission to track or view this order.")
        return redirect('store:home')
    return render(request, 'orders/order_detail.html', {'order': order})


@login_required
def order_invoice(request, order_number):
    """Clean Tax Invoice view for printing and saving as PDF."""
    order = get_object_or_404(Order, order_number=order_number)
    if order.user != request.user and not request.user.is_staff:
        messages.error(request, "You do not have permission to view this invoice.")
        return redirect('store:home')
    return render(request, 'orders/invoice.html', {
        'order': order,
        'page_title': f'Tax Invoice #{order.order_number}',
    })


@login_required
@require_POST
def order_cancel(request, order_number):
    """Customer self-service order cancellation before shipment."""
    order = get_object_or_404(Order, order_number=order_number)

    # Permission check
    if order.user != request.user and not request.user.is_staff:
        messages.error(request, "You do not have permission to cancel this order.")
        return redirect('orders:order_history')

    # Already cancelled
    if order.status == 'CANCELLED':
        messages.warning(request, f"Order #{order.order_number} is already cancelled.")
        return redirect('orders:order_detail', order_number=order.order_number)

    # Status check
    if not order.can_cancel and not request.user.is_staff:
        messages.error(
            request,
            f"Order #{order.order_number} cannot be cancelled because it is already {order.get_status_display().lower()}. "
            "Please contact our support team for assistance."
        )
        return redirect('orders:order_detail', order_number=order.order_number)

    reason = request.POST.get('cancellation_reason', '').strip()
    custom_comment = request.POST.get('cancellation_comment', '').strip()
    full_reason = f"{reason} - {custom_comment}".strip(' -') if custom_comment else (reason or "Cancelled by customer")

    success = order.cancel_order(reason=full_reason)
    if success:
        if order.is_paid:
            messages.success(
                request,
                f"Order #{order.order_number} has been cancelled successfully. "
                "Your refund has been initiated and will credit to your original payment method in 3-5 business days."
            )
        else:
            messages.success(
                request,
                f"Order #{order.order_number} has been cancelled successfully."
            )
    else:
        messages.error(request, f"Unable to cancel order #{order.order_number}.")

    return redirect('orders:order_detail', order_number=order.order_number)


@login_required
def razorpay_payment_view(request, order_number):
    """Render Razorpay Checkout popup page for pending order."""
    order = get_object_or_404(Order, order_number=order_number, user=request.user)
    if order.is_paid:
        messages.info(request, f"Order #{order.order_number} is already paid.")
        return redirect('orders:order_success', order_number=order.order_number)

    if not order.razorpay_order_id:
        try:
            client = razorpay.Client(auth=(settings.RAZORPAY_KEY_ID, settings.RAZORPAY_KEY_SECRET))
            amount_paise = int(order.total_amount * 100)
            razorpay_order = client.order.create({
                'amount': amount_paise,
                'currency': 'INR',
                'receipt': order.order_number,
                'payment_capture': 1,
                'notes': {
                    'order_number': order.order_number,
                    'email': order.email,
                    'phone': order.phone,
                }
            })
            order.razorpay_order_id = razorpay_order['id']
            order.save(update_fields=['razorpay_order_id'])
        except Exception as exc:
            logger.exception("Failed creating Razorpay order: %s", exc)
            messages.error(request, "Failed to initialize payment gateway. Please contact support.")
            return redirect('orders:checkout')

    amount_paise = int(order.total_amount * 100)
    context = {
        'order': order,
        'razorpay_order_id': order.razorpay_order_id,
        'razorpay_key_id': settings.RAZORPAY_KEY_ID,
        'amount_paise': amount_paise,
        'currency': 'INR',
    }
    return render(request, 'orders/razorpay_payment.html', context)


@csrf_exempt
@require_POST
def razorpay_callback_view(request):
    """Verify Razorpay payment signature and mark order as paid."""
    razorpay_order_id = request.POST.get('razorpay_order_id', '').strip()
    razorpay_payment_id = request.POST.get('razorpay_payment_id', '').strip()
    razorpay_signature = request.POST.get('razorpay_signature', '').strip()

    if not razorpay_order_id or not razorpay_payment_id or not razorpay_signature:
        messages.error(request, "Incomplete payment verification payload from Razorpay.")
        return redirect('orders:checkout')

    order = get_object_or_404(Order, razorpay_order_id=razorpay_order_id)
    client = razorpay.Client(auth=(settings.RAZORPAY_KEY_ID, settings.RAZORPAY_KEY_SECRET))

    try:
        client.utility.verify_payment_signature({
            'razorpay_order_id': razorpay_order_id,
            'razorpay_payment_id': razorpay_payment_id,
            'razorpay_signature': razorpay_signature,
        })
        order.is_paid = True
        order.status = 'CONFIRMED'
        order.razorpay_payment_id = razorpay_payment_id
        order.razorpay_signature = razorpay_signature
        order.save(update_fields=['is_paid', 'status', 'razorpay_payment_id', 'razorpay_signature', 'updated_at'])

        cart = Cart(request)
        cart.clear()

        messages.success(request, f"Payment successful! Order #{order.order_number} confirmed via Razorpay.")
        return redirect('orders:order_success', order_number=order.order_number)

    except (razorpay.errors.SignatureVerificationError, Exception) as exc:
        logger.exception("Signature verification failed: %s", exc)
        messages.error(request, "Payment signature verification failed. Please contact support if your money was deducted.")
        return redirect('orders:order_detail', order_number=order.order_number)


# =========================================================================
# 4. CUSTOMER ACCOUNTS
# =========================================================================

def register_view(request):
    """Register a new customer account."""
    if request.user.is_authenticated:
        return redirect('store:home')

    if request.method == 'POST':
        post_data = request.POST.copy()
        if not post_data.get('username') and post_data.get('email'):
            post_data['username'] = post_data.get('email').split('@')[0]
            base_uname = post_data['username']
            counter = 1
            while User.objects.filter(username=post_data['username']).exists():
                post_data['username'] = f"{base_uname}{counter}"
                counter += 1

        form = UserRegisterForm(post_data)
        if form.is_valid():
            user = form.save()
            phone = form.cleaned_data.get('phone', '')

            profile, _ = UserProfile.objects.get_or_create(user=user)
            if phone:
                profile.phone = phone
                profile.save()

            try:
                subject = "Welcome to VoltCraft Smart Appliances!"
                message = (
                    f"Dear {user.first_name or user.username},\n\n"
                    f"Thank you for creating an account with VoltCraft Smart Appliances!\n\n"
                    f"Username: {user.username}\nRegistered Email: {user.email}\n\n"
                    f"Warm Regards,\nCustomer Support"
                )
                send_mail(
                    subject=subject,
                    message=message,
                    from_email=settings.DEFAULT_FROM_EMAIL,
                    recipient_list=[user.email],
                )
            except (OSError, SMTPException):
                logger.exception("Unable to send welcome email for user %s", user.pk)

            login(request, user)
            Cart(request).clear()
            messages.success(request, f"Welcome, {user.first_name or user.username}! Your account was created.")
            return redirect('accounts:profile')
    else:
        form = UserRegisterForm()

    return render(request, 'accounts/register.html', {'form': form})


def login_view(request):
    """Sign in existing user via username or email."""
    if request.user.is_authenticated:
        return redirect('store:home')

    raw_next = request.GET.get('next') or request.POST.get('next') or ''
    if raw_next and url_has_allowed_host_and_scheme(raw_next, allowed_hosts={request.get_host()}):
        next_url = raw_next
    else:
        next_url = reverse('store:home')

    if request.method == 'POST':
        login_input = request.POST.get('username', '').strip()
        password = request.POST.get('password', '')

        if '@' in login_input:
            user_obj = User.objects.filter(email__iexact=login_input).first()
            if user_obj:
                login_input = user_obj.username
        user = authenticate(request, username=login_input, password=password)
        if user is not None:
            login(request, user)
            Cart(request).clear()
            messages.success(request, f"Welcome back, {user.first_name or user.username}!")
            return redirect(next_url)
        else:
            messages.error(request, "Invalid email/username or password. Please try again.")
            form = UserLoginForm(request, data={'username': request.POST.get('username', ''), 'password': ''})
    else:
        form = UserLoginForm()

    return render(request, 'accounts/login.html', {'form': form, 'next': next_url})


@require_POST
def logout_view(request):
    """Log out customer."""
    logout(request)
    messages.info(request, "You have been logged out successfully.")
    return redirect('store:home')


@login_required
def profile_view(request):
    """Customer profile dashboard with photo upload and recent orders."""
    profile, _ = UserProfile.objects.get_or_create(user=request.user)

    if request.method == 'POST':
        form = UserProfileForm(request.POST, request.FILES, instance=request.user)
        if form.is_valid():
            form.save()
            if 'avatar' in request.FILES:
                profile.avatar = request.FILES['avatar']
                profile.save()
            messages.success(request, "Your profile details and photo have been updated successfully!")
            return redirect('accounts:profile')
    else:
        form = UserProfileForm(instance=request.user)

    orders = Order.objects.filter(user=request.user).order_by('-created_at')[:6]
    total_orders = Order.objects.filter(user=request.user).count()
    reward_points = total_orders * 50

    recently_viewed = get_recently_viewed_products(request, limit=6)
    recently_viewed_count = ProductView.objects.filter(user=request.user).values('product').distinct().count()

    context = {
        'form': form,
        'profile': profile,
        'orders': orders,
        'total_orders': total_orders,
        'returns_count': 0,
        'wishlist_count': 0,
        'reward_points': reward_points,
        'recently_viewed': recently_viewed,
        'recently_viewed_count': recently_viewed_count,
    }
    return render(request, 'accounts/profile.html', context)


def forgot_password_view(request):
    """Generate and email a 6-digit OTP for secure password recovery."""
    if request.user.is_authenticated:
        return redirect('store:home')
    if request.method == 'POST':
        email_or_user = request.POST.get('email', '').strip()
        input_phone = request.POST.get('phone', '').strip()

        # 1. à¦‡à¦®à§‡à¦‡à¦² à¦¬à¦¾ à¦‡à¦‰à¦œà¦¾à¦°à¦¨à§‡à¦® à¦¦à¦¿à§Ÿà§‡ à¦‡à¦‰à¦œà¦¾à¦° à¦–à§‹à¦à¦œà¦¾
        user = User.objects.filter(
            Q(email__iexact=email_or_user) | Q(username__iexact=email_or_user)
        ).first()

        if not user:
            messages.error(request, 'No registered user found with this email or username.')
            return render(request, 'accounts/forget_password.html')

        if not user.email:
            messages.error(request, 'This account has no registered email address.')
            return render(request, 'accounts/forget_password.html')

        # 2. à¦«à§‹à¦¨ à¦¨à¦®à§à¦¬à¦° à¦­à§à¦¯à¦¾à¦²à¦¿à¦¡à§‡à¦¶à¦¨ (à¦¯à¦¦à¦¿ à¦ªà§à¦°à§‹à¦«à¦¾à¦‡à¦²à§‡ à¦¥à¦¾à¦•à§‡)
        clean_input = ''.join(c for c in input_phone if c.isdigit())
        profile = getattr(user, 'profile', None)
        if profile and profile.phone:
            clean_db = ''.join(c for c in profile.phone if c.isdigit())
            if not clean_input or not (clean_input == clean_db or clean_db.endswith(clean_input[-10:]) or clean_input.endswith(clean_db[-10:])):
                messages.error(request, 'The provided phone number does not match the registered phone for this account.')
                return render(request, 'accounts/forget_password.html')

        # 3. à¦“à¦Ÿà¦¿à¦ªà¦¿ à¦¤à§ˆà¦°à¦¿ à¦“ à¦¸à§‡à¦¶à¦¨à§‡ à¦¸à¦‚à¦°à¦•à§à¦·à¦£
        otp = str(secrets.randbelow(900000) + 100000)
        request.session['reset_user_id'] = user.id
        request.session['reset_otp'] = otp
        request.session['reset_otp_created'] = timezone.now().timestamp()
        request.session['reset_otp_attempts'] = 0

        subject = 'Password Reset OTP - HomeHub Appliances'
        message = (
            f"Hello {user.first_name or user.username},\n\n"
            f"Your OTP to reset your password is: {otp}\n"
            f"This OTP is valid for 10 minutes.\n\n"
            f"Do not share this OTP with anyone."
        )

        try:
            send_mail(
                subject=subject,
                message=message,
                from_email=settings.DEFAULT_FROM_EMAIL,
                recipient_list=[user.email],
                fail_silently=False
            )
            messages.success(request, f'An OTP has been sent to your registered email address ({user.email}).')
            return redirect('accounts:reset_password_verify')
        except (OSError, SMTPException):
            logger.exception("Unable to send password reset email for user %s", user.pk)
            messages.error(request, 'We could not send the reset email. Please try again later.')

    return render(request, 'accounts/forget_password.html')
def reset_password_verify_view(request):
    """Verify submitted OTP within 10-minute expiry and update password."""
    user_id = request.session.get('reset_user_id')
    session_otp = request.session.get('reset_otp')
    otp_created = request.session.get('reset_otp_created', 0)
    # à¦«à¦¿à¦•à§à¦¸ à§©: à¦®à§‡à§Ÿà¦¾à¦¦ à¦¶à§‡à¦· à¦¹à¦²à§‡ à¦¸à§‡à¦¶à¦¨ à¦ªà§à¦°à§‹à¦ªà§à¦°à¦¿ à¦¡à¦¿à¦²à¦¿à¦Ÿ à¦•à¦°à§‡ à¦°à¦¿à¦¡à¦¾à¦‡à¦°à§‡à¦•à§à¦Ÿ à¦•à¦°à¦¬à§‡
    if not user_id or not session_otp or (timezone.now().timestamp() - otp_created > 600):
        request.session.pop('reset_user_id', None)
        request.session.pop('reset_otp', None)
        request.session.pop('reset_otp_created', None)
        request.session.pop('reset_otp_attempts', None)
        messages.warning(request, 'Your reset session has expired. Please request a new OTP.')
        return redirect('accounts:forgot_password')
    if request.method == 'POST':
        submitted_otp = request.POST.get('otp', '').strip()
        new_password = request.POST.get('new_password', '').strip()
        confirm_password = request.POST.get('confirm_password', '').strip()
        # à¦«à¦¿à¦•à§à¦¸ à§§: à§© à¦¬à¦¾à¦° à¦­à§à¦² à¦“à¦Ÿà¦¿à¦ªà¦¿ à¦¦à¦¿à¦²à§‡ à¦¸à§‡à¦¶à¦¨ à¦¬à§à¦²à¦• à¦¹à¦¬à§‡ (Brute Force Protection)
        if submitted_otp != session_otp:
            attempts = request.session.get('reset_otp_attempts', 0) + 1
            request.session['reset_otp_attempts'] = attempts
            if attempts >= 3:
                request.session.pop('reset_user_id', None)
                request.session.pop('reset_otp', None)
                request.session.pop('reset_otp_created', None)
                request.session.pop('reset_otp_attempts', None)
                messages.error(request, 'Too many invalid attempts. Your reset session has been cancelled.')
                return redirect('accounts:forgot_password')
            messages.error(request, f'Invalid OTP. You have {3 - attempts} attempt(s) left.')
            return render(request, 'accounts/reset_password_verify.html')
        elif len(new_password) < 8:
            messages.error(request, 'Password must be at least 8 characters long.')
        elif new_password != confirm_password:
            messages.error(request, 'Passwords do not match.')
        else:
            user = get_object_or_404(User, id=user_id)
            user.set_password(new_password)
            user.save()
            # à¦•à¦¾à¦œ à¦¶à§‡à¦· à¦¹à¦²à§‡ à¦¸à§‡à¦¶à¦¨ à¦•à§à¦²à¦¿à¦¨à¦†à¦ª
            request.session.pop('reset_user_id', None)
            request.session.pop('reset_otp', None)
            request.session.pop('reset_otp_created', None)
            request.session.pop('reset_otp_attempts', None)
            messages.success(request, 'Password has been reset successfully! Please sign in.')
            return redirect('accounts:login')
    return render(request, 'accounts/reset_password_verify.html')
# =========================================================================
# 5. ADMIN PORTAL (Staff Only)
# =========================================================================

def portal_login_view(request):
    """Staff-only admin portal sign-in."""
    if request.user.is_authenticated:
        if request.user.is_staff:
            return redirect('admin_portal:dashboard')
        messages.error(request, "Access Denied: Administrative area is restricted to staff only.")
        return redirect('store:home')

    if request.method == 'POST':
        username = request.POST.get('username', '').strip()
        password = request.POST.get('password', '').strip()

        if not username or not password:
            messages.error(request, "Please enter both username and password.")
        else:
            user = authenticate(request, username=username, password=password)
            if user is not None:
                if user.is_staff:
                    login(request, user)
                    Cart(request).clear()
                    messages.success(request, f"Welcome back, Administrator {user.username}!")
                    return redirect('admin_portal:dashboard')
                messages.error(request, "Access Denied: This account does not possess staff privileges.")
            else:
                messages.error(request, "Invalid admin username or password. Please try again.")

    return render(request, 'portal/login.html')


@admin_required
def dashboard_view(request):
    """Admin Dashboard with dynamic sales metrics and charts."""
    now = timezone.now()
    today = now.date()
    seven_days_ago = today - timedelta(days=6)

    orders_qs = Order.objects.all()
    products_qs = Product.objects.all()

    total_products = products_qs.count()
    total_orders = orders_qs.count()
    total_customers = User.objects.filter(is_staff=False).count()
    total_revenue = orders_qs.exclude(status='CANCELLED').aggregate(Sum('total_amount'))['total_amount__sum'] or Decimal('0.00')

    pending_orders_count = orders_qs.filter(status='PENDING').count()
    processing_orders_count = orders_qs.filter(status='CONFIRMED').count()
    shipped_orders_count = orders_qs.filter(status='SHIPPED').count()
    delivered_orders_count = orders_qs.filter(status='DELIVERED').count()

    in_stock_count = products_qs.filter(stock__gt=1, is_available=True).count()
    low_stock_products = products_qs.filter(stock=1, is_available=True).order_by('stock')[:5]
    low_stock_count = products_qs.filter(stock=1, is_available=True).count()

    orders_this_week = orders_qs.filter(created_at__date__gte=seven_days_ago).count()
    revenue_this_week = orders_qs.filter(created_at__date__gte=seven_days_ago).exclude(status='CANCELLED').aggregate(Sum('total_amount'))['total_amount__sum'] or Decimal('0.00')
    new_customers_this_week = User.objects.filter(is_staff=False, date_joined__date__gte=seven_days_ago).count()
    new_products_this_week = products_qs.filter(created_at__date__gte=seven_days_ago).count()

    current_date_range = f"{seven_days_ago.strftime('%d %b %Y')} â€“ {today.strftime('%d %b %Y')}"

    daily_sales = []
    for i in range(7):
        day_date = seven_days_ago + timedelta(days=i)
        day_rev = orders_qs.filter(created_at__date=day_date).exclude(status='CANCELLED').aggregate(Sum('total_amount'))['total_amount__sum'] or Decimal('0.00')
        daily_sales.append({
            'date': day_date,
            'label': day_date.strftime('%d %b'),
            'revenue': float(day_rev)
        })

    max_rev = max([d['revenue'] for d in daily_sales] + [10000.0])

    chart_nodes = []
    points = []
    for idx, d in enumerate(daily_sales):
        x = 40 + idx * (380 / 6)
        y = 175 - ((d['revenue'] / max_rev) * 135) if (max_rev > 0 and d['revenue'] > 0) else 175
        points.append(f"{x:.1f} {y:.1f}")
        chart_nodes.append({
            'cx': f"{x:.1f}",
            'cy': f"{y:.1f}",
            'label': d['label'],
            'revenue': int(d['revenue'])
        })

    sales_line_path = "M " + " L ".join(points)
    sales_area_path = f"{sales_line_path} L 420 180 L 40 180 Z"

    chart_y_top = f"â‚¹{max_rev/100000:.1f}L" if max_rev >= 100000 else f"â‚¹{int(max_rev):,}"
    chart_y_mid = f"â‚¹{(max_rev/2)/100000:.1f}L" if max_rev >= 100000 else f"â‚¹{int(max_rev/2):,}"

    circ = 238.76
    if total_orders > 0:
        delivered_pct = round((delivered_orders_count / total_orders) * 100, 1)
        processing_pct = round((processing_orders_count / total_orders) * 100, 1)
        shipped_pct = round((shipped_orders_count / total_orders) * 100, 1)
        pending_pct = round((pending_orders_count / total_orders) * 100, 1)

        deliv_dash = round((delivered_orders_count / total_orders) * circ, 1)
        proc_dash = round((processing_orders_count / total_orders) * circ, 1)
        ship_dash = round((shipped_orders_count / total_orders) * circ, 1)
        pend_dash = round((pending_orders_count / total_orders) * circ, 1)

        donut_deliv_offset = "0"
        donut_proc_offset = f"{-deliv_dash:.1f}"
        donut_ship_offset = f"{-(deliv_dash + proc_dash):.1f}"
        donut_pend_offset = f"{-(deliv_dash + proc_dash + ship_dash):.1f}"
    else:
        delivered_pct = processing_pct = shipped_pct = pending_pct = 0.0
        deliv_dash = proc_dash = ship_dash = pend_dash = 0.0
        donut_deliv_offset = donut_proc_offset = donut_ship_offset = donut_pend_offset = "0"

    recent_orders = orders_qs.prefetch_related('items__product').order_by('-created_at')[:6]
    top_selling_products = products_qs.filter(is_available=True).annotate(
        total_sales=Coalesce(Sum('orderitem__quantity'), Value(0), output_field=IntegerField())
    ).order_by('-total_sales', '-created_at')[:5]

    context = {
        'page_title': 'Dashboard',
        'active_menu': 'dashboard',
        'current_date_range': current_date_range,
        'total_revenue': total_revenue,
        'total_orders': total_orders,
        'total_products': total_products,
        'total_customers': total_customers,
        'pending_orders_count': pending_orders_count,
        'processing_orders_count': processing_orders_count,
        'shipped_orders_count': shipped_orders_count,
        'delivered_orders_count': delivered_orders_count,
        'in_stock_count': in_stock_count,
        'low_stock_count': low_stock_count,
        'low_stock_products': low_stock_products,
        'orders_this_week': orders_this_week,
        'revenue_this_week': revenue_this_week,
        'new_customers_this_week': new_customers_this_week,
        'new_products_this_week': new_products_this_week,
        'sales_line_path': sales_line_path,
        'sales_area_path': sales_area_path,
        'chart_nodes': chart_nodes,
        'chart_y_top': chart_y_top,
        'chart_y_mid': chart_y_mid,
        'delivered_pct': delivered_pct,
        'processing_pct': processing_pct,
        'shipped_pct': shipped_pct,
        'pending_pct': pending_pct,
        'donut_deliv_dash': f"{deliv_dash:.1f} {circ:.1f}",
        'donut_proc_dash': f"{proc_dash:.1f} {circ:.1f}",
        'donut_ship_dash': f"{ship_dash:.1f} {circ:.1f}",
        'donut_pend_dash': f"{pend_dash:.1f} {circ:.1f}",
        'donut_deliv_offset': donut_deliv_offset,
        'donut_proc_offset': donut_proc_offset,
        'donut_ship_offset': donut_ship_offset,
        'donut_pend_offset': donut_pend_offset,
        'recent_orders': recent_orders,
        'top_selling_products': top_selling_products,
        'recent_feedbacks': CustomerFeedback.objects.order_by('-created_at')[:4],
        'total_feedbacks_count': CustomerFeedback.objects.count(),
    }
    return render(request, 'portal/dashboard.html', context)


@admin_required
def products_view(request):
    products_qs = Product.objects.select_related('brand', 'category').order_by('-created_at')
    query = request.GET.get('q', '').strip()
    if query:
        products_qs = products_qs.filter(
            Q(title__icontains=query) |
            Q(sku__icontains=query) |
            Q(model_number__icontains=query) |
            Q(brand__name__icontains=query)
        )
    category_id = request.GET.get('category', '')
    if category_id:
        products_qs = products_qs.filter(category_id=category_id)

    paginator = Paginator(products_qs, 12)
    page_obj = paginator.get_page(request.GET.get('page'))

    return render(request, 'portal/products/list.html', {
        'page_title': 'Products',
        'active_menu': 'products',
        'page_obj': page_obj,
        'categories': Category.objects.all(),
        'query': query,
        'selected_category': category_id,
        'total_products': paginator.count,
    })


@admin_required
def product_create_view(request):
    if request.method == 'POST':
        form = ProductAdminForm(request.POST, request.FILES)
        if form.is_valid():
            product = form.save()
            messages.success(request, f"Appliance '{product.title}' has been added successfully.")
            return redirect('admin_portal:products')
    else:
        form = ProductAdminForm()

    return render(request, 'portal/products/form.html', {
        'page_title': 'Add New Appliance',
        'active_menu': 'products',
        'form': form,
        'is_edit': False,
    })


@admin_required
def product_edit_view(request, product_id):
    product = get_object_or_404(Product, id=product_id)
    if request.method == 'POST':
        form = ProductAdminForm(request.POST, request.FILES, instance=product)
        if form.is_valid():
            form.save()
            messages.success(request, f"Appliance '{product.title}' updated successfully.")
            return redirect('admin_portal:products')
    else:
        form = ProductAdminForm(instance=product)

    return render(request, 'portal/products/form.html', {
        'page_title': f'Edit {product.title}',
        'active_menu': 'products',
        'form': form,
        'product': product,
        'is_edit': True,
    })


@admin_required
@require_POST
def product_delete_view(request, product_id):
    product = get_object_or_404(Product, id=product_id)
    title = product.title
    try:
        product.delete()
        messages.warning(request, f"Appliance '{title}' has been deleted.")
    except ProtectedError:
        messages.error(request, f"Cannot delete '{title}' because it has associated orders. Set it to unavailable instead.")
    return redirect('admin_portal:products')


@admin_required
@require_POST
def product_delete_all_view(request):
    try:
        # Avoid deleting products linked to existing orders
        deletable = Product.objects.filter(orderitem__isnull=True)
        count = deletable.count()
        deletable.delete()
        messages.success(request, f"Deleted {count} products with no active order history.")
    except ProtectedError:
        messages.error(request, "Some products could not be deleted because they are attached to customer orders.")
    return redirect('admin_portal:products')


@admin_required
def categories_view(request):
    if request.method == 'POST':
        form = CategoryAdminForm(request.POST, request.FILES)
        if form.is_valid():
            cat = form.save()
            messages.success(request, f"Category '{cat.name}' created successfully.")
            return redirect('admin_portal:categories')
    else:
        form = CategoryAdminForm()

    categories = Category.objects.annotate(product_count=Count('products')).order_by('name')
    return render(request, 'portal/categories/list.html', {
        'page_title': 'Categories',
        'active_menu': 'categories',
        'categories': categories,
        'form': form,
    })


@admin_required
@require_POST
def category_delete_view(request, category_id):
    category = get_object_or_404(Category, id=category_id)
    name = category.name
    try:
        category.delete()
        messages.warning(request, f"Category '{name}' deleted.")
    except ProtectedError:
        messages.error(request, f"Cannot delete category '{name}' because it contains products.")
    return redirect('admin_portal:categories')


@admin_required
def brands_view(request):
    if request.method == 'POST':
        form = BrandAdminForm(request.POST)
        if form.is_valid():
            brand = form.save()
            messages.success(request, f"Brand '{brand.name}' added successfully.")
            return redirect('admin_portal:brands')
    else:
        form = BrandAdminForm()

    brands = Brand.objects.annotate(product_count=Count('products')).order_by('name')
    return render(request, 'portal/brands/list.html', {
        'page_title': 'Brands',
        'active_menu': 'brands',
        'brands': brands,
        'form': form,
    })


@admin_required
@require_POST
def brand_delete_view(request, brand_id):
    brand = get_object_or_404(Brand, id=brand_id)
    name = brand.name
    try:
        brand.delete()
        messages.warning(request, f"Brand '{name}' deleted.")
    except ProtectedError:
        messages.error(request, f"Cannot delete brand '{name}' because it contains products.")
    return redirect('admin_portal:brands')


@admin_required
def orders_view(request):
    orders_qs = Order.objects.prefetch_related('items').order_by('-created_at')
    status_filter = request.GET.get('status', '').strip()
    if status_filter:
        orders_qs = orders_qs.filter(status=status_filter)

    query = request.GET.get('q', '').strip()
    if query:
        orders_qs = orders_qs.filter(
            Q(order_number__icontains=query) |
            Q(first_name__icontains=query) |
            Q(last_name__icontains=query) |
            Q(email__icontains=query) |
            Q(phone__icontains=query)
        )

    paginator = Paginator(orders_qs, 15)
    page_obj = paginator.get_page(request.GET.get('page'))

    status_counts = {
        'all': Order.objects.count(),
        'PENDING': Order.objects.filter(status='PENDING').count(),
        'CONFIRMED': Order.objects.filter(status='CONFIRMED').count(),
        'SHIPPED': Order.objects.filter(status='SHIPPED').count(),
        'DELIVERED': Order.objects.filter(status='DELIVERED').count(),
        'CANCELLED': Order.objects.filter(status='CANCELLED').count(),
    }

    return render(request, 'portal/orders/list.html', {
        'page_title': 'Customer Orders',
        'active_menu': 'orders',
        'page_obj': page_obj,
        'selected_status': status_filter,
        'query': query,
        'status_counts': status_counts,
    })


@admin_required
def order_detail_view(request, order_number):
    order = get_object_or_404(Order, order_number=order_number)
    if request.method == 'POST':
        new_status = request.POST.get('status')
        is_paid = request.POST.get('is_paid') == 'on'
        if new_status in dict(Order.STATUS_CHOICES):
            if new_status == 'CANCELLED' and order.status != 'CANCELLED':
                reason = request.POST.get('cancellation_reason', '').strip() or 'Cancelled by store administrator'
                order.cancel_order(reason=reason)
                order.is_paid = is_paid
                order.save(update_fields=['is_paid'])
            else:
                order.status = new_status
                order.is_paid = is_paid
                order.save()
            messages.success(request, f"Order #{order.order_number} updated to {order.get_status_display()}.")
            return redirect('admin_portal:order_detail', order_number=order.order_number)

    return render(request, 'portal/orders/detail.html', {
        'page_title': f'Order #{order.order_number}',
        'active_menu': 'orders',
        'order': order,
        'status_choices': Order.STATUS_CHOICES,
    })


@admin_required
@require_POST
def order_delete_view(request, order_number):
    order = get_object_or_404(Order, order_number=order_number)
    order.delete()
    messages.warning(request, f"Order #{order_number} has been deleted permanently.")
    return redirect('admin_portal:orders')


@admin_required
@require_POST
def order_delete_all_view(request):
    with transaction.atomic():
        count = Order.objects.count()
        OrderItem.objects.all().delete()
        Order.objects.all().delete()
    messages.success(request, f"All {count} orders have been deleted permanently.")
    return redirect('admin_portal:orders')


@admin_required
def customers_view(request):
    customers = User.objects.filter(is_staff=False).annotate(
        order_count=Count('orders'),
        total_spend=Sum('orders__total_amount')
    ).order_by('-date_joined')

    query = request.GET.get('q', '').strip()
    if query:
        customers = customers.filter(
            Q(username__icontains=query) |
            Q(first_name__icontains=query) |
            Q(last_name__icontains=query) |
            Q(email__icontains=query)
        )

    paginator = Paginator(customers, 20)
    page_obj = paginator.get_page(request.GET.get('page'))

    return render(request, 'portal/customers/list.html', {
        'page_title': 'Customers',
        'active_menu': 'customers',
        'page_obj': page_obj,
        'query': query,
        'total_customers': paginator.count,
    })


@admin_required
@require_POST
def customer_delete_view(request, customer_id):
    customer = get_object_or_404(User, id=customer_id, is_staff=False)
    name = customer.get_full_name() or customer.username
    customer.delete()
    messages.warning(request, f"Customer account '{name}' has been deleted permanently.")
    return redirect('admin_portal:customers')


@admin_required
def inventory_view(request):
    products_qs = Product.objects.select_related('brand', 'category').order_by('stock')
    filter_type = request.GET.get('type', 'all')
    if filter_type == 'out_of_stock':
        products_qs = products_qs.filter(stock=0)
    elif filter_type == 'low_stock':
        products_qs = products_qs.filter(stock__gt=0, stock__lte=5)
    elif filter_type == 'in_stock':
        products_qs = products_qs.filter(stock__gt=5)

    counts = {
        'all': Product.objects.count(),
        'out_of_stock': Product.objects.filter(stock=0).count(),
        'low_stock': Product.objects.filter(stock__gt=0, stock__lte=5).count(),
        'in_stock': Product.objects.filter(stock__gt=5).count(),
    }

    paginator = Paginator(products_qs, 15)
    page_obj = paginator.get_page(request.GET.get('page'))

    return render(request, 'portal/inventory/list.html', {
        'page_title': 'Inventory Management',
        'active_menu': 'inventory',
        'page_obj': page_obj,
        'counts': counts,
        'filter_type': filter_type,
    })


@admin_required
@require_POST
def inventory_quick_update_view(request, product_id):
    product = get_object_or_404(Product, id=product_id)
    try:
        new_stock = max(0, int(request.POST.get('stock', product.stock)))
        product.stock = new_stock
        product.save(update_fields=['stock'])
        messages.success(request, f"Updated stock for '{product.title}' to {product.stock} units.")
    except (ValueError, TypeError):
        messages.error(request, "Invalid stock value provided.")
    return redirect('admin_portal:inventory')


@admin_required
def coupons_view(request):
    if request.method == 'POST':
        form = CouponAdminForm(request.POST)
        if form.is_valid():
            coupon = form.save()
            messages.success(request, f"Coupon code '{coupon.code}' created successfully!")
            return redirect('admin_portal:coupons')
        messages.error(request, "Coupon could not be created. Please check fields.")
    else:
        form = CouponAdminForm(initial={
            'valid_from': timezone.now().date(),
            'valid_until': timezone.now().date() + timedelta(days=30),
        })

    coupons = Coupon.objects.all().order_by('-created_at')
    return render(request, 'portal/coupons/list.html', {
        'page_title': 'Coupons & Promo Codes',
        'active_menu': 'coupons',
        'coupons': coupons,
        'form': form,
    })


@admin_required
@require_POST
def coupon_toggle_view(request, coupon_id):
    coupon = get_object_or_404(Coupon, id=coupon_id)
    coupon.is_active = not coupon.is_active
    coupon.save(update_fields=['is_active'])
    status_str = "activated" if coupon.is_active else "deactivated"
    messages.info(request, f"Coupon '{coupon.code}' {status_str}.")
    return redirect('admin_portal:coupons')


@admin_required
@require_POST
def coupon_delete_view(request, coupon_id):
    coupon = get_object_or_404(Coupon, id=coupon_id)
    code = coupon.code
    coupon.delete()
    messages.warning(request, f"Coupon '{code}' deleted.")
    return redirect('admin_portal:coupons')


@admin_required
def banners_view(request):
    if request.method == 'POST':
        form = BannerAdminForm(request.POST, request.FILES)
        if form.is_valid():
            banner = form.save()
            messages.success(request, f"Promotional banner '{banner.title}' added!")
            return redirect('admin_portal:banners')
    else:
        form = BannerAdminForm()

    banners = Banner.objects.all().order_by('order', '-created_at')
    return render(request, 'portal/banners/list.html', {
        'page_title': 'Hero & Promotional Banners',
        'active_menu': 'banners',
        'banners': banners,
        'form': form,
    })


@admin_required
@require_POST
def banner_toggle_view(request, banner_id):
    banner = get_object_or_404(Banner, id=banner_id)
    banner.is_active = not banner.is_active
    banner.save(update_fields=['is_active'])
    messages.info(request, f"Banner '{banner.title}' active status toggled.")
    return redirect('admin_portal:banners')


@admin_required
@require_POST
def banner_delete_view(request, banner_id):
    banner = get_object_or_404(Banner, id=banner_id)
    title = banner.title
    banner.delete()
    messages.warning(request, f"Banner '{title}' deleted.")
    return redirect('admin_portal:banners')


@admin_required
def reviews_view(request):
    reviews_qs = Review.objects.select_related('product', 'user').order_by('-created_at')
    rating_filter = request.GET.get('rating', '')
    if rating_filter:
        reviews_qs = reviews_qs.filter(rating=rating_filter)

    paginator = Paginator(reviews_qs, 15)
    page_obj = paginator.get_page(request.GET.get('page'))

    return render(request, 'portal/reviews/list.html', {
        'page_title': 'Customer Reviews',
        'active_menu': 'reviews',
        'page_obj': page_obj,
        'selected_rating': rating_filter,
        'total_reviews': paginator.count,
    })


@admin_required
@require_POST
def review_delete_view(request, review_id):
    review = get_object_or_404(Review, id=review_id)
    review.delete()
    messages.warning(request, "Customer review has been deleted.")
    return redirect('admin_portal:reviews')


@admin_required
def portal_feedback_list(request):
    """Admin portal: View and manage all customer feedback and inquiries."""
    feedbacks_qs = CustomerFeedback.objects.all().select_related('user').order_by('-created_at')

    rating_filter = request.GET.get('rating', '').strip()
    if rating_filter in ['1', '2', '3', '4', '5']:
        feedbacks_qs = feedbacks_qs.filter(rating=int(rating_filter))

    type_filter = request.GET.get('type', '').strip()
    if type_filter:
        feedbacks_qs = feedbacks_qs.filter(feedback_type=type_filter)

    search_query = request.GET.get('q', '').strip()
    if search_query:
        feedbacks_qs = feedbacks_qs.filter(
            Q(name__icontains=search_query) |
            Q(email__icontains=search_query) |
            Q(phone__icontains=search_query) |
            Q(subject__icontains=search_query) |
            Q(message__icontains=search_query) |
            Q(order_number__icontains=search_query)
        )

    paginator = Paginator(feedbacks_qs, 15)
    page_obj = paginator.get_page(request.GET.get('page'))

    total_feedbacks = CustomerFeedback.objects.count()
    avg_aggregate = CustomerFeedback.objects.aggregate(avg=Avg('rating'))['avg']
    avg_rating = round(float(avg_aggregate), 1) if avg_aggregate else 5.0

    return render(request, 'portal/feedback/list.html', {
        'page_title': 'Customer Feedback & Ratings',
        'active_menu': 'customer_feedback',
        'page_obj': page_obj,
        'selected_rating': rating_filter,
        'selected_type': type_filter,
        'search_query': search_query,
        'total_feedbacks': total_feedbacks,
        'avg_rating': avg_rating,
    })


@admin_required
def portal_feedback_toggle_approve(request, feedback_id):
    """Toggle whether feedback is displayed publicly."""
    feedback = get_object_or_404(CustomerFeedback, id=feedback_id)
    feedback.is_approved = not feedback.is_approved
    feedback.save(update_fields=['is_approved'])
    status_label = "Approved (Visible to Public)" if feedback.is_approved else "Hidden from Public"
    messages.info(request, f"Feedback #{feedback.id} status updated to: {status_label}")
    return redirect('admin_portal:feedback_list')


@admin_required
def portal_feedback_reply(request, feedback_id):
    """Add or update admin reply to customer feedback."""
    feedback = get_object_or_404(CustomerFeedback, id=feedback_id)
    if request.method == 'POST':
        admin_reply = request.POST.get('admin_reply', '').strip()
        is_approved = 'is_approved' in request.POST
        is_featured = 'is_featured' in request.POST
        feedback.admin_reply = admin_reply
        feedback.is_approved = is_approved
        feedback.is_featured = is_featured
        feedback.save(update_fields=['admin_reply', 'is_approved', 'is_featured'])
        messages.success(request, f"Official reply & visibility saved for Feedback #{feedback.id}.")
    return redirect('admin_portal:feedback_list')


@admin_required
@require_POST
def portal_feedback_delete(request, feedback_id):
    """Delete a customer feedback item."""
    feedback = get_object_or_404(CustomerFeedback, id=feedback_id)
    feedback.delete()
    messages.warning(request, "Customer feedback entry has been deleted.")
    return redirect('admin_portal:feedback_list')



@admin_required
def settings_view(request):
    settings_obj = StoreSetting.get_settings()
    if request.method == 'POST':
        form = StoreSettingForm(request.POST, instance=settings_obj)
        if form.is_valid():
            form.save()
            messages.success(request, "Store configuration settings saved successfully!")
            return redirect('admin_portal:settings')
    else:
        form = StoreSettingForm(instance=settings_obj)

    return render(request, 'portal/settings.html', {
        'page_title': 'Store Settings',
        'active_menu': 'settings',
        'form': form,
        'settings': settings_obj,
    })


@admin_required
def portal_product_views_view(request):
    """Staff portal view product system: analytics, traffic, and most viewed appliances."""
    total_views = ProductView.objects.count()
    unique_users = ProductView.objects.filter(user__isnull=False).values('user').distinct().count()
    unique_guests = ProductView.objects.filter(user__isnull=True).values('session_key').distinct().count()

    # Most viewed appliances
    top_viewed_products = Product.objects.annotate(
        view_count=Count('views_history')
    ).filter(view_count__gt=0).order_by('-view_count')[:10]

    # Browsing activity logs
    logs_qs = ProductView.objects.select_related('product__brand', 'product__category', 'user').order_by('-viewed_at')

    query = request.GET.get('q', '').strip()
    if query:
        logs_qs = logs_qs.filter(
            Q(product__title__icontains=query) |
            Q(user__username__icontains=query) |
            Q(session_key__icontains=query)
        )

    paginator = Paginator(logs_qs, 20)
    page_obj = paginator.get_page(request.GET.get('page'))

    return render(request, 'portal/product_views.html', {
        'page_title': 'Product Views & Analytics',
        'active_menu': 'product_views',
        'total_views': total_views,
        'unique_users': unique_users,
        'unique_guests': unique_guests,
        'top_viewed_products': top_viewed_products,
        'page_obj': page_obj,
        'query': query,
    })


@admin_required
@require_POST
def portal_clear_views_view(request):
    """Clear product browsing history logs from admin portal."""
    count = ProductView.objects.count()
    ProductView.objects.all().delete()
    messages.success(request, f"Successfully cleared all {count} product view tracking records.")
    return redirect('admin_portal:product_views')
