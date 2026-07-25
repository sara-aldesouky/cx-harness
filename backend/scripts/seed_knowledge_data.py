"""Seed deterministic approved knowledge for local development and demos."""

import sys
from datetime import datetime, timedelta, timezone
from uuid import NAMESPACE_URL, uuid5

from sqlalchemy import func, select

from app.database.models import KnowledgeArticle, KnowledgeArticleVersion
from app.database.session import get_session_factory

BASE_TIME = datetime(2026, 7, 1, 9, 0, tzinfo=timezone.utc)

APPROVED_ARTICLES = (
    ("refund-policy", "policy", "Refund Policy", "Eligible orders may receive a full or partial refund after review under the published refund policy."),
    ("refund-processing-time", "refund", "Refund Processing Time", "Approved refunds normally appear within three to five business days, depending on the payment method."),
    ("order-cancellation", "orders", "Order Cancellation", "Orders may be cancelled before preparation begins. Availability depends on the current order stage."),
    ("delivery-hours", "delivery", "Delivery Hours", "Deliveries are available daily from 8 AM to 10 PM, subject to local service availability."),
    ("delivery-address-changes", "delivery", "Delivery Address Changes", "A delivery address may be changed before dispatch when the new address remains within the supported area."),
    ("missing-items", "orders", "Missing Items", "Report a missing item through customer care with the order number and affected item name."),
    ("accepted-payment-methods", "payment", "Accepted Payment Methods", "Accepted methods may include cards, supported wallets, bank transfer, or cash where shown at checkout."),
    ("failed-payments", "payment", "Failed Payments", "A failed payment does not confirm an order. Check the payment status before trying again."),
    ("delivery-delays", "delivery", "Delivery Delays", "Delivery estimates may change because of demand, traffic, weather, or operational disruption."),
    ("contact-customer-care", "faq", "Contacting Customer Care", "Customer care is available through the help area in the application during published service hours."),
    ("promotions", "faq", "Promotions", "Promotion eligibility and expiry are shown in the offer terms. Promotions cannot be applied after expiry."),
    ("order-modifications", "orders", "Order Modifications", "Items may be changed only before preparation begins and when inventory remains available."),
    ("replacement-policy", "policy", "Replacement Policy", "When an item is unavailable, an approved replacement may be offered according to the selected replacement preference."),
    ("delivery-windows", "delivery", "Delivery Windows", "Available delivery windows are displayed during checkout and may vary by address and capacity."),
    ("general-faq", "faq", "General FAQ", "For account-specific information, provide the requested reference so the system can check trusted business records."),
)


def current_counts(session) -> tuple[int, int]:  # type: ignore[no-untyped-def]
    return (
        session.scalar(select(func.count()).select_from(KnowledgeArticle)) or 0,
        session.scalar(select(func.count()).select_from(KnowledgeArticleVersion)) or 0,
    )


def seed(session) -> tuple[int, int]:  # type: ignore[no-untyped-def]
    """Insert the complete deterministic dataset or safely skip existing data."""
    if any(current_counts(session)):
        return (0, 0)
    article_count = version_count = 0
    for index, (slug, category, title, content) in enumerate(APPROVED_ARTICLES):
        article = KnowledgeArticle(id=uuid5(NAMESPACE_URL, f"cx-harness/knowledge/{slug}"), slug=slug, category=category, language="en", is_active=True, created_at=BASE_TIME, updated_at=BASE_TIME + timedelta(days=index))
        session.add(article)
        versions = [("1.0", content, BASE_TIME + timedelta(days=index))]
        if slug == "refund-policy":
            versions = [("1.0", "Eligible orders may receive a refund after review.", BASE_TIME), ("2.0", content, BASE_TIME + timedelta(days=14))]
        for version, body, published_at in versions:
            session.add(KnowledgeArticleVersion(id=uuid5(NAMESPACE_URL, f"cx-harness/knowledge/{slug}/{version}"), article=article, version=version, title=title, content=body, is_published=True, published_at=published_at))
            version_count += 1
        article_count += 1

    inactive = KnowledgeArticle(id=uuid5(NAMESPACE_URL, "cx-harness/knowledge/inactive-example"), slug="inactive-example", category="faq", language="en", is_active=False, created_at=BASE_TIME, updated_at=BASE_TIME)
    session.add(inactive)
    session.add(KnowledgeArticleVersion(id=uuid5(NAMESPACE_URL, "cx-harness/knowledge/inactive-example/1.0"), article=inactive, version="1.0", title="Inactive Example", content="This inactive content must never be returned.", is_published=True, published_at=BASE_TIME))
    draft = KnowledgeArticle(id=uuid5(NAMESPACE_URL, "cx-harness/knowledge/unpublished-example"), slug="unpublished-example", category="faq", language="en", is_active=True, created_at=BASE_TIME, updated_at=BASE_TIME)
    session.add(draft)
    session.add(KnowledgeArticleVersion(id=uuid5(NAMESPACE_URL, "cx-harness/knowledge/unpublished-example/1.0"), article=draft, version="1.0", title="Unpublished Example", content="This draft content must never be returned.", is_published=False, published_at=BASE_TIME))
    return (article_count + 2, version_count + 2)


def main() -> int:
    session = get_session_factory()()
    try:
        articles, versions = seed(session)
        if articles == 0:
            print("Knowledge seeding skipped: knowledge data already exists.")
        else:
            session.commit()
            print(f"Knowledge seeded successfully: {articles} articles, {versions} versions.")
        return 0
    except Exception as error:
        session.rollback()
        print(f"Knowledge seeding failed ({type(error).__name__}): {error}", file=sys.stderr)
        return 1
    finally:
        session.close()


if __name__ == "__main__":
    raise SystemExit(main())
