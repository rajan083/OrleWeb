from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime
from flask_login import UserMixin

db = SQLAlchemy()

class User(db.Model, UserMixin):
    __tablename__ = "users"
    
    id = db.Column(db.Integer, primary_key = True)
    name = db.Column(db.String(200), nullable = False)
    email = db.Column(db.String(220), unique = True, nullable = False)
    phone_number = db.Column(db.String(20), nullable = True)
    password_hash = db.Column(db.String(255), nullable = True)
    google_id = db.Column(db.String(255), unique = True, nullable= True)
    profile_picture = db.Column(db.String(500), nullable=True)
    
    is_admin = db.Column(db.Boolean, default=False, nullable=False)  # NEW
    
    created_at = db.Column(db.DateTime, default = datetime.utcnow)
        
    is_verified = db.Column(db.Boolean, default=False, nullable=False)
    
    profile = db.relationship('UserProfile', backref='user', uselist=False, cascade='all, delete-orphan')
    
    cart_items = db.relationship('CartItem', backref='user', lazy=True)
    
    is_vendor = False
    
    def get_id(self):
        return f"user-{self.id}"
    
    def set_password(self, password):
        self.password_hash = generate_password_hash(password)
        
    def check_password(self, password):
        if not self.password_hash:
            return False
        return check_password_hash(self.password_hash, password)
    
    def to_dict(self):
        return {
            'id': self.id,
            'name': self.name,
            'email': self.email,
            'phone_number': self.phone_number
        }
        
class UserProfile(db.Model):
    __tablename__ = 'user_profiles'
    id = db.Column(db.Integer(), primary_key = True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable = False, unique = True)

    age_group = db.Column(db.String(20), nullable=True)
    height_range = db.Column(db.String(30), nullable=True)
    body_type = db.Column(db.String(30), nullable=True)
    skin_tone = db.Column(db.String(20), nullable=True)
    occasion = db.Column(db.String(30), nullable=True)
    
    undertone = db.Column(db.String(10), nullable=True)
                          
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def to_dict(self):
        return {
            'age_group' : self.age_group,
            'height_range' : self.height_range,
            'body_type' : self.body_type,
            'skin_tone' : self.skin_tone,
            'occasion' : self.occasion
        }       
        
        
class Product(db.Model):
    __tablename__ = 'products'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(150), nullable=False)
    description = db.Column(db.Text, nullable=True)
    price = db.Column(db.Integer, nullable=False)
    category = db.Column(db.String(50), nullable=False)
    image_url = db.Column(db.String(300), nullable=True)

    best_for_body_types = db.Column(db.String(200), nullable=True)
    best_for_occasions = db.Column(db.String(200), nullable=True)
    
    color = db.Column(db.String(30), nullable=True)          # e.g. "navy", "olive", "cream", "burgundy"
    color_undertone = db.Column(db.String(10), nullable=True)  # "warm", "cool", "neutral"
    silhouette = db.Column(db.String(30), nullable=True)       # "structured", "relaxed", "fitted"

    fit_note = db.Column(db.String(300), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    vendor_id = db.Column(db.Integer, db.ForeignKey('vendors.id'), nullable=True)
    
    requires_size = db.Column(db.Boolean, default=False, nullable=False)  # NEW — vendor toggles this on for clothing
    
    stock_quantity = db.Column(db.Integer, nullable=False, default=0)  # NEW — only meaningful when requires_size=False

    @property
    def available_stock(self):
        """Unified stock check regardless of whether the product is sized."""
        if self.requires_size:
            return sum(s.stock_quantity for s in self.sizes)
        return self.stock_quantity

    def stock_for_size(self, size):
        if not self.requires_size:
            return self.stock_quantity
        match = next((s for s in self.sizes if s.size == size), None)
        return match.stock_quantity if match else 0

    @property
    def average_rating(self):
        if not self.reviews:
            return None
        return round(sum(r.rating for r in self.reviews) / len(self.reviews), 1)

    @property
    def review_count(self):
        return len(self.reviews)

    def to_dict(self):
        return {
            'id': self.id,
            'name': self.name,
            'description': self.description,
            'price': self.price,
            'category': self.category,
            'image_url': self.image_url,
            'fit_note': self.fit_note
        }


class Offer(db.Model):
    __tablename__ = 'offers'

    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(150), nullable=False)
    subtitle = db.Column(db.String(250), nullable=True)
    image_url = db.Column(db.String(300), nullable=False)
    link_url = db.Column(db.String(300), nullable=True)
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    display_order = db.Column(db.Integer, default=0)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
class Vendor(db.Model, UserMixin):
    __tablename__ = 'vendors'

    id = db.Column(db.Integer, primary_key=True)
    business_name = db.Column(db.String(200), nullable=False)
    email = db.Column(db.String(220), unique=True, nullable=False)
    phone_number = db.Column(db.String(20), nullable=True)
    password_hash = db.Column(db.String(255), nullable=False)
    is_verified = db.Column(db.Boolean, default=False, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    products = db.relationship('Product', backref='vendor', lazy=True)

    is_vendor = True  # lets base.html tell customers and vendors apart without isinstance()

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    def get_id(self):
        return f"vendor-{self.id}"

    def to_dict(self):
        return {
            'id': self.id,
            'business_name': self.business_name,
            'email': self.email,
            'phone_number': self.phone_number
        }


class Sale(db.Model):
    __tablename__ = 'sales'

    id = db.Column(db.Integer, primary_key=True)
    vendor_id = db.Column(db.Integer, db.ForeignKey('vendors.id'), nullable=False)
    product_id = db.Column(db.Integer, db.ForeignKey('products.id'), nullable=False)
    quantity = db.Column(db.Integer, nullable=False)
    amount = db.Column(db.Integer, nullable=False)  # total sale value, whole rupees
    sale_date = db.Column(db.Date, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    product = db.relationship('Product')

    def to_dict(self):
        return {
            'id': self.id,
            'product_name': self.product.name if self.product else 'Unknown',
            'quantity': self.quantity,
            'amount': self.amount,
            'sale_date': self.sale_date.isoformat()
        }
        
        
class Wishlist(db.Model):
    __tablename__ = 'wishlist'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    product_id = db.Column(db.Integer, db.ForeignKey('products.id'), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    product = db.relationship('Product')

    __table_args__ = (db.UniqueConstraint('user_id', 'product_id', name='uq_user_product_wishlist'),)


class CartItem(db.Model):
    __tablename__ = 'cart_items'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    product_id = db.Column(db.Integer, db.ForeignKey('products.id'), nullable=False)
    quantity = db.Column(db.Integer, nullable=False, default=1)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    size = db.Column(db.String(10), nullable=True)  # NEW

    product = db.relationship('Product')


class Order(db.Model):
    __tablename__ = 'orders'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    total_amount = db.Column(db.Integer, nullable=False)
    status = db.Column(db.String(20), nullable=False, default='pending_payment')
    user = db.relationship('User')
    
    # pending_payment -> placed -> shipped -> delivered  (or -> cancelled at any point)

    payment_status = db.Column(db.String(20), nullable=False, default='pending')  # pending, paid, failed
    razorpay_order_id = db.Column(db.String(100), nullable=True)
    razorpay_payment_id = db.Column(db.String(100), nullable=True)

    shipping_name = db.Column(db.String(200), nullable=False)
    shipping_address = db.Column(db.Text, nullable=False)
    shipping_phone = db.Column(db.String(20), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    items = db.relationship('OrderItem', backref='order', cascade='all, delete-orphan')


class OrderItem(db.Model):
    __tablename__ = 'order_items'

    id = db.Column(db.Integer, primary_key=True)
    order_id = db.Column(db.Integer, db.ForeignKey('orders.id'), nullable=False)
    product_id = db.Column(db.Integer, db.ForeignKey('products.id'), nullable=True)  # nullable in case a product is later deleted
    product_name = db.Column(db.String(150), nullable=False)  # snapshot — survives product deletion
    unit_price = db.Column(db.Integer, nullable=False)         # snapshot — survives price changes
    quantity = db.Column(db.Integer, nullable=False)
    size = db.Column(db.String(10), nullable=True)  # NEW — snapshot, same pattern as product_name/unit_price
    product = db.relationship('Product')
    
class Address(db.Model):
    __tablename__ = 'addresses'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    full_name = db.Column(db.String(200), nullable=False)
    phone = db.Column(db.String(20), nullable=False)
    address_line = db.Column(db.Text, nullable=False)
    is_default = db.Column(db.Boolean, default=False, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    user = db.relationship('User', backref='addresses')
    
# ── Reviews ──────────────────────────────────────────────
class Review(db.Model):
    __tablename__ = 'reviews'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    product_id = db.Column(db.Integer, db.ForeignKey('products.id'), nullable=False)
    order_item_id = db.Column(db.Integer, db.ForeignKey('order_items.id'), nullable=False)
    rating = db.Column(db.Integer, nullable=False)       # 1-5
    comment = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    user = db.relationship('User')
    product = db.relationship('Product', backref=db.backref('reviews', cascade='all, delete-orphan'))
    order_item = db.relationship('OrderItem')

    # one review per actual purchased line-item — this is what enforces "verified purchase only"
    __table_args__ = (db.UniqueConstraint('order_item_id', name='uq_review_per_order_item'),)


# ── Multi-image products ────────────────────────────────
class ProductImage(db.Model):
    __tablename__ = 'product_images'

    id = db.Column(db.Integer, primary_key=True)
    product_id = db.Column(db.Integer, db.ForeignKey('products.id'), nullable=False)
    image_url = db.Column(db.String(300), nullable=False)
    display_order = db.Column(db.Integer, default=0)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    product = db.relationship(
        'Product',
        backref=db.backref('gallery_images', order_by='ProductImage.display_order', cascade='all, delete-orphan')
    )
    # NOTE: Product.image_url stays as-is — it's the cover image.
    # gallery_images are the *additional* angles shown on the product page.


# ── Size chart / per-size stock ─────────────────────────
SIZE_CHOICES = ['XS', 'S', 'M', 'L', 'XL', 'XXL']

class ProductSize(db.Model):
    __tablename__ = 'product_sizes'

    id = db.Column(db.Integer, primary_key=True)
    product_id = db.Column(db.Integer, db.ForeignKey('products.id'), nullable=False)
    size = db.Column(db.String(10), nullable=False)
    stock_quantity = db.Column(db.Integer, nullable=False, default=0)

    product = db.relationship('Product', backref=db.backref('sizes', cascade='all, delete-orphan'))

    __table_args__ = (db.UniqueConstraint('product_id', 'size', name='uq_product_size'),)