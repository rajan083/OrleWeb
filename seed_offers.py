# seed_data.py
#
# Populates the local database with sample products and offers so the
# dashboard/catalogue have real content to browse instead of looking empty.
#
# Run with:
#   python seed_data.py
#
# Safe to re-run — it clears existing Product/Offer rows first so you don't
# end up with duplicates every time you run it.

from main import app
from models import db, Product, Offer

sample_products = [
    Product(
        name="The Onyx Column Gown", description="Bias-cut evening gown in matte crepe, minimal seaming.",
        price=48900, category="dress",
        image_url="https://images.unsplash.com/photo-1595777457583-95e059d581b8?w=500&q=80",
        best_for_body_types="hourglass", best_for_occasions="wedding,black_tie",
        fit_note="Waist-defined column cut, elongates through the hip. Best for hourglass, black tie."
    ),
    Product(
        name="Sablé Blazer Dress", description="Structured blazer-dress hybrid with a nipped waist.",
        price=32500, category="dress",
        image_url="https://images.unsplash.com/photo-1566174053879-31528523f8ae?w=500&q=80",
        best_for_body_types="hourglass,rectangle", best_for_occasions="business,cocktail",
        fit_note="Structured shoulder, nipped waist suppression. Best for hourglass, cocktail."
    ),
    Product(
        name="Noir Slip Dress", description="Bias-cut silk slip, minimal hardware.",
        price=26700, category="dress",
        image_url="https://images.unsplash.com/photo-1595950653106-6c9ebd614d3a?w=500&q=80",
        best_for_body_types="rectangle,inverted_triangle", best_for_occasions="cocktail,everyday",
        fit_note="Bias cut, minimal seaming for a clean line. Best for cocktail, everyday refined."
    ),
    Product(
        name="Cavallo Trouser Suit", description="High-rise tailored trouser suit, straight leg.",
        price=41000, category="suit",
        image_url="https://images.unsplash.com/photo-1539109136881-3be0616acf4b?w=500&q=80",
        best_for_body_types="hourglass,inverted_triangle", best_for_occasions="business",
        fit_note="High-rise, straight leg, sharp shoulder line. Best for business formal."
    ),
    Product(
        name="The Charcoal Two-Piece", description="Classic wool-blend two-piece suit.",
        price=54200, category="suit",
        image_url="https://images.unsplash.com/photo-1594938298603-c8148c4dae35?w=500&q=80",
        best_for_body_types="rectangle,athletic", best_for_occasions="business,wedding",
        fit_note="Tailored through the chest, tapered leg. Best for business formal, wedding guest."
    ),
    Product(
        name="Sable Blazer", description="Single-breasted wool blazer, notch lapel.",
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
        name="Cavallo Trouser", description="High-rise tailored trouser, straight leg.",
        price=18200, category="trouser",
        image_url="https://images.unsplash.com/photo-1594938291221-94f18cbb5660?w=500&q=80",
        best_for_body_types="all", best_for_occasions="business,everyday",
        fit_note="High-rise, straight leg. Pairs with most silhouettes above the waist."
    ),
    Product(
        name="The Brass-Button Coat", description="Belted wool coat with structured shoulder.",
        price=52300, category="outerwear",
        image_url="https://images.unsplash.com/photo-1520975954732-35dd22299614?w=500&q=80",
        best_for_body_types="rectangle,apple", best_for_occasions="business,everyday",
        fit_note="Belted waist, structured shoulder. Best for rectangle, apple body types."
    ),
    Product(
        name="Onyx Overshirt", description="Heavyweight cotton overshirt, boxy fit.",
        price=24900, category="outerwear",
        image_url="https://images.unsplash.com/photo-1544923246-77307dd654cb?w=500&q=80",
        best_for_body_types="athletic,rectangle", best_for_occasions="everyday",
        fit_note="Boxy, relaxed through the body. Best for everyday refined, layering."
    ),
    Product(
        name="Envelope Silk Top", description="Wrap-front silk top, draped bodice.",
        price=18200, category="top",
        image_url="https://images.unsplash.com/photo-1515372039744-b8f02a3ae446?w=500&q=80",
        best_for_body_types="all", best_for_occasions="business,cocktail,everyday",
        fit_note="Wrap front, draped bodice skims rather than clings. Best for all body types."
    ),
    Product(
        name="Structured Poplin Shirt", description="Crisp cotton poplin, French cuff.",
        price=12400, category="shirt",
        image_url="https://images.unsplash.com/photo-1602810318383-e386cc2a3ccf?w=500&q=80",
        best_for_body_types="all", best_for_occasions="business,everyday",
        fit_note="Structured through the shoulder, tapered waist. A foundational piece for most builds."
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
        title="The Tailoring Edit", subtitle="Structured pieces built for the boardroom",
        image_url="https://images.unsplash.com/photo-1617137968427-85924c800a22?w=800&q=80",
        display_order=3
    ),
]

with app.app_context():
    # Clear existing sample data so re-running this doesn't create duplicates
    Product.query.delete()
    Offer.query.delete()
    db.session.commit()

    db.session.add_all(sample_products)
    db.session.add_all(sample_offers)
    db.session.commit()

    print(f"Added {len(sample_products)} products and {len(sample_offers)} offers.")