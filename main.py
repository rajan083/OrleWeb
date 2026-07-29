import os
import uuid
from werkzeug.utils import secure_filename
from flask import Flask, request, render_template, redirect, url_for, session, flash
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import or_
from flask_login import LoginManager, login_user, logout_user, login_required, current_user
from flask_jwt_extended import JWTManager
from config import Config
from functools import wraps
from models import db, User, UserProfile, Product, Offer, Vendor, Sale, Wishlist, CartItem, Order, OrderItem, Address, Review, ProductImage, ProductSize, SIZE_CHOICES, Coupon
from datetime import datetime, timedelta
from flask_migrate import Migrate
from authlib.integrations.flask_client import OAuth
from flask_mail import Mail, Message
from itsdangerous import URLSafeTimedSerializer, SignatureExpired, BadSignature
from recommendations import recommend_products
import razorpay




app = Flask(__name__)
app.config.from_object(Config)

UPLOAD_FOLDER = os.path.join(app.root_path, "static", "uploads", "products")
ALLOWED_EXTENSIONS = {"png", "jpg", "jpeg", "webp"}

app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER

os.makedirs(UPLOAD_FOLDER, exist_ok=True)

db.init_app(app)
migrate = Migrate(app, db)
jwt = JWTManager(app)

mail = Mail(app)
serializer = URLSafeTimedSerializer(app.config['SECRET_KEY'])

razorpay_client = razorpay.Client(auth=(app.config['RAZORPAY_KEY_ID'], app.config['RAZORPAY_KEY_SECRET']))


def send_verification_email(user, next_page=None):
    token = serializer.dumps(user.email, salt='email-verify')
    link = url_for('verify_email', token=token, next=next_page, _external=True)
    msg = Message(
        'Verify your ORLE account',
        recipients=[user.email],
        sender=app.config['MAIL_USERNAME']
    )
    msg.body = f'Welcome to ORLE. Click the link below to verify your email:\n\n{link}\n\nThis link expires in 1 hour.'
    mail.send(msg)


def send_order_email(order, event):
    subjects = {
        'placed': 'Your ORLE order has been placed',
        'shipped': 'Your ORLE order has shipped',
        'delivered': 'Your ORLE order has been delivered',
        'cancelled': 'Your ORLE order has been cancelled'
    }
    bodies = {
        'placed': f"Thanks for your order! Order #{order.id} has been placed and payment confirmed.\n\nTotal: ₹{order.total_amount}\n\nWe'll notify you once it ships.",
        'shipped': f"Good news — Order #{order.id} is on its way.\n\nShipping to: {order.shipping_name}, {order.shipping_address}",
        'delivered': f"Order #{order.id} has been marked as delivered. We hope you love it.",
        'cancelled': f"Order #{order.id} has been cancelled. If a payment was made, it will be refunded within 5-7 business days."
    }

    msg = Message(
        subjects.get(event, 'Order update'),
        recipients=[order.user.email],
        sender=app.config['MAIL_USERNAME']
    )
    msg.body = bodies.get(event, f"Your order status has changed to: {event}")
    mail.send(msg)
    
    
oauth = OAuth(app)
google = oauth.register(
    name='google',
    client_id=app.config['GOOGLE_CLIENT_ID'],
    client_secret=app.config['GOOGLE_CLIENT_SECRET'],
    server_metadata_url='https://accounts.google.com/.well-known/openid-configuration',
    client_kwargs={'scope': 'openid email profile'}
)

login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'

@login_manager.user_loader
def load_user(user_id):
    if "-" not in user_id:
        return User.query.get(int(user_id))

    kind, real_id = [x.strip() for x in user_id.split("-", 1)]

    if kind == "user":
        return User.query.get(int(real_id))

    elif kind == "vendor":
        return Vendor.query.get(int(real_id))

    return None


def allowed_file(filename):
    return (
        "." in filename and
        filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS
    )

def vendor_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not current_user.is_authenticated or not getattr(current_user, 'is_vendor', False):
            flash("Please log in as a vendor to access this page.", "error")
            return redirect(url_for('vendor_login'))
        return f(*args, **kwargs)
    return decorated

 #===============================================Register===================================================================

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'GET':
        return render_template('register.html')

    name = request.form.get('name')
    phone_number = request.form.get('phone_number')
    email = request.form.get('email')
    password = request.form.get('password')
    confirm_password = request.form.get('confirm_password')
    next_page = request.args.get('next') or request.form.get('next')

    if not name or not email or not password or not confirm_password:
        flash("Please enter the required credentials.", "error")
        return render_template('register.html')

    if password != confirm_password:
        flash("The passwords don't match.", "error")
        return render_template('register.html')

    existing_user = User.query.filter_by(email=email).first()
    if existing_user:
        flash("This email is already registered. Try logging in instead.", "error")
        return redirect(url_for('login', next=next_page))

    new_user = User(name=name, email=email, phone_number=phone_number)
    new_user.set_password(password)

    db.session.add(new_user)
    db.session.commit()

    send_verification_email(new_user, next_page)
    flash("Account created! Check your email to verify before logging in.", "success")
    return render_template('check_email.html', email=email)

 #===============================================Email Verification===================================================================

@app.route('/verify/<token>')
def verify_email(token):
    next_page = request.args.get('next')
    try:
        email = serializer.loads(token, salt='email-verify', max_age=3600)
    except SignatureExpired:
        return render_template('verify_result.html', success=False, message="This verification link has expired. Please register again or request a new link.")
    except BadSignature:
        return render_template('verify_result.html', success=False, message="This verification link is invalid.")

    user = User.query.filter_by(email=email).first()
    if not user:
        return render_template('verify_result.html', success=False, message="No account found for this link.")

    if user.is_verified:
        return render_template('verify_result.html', success=True, message="Your email is already verified — you can log in.", next=next_page)

    user.is_verified = True
    db.session.commit()

    return render_template('verify_result.html', success=True, message="Your email has been verified. You can now log in.", next=next_page)


 #===============================================Login================================================================

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'GET':
        return render_template('login.html')

    email = request.form.get('email')
    password = request.form.get('password')

    if not email or not password:
        flash("Please enter your email and password.", "error")
        return render_template('login.html')

    user = User.query.filter_by(email=email).first()

    if not user:
        flash("No account found with that email. Try registering first.", "error")
        return render_template('login.html')

    if not user.check_password(password):
        flash("Incorrect password.", "error")
        return render_template('login.html')

    if not user.is_verified:
        flash("Please verify your email before logging in. Check your inbox.", "error")
        return render_template('login.html')

    login_user(user)
    flash(f"Welcome back, {user.name}.", "success")
    if current_user.profile:
        return redirect(url_for('dashboard'))
    return redirect(url_for('onboarding'))


 #===============================================GOOGLE-Login===================================================================

@app.route('/login/google')
def login_google():
    redirect_uri = url_for('login_google_callback', _external=True)
    session['oauth_next'] = request.args.get('next')  # stash it — OAuth round-trip loses query params otherwise
    return google.authorize_redirect(redirect_uri)


@app.route('/login/google/callback')
def login_google_callback():
    token = google.authorize_access_token()
    user_info = token.get('userinfo')

    if not user_info or not user_info.get('email'):
        flash("Google didn't return an email. Please try again.", "error")
        return redirect(url_for('login'))

    email = user_info['email']
    google_id = user_info['sub']
    name = user_info.get('name', email.split('@')[0])
    picture = user_info.get('picture')

    user = User.query.filter_by(email=email).first()
    is_new_user = False

    if not user:
        user = User(email=email, name=name, google_id=google_id, is_verified=True, profile_picture=picture)
        db.session.add(user)
        is_new_user = True
    elif not user.google_id:
        user.google_id = google_id
        if picture:
            user.profile_picture = picture

    db.session.commit()
    login_user(user)

    next_page = session.pop('oauth_next', None)

    if is_new_user:
        flash(f"Welcome to ORLE, {user.name}.", "success")
        return redirect(next_page or url_for('onboarding'))
    elif not user.profile:
        flash(f"Welcome back, {user.name}. Let's finish setting up your style profile.", "success")
        return redirect(next_page or url_for('onboarding'))
    else:
        flash(f"Welcome back, {user.name}.", "success")
        return redirect(next_page or url_for('dashboard'))
    

 #===============================================Onboarding===================================================================

@app.route('/onboarding', methods=['GET', 'POST'])
@login_required
def onboarding():
    if request.method == 'GET':
        return render_template('onboarding.html')

    age_group = request.form.get('age_group')
    height_range = request.form.get('height_range')
    body_type = request.form.get('body_type')
    skin_tone = request.form.get('skin_tone')
    occasion = request.form.get('occasion')

    if not all([age_group, height_range, body_type, skin_tone, occasion]):
        flash("Please fill in every category to get your recommendations.", "error")
        return render_template('onboarding.html')

    profile = UserProfile.query.filter_by(user_id=current_user.id).first()
    if profile:
        profile.age_group = age_group
        profile.height_range = height_range
        profile.body_type = body_type
        profile.skin_tone = skin_tone
        profile.occasion = occasion
    else:
        profile = UserProfile(
            user_id=current_user.id,
            age_group=age_group,
            height_range=height_range,
            body_type=body_type,
            skin_tone=skin_tone,
            occasion=occasion
        )
        db.session.add(profile)

    db.session.commit()
    flash("Your style profile has been saved.", "success")
    return redirect(url_for('recommendations'))


 #===============================================Profile===================================================================

@app.route('/profile')
@login_required
def profile():
    order_count = Order.query.filter_by(user_id=current_user.id).count()
    wishlist_count = Wishlist.query.filter_by(user_id=current_user.id).count()
    address_count = Address.query.filter_by(user_id=current_user.id).count()

    return render_template(
        'profile.html',
        user=current_user,
        profile=current_user.profile,
        order_count=order_count,
        wishlist_count=wishlist_count,
        address_count=address_count
    )


@app.route('/profile/edit', methods=['GET', 'POST'])
@login_required
def edit_profile():
    if request.method == 'GET':
        return render_template('edit_profile.html', user=current_user)

    name = request.form.get('name')
    phone_number = request.form.get('phone_number')

    if not name:
        flash("Name can't be empty.", "error")
        return render_template('edit_profile.html', user=current_user)

    current_user.name = name
    current_user.phone_number = phone_number
    db.session.commit()

    flash("Your profile has been updated.", "success")
    return redirect(url_for('profile'))

#===============================================Addresses===================================================================

@app.route('/addresses')
@login_required
def addresses():
    saved = Address.query.filter_by(user_id=current_user.id).order_by(Address.is_default.desc(), Address.created_at.desc()).all()
    return render_template('addresses.html', addresses=saved)


@app.route('/addresses/add', methods=['GET', 'POST'])
@login_required
def address_add():
    if request.method == 'GET':
        return render_template('address_form.html', address=None)

    full_name = request.form.get('full_name')
    phone = request.form.get('phone')
    address_line = request.form.get('address_line')
    make_default = request.form.get('is_default') == 'on'

    if not full_name or not phone or not address_line:
        flash("Please fill in all address fields.", "error")
        return render_template('address_form.html', address=None)

    if make_default:
        Address.query.filter_by(user_id=current_user.id).update({'is_default': False})

    new_address = Address(
        user_id=current_user.id,
        full_name=full_name,
        phone=phone,
        address_line=address_line,
        is_default=make_default
    )
    db.session.add(new_address)
    db.session.commit()

    flash("Address saved.", "success")
    return redirect(request.args.get('next') or url_for('addresses'))


@app.route('/addresses/<int:address_id>/edit', methods=['GET', 'POST'])
@login_required
def address_edit(address_id):
    address = Address.query.get_or_404(address_id)
    if address.user_id != current_user.id:
        flash("You don't have permission to edit this address.", "error")
        return redirect(url_for('addresses'))

    if request.method == 'GET':
        return render_template('address_form.html', address=address)

    address.full_name = request.form.get('full_name')
    address.phone = request.form.get('phone')
    address.address_line = request.form.get('address_line')

    if request.form.get('is_default') == 'on':
        Address.query.filter_by(user_id=current_user.id).update({'is_default': False})
        address.is_default = True

    db.session.commit()
    flash("Address updated.", "success")
    return redirect(url_for('addresses'))


@app.route('/addresses/<int:address_id>/delete', methods=['POST'])
@login_required
def address_delete(address_id):
    address = Address.query.get_or_404(address_id)
    if address.user_id != current_user.id:
        flash("You don't have permission to delete this address.", "error")
        return redirect(url_for('addresses'))

    db.session.delete(address)
    db.session.commit()
    flash("Address removed.", "info")
    return redirect(url_for('addresses'))

 #===============================================Dashboard===================================================================

@app.route('/dashboard')
def dashboard():
    offers = Offer.query.filter_by(is_active=True).order_by(Offer.display_order.asc()).all()
    latest_products = Product.query.order_by(Product.created_at.desc()).limit(8).all()
    all_products = Product.query.order_by(Product.created_at.desc()).all()

    ranked = []
    wishlisted_ids = set()
    if current_user.is_authenticated and not getattr(current_user, 'is_vendor', False):
        if current_user.profile:
            ranked = recommend_products(current_user.profile, all_products, top_n=4)
        wishlisted_ids = {w.product_id for w in Wishlist.query.filter_by(user_id=current_user.id).all()}

    return render_template(
        'dashboard.html',
        offers=offers,
        latest_products=latest_products,
        all_products=all_products,
        ranked=ranked,
        wishlisted_ids=wishlisted_ids
    )

 #===============================================Catalogue===================================================================

@app.route('/catalogue')
def catalogue():
    category = request.args.get('category')

    query = Product.query
    if category:
        query = query.filter_by(category=category)

    products = query.order_by(Product.created_at.desc()).all()
    categories = db.session.query(Product.category).distinct().all()
    categories = [c[0] for c in categories]

    wishlisted_ids = set()
    if current_user.is_authenticated and not getattr(current_user, 'is_vendor', False):
        wishlisted_ids = {w.product_id for w in Wishlist.query.filter_by(user_id=current_user.id).all()}

    return render_template('catalogue.html', products=products, categories=categories, active_category=category, wishlisted_ids=wishlisted_ids)


@app.route('/catalogue/<int:product_id>')
def product_detail(product_id):
    product = Product.query.get_or_404(product_id)

    is_wishlisted = False
    reviewable_order_items = []
    if current_user.is_authenticated and not getattr(current_user, 'is_vendor', False):
        is_wishlisted = Wishlist.query.filter_by(user_id=current_user.id, product_id=product_id).first() is not None

        reviewable_order_items = (
            db.session.query(OrderItem)
            .join(Order)
            .outerjoin(Review, Review.order_item_id == OrderItem.id)
            .filter(
                Order.user_id == current_user.id,
                OrderItem.product_id == product_id,
                Order.status == 'delivered',
                Review.id.is_(None)
            )
            .all()
        )

    reviews = Review.query.filter_by(product_id=product_id).order_by(Review.created_at.desc()).all()

    related_products = (
        Product.query
        .filter(Product.category == product.category, Product.id != product.id)
        .order_by(Product.created_at.desc())
        .limit(4)
        .all()
    )

    return render_template(
        'product_detail.html',
        product=product,
        is_wishlisted=is_wishlisted,
        related_products=related_products,
        reviews=reviews,
        reviewable_order_items=reviewable_order_items
    )
    

@app.route('/catalogue/<int:product_id>/review', methods=['POST'])
@login_required
def add_review(product_id):
    if getattr(current_user, 'is_vendor', False):
        flash("Vendors can't post reviews.", "error")
        return redirect(url_for('product_detail', product_id=product_id))

    order_item = OrderItem.query.get_or_404(request.form.get('order_item_id'))
    order = order_item.order

    if order.user_id != current_user.id or order_item.product_id != product_id:
        flash("You can only review products you've purchased.", "error")
        return redirect(url_for('product_detail', product_id=product_id))

    if order.status != 'delivered':
        flash("You can review this once your order is delivered.", "error")
        return redirect(url_for('product_detail', product_id=product_id))

    if Review.query.filter_by(order_item_id=order_item.id).first():
        flash("You've already reviewed this purchase.", "info")
        return redirect(url_for('product_detail', product_id=product_id))

    rating = int(request.form.get('rating') or 0)
    if rating < 1 or rating > 5:
        flash("Please select a rating between 1 and 5.", "error")
        return redirect(url_for('product_detail', product_id=product_id))

    db.session.add(Review(
        user_id=current_user.id,
        product_id=product_id,
        order_item_id=order_item.id,
        rating=rating,
        comment=request.form.get('comment')
    ))
    db.session.commit()
    flash("Thanks for your review.", "success")
    return redirect(url_for('product_detail', product_id=product_id))

#===============================================Wishlist===================================================================

@app.route('/wishlist')
@login_required
def wishlist():
    items = Wishlist.query.filter_by(user_id=current_user.id).order_by(Wishlist.created_at.desc()).all()
    return render_template('wishlist.html', items=items)


@app.route('/wishlist/toggle/<int:product_id>', methods=['POST'])
@login_required
def wishlist_toggle(product_id):
    existing = Wishlist.query.filter_by(user_id=current_user.id, product_id=product_id).first()

    if existing:
        db.session.delete(existing)
        db.session.commit()
        flash("Removed from wishlist.", "info")
    else:
        db.session.add(Wishlist(user_id=current_user.id, product_id=product_id))
        db.session.commit()
        flash("Added to wishlist.", "success")

    return redirect(request.referrer or url_for('catalogue'))


#===============================================Cart===================================================================

@app.route('/cart')
@login_required
def cart():
    items = CartItem.query.filter_by(user_id=current_user.id).all()
    total = sum(item.product.price * item.quantity for item in items if item.product)

    discount = 0
    coupon = None
    coupon_code = session.get('coupon_code')
    if coupon_code:
        coupon = Coupon.query.filter_by(code=coupon_code).first()
        if coupon:
            valid, error = coupon.is_valid_for(total)
            if valid:
                discount = coupon.calculate_discount(total)
            else:
                session.pop('coupon_code', None)
                coupon = None

    final_total = total - discount
    return render_template('cart.html', items=items, total=total, discount=discount, final_total=final_total, coupon=coupon)


@app.route('/cart/apply-coupon', methods=['POST'])
@login_required
def apply_coupon():
    code = (request.form.get('coupon_code') or '').strip().upper()
    items = CartItem.query.filter_by(user_id=current_user.id).all()
    total = sum(item.product.price * item.quantity for item in items if item.product)

    coupon = Coupon.query.filter_by(code=code).first()
    if not coupon:
        flash("Invalid coupon code.", "error")
        session.pop('coupon_code', None)
        return redirect(url_for('cart'))

    valid, error = coupon.is_valid_for(total)
    if not valid:
        flash(error, "error")
        session.pop('coupon_code', None)
        return redirect(url_for('cart'))

    session['coupon_code'] = coupon.code
    discount = coupon.calculate_discount(total)
    flash(f"Coupon applied — ₹{discount} off.", "success")
    return redirect(url_for('cart'))


@app.route('/cart/remove-coupon', methods=['POST'])
@login_required
def remove_coupon():
    session.pop('coupon_code', None)
    flash("Coupon removed.", "info")
    return redirect(url_for('cart'))

@app.route('/cart/add/<int:product_id>', methods=['POST'])
@login_required
def cart_add(product_id):
    product = Product.query.get_or_404(product_id)
    quantity = int(request.form.get('quantity') or 1)
    size = request.form.get('size')

    if product.requires_size and not size:
        flash("Please select a size.", "error")
        return redirect(request.referrer or url_for('catalogue'))

    available = product.stock_for_size(size)

    existing = CartItem.query.filter_by(user_id=current_user.id, product_id=product_id, size=size).first()
    already_in_cart = existing.quantity if existing else 0

    if available <= 0:
        flash(f"{product.name} is out of stock" + (f" in size {size}" if size else "") + ".", "error")
        return redirect(request.referrer or url_for('catalogue'))

    if already_in_cart + quantity > available:
        remaining = max(available - already_in_cart, 0)
        flash(f"Only {available} left in stock" + (f" for size {size}" if size else "") + f" — you already have {already_in_cart} in your bag, so you can add {remaining} more.", "error")
        return redirect(request.referrer or url_for('catalogue'))

    if existing:
        existing.quantity += quantity
    else:
        db.session.add(CartItem(user_id=current_user.id, product_id=product_id, quantity=quantity, size=size))

    db.session.commit()
    flash(f"{product.name} added to your bag.", "success")
    return redirect(request.referrer or url_for('catalogue'))


@app.route('/cart/update/<int:item_id>', methods=['POST'])
@login_required
def cart_update(item_id):
    item = CartItem.query.get_or_404(item_id)
    if item.user_id != current_user.id:
        flash("You don't have permission to modify this item.", "error")
        return redirect(url_for('cart'))

    quantity = int(request.form.get('quantity') or 1)

    if quantity < 1:
        db.session.delete(item)
        db.session.commit()
        return redirect(url_for('cart'))

    available = item.product.stock_for_size(item.size)
    if quantity > available:
        flash(f"Only {available} left in stock" + (f" for size {item.size}" if item.size else "") + ".", "error")
        quantity = available if available > 0 else 1  # clamp rather than reject outright

    item.quantity = quantity
    db.session.commit()
    return redirect(url_for('cart'))


@app.route('/cart/remove/<int:item_id>', methods=['POST'])
@login_required
def cart_remove(item_id):
    item = CartItem.query.get_or_404(item_id)
    if item.user_id != current_user.id:
        flash("You don't have permission to modify this item.", "error")
        return redirect(url_for('cart'))

    db.session.delete(item)
    db.session.commit()
    flash("Item removed from bag.", "info")
    return redirect(url_for('cart'))




@app.route('/orders')
@login_required
def orders():
    user_orders = Order.query.filter_by(user_id=current_user.id).order_by(Order.created_at.desc()).all()
    return render_template('orders.html', orders=user_orders)


@app.route('/orders/<int:order_id>')
@login_required
def order_detail(order_id):
    order = Order.query.get_or_404(order_id)
    if order.user_id != current_user.id:
        flash("You don't have permission to view this order.", "error")
        return redirect(url_for('orders'))
    return render_template('order_detail.html', order=order)


#===============================================Order Cancellation (Customer)===================================================================

CANCELLABLE_STATUSES = ('pending_payment', 'placed')

@app.route('/orders/<int:order_id>/cancel', methods=['POST'])
@login_required
def order_cancel(order_id):
    order = Order.query.get_or_404(order_id)

    if order.user_id != current_user.id:
        flash("You don't have permission to cancel this order.", "error")
        return redirect(url_for('orders'))

    if order.status not in CANCELLABLE_STATUSES:
        flash(f"This order can no longer be cancelled — it's already {order.status}.", "error")
        return redirect(url_for('order_detail', order_id=order.id))

    # If payment was captured, attempt a refund before touching anything else.
    # If the refund fails, we bail out entirely rather than cancelling an order
    # whose money hasn't actually been returned.
    if order.payment_status == 'paid' and order.razorpay_payment_id:
        try:
            razorpay_client.payment.refund(order.razorpay_payment_id, {
                'amount': order.total_amount * 100,  # full refund, in paise
                'speed': 'optimum',
                'notes': {'reason': 'Customer-initiated cancellation', 'order_id': str(order.id)}
            })
        except razorpay.errors.BadRequestError as e:
            flash(f"We couldn't process the refund automatically ({str(e)}). Please contact support to complete this cancellation.", "error")
            return redirect(url_for('order_detail', order_id=order.id))
        except Exception:
            flash("Something went wrong initiating the refund. Please contact support — your order has not been cancelled.", "error")
            return redirect(url_for('order_detail', order_id=order.id))

        order.payment_status = 'refunded'

    # Refund succeeded (or nothing was charged yet) — now restore stock and finalize.
    for oi in order.items:
        product = oi.product
        if not product:
            continue
        if product.requires_size and oi.size:
            size_row = ProductSize.query.filter_by(product_id=product.id, size=oi.size).first()
            if size_row:
                size_row.stock_quantity += oi.quantity
            else:
                # size row was deleted since the order was placed (e.g. vendor removed that size) — recreate it
                db.session.add(ProductSize(product_id=product.id, size=oi.size, stock_quantity=oi.quantity))
        elif not product.requires_size:
            product.stock_quantity += oi.quantity

    order.status = 'cancelled'
    db.session.commit()

    send_order_email(order, 'cancelled')
    flash("Your order has been cancelled." + (" A refund has been initiated and will reflect in 5-7 business days." if order.payment_status == 'refunded' else ""), "success")
    return redirect(url_for('order_detail', order_id=order.id))


 #===============================================Recommendations===================================================================

@app.route('/recommendations')
@login_required
def recommendations():
    profile = current_user.profile
    if not profile:
        flash("Complete your style profile first to get recommendations.", "error")
        return redirect(url_for('onboarding'))

    all_products = Product.query.all()
    ranked = recommend_products(profile, all_products, top_n=12)
    wishlisted_ids = {w.product_id for w in Wishlist.query.filter_by(user_id=current_user.id).all()}

    return render_template('recommendations.html', ranked=ranked, wishlisted_ids=wishlisted_ids, profile=profile)


@app.route('/recommendations/update', methods=['POST'])
@login_required
def recommendations_update():
    profile = current_user.profile
    if not profile:
        return {"error": "No style profile found."}, 400

    profile.age_group = request.form.get('age_group', profile.age_group)
    profile.height_range = request.form.get('height_range', profile.height_range)
    profile.body_type = request.form.get('body_type', profile.body_type)
    profile.skin_tone = request.form.get('skin_tone', profile.skin_tone)
    profile.occasion = request.form.get('occasion', profile.occasion)
    db.session.commit()

    all_products = Product.query.all()
    ranked = recommend_products(profile, all_products, top_n=12)
    wishlisted_ids = {w.product_id for w in Wishlist.query.filter_by(user_id=current_user.id).all()}

    return render_template('_recommendation_grid.html', ranked=ranked, wishlisted_ids=wishlisted_ids)

 #===============================================Logout===================================================================

@app.route('/logout')
@login_required
def logout():
    logout_user()
    session.clear()
    flash("You've been logged out.", "info")
    return redirect(url_for('home'))


 #===============================================Forgot Password===================================================================

@app.route('/forgot-password', methods=['GET', 'POST'])
def forgot_password():
    if request.method == 'GET':
        return render_template('forgot_password.html')

    email = request.form.get('email')

    if not email:
        flash("Please enter your email.", "error")
        return render_template('forgot_password.html')

    user = User.query.filter_by(email=email).first()

    if user and user.password_hash:
        token = serializer.dumps(user.email, salt='password-reset')
        link = url_for('reset_password', token=token, _external=True)
        msg = Message(
            'Reset your ORLE password',
            recipients=[user.email],
            sender=app.config['MAIL_USERNAME']
        )
        msg.body = f'Click the link below to reset your password:\n\n{link}\n\nThis link expires in 1 hour. If you did not request this, ignore this email.'
        mail.send(msg)

    flash("If an account exists with that email, a reset link has been sent.", "info")
    return redirect(url_for('login'))


@app.route('/reset-password/<token>', methods=['GET', 'POST'])
def reset_password(token):
    try:
        email = serializer.loads(token, salt='password-reset', max_age=3600)
    except SignatureExpired:
        flash("This reset link has expired. Please request a new one.", "error")
        return redirect(url_for('forgot_password'))
    except BadSignature:
        flash("This reset link is invalid.", "error")
        return redirect(url_for('forgot_password'))

    user = User.query.filter_by(email=email).first()
    if not user:
        flash("No account found for this link.", "error")
        return redirect(url_for('forgot_password'))

    if request.method == 'GET':
        return render_template('reset_password.html', token=token)

    password = request.form.get('password')
    confirm_password = request.form.get('confirm_password')

    if not password or not confirm_password:
        flash("Please fill in both password fields.", "error")
        return render_template('reset_password.html', token=token)

    if password != confirm_password:
        flash("Passwords don't match.", "error")
        return render_template('reset_password.html', token=token)

    user.set_password(password)
    db.session.commit()

    flash("Your password has been reset. You can now log in.", "success")
    return redirect(url_for('login'))


 #===============================================Delete Account===================================================================

@app.route('/profile/delete', methods=['GET', 'POST'])
@login_required
def delete_account():
    if request.method == 'GET':
        return render_template('delete_account.html')

    password = request.form.get('password')

    if current_user.password_hash:
        if not password or not current_user.check_password(password):
            flash("Incorrect password.", "error")
            return render_template('delete_account.html')

    user = current_user._get_current_object()
    logout_user()
    db.session.delete(user)
    db.session.commit()
    session.clear()

    flash("Your account has been deleted. We're sorry to see you go.", "info")
    return redirect(url_for('home'))


#===============================================Vendor Auth===================================================================

@app.route('/vendor/register', methods=['GET', 'POST'])
def vendor_register():
    if request.method == 'GET':
        return render_template('vendor_register.html')

    business_name = request.form.get('business_name')
    email = request.form.get('email')
    phone_number = request.form.get('phone_number')
    password = request.form.get('password')
    confirm_password = request.form.get('confirm_password')

    if not business_name or not email or not password or not confirm_password:
        flash("Please fill in all required fields.", "error")
        return render_template('vendor_register.html')

    if password != confirm_password:
        flash("Passwords don't match.", "error")
        return render_template('vendor_register.html')

    if Vendor.query.filter_by(email=email).first():
        flash("A vendor account with this email already exists.", "error")
        return redirect(url_for('vendor_login'))

    vendor = Vendor(business_name=business_name, email=email, phone_number=phone_number)
    vendor.set_password(password)
    db.session.add(vendor)
    db.session.commit()

    flash("Vendor account created. You can log in now.", "success")
    return redirect(url_for('vendor_login'))


@app.route('/vendor/login', methods=['GET', 'POST'])
def vendor_login():
    if request.method == 'GET':
        return render_template('vendor_login.html')

    email = request.form.get('email')
    password = request.form.get('password')

    vendor = Vendor.query.filter_by(email=email).first()

    if not vendor or not vendor.check_password(password):
        flash("Invalid vendor credentials.", "error")
        return render_template('vendor_login.html')

    login_user(vendor)
    flash(f"Welcome back, {vendor.business_name}.", "success")
    return redirect(url_for('vendor_dashboard'))


#===============================================Vendor Dashboard===================================================================

@app.route('/vendor/dashboard')
@vendor_required
def vendor_dashboard():
    products = Product.query.filter_by(vendor_id=current_user.id).order_by(Product.created_at.desc()).all()
    return render_template('vendor_dashboard.html', products=products)


@app.route('/vendor/products/add', methods=['GET', 'POST'])
@vendor_required
def vendor_add_product():
    if request.method == 'GET':
        return render_template('vendor_product_form.html', product=None, SIZE_CHOICES=SIZE_CHOICES, size_stock={})

    image = request.files.get("product_image")
    image_path = None

    if image and image.filename:
        if not allowed_file(image.filename):
            flash("Please upload a JPG, JPEG, PNG or WEBP image.", "error")
            return redirect(request.url)
        image_path = save_product_image(image)

    requires_size = request.form.get('requires_size') == 'on'

    product = Product(
        name=request.form.get('name'),
        description=request.form.get('description'),
        price=int(request.form.get('price') or 0),
        category=request.form.get('category'),
        image_url=image_path,
        best_for_body_types=request.form.get('best_for_body_types'),
        best_for_occasions=request.form.get('best_for_occasions'),
        fit_note=request.form.get('fit_note'),
        vendor_id=current_user.id,
        requires_size=requires_size,
        stock_quantity=0 if requires_size else int(request.form.get('stock_quantity') or 0)
    )
    db.session.add(product)
    db.session.flush()

    gallery_files = request.files.getlist("gallery_images")
    for order, gfile in enumerate(gallery_files):
        path = save_product_image(gfile)
        if path:
            db.session.add(ProductImage(product_id=product.id, image_url=path, display_order=order))

    if product.requires_size:
        for size in SIZE_CHOICES:
            qty = request.form.get(f'stock_{size}')
            if qty and int(qty) > 0:
                db.session.add(ProductSize(product_id=product.id, size=size, stock_quantity=int(qty)))

    db.session.commit()
    flash("Product listed successfully.", "success")
    return redirect(url_for('vendor_dashboard'))


def save_product_image(image):
    """Returns relative path or None. Reuses your existing UPLOAD_FOLDER/allowed_file setup."""
    if not image or not image.filename or not allowed_file(image.filename):
        return None
    extension = image.filename.rsplit(".", 1)[1].lower()
    filename = f"{uuid.uuid4().hex}.{extension}"
    image.save(os.path.join(app.config["UPLOAD_FOLDER"], filename))
    return f"uploads/products/{filename}"

@app.template_filter('product_image')
def product_image(image_url):
    if not image_url:
        return url_for('static', filename='img/placeholder.png')
    if image_url.startswith('http://') or image_url.startswith('https://'):
        return image_url
    return url_for('static', filename=image_url)


@app.route('/vendor/products/<int:product_id>/edit', methods=['GET', 'POST'])
@vendor_required
def vendor_edit_product(product_id):
    product = Product.query.get_or_404(product_id)

    if product.vendor_id != current_user.id:
        flash("You don't have permission to edit this product.", "error")
        return redirect(url_for('vendor_dashboard'))

    if request.method == 'GET':
        size_stock = {s.size: s.stock_quantity for s in product.sizes} if product else {}
        return render_template('vendor_product_form.html', product=product, SIZE_CHOICES=SIZE_CHOICES, size_stock=size_stock)

    product.name = request.form.get('name')
    product.description = request.form.get('description')
    product.price = int(request.form.get('price') or 0)
    product.category = request.form.get('category')
    product.best_for_body_types = request.form.get('best_for_body_types')
    product.best_for_occasions = request.form.get('best_for_occasions')
    product.fit_note = request.form.get('fit_note')

    # cover image — unchanged behavior, replaces image_url if a new file is uploaded
    image = request.files.get("product_image")
    if image and image.filename:
        if not allowed_file(image.filename):
            flash("Please upload a JPG, JPEG, PNG or WEBP image.", "error")
            return redirect(request.url)
        product.image_url = save_product_image(image)

    # ── Gallery: delete selected existing images ──────────────
    delete_ids = request.form.getlist('delete_gallery_image')  # checkboxes named delete_gallery_image, value=image.id
    if delete_ids:
        ProductImage.query.filter(
            ProductImage.id.in_(delete_ids),
            ProductImage.product_id == product.id
        ).delete(synchronize_session=False)

    # ── Gallery: add new images ────────────────────────────────
    existing_count = ProductImage.query.filter_by(product_id=product.id).count()
    gallery_files = request.files.getlist("gallery_images")
    for offset, gfile in enumerate(gallery_files):
        path = save_product_image(gfile)
        if path:
            db.session.add(ProductImage(
                product_id=product.id,
                image_url=path,
                display_order=existing_count + offset
            ))

    # ── Sizes: toggle requires_size, then add/update/remove per size ──
    product.requires_size = request.form.get('requires_size') == 'on'

    if product.requires_size:
        for size in SIZE_CHOICES:
            qty_raw = request.form.get(f'stock_{size}')
            qty = int(qty_raw) if qty_raw and qty_raw.isdigit() else 0

            existing_size = ProductSize.query.filter_by(product_id=product.id, size=size).first()

            if qty > 0:
                if existing_size:
                    existing_size.stock_quantity = qty
                else:
                    db.session.add(ProductSize(product_id=product.id, size=size, stock_quantity=qty))
            elif existing_size:
                # quantity was cleared to 0 — remove the row rather than keep a stale 0-stock entry
                db.session.delete(existing_size)
    else:
        # sizing turned off — clear any leftover per-size stock rows
        ProductSize.query.filter_by(product_id=product.id).delete()
        if not product.requires_size:
            product.stock_quantity = int(request.form.get('stock_quantity') or 0)

    db.session.commit()
    flash("Product updated.", "success")
    return redirect(url_for('vendor_dashboard'))


@app.route('/vendor/products/<int:product_id>/delete', methods=['POST'])
@vendor_required
def vendor_delete_product(product_id):
    product = Product.query.get_or_404(product_id)

    if product.vendor_id != current_user.id:
        flash("You don't have permission to delete this product.", "error")
        return redirect(url_for('vendor_dashboard'))

    db.session.delete(product)
    db.session.commit()
    flash("Product removed.", "info")
    return redirect(url_for('vendor_dashboard'))

#===============================================Vendor Profile & Sales===================================================================

@app.route('/vendor/profile')
@vendor_required
def vendor_profile():
    start = request.args.get('start')
    end = request.args.get('end')

    if start:
        start_date = datetime.strptime(start, '%Y-%m-%d').date()
    else:
        start_date = (datetime.utcnow() - timedelta(days=30)).date()

    if end:
        end_date = datetime.strptime(end, '%Y-%m-%d').date()
    else:
        end_date = datetime.utcnow().date()

    sales = Sale.query.filter(
        Sale.vendor_id == current_user.id,
        Sale.sale_date >= start_date,
        Sale.sale_date <= end_date
    ).order_by(Sale.sale_date.asc()).all()

    # Group totals by date for the line chart
    daily_totals = {}
    for sale in sales:
        key = sale.sale_date.isoformat()
        daily_totals[key] = daily_totals.get(key, 0) + sale.amount

    chart_labels = list(daily_totals.keys())
    chart_values = list(daily_totals.values())

    # NEW — group by product for units-sold bar chart + revenue-share doughnut
    product_totals = {}  # name -> {'units': x, 'revenue': y}
    for sale in sales:
        name = sale.product.name if sale.product else 'Unknown'
        if name not in product_totals:
            product_totals[name] = {'units': 0, 'revenue': 0}
        product_totals[name]['units'] += sale.quantity
        product_totals[name]['revenue'] += sale.amount

    # sort by revenue descending so the busiest products lead the chart
    sorted_products = sorted(product_totals.items(), key=lambda kv: kv[1]['revenue'], reverse=True)
    product_labels = [name for name, _ in sorted_products]
    product_units = [totals['units'] for _, totals in sorted_products]
    product_revenue = [totals['revenue'] for _, totals in sorted_products]

    # NEW — sales grouped by weekday, to spot which days perform best
    weekday_names = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']
    weekday_totals = [0] * 7
    for sale in sales:
        weekday_totals[sale.sale_date.weekday()] += sale.amount

    total_revenue = sum(s.amount for s in sales)
    total_units = sum(s.quantity for s in sales)

    products = Product.query.filter_by(vendor_id=current_user.id).all()

    return render_template(
        'vendor_profile.html',
        vendor=current_user,
        sales=sales,
        products=products,
        chart_labels=chart_labels,
        chart_values=chart_values,
        product_labels=product_labels,
        product_units=product_units,
        product_revenue=product_revenue,
        weekday_names=weekday_names,
        weekday_totals=weekday_totals,
        total_revenue=total_revenue,
        total_units=total_units,
        start_date=start_date.isoformat(),
        end_date=end_date.isoformat()
    )
    

@app.route('/vendor/sales/add', methods=['POST'])
@vendor_required
def vendor_add_sale():
    product_id = request.form.get('product_id')
    product = Product.query.get_or_404(product_id)

    if product.vendor_id != current_user.id:
        flash("You can only log sales for your own products.", "error")
        return redirect(url_for('vendor_profile'))

    sale = Sale(
        vendor_id=current_user.id,
        product_id=product.id,
        quantity=int(request.form.get('quantity') or 1),
        amount=int(request.form.get('amount') or 0),
        sale_date=datetime.strptime(request.form.get('sale_date'), '%Y-%m-%d').date()
    )
    db.session.add(sale)
    db.session.commit()
    flash("Sale logged.", "success")
    return redirect(url_for('vendor_profile'))


@app.route('/vendor/sales/<int:sale_id>/delete', methods=['POST'])
@vendor_required
def vendor_delete_sale(sale_id):
    sale = Sale.query.get_or_404(sale_id)

    if sale.vendor_id != current_user.id:
        flash("You don't have permission to delete this entry.", "error")
        return redirect(url_for('vendor_profile'))

    db.session.delete(sale)
    db.session.commit()
    flash("Sale entry removed.", "info")
    return redirect(url_for('vendor_profile'))

#===============================================Order Status (Vendor)===================================================================

@app.route('/vendor/orders')
@vendor_required
def vendor_orders():
    order_ids = db.session.query(OrderItem.order_id).join(Product).filter(
        Product.vendor_id == current_user.id
    ).distinct().all()
    order_ids = [o[0] for o in order_ids]

    orders_list = Order.query.filter(Order.id.in_(order_ids)).order_by(Order.created_at.desc()).all()
    return render_template('vendor_orders.html', orders=orders_list)


@app.route('/vendor/orders/<int:order_id>/status', methods=['POST'])
@vendor_required
def vendor_update_order_status(order_id):
    order = Order.query.get_or_404(order_id)
    new_status = request.form.get('status')

    if new_status not in ('shipped', 'delivered', 'cancelled'):
        flash("Invalid status.", "error")
        return redirect(url_for('vendor_orders'))

    order.status = new_status
    db.session.commit()

    send_order_email(order, new_status)
    flash(f"Order marked as {new_status}.", "success")
    return redirect(url_for('vendor_orders'))

#===============================================Checkout & Payment===================================================================

@app.route('/checkout', methods=['GET', 'POST'])
@login_required
def checkout():
    items = CartItem.query.filter_by(user_id=current_user.id).all()

    if not items:
        flash("Your bag is empty.", "error")
        return redirect(url_for('cart'))

    # NEW — re-check stock right before payment, since cart items can sit for a while
    stock_problems = []
    for item in items:
        available = item.product.stock_for_size(item.size)
        if item.quantity > available:
            label = f"{item.product.name}" + (f" (size {item.size})" if item.size else "")
            stock_problems.append(f"{label} — only {available} left, you have {item.quantity} in your bag")

    if stock_problems:
        flash("Some items in your bag are no longer available in the quantity requested: " + "; ".join(stock_problems), "error")
        return redirect(url_for('cart'))

    total = sum(item.product.price * item.quantity for item in items if item.product)
    
    discount = 0
    coupon = None
    coupon_code = session.get('coupon_code')
    if coupon_code:
        coupon = Coupon.query.filter_by(code=coupon_code).first()
        if coupon:
            valid, error = coupon.is_valid_for(total)
            if valid:
                discount = coupon.calculate_discount(total)
            else:
                coupon = None
                session.pop('coupon_code', None)
    final_total = total - discount

    
    saved_addresses = Address.query.filter_by(user_id=current_user.id).order_by(Address.is_default.desc()).all()

    if request.method == 'GET':
        return render_template('checkout.html', items=items, final_total=final_total, saved_addresses=saved_addresses)

    address_id = request.form.get('address_id')

    if not address_id or address_id == 'new':
        shipping_name = request.form.get('shipping_name')
        shipping_address = request.form.get('shipping_address')
        shipping_phone = request.form.get('shipping_phone')

        if not shipping_name or not shipping_address or not shipping_phone:
            flash("Please fill in all shipping details.", "error")
            return render_template('checkout.html', items=items, total=total, saved_addresses=saved_addresses)

        if request.form.get('save_address') == 'on':
            if not saved_addresses:  # first address automatically becomes default
                db.session.add(Address(user_id=current_user.id, full_name=shipping_name, phone=shipping_phone, address_line=shipping_address, is_default=True))
            else:
                db.session.add(Address(user_id=current_user.id, full_name=shipping_name, phone=shipping_phone, address_line=shipping_address))
            db.session.commit()
    else:
        address = Address.query.get_or_404(address_id)
        if address.user_id != current_user.id:
            flash("Invalid address selected.", "error")
            return redirect(url_for('checkout'))
        shipping_name = address.full_name
        shipping_address = address.address_line
        shipping_phone = address.phone

    order = Order(
        user_id=current_user.id,
        total_amount=total,
        status='pending_payment',
        payment_status='pending',
        shipping_name=shipping_name,
        shipping_address=shipping_address,
        shipping_phone=shipping_phone
    )
    db.session.add(order)
    db.session.flush()

    for item in items:
        db.session.add(OrderItem(
            order_id=order.id,
            product_id=item.product_id,
            product_name=item.product.name,
            unit_price=item.product.price,
            quantity=item.quantity,
            size=item.size
        ))

    razorpay_order = razorpay_client.order.create({
        'amount': final_total * 100,
        'currency': 'INR',
        'receipt': f'order_{order.id}',
        'payment_capture': 1
    })
    order.razorpay_order_id = razorpay_order['id']

    db.session.commit()

    return render_template(
        'payment.html',
        order=order,
        razorpay_key_id=app.config['RAZORPAY_KEY_ID'],
        razorpay_order_id=razorpay_order['id'],
        amount=final_total * 100
    )

@app.route('/payment/verify', methods=['POST'])
@login_required
def payment_verify():
    order_id = request.form.get('order_id')
    razorpay_payment_id = request.form.get('razorpay_payment_id')
    razorpay_order_id = request.form.get('razorpay_order_id')
    razorpay_signature = request.form.get('razorpay_signature')

    order = Order.query.get_or_404(order_id)
    if order.user_id != current_user.id:
        flash("You don't have permission to complete this order.", "error")
        return redirect(url_for('cart'))

    try:
        razorpay_client.utility.verify_payment_signature({
            'razorpay_order_id': razorpay_order_id,
            'razorpay_payment_id': razorpay_payment_id,
            'razorpay_signature': razorpay_signature
        })
    except razorpay.errors.SignatureVerificationError:
        order.payment_status = 'failed'
        db.session.commit()
        flash("Payment verification failed. Please try again.", "error")
        return redirect(url_for('checkout'))

    # Signature verified — payment is genuine, finalize the order
    order.payment_status = 'paid'
    order.status = 'placed'
    order.razorpay_payment_id = razorpay_payment_id
    db.session.commit()

    # Decrement stock now that payment is confirmed
    for oi in order.items:
        product = oi.product
        if not product:
            continue
        if product.requires_size and oi.size:
            size_row = ProductSize.query.filter_by(product_id=product.id, size=oi.size).first()
            if size_row:
                size_row.stock_quantity = max(size_row.stock_quantity - oi.quantity, 0)
        elif not product.requires_size:
            product.stock_quantity = max(product.stock_quantity - oi.quantity, 0)

    # Record coupon usage now that the order is actually paid — not before,
    # since a failed/abandoned payment shouldn't burn a redemption
    if order.coupon_code:
        coupon = Coupon.query.filter_by(code=order.coupon_code).first()
        if coupon:
            coupon.times_used += 1

    db.session.commit()

    # Clear the cart now that payment succeeded
    CartItem.query.filter_by(user_id=current_user.id).delete()
    db.session.commit()

    send_order_email(order, 'placed')
    session.pop('coupon_code', None)

    flash("Payment successful. Your order has been placed.", "success")
    return redirect(url_for('order_detail', order_id=order.id))


#===============================================ADMIN===================================================================

@app.route('/admin/login', methods=['GET', 'POST'])
def admin_login():
    if request.method == 'GET':
        return render_template('admin_login.html')

    email = request.form.get('email')
    password = request.form.get('password')

    if not email or not password:
        flash("Please enter your email and password.", "error")
        return render_template('admin_login.html')

    user = User.query.filter_by(email=email).first()

    if not user or not user.check_password(password):
        flash("Invalid credentials.", "error")
        return render_template('admin_login.html')

    if not user.is_admin:
        flash("This account doesn't have admin access.", "error")
        return render_template('admin_login.html')

    login_user(user)
    flash(f"Welcome back, {user.name}.", "success")
    return redirect(url_for('admin_dashboard'))


def admin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not current_user.is_authenticated or getattr(current_user, 'is_vendor', False) or not getattr(current_user, 'is_admin', False):
            flash("Admin access required.", "error")
            return redirect(url_for('admin_login'))
        return f(*args, **kwargs)
    return decorated


@app.route('/admin')
@admin_required
def admin_dashboard():
    total_revenue = db.session.query(db.func.sum(Order.total_amount)).filter(Order.payment_status == 'paid').scalar() or 0
    total_orders = Order.query.filter(Order.payment_status == 'paid').count()
    total_users = User.query.count()
    total_vendors = Vendor.query.count()
    total_products = Product.query.count()

    orders_by_status = dict(db.session.query(Order.status, db.func.count(Order.id)).group_by(Order.status).all())

    thirty_days_ago = datetime.utcnow() - timedelta(days=30)
    daily = (
        db.session.query(db.func.date(Order.created_at), db.func.sum(Order.total_amount))
        .filter(Order.payment_status == 'paid', Order.created_at >= thirty_days_ago)
        .group_by(db.func.date(Order.created_at))
        .order_by(db.func.date(Order.created_at))
        .all()
    )
    chart_labels = [str(d[0]) for d in daily]
    chart_values = [d[1] for d in daily]

    top_products = (
        db.session.query(
            OrderItem.product_name,
            db.func.sum(OrderItem.quantity).label('units'),
            db.func.sum(OrderItem.unit_price * OrderItem.quantity).label('revenue')
        )
        .join(Order).filter(Order.payment_status == 'paid')
        .group_by(OrderItem.product_name)
        .order_by(db.desc('revenue'))
        .limit(5).all()
    )

    top_vendors = (
        db.session.query(Vendor.business_name, db.func.sum(OrderItem.unit_price * OrderItem.quantity).label('revenue'))
        .join(Product, Product.vendor_id == Vendor.id)
        .join(OrderItem, OrderItem.product_id == Product.id)
        .join(Order, Order.id == OrderItem.order_id)
        .filter(Order.payment_status == 'paid')
        .group_by(Vendor.id)
        .order_by(db.desc('revenue'))
        .limit(5).all()
    )

    recent_orders = Order.query.order_by(Order.created_at.desc()).limit(10).all()

    return render_template(
        'admin_dashboard.html',
        total_revenue=total_revenue, total_orders=total_orders,
        total_users=total_users, total_vendors=total_vendors, total_products=total_products,
        orders_by_status=orders_by_status,
        chart_labels=chart_labels, chart_values=chart_values,
        top_products=top_products, top_vendors=top_vendors,
        recent_orders=recent_orders
    )
    
    
    #===================================== Add/Remove Coupon====================================
    
@app.route('/admin/coupons')
@admin_required
def admin_coupons():
    coupons = Coupon.query.order_by(Coupon.created_at.desc()).all()
    return render_template('admin_coupons.html', coupons=coupons)


@app.route('/admin/coupons/add', methods=['GET', 'POST'])
@admin_required
def admin_add_coupon():
    if request.method == 'GET':
        return render_template('admin_coupon_form.html', coupon=None)

    code = (request.form.get('code') or '').strip().upper()
    discount_type = request.form.get('discount_type')
    discount_value = int(request.form.get('discount_value') or 0)
    min_order_amount = int(request.form.get('min_order_amount') or 0)
    max_uses = request.form.get('max_uses')
    expires_at = request.form.get('expires_at')

    if not code or discount_type not in ('percent', 'flat') or discount_value <= 0:
        flash("Please fill in a valid code, type, and discount value.", "error")
        return render_template('admin_coupon_form.html', coupon=None)

    if Coupon.query.filter_by(code=code).first():
        flash("A coupon with this code already exists.", "error")
        return render_template('admin_coupon_form.html', coupon=None)

    coupon = Coupon(
        code=code,
        discount_type=discount_type,
        discount_value=discount_value,
        min_order_amount=min_order_amount,
        max_uses=int(max_uses) if max_uses else None,
        expires_at=datetime.strptime(expires_at, '%Y-%m-%d') if expires_at else None
    )
    db.session.add(coupon)
    db.session.commit()
    flash(f"Coupon {code} created.", "success")
    return redirect(url_for('admin_coupons'))


@app.route('/admin/coupons/<int:coupon_id>/toggle', methods=['POST'])
@admin_required
def admin_toggle_coupon(coupon_id):
    coupon = Coupon.query.get_or_404(coupon_id)
    coupon.is_active = not coupon.is_active
    db.session.commit()
    flash(f"Coupon {coupon.code} {'activated' if coupon.is_active else 'deactivated'}.", "info")
    return redirect(url_for('admin_coupons'))


@app.route('/admin/coupons/<int:coupon_id>/delete', methods=['POST'])
@admin_required
def admin_delete_coupon(coupon_id):
    coupon = Coupon.query.get_or_404(coupon_id)
    db.session.delete(coupon)
    db.session.commit()
    flash("Coupon deleted.", "info")
    return redirect(url_for('admin_coupons'))

#===============================================Search===================================================================


@app.route('/search')
def search():
    query = request.args.get('q', '').strip()

    wishlisted_ids = set()
    if current_user.is_authenticated and not getattr(current_user, 'is_vendor', False):
        wishlisted_ids = {w.product_id for w in Wishlist.query.filter_by(user_id=current_user.id).all()}

    if not query:
        return render_template('search_results.html', products=[], query='', wishlisted_ids=wishlisted_ids)

    like_pattern = f"%{query}%"
    products = Product.query.filter(
        or_(
            Product.name.ilike(like_pattern),
            Product.description.ilike(like_pattern),
            Product.category.ilike(like_pattern)
        )
    ).order_by(Product.created_at.desc()).all()

    return render_template('search_results.html', products=products, query=query, wishlisted_ids=wishlisted_ids)

#===============================================Home===================================================================

@app.route('/')
def home():
    best_sellers = Product.query.order_by(Product.created_at.desc()).limit(5).all()
    new_arrivals = Product.query.order_by(Product.created_at.desc()).limit(2).all()
    offer = Offer.query.filter_by(is_active=True).order_by(Offer.display_order.asc()).first()
    categories = db.session.query(Product.category).distinct().limit(3).all()
    categories = [c[0] for c in categories]

    carousel_products = (
        Product.query
        .filter(Product.image_url.isnot(None), Product.vendor_id.isnot(None))
        .order_by(Product.created_at.desc())
        .limit(4)
        .all()
    )
    if not carousel_products:
        carousel_products = (
            Product.query
            .filter(Product.image_url.isnot(None))
            .order_by(Product.created_at.desc())
            .limit(4)
            .all()
        )

    mission_products = (
        Product.query
        .filter(Product.image_url.isnot(None))
        .order_by(Product.created_at.desc())
        .limit(2)
        .all()
    )

    return render_template(
        'home.html',
        best_sellers=best_sellers,
        new_arrivals=new_arrivals,
        offer=offer,
        categories=categories,
        carousel_products=carousel_products,
        mission_products=mission_products
    )
    
    
  #===============================================MAIN===================================================================
   
if __name__ == '__main__':
    with app.app_context():
        db.create_all()
    app.run(debug=True)