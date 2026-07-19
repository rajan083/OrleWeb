# seed_offers.py
from main import app
from models import db, Offer

sample_offers = [
    Offer(title="Wedding Season Edit", subtitle="Curated formalwear for the ceremony circuit",
          image_url="https://images.unsplash.com/photo-1519741497674-611481863552?w=800&q=80",
          display_order=1),
    Offer(title="New Arrivals", subtitle="This week's additions to the atelier",
          image_url="https://images.unsplash.com/photo-1490481651871-ab68de25d43d?w=800&q=80",
          display_order=2),
]

with app.app_context():
    db.session.add_all(sample_offers)
    db.session.commit()
    print(f"Added {len(sample_offers)} offers.")