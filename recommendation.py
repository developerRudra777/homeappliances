"""
AI & Machine Learning Recommendation Engine for HomeHub Appliances.

Techniques & Algorithms:
1. NLP Feature Extraction: Term Frequency-Inverse Document Frequency (TF-IDF)
   via scikit-learn's `TfidfVectorizer`.
2. Vector Similarity: `cosine_similarity` for calculating angular similarity
   between high-dimensional appliance text vectors.
3. Content-Based Filtering: Recommending appliances with similar specifications,
   energy ratings, dimensions, and descriptions.
4. Personalized User Preference Profiling: Synthesizing user taste vectors
   from previous orders and browsing history (ProductView) to recommend tailor-made products.
5. Semantic Smart Search: Vectorizing natural language queries to match relevant appliances
   even when exact keyword substrings do not match.
"""

import logging
from typing import List, Optional
import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

from django.db.models import QuerySet
from django.contrib.auth.models import User
from .models import Product, OrderItem, ProductView

logger = logging.getLogger(__name__)


def get_product_text(product: Product) -> str:
    """Extract and combine rich technical attributes and metadata of an appliance

    into a unified natural language document for vectorization.
    """
    specs_list = []
    try:
        specs_list = [f"{s.spec_key} {s.spec_value}" for s in product.specifications.all()]
    except Exception:
        pass
    specs_text = " ".join(specs_list)

    tokens = [
        product.title or "",
        product.brand.name if product.brand else "",
        product.category.name if product.category else "",
        product.energy_rating or "",
        product.capacity or "",
        product.color or "",
        product.warranty or "",
        product.power_consumption or "",
        product.dimensions or "",
        product.summary or "",
        product.description or "",
        specs_text,
    ]
    return " ".join(tokens)


def get_similar_appliances(product_id: int, limit: int = 4) -> List[Product]:
    """Find the most similar appliances using TF-IDF and Cosine Similarity (Content-Based Filtering).

    Falls back gracefully to category/brand matching if ML dataset is small.
    """
    try:
        products = list(
            Product.objects.filter(is_available=True)
            .select_related('brand', 'category')
            .prefetch_related('specifications')
        )

        if not products or len(products) <= 1:
            return []

        target_product = next((p for p in products if p.id == product_id), None)
        if not target_product:
            return []

        documents = [get_product_text(p) for p in products]

        vectorizer = TfidfVectorizer(
            stop_words='english',
            token_pattern=r'(?u)\b\w+\b',
            ngram_range=(1, 2),
            max_features=2500,
        )
        tfidf_matrix = vectorizer.fit_transform(documents)

        target_index = products.index(target_product)
        similarity_scores = cosine_similarity(tfidf_matrix[target_index], tfidf_matrix).flatten()

        # Prioritize appliances from the exact same category
        # If other products in the same category exist, prioritize them first
        same_cat_exists = any(p.category_id == target_product.category_id and p.id != product_id for p in products)
        if same_cat_exists:
            for idx, candidate in enumerate(products):
                if candidate.category_id != target_product.category_id:
                    similarity_scores[idx] -= 10.0

        ranked_indices = similarity_scores.argsort()[::-1]

        recommended: List[Product] = []
        for idx in ranked_indices:
            candidate = products[idx]
            if candidate.id == product_id or similarity_scores[idx] < 0:
                continue
            # Store similarity score on the instance for optional badge display
            candidate.ai_similarity_score = round(float(similarity_scores[idx]) * 100, 1)
            recommended.append(candidate)
            if len(recommended) >= limit:
                break

        return recommended

    except Exception as exc:
        logger.exception("Error calculating similar appliances for product %s", product_id, exc_info=exc)
        # Safe fallback: same category or brand
        return list(
            Product.objects.filter(is_available=True)
            .exclude(id=product_id)[:limit]
        )


def get_personalized_recommendations(
    user: Optional[User] = None,
    session_key: Optional[str] = None,
    limit: int = 4
) -> List[Product]:
    """Build a personalized User Taste Vector from past orders and browsing history (ProductView),

    then calculate cosine similarity against available appliances.
    """
    try:
        interacted_product_ids = set()

        if user and user.is_authenticated:
            # 1. Past purchased appliances
            ordered_ids = OrderItem.objects.filter(order__user=user).values_list('product_id', flat=True)
            interacted_product_ids.update(ordered_ids)

            # 2. Recently viewed appliances
            viewed_ids = ProductView.objects.filter(user=user).values_list('product_id', flat=True)[:10]
            interacted_product_ids.update(viewed_ids)

        elif session_key:
            # Guest visitor interaction tracking via session
            viewed_ids = ProductView.objects.filter(session_key=session_key).values_list('product_id', flat=True)[:10]
            interacted_product_ids.update(viewed_ids)

        all_products = list(
            Product.objects.filter(is_available=True)
            .select_related('brand', 'category')
            .prefetch_related('specifications')
        )

        if not all_products:
            return []

        # If user has no browsing or purchase history (cold start) -> return featured/top-rated deals
        if not interacted_product_ids:
            featured = [p for p in all_products if p.is_featured or p.is_deal_of_the_day][:limit]
            if len(featured) < limit:
                featured += [p for p in all_products if p not in featured][:limit - len(featured)]
            return featured

        documents = [get_product_text(p) for p in all_products]

        vectorizer = TfidfVectorizer(
            stop_words='english',
            token_pattern=r'(?u)\b\w+\b',
            ngram_range=(1, 2),
            max_features=2500,
        )
        tfidf_matrix = vectorizer.fit_transform(documents)

        interacted_indices = [
            i for i, p in enumerate(all_products)
            if p.id in interacted_product_ids
        ]

        if not interacted_indices:
            return all_products[:limit]

        # Calculate mean vector across all interacted products to represent the user's taste profile
        user_taste_vector = tfidf_matrix[interacted_indices].mean(axis=0)
        # Convert np.matrix/sparse to 2D array format for cosine_similarity
        user_taste_vector = np.asarray(user_taste_vector)

        similarity_scores = cosine_similarity(user_taste_vector, tfidf_matrix).flatten()
        ranked_indices = similarity_scores.argsort()[::-1]

        recommendations: List[Product] = []
        for idx in ranked_indices:
            candidate = all_products[idx]
            # Prioritize items not yet purchased
            candidate.ai_match_score = round(float(similarity_scores[idx]) * 100, 1)
            recommendations.append(candidate)
            if len(recommendations) >= limit:
                break

        return recommendations

    except Exception as exc:
        logger.exception("Error generating personalized recommendations for user %s", user, exc_info=exc)
        return list(Product.objects.filter(is_available=True)[:limit])


def smart_semantic_search(query_text: str, limit: int = 12) -> List[Product]:
    """Semantic vector search: transforms natural language search query into TF-IDF vector

    space and ranks appliances by cosine similarity.
    """
    query_text = (query_text or "").strip()
    if not query_text:
        return []

    try:
        products = list(
            Product.objects.filter(is_available=True)
            .select_related('brand', 'category')
            .prefetch_related('specifications')
        )
        if not products:
            return []

        documents = [get_product_text(p) for p in products]

        vectorizer = TfidfVectorizer(
            stop_words='english',
            token_pattern=r'(?u)\b\w+\b',
            ngram_range=(1, 2),
        )
        tfidf_matrix = vectorizer.fit_transform(documents)

        query_vector = vectorizer.transform([query_text])
        similarity_scores = cosine_similarity(query_vector, tfidf_matrix).flatten()

        ranked_indices = similarity_scores.argsort()[::-1]

        results = []
        for idx in ranked_indices:
            score = similarity_scores[idx]
            if score > 0.05:  # Relevance threshold
                prod = products[idx]
                prod.search_relevance = round(float(score) * 100, 1)
                results.append(prod)
            if len(results) >= limit:
                break

        return results

    except Exception as exc:
        logger.exception("Error in smart semantic search for query '%s'", query_text, exc_info=exc)
        return []


# Alias for convenience
smart_search_appliances = smart_semantic_search

