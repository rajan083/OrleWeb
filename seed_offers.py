# seed_data.py
#
# Populates the local database with sample men's formalwear products and
# offers, matching ORLE's target buyer (men only).
#
# Run with:
#   python seed_data.py
#
# Safe to re-run — clears existing Product/Offer rows first so re-running
# doesn't create duplicates.

from main import app
from models import db, Product, Offer

sample_products = [
    Product(
        name="The Charcoal Two-Piece Suit", description="Classic wool-blend two-piece suit, notch lapel.",
        price=54200, category="suit",
        image_url="https://images.unsplash.com/photo-1594938298603-c8148c4dae35?w=500&q=80",
        best_for_body_types="rectangle,athletic", best_for_occasions="business,wedding",
        fit_note="Tailored through the chest, tapered leg. Best for business formal, wedding guest."
    ),
    Product(
        name="Midnight Tuxedo", description="Satin-lapel tuxedo, single-button close.",
        price=68500, category="tuxedo",
        image_url="https://images.unsplash.com/photo-1507679799987-c73779587ccf?w=500&q=80",
        best_for_body_types="athletic,rectangle", best_for_occasions="black_tie,wedding",
        fit_note="Structured shoulder, satin peak lapel. Best for black tie, wedding ceremony."
    ),
    Product(
        name="Ivory Bandhgala Suit", description="Mandarin-collar bandhgala in raw silk.",
        price=61000, category="suit",
        image_url="https://images.unsplash.com/photo-1622519407650-3df9883f76a5?w=500&q=80",
        best_for_body_types="slim,athletic", best_for_occasions="wedding,festival",
        fit_note="Closed collar, structured through the torso. Best for wedding ceremony, festival."
    ),
    Product(
        name="The Sherwani — Emerald", description="Hand-embroidered sherwani, silk lining.",
        price=72500, category="sherwani",
        image_url="https://images.unsplash.com/photo-1553516581-4d5f8b8f2e05?w=500&q=80",
        best_for_body_types="all", best_for_occasions="wedding,festival",
        fit_note="Floor-length silhouette, structured shoulder. Best for wedding ceremony, festival."
    ),
    Product(
        name="Sable Wool Blazer", description="Single-breasted wool blazer, notch lapel.",
        price=29800, category="blazer",
        image_url="https://images.unsplash.com/photo-1521572163474-6864f9cf17ab?w=500&q=80",
        best_for_body_types="rectangle,triangle", best_for_occasions="business,everyday",
        fit_note="Structured shoulder, single-button close. Best for business, everyday refined."
    ),
    Product(
        name="Ivory Linen Blazer", description="Unstructured linen blazer for warm-weather formal.",
        price=27500, category="blazer",
        image_url="https://images.unsplash.com/photo-1591047139829-d91aecb6caea?w=500&q=80",
        best_for_body_types="all", best_for_occasions="wedding,everyday",
        fit_note="Unstructured, breathable. Best for wedding guest, warm-climate business casual."
    ),
    Product(
        name="Tailored Wool Trouser", description="High-rise tailored trouser, straight leg.",
        price=18200, category="trouser",
        image_url="https://images.unsplash.com/photo-1594938291221-94f18cbb5660?w=500&q=80",
        best_for_body_types="all", best_for_occasions="business,everyday",
        fit_note="High-rise, straight leg. Pairs with most jacket silhouettes."
    ),
    Product(
        name="The Brass-Button Overcoat", description="Belted wool overcoat, structured shoulder.",
        price=52300, category="outerwear",
        image_url="https://images.unsplash.com/photo-1520975954732-35dd22299614?w=500&q=80",
        best_for_body_types="rectangle,apple", best_for_occasions="business,everyday",
        fit_note="Belted waist, structured shoulder. Best for rectangle, apple body types."
    ),
    Product(
        name="Structured Poplin Shirt", description="Crisp cotton poplin, French cuff.",
        price=12400, category="shirt",
        image_url="https://images.unsplash.com/photo-1602810318383-e386cc2a3ccf?w=500&q=80",
        best_for_body_types="all", best_for_occasions="business,everyday",
        fit_note="Structured through the shoulder, tapered waist. A foundational piece for most builds."
    ),
    Product(
        name="Silk Waistcoat", description="Three-piece suit waistcoat, silk-backed.",
        price=14800, category="waistcoat",
        image_url="https://images.unsplash.com/photo-1617137968427-85924c800a22?w=500&q=80",
        best_for_body_types="rectangle,athletic", best_for_occasions="wedding,black_tie",
        fit_note="Fitted through the torso. Layers under a suit jacket for black tie, wedding."
    ),
    Product(
        name="The Tan Tuxedo", description="Warm-toned tuxedo, shawl collar.",
        price=64900, category="tuxedo",
        image_url="https://images.unsplash.com/photo-1553484771-047a44eee27a?w=500&q=80",
        best_for_body_types="athletic,rectangle", best_for_occasions="black_tie,wedding",
        fit_note="Shawl collar, tapered leg. A distinctive alternative to classic black tie."
    ),
    Product(
        name="Business Two-Piece — Navy", description="Slim-fit navy suit, two-button close.",
        price=49500, category="suit",
        image_url="https://images.unsplash.com/photo-1600180758890-6b94519a8ba6?w=500&q=80",
        best_for_body_types="slim,athletic", best_for_occasions="business",
        fit_note="Slim through the body, tapered leg. Best for business formal, everyday refined."
    ),
]

sample_offers = [
    Offer(
        title="Wedding Season Edit", subtitle="Curated formalwear for the ceremony circuit",
        image_url="https://images.unsplash.com/photo-1519741497674-611481863552?w=800&q=80",
        display_order=1
    ),
    Offer(
        title="New Arrivals", subtitle="This week's additions to the atelier",
        image_url="https://images.unsplash.com/photo-1490481651871-ab68de25d43d?w=800&q=80",
        display_order=2
    ),
    Offer(
        title="The Tailoring Edit", subtitle="Structured suiting built for the boardroom",
        image_url="https://images.unsplash.com/photo-1617137968427-85924c800a22?w=800&q=80",
        display_order=3
    ),
]

with app.app_context():
    Product.query.delete()
    Offer.query.delete()
    db.session.commit()

    db.session.add_all(sample_products)
    db.session.add_all(sample_offers)
    db.session.commit()

    print(f"Added {len(sample_products)} products and {len(sample_offers)} offers.")