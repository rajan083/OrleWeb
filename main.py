import os
import uuid
from flask import Flask, request, render_template, redirect, url_for, session, flash
from sqlalchemy import or_
from flask_login import LoginManager, login_user, logout_user, login_required, current_user
from flask_jwt_extended import JWTManager
from config import Config
from functools import wraps
from models import db, User, UserProfile, Product, Offer, Vendor, Sale, Wishlist, CartItem, Order, OrderItem, Address, Review, ProductImage, ProductSize, SIZE_CHOICES, Coupon, SearchHistory,CATEGORY_CHOICES, Return
from datetime import datetime, timedelta
from flask_migrate import Migrate
from authlib.integrations.flask_client import OAuth
from flask_mail import Mail, Message
from itsdangerous import URLSafeTimedSerializer, SignatureExpired, BadSignature
from recommendations import recommend_products
import razorpay
import click
import hmac
import hashlib
import json
from flask_wtf.csrf import CSRFProtect
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from PIL import Image, UnidentifiedImageError
import sentry_sdk
from sentry_sdk.integrations.flask import FlaskIntegration


app = Flask(__name__)
Config.validate()
app.config.from_object(Config)

csrf = CSRFProtect(app)

limiter = Limiter(
    get_remote_address,
    app=app,
    default_limits=[],
    storage_uri=app.config.get('REDIS_URL') or "memory://",  # CHANGED — falls back to memory:// if REDIS_URL isn't set
)


if app.config.get('SENTRY_DSN'):
    sentry_sdk.init(
        dsn=app.config['SENTRY_DSN'],
        integrations=[FlaskIntegration()],
        traces_sample_rate=0.1,
        environment='production' if Config.IS_PRODUCTION else 'development',
        send_default_pii=False,  # or True, your call — see note above
    )
    
UPLOAD_FOLDER = os.path.join(app.root_path, "static", "uploads", "products")
ALLOWED_EXTENSIONS = {"png", "jpg", "jpeg", "webp"}

app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER

os.makedirs(UPLOAD_FOLDER, exist_ok=True)

MAX_IMAGE_SIZE_BYTES = 5 * 1024 * 1024  # NEW — 5MB per file
ALLOWED_IMAGE_FORMATS = {"JPEG", "PNG", "WEBP"}  # NEW — Pillow's format names, not extensions

app.config["MAX_CONTENT_LENGTH"] = MAX_IMAGE_SIZE_BYTES  

db.init_app(app)
migrate = Migrate(app, db)
jwt = JWTManager(app)

mail = Mail(app)
serializer = URLSafeTimedSerializer(app.config['SECRET_KEY'])

razorpay_client = razorpay.Client(auth=(app.config['RAZORPAY_KEY_ID'], app.config['RAZORPAY_KEY_SECRET']))


@app.errorhandler(413)
def file_too_large(e):
    flash(f"File is too large — please keep uploads under {MAX_IMAGE_SIZE_BYTES // (1024*1024)}MB.", "error")
    return redirect(request.referrer or url_for('home')), 413


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


def send_vendor_verification_email(vendor):
    token = serializer.dumps(vendor.email, salt='vendor-email-verify')
    link = url_for('verify_vendor_email', token=token, _external=True)
    msg = Message(
        'Verify your ORLE vendor account',
        recipients=[vendor.email],
        sender=app.config['MAIL_USERNAME']
    )
    msg.body = f'Welcome to ORLE. Click the link below to verify your vendor account:\n\n{link}\n\nThis link expires in 1 hour.'
    mail.send(msg)


def send_return_email(ret, event):
    subjects = {
        'refunded': 'Your ORLE return has been approved',
        'rejected': 'Your ORLE return request was not approved',
    }
    bodies = {
        'refunded': (
            f"Good news — your return for Order #{ret.order_id} has been approved.\n\n"
            f"Reason: {ret.reason}\n\n"
            f"A refund has been initiated and will reflect in 5-7 business days."
        ),
        'rejected': (
            f"Your return request for Order #{ret.order_id} was not approved.\n\n"
            f"Reason given: {ret.reason}\n\n"
            f"If you have questions about this decision, please contact support."
        ),
    }

    msg = Message(
        subjects.get(event, 'Return update'),
        recipients=[ret.customer.email],
        sender=app.config['MAIL_USERNAME']
    )
    msg.body = bodies.get(event, f"Your return status has changed to: {event}")
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


def safe_int(value, default=None, min_value=None, max_value=None):
    """Parses a form value as int, returning `default` (not raising) on bad input."""
    if value is None or value == '':
        return default
    try:
        result = int(value)
    except (ValueError, TypeError):
        return default
    if min_value is not None:
        result = max(result, min_value)
    if max_value is not None:
        result = min(result, max_value)
    return result


def safe_date(value, fmt='%Y-%m-%d'):
    """Parses a form/query date string, returning None (not raising) on bad input."""
    if not value:
        return None
    try:
        return datetime.strptime(value, fmt)
    except (ValueError, TypeError):
        return None


def vendor_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not current_user.is_authenticated or not getattr(current_user, 'is_vendor', False):
            flash("Please log in as a vendor to access this page.", "error")
            return redirect(url_for('vendor_login'))
        return f(*args, **kwargs)
    return decorated


@app.errorhandler(429)
def ratelimit_handler(e):
    flash("Too many attempts. Please wait a moment and try again.", "error")
    return redirect(request.referrer or url_for('home')), 429


 #===============================================Register===================================================================

@app.route('/register', methods=['GET', 'POST'])
@limiter.limit("5 per hour", methods=["POST"])
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


@app.route('/vendor/verify/<token>')
def verify_vendor_email(token):
    try:
        email = serializer.loads(token, salt='vendor-email-verify', max_age=3600)
    except SignatureExpired:
        return render_template('verify_result.html', success=False, message="This verification link has expired. Please register again or request a new link.")
    except BadSignature:
        return render_template('verify_result.html', success=False, message="This verification link is invalid.")

    vendor = Vendor.query.filter_by(email=email).first()
    if not vendor:
        return render_template('verify_result.html', success=False, message="No vendor account found for this link.")

    if vendor.is_verified:
        return render_template('verify_result.html', success=True, message="Your vendor account is already verified — you can log in.", next=url_for('vendor_login'))

    vendor.is_verified = True
    db.session.commit()

    return render_template('verify_result.html', success=True, message="Your vendor account has been verified. You can now log in.", next=url_for('vendor_login'))


 #===============================================Login================================================================

@app.route('/login', methods=['GET', 'POST'])
@limiter.limit("10 per minute", methods=["POST"])
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
    return_count = Return.query.filter_by(customer_id=current_user.id).count()
 
    return render_template(
        'profile.html',
        user=current_user,
        profile=current_user.profile,
        order_count=order_count,
        wishlist_count=wishlist_count,
        address_count=address_count,
        return_count=return_count
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


#===============================================Return===================================================================


@app.route('/returns')
@login_required
def returns():
    if getattr(current_user, 'is_vendor', False):
        flash("This page is for customers only.", "error")
        return redirect(url_for('vendor_dashboard'))
 
    user_returns = (
        Return.query
        .filter_by(customer_id=current_user.id)
        .order_by(Return.requested_at.desc())
        .all()
    )
    return render_template('returns.html', returns=user_returns)


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
    house_number = request.form.get('house_number')
    street = request.form.get('street')
    area = request.form.get('area')
    city = request.form.get('city')
    district = request.form.get('district')
    state = request.form.get('state')
    pincode = request.form.get('pincode')
    make_default = request.form.get('is_default') == 'on'

    if not full_name or not phone or not house_number or not street or not city or not state or not pincode:
        flash("Please fill in all required address fields.", "error")
        return render_template('address_form.html', address=None)

    if make_default:
        Address.query.filter_by(user_id=current_user.id).update({'is_default': False})

    new_address = Address(
        user_id=current_user.id,
        full_name=full_name,
        phone=phone,
        house_number=house_number,
        street=street,
        area=area,
        city=city,
        district=district,
        state=state,
        pincode=pincode,
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
    address.house_number = request.form.get('house_number')
    address.street = request.form.get('street')
    address.area = request.form.get('area')
    address.city = request.form.get('city')
    address.district = request.form.get('district')
    address.state = request.form.get('state')
    address.pincode = request.form.get('pincode')

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
    latest_products = Product.query.filter_by(is_active=True).order_by(Product.created_at.desc()).limit(8).all()
    all_products = Product.query.filter_by(is_active=True).order_by(Product.created_at.desc()).all()

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
    min_price = request.args.get('min_price', type=int)
    max_price = request.args.get('max_price', type=int)
    size = request.args.get('size')
    color = request.args.get('color')
    sort = request.args.get('sort', 'newest')
    page = request.args.get('page', 1, type=int)

    query = Product.query.filter_by(is_active = True)
    if category:
        query = query.filter_by(category=category)
    if min_price is not None:
        query = query.filter(Product.price >= min_price)
    if max_price is not None:
        query = query.filter(Product.price <= max_price)
    if color:
        query = query.filter_by(color=color)
    if size:
        # sized products: must have that size in stock. unsized products: excluded when a size filter is active.
        query = query.join(ProductSize).filter(ProductSize.size == size, ProductSize.stock_quantity > 0)

    sort_options = {
        'newest': Product.created_at.desc(),
        'price_low': Product.price.asc(),
        'price_high': Product.price.desc(),
    }
    query = query.order_by(sort_options.get(sort, Product.created_at.desc()))

    pagination = query.paginate(page=page, per_page=24, error_out=False)
    products = pagination.items

    categories = db.session.query(Product.category).distinct().all()
    categories = [c[0] for c in categories]

    colors = db.session.query(Product.color).filter(Product.color.isnot(None)).distinct().all()
    colors = [c[0] for c in colors]

    wishlisted_ids = set()
    if current_user.is_authenticated and not getattr(current_user, 'is_vendor', False):
        wishlisted_ids = {w.product_id for w in Wishlist.query.filter_by(user_id=current_user.id).all()}

    return render_template(
        'catalogue.html',
        products=products,
        categories=categories,
        colors=colors,
        active_category=category,
        active_min_price=min_price,
        active_max_price=max_price,
        active_size=size,
        active_color=color,
        active_sort=sort,
        pagination=pagination,
        wishlisted_ids=wishlisted_ids,
        SIZE_CHOICES=SIZE_CHOICES
    )


@app.route('/catalogue/<int:product_id>')
def product_detail(product_id):
    product = Product.query.get_or_404(product_id)

    is_admin_or_owner = (
        current_user.is_authenticated and
        (getattr(current_user, 'is_admin', False) or
         (getattr(current_user, 'is_vendor', False) and product.vendor_id == current_user.id))
    )

    if not product.is_active and not is_admin_or_owner:
        flash("This product is no longer available.", "error")
        return redirect(url_for('catalogue'))
                        
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

    rating = safe_int(request.form.get('rating'), default=0)
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


@app.context_processor
def inject_wishlist_count():
    if current_user.is_authenticated and not getattr(current_user, 'is_vendor', False):
        count = Wishlist.query.filter_by(user_id=current_user.id).count()
        return {'wishlist_count': count}
    return {'wishlist_count': 0}


#===============================================Cart===================================================================

@app.route('/cart')
@login_required
def cart():
    items = CartItem.query.filter_by(user_id=current_user.id).all()
    total = sum(item.product.discounted_price * item.quantity for item in items if item.product)
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

    available_coupons = []
    for c in Coupon.query.all():
        eligible, reason = c.is_valid_for(total)
        c.eligible = eligible
        c.ineligible_reason = reason
        available_coupons.append(c)

    return render_template('cart.html', items=items, total=total, discount=discount, final_total=final_total, coupon=coupon, available_coupons=available_coupons)

@app.route('/cart/apply-coupon', methods=['POST'])
@login_required
def apply_coupon():
    code = (request.form.get('coupon_code') or '').strip().upper()
    items = CartItem.query.filter_by(user_id=current_user.id).all()
    total = sum(item.product.discounted_price * item.quantity for item in items if item.product)
    
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
    quantity = safe_int(request.form.get('quantity'), default=1, min_value=1)
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

    quantity = safe_int(request.form.get('quantity'), default=1, min_value=1)

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

    # most recent return for this order, regardless of status — drives both
    # the status badge and whether the "Request a Return" form is shown
    return_request = (Return.query.filter_by(order_id=order.id).order_by(Return.requested_at.desc()).first())

    return render_template('order_detail.html', order=order, return_request=return_request)

#===============================================Order Cancellation (Customer)===================================================================

CANCELLABLE_STATUSES = ('pending_payment', 'placed')

def cancel_order_with_refund(order, reason='Order cancellation'):
    """
    Restocks items and issues a Razorpay refund if payment was captured.
    Returns (success: bool, message: str). Does NOT commit — caller commits.
    Mutates order.status to 'cancelled' only on success.
    """
    if order.payment_status == 'paid' and order.razorpay_payment_id:
        try:
            razorpay_client.payment.refund(order.razorpay_payment_id, {
                'amount': order.total_amount * 100,
                'speed': 'optimum',
                'notes': {'reason': reason, 'order_id': str(order.id)}
            }, idempotency_key=f"order-cancel-{order.id}")  # NEW
        except razorpay.errors.BadRequestError as e:
            return False, f"We couldn't process the refund automatically ({str(e)}). Please contact support to complete this cancellation."
        except Exception:
            return False, "Something went wrong initiating the refund. Please contact support — this order has not been cancelled."

        order.payment_status = 'refunded'

    for oi in order.items:
        product = oi.product
        if not product:
            continue
        if product.requires_size and oi.size:
            size_row = ProductSize.query.filter_by(product_id=product.id, size=oi.size).first()
            if size_row:
                size_row.stock_quantity += oi.quantity
            else:
                db.session.add(ProductSize(product_id=product.id, size=oi.size, stock_quantity=oi.quantity))
        elif not product.requires_size:
            product.stock_quantity += oi.quantity

    order.status = 'cancelled'
    return True, "Order cancelled." + (" A refund has been initiated and will reflect in 5-7 business days." if order.payment_status == 'refunded' else "")


def process_return_refund(ret):
    """
    Restocks the returned item(s) and issues a Razorpay refund for just that portion.
    Returns (success: bool, message: str). Does NOT commit — caller commits.
    Mutates ret.status to 'refunded' only on success.
    """
    order = ret.order

    if ret.order_item_id:
        items_to_restock = [ret.order_item]
        refund_amount = ret.order_item.unit_price * ret.order_item.quantity
    else:
        items_to_restock = order.items
        refund_amount = order.total_amount

    if order.payment_status == 'paid' and order.razorpay_payment_id:
        try:
            razorpay_client.payment.refund(order.razorpay_payment_id, {
                'amount': refund_amount * 100,
                'speed': 'optimum',
                'notes': {'reason': 'Return approved', 'order_id': str(order.id), 'return_id': str(ret.id)}
            }, idempotency_key=f"return-refund-{ret.id}")  # NEW
        except razorpay.errors.BadRequestError as e:
            return False, f"We couldn't process the refund automatically ({str(e)}). Please contact support to complete this return."
        except Exception:
            return False, "Something went wrong initiating the refund. Please contact support — this return has not been processed."

    for oi in items_to_restock:
        product = oi.product
        if not product:
            continue
        if product.requires_size and oi.size:
            size_row = ProductSize.query.filter_by(product_id=product.id, size=oi.size).first()
            if size_row:
                size_row.stock_quantity += oi.quantity
            else:
                db.session.add(ProductSize(product_id=product.id, size=oi.size, stock_quantity=oi.quantity))
        elif not product.requires_size:
            product.stock_quantity += oi.quantity

    ret.status = 'refunded'
    ret.resolved_at = datetime.utcnow()
    return True, f"Return refunded (₹{refund_amount})."


@app.route('/orders/<int:order_id>/cancel', methods=['POST'])
@login_required
def order_cancel(order_id):
    order = Order.query.with_for_update().get_or_404(order_id)  # CHANGED

    if order.user_id != current_user.id:
        flash("You don't have permission to cancel this order.", "error")
        return redirect(url_for('orders'))

    if order.status not in CANCELLABLE_STATUSES:
        flash(f"This order can no longer be cancelled — it's already {order.status}.", "error")
        return redirect(url_for('order_detail', order_id=order.id))

    success, message = cancel_order_with_refund(order, reason='Customer-initiated cancellation')
    db.session.commit()  # releases the row lock

    if success:
        send_order_email(order, 'cancelled')
        flash(message, "success")
    else:
        flash(message, "error")

    return redirect(url_for('order_detail', order_id=order.id))


@app.route('/orders/<int:order_id>/return', methods=['POST'])
@login_required
def order_return_request(order_id):
    order = Order.query.get_or_404(order_id)

    if order.user_id != current_user.id:
        flash("You don't have permission to do that.", "error")
        return redirect(url_for('order_detail', order_id=order.id))

    if order.status != 'delivered':
        flash("Returns can only be requested for delivered orders.", "error")
        return redirect(url_for('order_detail', order_id=order.id))

    existing = Return.query.filter_by(order_id=order.id, status='requested').first()
    if existing:
        flash("A return request is already pending for this order.", "error")
        return redirect(url_for('order_detail', order_id=order.id))

    reason = request.form.get('reason', '').strip()
    if not reason:
        flash("Please provide a reason for the return.", "error")
        return redirect(url_for('order_detail', order_id=order.id))

    order_item_id = request.form.get('order_item_id')  # optional — None means whole order
    return_req = Return(
        order_id=order.id,
        order_item_id=order_item_id if order_item_id else None,
        customer_id=current_user.id,
        reason=reason
    )
    db.session.add(return_req)
    db.session.commit()
    flash("Return request submitted. You'll be notified once it's reviewed.", "success")
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
@limiter.limit("5 per hour", methods=["POST"])
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



@app.route('/vendor/forgot-password', methods=['GET', 'POST'])
@limiter.limit("5 per hour", methods=["POST"])
def vendor_forgot_password():
    if request.method == 'GET':
        return render_template('vendor_forgot_password.html')

    email = request.form.get('email')

    if not email:
        flash("Please enter your email.", "error")
        return render_template('vendor_forgot_password.html')

    vendor = Vendor.query.filter_by(email=email).first()

    if vendor:
        token = serializer.dumps(vendor.email, salt='vendor-password-reset')
        link = url_for('vendor_reset_password', token=token, _external=True)
        msg = Message(
            'Reset your ORLE vendor password',
            recipients=[vendor.email],
            sender=app.config['MAIL_USERNAME']
        )
        msg.body = f'Click the link below to reset your vendor password:\n\n{link}\n\nThis link expires in 1 hour. If you did not request this, ignore this email.'
        mail.send(msg)

    flash("If a vendor account exists with that email, a reset link has been sent.", "info")
    return redirect(url_for('vendor_login'))


@app.route('/vendor/reset-password/<token>', methods=['GET', 'POST'])
def vendor_reset_password(token):
    try:
        email = serializer.loads(token, salt='vendor-password-reset', max_age=3600)
    except SignatureExpired:
        flash("This reset link has expired. Please request a new one.", "error")
        return redirect(url_for('vendor_forgot_password'))
    except BadSignature:
        flash("This reset link is invalid.", "error")
        return redirect(url_for('vendor_forgot_password'))

    vendor = Vendor.query.filter_by(email=email).first()
    if not vendor:
        flash("No vendor account found for this link.", "error")
        return redirect(url_for('vendor_forgot_password'))

    if request.method == 'GET':
        return render_template('vendor_reset_password.html', token=token)

    password = request.form.get('password')
    confirm_password = request.form.get('confirm_password')

    if not password or not confirm_password:
        flash("Please fill in both password fields.", "error")
        return render_template('vendor_reset_password.html', token=token)

    if password != confirm_password:
        flash("Passwords don't match.", "error")
        return render_template('vendor_reset_password.html', token=token)

    vendor.set_password(password)
    db.session.commit()

    flash("Your vendor password has been reset. You can now log in.", "success")
    return redirect(url_for('vendor_login'))

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
@limiter.limit("5 per hour", methods=["POST"])
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

    send_vendor_verification_email(vendor)
    flash("Vendor account created! Check your email to verify before logging in.", "success")
    return render_template('check_email.html', email=email)


@app.route('/vendor/login', methods=['GET', 'POST'])
@limiter.limit("10 per minute", methods=["POST"])
def vendor_login():
    if request.method == 'GET':
        return render_template('vendor_login.html')

    email = request.form.get('email')
    password = request.form.get('password')

    vendor = Vendor.query.filter_by(email=email).first()

    if not vendor or not vendor.check_password(password):
        flash("Invalid vendor credentials.", "error")
        return render_template('vendor_login.html')

    if not vendor.is_verified:
        flash("Please verify your email before logging in. Check your inbox.", "error")
        return render_template('vendor_login.html')

    if vendor.is_suspended:
        flash("This vendor account has been suspended. Contact support for details.", "error")
        return render_template('vendor_login.html')

    login_user(vendor)
    flash(f"Welcome back, {vendor.business_name}.", "success")
    return redirect(url_for('vendor_dashboard'))


#===============================================Vendor Dashboard===================================================================

@app.route('/vendor/dashboard')
@vendor_required
def vendor_dashboard():
    page = request.args.get('page', 1, type=int)  # NEW
    pagination = Product.query.filter_by(vendor_id=current_user.id).order_by(Product.created_at.desc()).paginate(page=page, per_page=12, error_out=False)  # NEW
    return render_template('vendor_dashboard.html', products=pagination.items, pagination=pagination)  # CHANGED


@app.route('/vendor/products/add', methods=['GET', 'POST'])
@vendor_required
def vendor_add_product():
    if request.method == 'GET':
        active_offers = Offer.query.filter_by(is_active=True).order_by(Offer.display_order.asc()).all()
        return render_template('vendor_product_form.html', product=None, SIZE_CHOICES=SIZE_CHOICES, CATEGORY_CHOICES=CATEGORY_CHOICES, size_stock={}, active_offers=active_offers)
    image = request.files.get("product_image")
    image_path = None

    if image and image.filename:
        image_path, error = validate_and_save_image(image)
        if error:
            flash(error, "error")
            return redirect(request.url)

    requires_size = request.form.get('requires_size') == 'on'

    body_types = request.form.getlist('best_for_body_types')
    occasions = request.form.getlist('best_for_occasions')

    product = Product(
        name=request.form.get('name'),
        description=request.form.get('description'),
        price=safe_int(request.form.get('price'), default=0, min_value=0),
        category=request.form.get('category'),
        image_url=image_path,
        best_for_body_types=','.join(body_types) if body_types else None,
        best_for_occasions=','.join(occasions) if occasions else None,
        color=request.form.get('color') or None,
        color_undertone=request.form.get('color_undertone') or None,
        fit_note=request.form.get('fit_note'),
        vendor_id=current_user.id,
        requires_size=requires_size,
        stock_quantity=0 if requires_size else safe_int(request.form.get('stock_quantity'), default=0, min_value=0),
        discount_percent=safe_int(request.form.get('discount_percent'), default=0, min_value=0, max_value=100),
        offer_id=safe_int(request.form.get('offer_id'), default=None),
    )
    db.session.add(product)
    db.session.flush()

    gallery_files = request.files.getlist("gallery_images")
    for order, gfile in enumerate(gallery_files):
        path, error = validate_and_save_image(gfile)  # CHANGED
        if path:
            db.session.add(ProductImage(product_id=product.id, image_url=path, display_order=order))
    # silently skips invalid gallery files rather than failing the whole submit — a bad gallery image

    if product.requires_size:
        
        for size in SIZE_CHOICES:
            qty = safe_int(request.form.get(f'stock_{size}'), default=0, min_value=0)
            if qty > 0:
                db.session.add(ProductSize(product_id=product.id, size=size, stock_quantity=qty))

    db.session.commit()
    flash("Product listed successfully.", "success")
    return redirect(url_for('vendor_dashboard'))


def validate_and_save_image(file_storage):
    """
    Validates that file_storage is a genuine image — checked via Pillow's actual
    decode, not just the extension or browser-supplied Content-Type (both spoofable) —
    then re-encodes it fresh and saves under a new UUID filename. Re-encoding also
    strips any non-image payload that might be hiding inside an otherwise-valid file.
    Returns (relative_path, error_message) — exactly one of the two will be set.
    """
    if not file_storage or not file_storage.filename:
        return None, None  # nothing submitted — not an error

    if not allowed_file(file_storage.filename):
        return None, "Please upload a JPG, JPEG, PNG or WEBP image."

    file_storage.stream.seek(0, os.SEEK_END)
    size = file_storage.stream.tell()
    file_storage.stream.seek(0)
    if size > MAX_IMAGE_SIZE_BYTES:
        return None, f"Image is too large — please keep uploads under {MAX_IMAGE_SIZE_BYTES // (1024*1024)}MB."

    try:
        img = Image.open(file_storage.stream)
        img.verify()  # checks the file is a structurally valid image
        file_storage.stream.seek(0)
        img = Image.open(file_storage.stream)  # re-open — verify() leaves the handle unusable for further ops
        if img.format not in ALLOWED_IMAGE_FORMATS:
            return None, "Unsupported image format."
        img.load()  # forces full decode now, catching truncated/corrupt files early
    except (UnidentifiedImageError, OSError, ValueError):
        return None, "This file isn't a valid image."

    if img.format == "JPEG" and img.mode in ("RGBA", "P"):
        img = img.convert("RGB")  # JPEG can't encode alpha/palette data — convert first or save() will error

    ext = {"JPEG": "jpg", "PNG": "png", "WEBP": "webp"}[img.format]
    filename = f"{uuid.uuid4().hex}.{ext}"
    img.save(os.path.join(app.config["UPLOAD_FOLDER"], filename))

    return f"uploads/products/{filename}", None

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
        active_offers = Offer.query.filter_by(is_active=True).order_by(Offer.display_order.asc()).all()
        return render_template('vendor_product_form.html', product=product, SIZE_CHOICES=SIZE_CHOICES, CATEGORY_CHOICES=CATEGORY_CHOICES, size_stock=size_stock, active_offers=active_offers)
    body_types = request.form.getlist('best_for_body_types')
    occasions = request.form.getlist('best_for_occasions')

    product.name = request.form.get('name')
    product.description = request.form.get('description')
    product.price = safe_int(request.form.get('price'), default=product.price, min_value=0)
    product.category = request.form.get('category')
    product.best_for_body_types = ','.join(body_types) if body_types else None
    product.best_for_occasions = ','.join(occasions) if occasions else None
    product.color = request.form.get('color') or None
    product.color_undertone = request.form.get('color_undertone') or None
    product.discount_percent = safe_int(request.form.get('discount_percent'), default=0, min_value=0, max_value=100)
    product.offer_id = safe_int(request.form.get('offer_id'), default=None)
    product.fit_note = request.form.get('fit_note')

    # cover image — unchanged behavior, replaces image_url if a new file is uploaded
    image = request.files.get("product_image")
    if image and image.filename:
        image_path, error = validate_and_save_image(image)
        if error:
            flash(error, "error")
            return redirect(request.url)

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
    for order, gfile in enumerate(gallery_files):
        path, error = validate_and_save_image(gfile)  # CHANGED
        if path:
            db.session.add(ProductImage(product_id=product.id, image_url=path, display_order=order))
        # silently skips invalid gallery files rather than failing the whole submit — a bad gallery image
        # shouldn't block the primary listing from being saved

    # ── Sizes: toggle requires_size, then add/update/remove per size ──
    product.requires_size = request.form.get('requires_size') == 'on'

    if product.requires_size:
        for size in SIZE_CHOICES:
            qty = safe_int(request.form.get(f'stock_{size}'), default=0, min_value=0)

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
        product.stock_quantity = safe_int(request.form.get('stock_quantity'), default=product.stock_quantity, min_value=0)

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

    start_date = safe_date(start).date() if start and safe_date(start) else (datetime.utcnow() - timedelta(days=30)).date()
    end_date = safe_date(end).date() if end and safe_date(end) else datetime.utcnow().date()

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
    
@app.route('/vendor/profile/edit', methods=['GET', 'POST'])
@vendor_required
def vendor_edit_profile():
    if request.method == 'GET':
        return render_template('vendor_edit_profile.html', vendor=current_user)

    business_name = request.form.get('business_name')
    phone_number = request.form.get('phone_number')

    if not business_name:
        flash("Business name can't be empty.", "error")
        return render_template('vendor_edit_profile.html', vendor=current_user)

    current_user.business_name = business_name
    current_user.phone_number = phone_number

    # Bank / payout details — all optional, admin uses these for manual settlement
    current_user.bank_account_holder = request.form.get('bank_account_holder') or None
    current_user.bank_account_number = request.form.get('bank_account_number') or None
    current_user.bank_ifsc = (request.form.get('bank_ifsc') or '').strip().upper() or None
    current_user.bank_name = request.form.get('bank_name') or None
    current_user.upi_id = (request.form.get('upi_id') or '').strip() or None

    db.session.commit()
    flash("Your business details have been updated.", "success")
    return redirect(url_for('vendor_profile'))

@app.route('/vendor/sales/add', methods=['POST'])
@vendor_required
def vendor_add_sale():
    product_id = request.form.get('product_id')
    product = Product.query.get_or_404(product_id)

    if product.vendor_id != current_user.id:
        flash("You can only log sales for your own products.", "error")
        return redirect(url_for('vendor_profile'))

    quantity = safe_int(request.form.get('quantity'), default=1, min_value=1)
    amount = safe_int(request.form.get('amount'), default=0, min_value=0)
    sale_date = safe_date(request.form.get('sale_date'))

    if not sale_date:
        flash("Please enter a valid sale date.", "error")
        return redirect(url_for('vendor_profile'))

    sale = Sale(
        vendor_id=current_user.id,
        product_id=product.id,
        quantity=quantity,
        amount=amount,
        sale_date=sale_date.date()
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



@app.route('/vendor/orders/<int:order_id>')
@vendor_required
def vendor_order_detail(order_id):
    order = Order.query.get_or_404(order_id)

    vendor_items = [oi for oi in order.items if oi.product and oi.product.vendor_id == current_user.id]

    if not vendor_items:
        flash("You don't have permission to view this order.", "error")
        return redirect(url_for('vendor_orders'))

    vendor_subtotal = sum(oi.unit_price * oi.quantity for oi in vendor_items)

    return render_template('vendor_order_detail.html', order=order, vendor_items=vendor_items, vendor_subtotal=vendor_subtotal)


@app.route('/vendor/orders/<int:order_id>/status', methods=['POST'])
@vendor_required
def vendor_update_order_status(order_id):
    order = Order.query.get_or_404(order_id)

    owns_item = db.session.query(OrderItem).join(Product).filter(OrderItem.order_id == order.id,Product.vendor_id == current_user.id).first()
    
    if not owns_item:
        flash("You don't have permission to update this order.", "error")
        return redirect(url_for('vendor_orders'))

    new_status = request.form.get('status')
    if new_status not in ('shipped', 'delivered', 'cancelled'):
        flash("Invalid status.", "error")
        return redirect(url_for('vendor_orders'))

    if new_status == 'cancelled':
        order = Order.query.with_for_update().get(order.id)  
        if order.status not in CANCELLABLE_STATUSES:
            flash(f"This order can no longer be cancelled — it's already {order.status}.", "error")
            return redirect(url_for('vendor_orders'))

        success, message = cancel_order_with_refund(order, reason='Vendor-initiated cancellation')
        db.session.commit()

        if success:
            send_order_email(order, 'cancelled')
            flash(message, "success")
        else:
            flash(message, "error")
        return redirect(url_for('vendor_orders'))

    if new_status == 'shipped':  # NEW
        order.carrier_name = request.form.get('carrier_name', '').strip() or None      # NEW
        order.tracking_number = request.form.get('tracking_number', '').strip() or None  # NEW
        order.tracking_url = request.form.get('tracking_url', '').strip() or None      # NEW

    order.status = new_status
    db.session.commit()
    send_order_email(order, new_status)
    flash(f"Order marked as {new_status}.", "success")
    return redirect(url_for('vendor_orders'))


#===============================================Checkout & Payment===================================================================


@app.route('/webhooks/razorpay', methods=['POST'])
@csrf.exempt
def razorpay_webhook():
    payload = request.get_data()  # raw bytes — signature is computed over the raw body, not parsed JSON
    signature = request.headers.get('X-Razorpay-Signature', '')

    expected_signature = hmac.new(
        app.config['RAZORPAY_WEBHOOK_SECRET'].encode('utf-8'),
        payload,
        hashlib.sha256
    ).hexdigest()

    if not hmac.compare_digest(expected_signature, signature):
        return {"error": "Invalid signature"}, 400

    event = json.loads(payload)
    event_type = event.get('event')

    if event_type == 'payment.captured':
        handle_payment_captured(event)
    elif event_type == 'payment.failed':
        handle_payment_failed(event)
    # Other events (refund.processed, etc.) can be added here later

    return {"status": "ok"}, 200


def handle_payment_captured(event):
    payment_entity = event['payload']['payment']['entity']
    razorpay_order_id = payment_entity.get('order_id')
    razorpay_payment_id = payment_entity.get('id')

    order = Order.query.filter_by(razorpay_order_id=razorpay_order_id).first()
    if not order:
        return  # unknown order — nothing to do (shouldn't normally happen)

    if order.payment_status == 'paid':
        return  # already processed — webhook retry, avoid double-decrementing stock

    order.payment_status = 'paid'
    order.status = 'placed'
    order.razorpay_payment_id = razorpay_payment_id
    db.session.commit()

    # Decrement stock — same logic as payment_verify()
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

    if order.coupon_code:
        coupon = Coupon.query.filter_by(code=order.coupon_code).first()
        if coupon:
            coupon.times_used += 1

    db.session.commit()

    CartItem.query.filter_by(user_id=order.user_id).delete()
    db.session.commit()

    send_order_email(order, 'placed')


def handle_payment_failed(event):
    payment_entity = event['payload']['payment']['entity']
    razorpay_order_id = payment_entity.get('order_id')

    order = Order.query.filter_by(razorpay_order_id=razorpay_order_id).first()
    if not order or order.payment_status == 'paid':
        return  # unknown order, or already succeeded elsewhere — don't downgrade a paid order

    order.payment_status = 'failed'
    db.session.commit()


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

    total = sum(item.product.discounted_price * item.quantity for item in items if item.product)
    
    # ── Apply coupon (mirrors cart()) ──────────────────────────
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
    # ─────────────────────────────────────────────────────────

    # Razorpay's minimum order amount is ₹1 (100 paise). A large flat coupon,
    # or a 100%-off percent coupon, can drive final_total to 0 or below —
    # catch that here instead of letting Razorpay's order.create() reject it.
    if final_total < 1:
        flash("This order's total is too low to process after the discount applied. Please adjust your cart or remove the coupon.", "error")
        return redirect(url_for('cart'))
 
    saved_addresses = Address.query.filter_by(user_id=current_user.id).order_by(Address.is_default.desc()).all()

    if request.method == 'GET':
        return render_template('checkout.html', items=items, total=total, discount=discount, final_total=final_total, coupon=coupon, saved_addresses=saved_addresses)

    address_id = request.form.get('address_id')

    if not address_id or address_id == 'new':
        shipping_name = request.form.get('shipping_name')
        house_number = request.form.get('house_number')
        street = request.form.get('street')
        area = request.form.get('area')
        city = request.form.get('city')
        district = request.form.get('district')
        state = request.form.get('state')
        pincode = request.form.get('pincode')
        shipping_phone = request.form.get('shipping_phone')

        if not shipping_name or not house_number or not street or not city or not state or not pincode or not shipping_phone:
            flash("Please fill in all shipping details.", "error")
            return render_template('checkout.html', items=items, total=total, discount=discount, final_total=final_total, coupon=coupon, saved_addresses=saved_addresses)

        # Build the combined address string the same way Address.full_address does
        parts = [house_number, street]
        if area:
            parts.append(area)
        parts.append(city)
        if district and district.lower() != city.lower():
            parts.append(district)
        parts.append(state)
        parts.append(pincode)
        shipping_address = ', '.join(p for p in parts if p)

        if request.form.get('save_address') == 'on':
            new_addr = Address(
                user_id=current_user.id, full_name=shipping_name, phone=shipping_phone,
                house_number=house_number, street=street, area=area, city=city,
                district=district, state=state, pincode=pincode,
                is_default=not saved_addresses
            )
            db.session.add(new_addr)
            db.session.commit()
    else:
        address = Address.query.get_or_404(address_id)
        if address.user_id != current_user.id:
            flash("Invalid address selected.", "error")
            return redirect(url_for('checkout'))
        shipping_name = address.full_name
        shipping_address = address.full_address
        shipping_phone = address.phone

    order = Order(
        user_id=current_user.id,
        subtotal_amount = total,
        discount_amount = discount,
        total_amount=final_total,
        coupon_code=coupon.code if coupon else None,
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
            unit_price=item.product.discounted_price,
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

    # NEW — if the webhook already finalized this order, don't redo the work
    if order.payment_status == 'paid':
        flash("Payment successful. Your order has been placed.", "success")
        return redirect(url_for('order_detail', order_id=order.id))

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

    order.payment_status = 'paid'
    order.status = 'placed'
    order.razorpay_payment_id = razorpay_payment_id
    db.session.commit()

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

    if order.coupon_code:
        coupon = Coupon.query.filter_by(code=order.coupon_code).first()
        if coupon:
            coupon.times_used += 1

    db.session.commit()

    CartItem.query.filter_by(user_id=current_user.id).delete()
    db.session.commit()

    send_order_email(order, 'placed')
    session.pop('coupon_code', None)

    flash("Payment successful. Your order has been placed.", "success")
    return redirect(url_for('order_detail', order_id=order.id))


#===============================================ADMIN===================================================================

@app.route('/admin/login', methods=['GET', 'POST'])
@limiter.limit("5 per minute", methods=["POST"])
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
    discount_value = safe_int(request.form.get('discount_value'), default=0)
    min_order_amount = safe_int(request.form.get('min_order_amount'), default=0)
    max_uses_raw = request.form.get('max_uses')
    max_uses = safe_int(max_uses_raw, default=None) if max_uses_raw else None
    expires_at_raw = request.form.get('expires_at')

    if expires_at_raw:
        expires_at = safe_date(expires_at_raw)
        if not expires_at:
            flash("Please enter a valid expiry date.", "error")
            return render_template('admin_coupon_form.html', coupon=None)
    else:
        expires_at = None

    if not code or discount_type not in ('percent', 'flat') or discount_value <= 0:
        flash("Please fill in a valid code, type, and discount value.", "error")
        return render_template('admin_coupon_form.html', coupon=None)

    coupon = Coupon(
        code=code,
        discount_type=discount_type,
        discount_value=discount_value,
        min_order_amount=min_order_amount,
        max_uses=max_uses,
        expires_at=expires_at
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


#===================================== Admin: Manage Users ====================================

@app.route('/admin/users')
@admin_required
def admin_users():
    search_q = request.args.get('q', '').strip()
    page = request.args.get('page', 1, type=int)  

    query = User.query
    if search_q:
        query = query.filter(
            or_(
                User.name.ilike(f"%{search_q}%"),
                User.email.ilike(f"%{search_q}%")
            )
        )

    pagination = query.order_by(User.created_at.desc()).paginate(page=page, per_page=12, error_out=False) 
    return render_template('admin_users.html', users=pagination.items, pagination=pagination, search_q=search_q)  


@app.route('/admin/users/<int:user_id>/toggle-admin', methods=['POST'])
@admin_required
def admin_toggle_admin(user_id):
    user = User.query.get_or_404(user_id)

    if user.id == current_user.id:
        flash("You can't remove your own admin access.", "error")
        return redirect(url_for('admin_users'))

    user.is_admin = not user.is_admin
    db.session.commit()
    flash(f"{user.email} {'granted' if user.is_admin else 'removed from'} admin access.", "info")
    return redirect(url_for('admin_users'))


#===================================== Admin: Manage Vendors ====================================

@app.route('/admin/vendors')
@admin_required
def admin_vendors():
    search_q = request.args.get('q', '').strip()
    page = request.args.get('page', 1, type=int)  # NEW

    query = Vendor.query
    if search_q:
        query = query.filter(
            or_(
                Vendor.business_name.ilike(f"%{search_q}%"),
                Vendor.email.ilike(f"%{search_q}%")
            )
        )

    pagination = query.order_by(Vendor.created_at.desc()).paginate(page=page, per_page=12, error_out=False)  # NEW

    product_counts = dict(
        db.session.query(Product.vendor_id, db.func.count(Product.id))
        .group_by(Product.vendor_id).all()
    )
    revenue_by_vendor = dict(
        db.session.query(Sale.vendor_id, db.func.sum(Sale.amount))
        .group_by(Sale.vendor_id).all()
    )

    return render_template(
        'admin_vendors.html',
        vendors=pagination.items,  # CHANGED
        pagination=pagination,  # NEW
        search_q=search_q,
        product_counts=product_counts,
        revenue_by_vendor=revenue_by_vendor
    )
    

@app.route('/admin/vendors/<int:vendor_id>/toggle-suspend', methods=['POST'])
@admin_required
def admin_toggle_vendor_suspend(vendor_id):
    vendor = Vendor.query.get_or_404(vendor_id)
    vendor.is_suspended = not vendor.is_suspended
    db.session.commit()
    flash(f"{vendor.business_name} {'suspended' if vendor.is_suspended else 'reinstated'}.", "info")
    return redirect(url_for('admin_vendors'))

#===================================== Admin: Offers ====================================

@app.route('/admin/offers')
@admin_required
def admin_offers():
    offers = Offer.query.order_by(Offer.display_order.asc()).all()
    return render_template('admin_offers.html', offers=offers)


@app.route('/admin/offers/add', methods=['GET', 'POST'])
@admin_required
def admin_add_offer():
    if request.method == 'GET':
        return render_template('admin_offer_form.html', offer=None)

    title = request.form.get('title')
    subtitle = request.form.get('subtitle')
    link_url = request.form.get('link_url')
    display_order = int(request.form.get('display_order') or 0)

    image = request.files.get('offer_image')
    image_path = None
    if image and image.filename:
        image_path, error = validate_and_save_image(image)
        if error:
            flash(error, "error")
            return redirect(request.url)

    if not title or not image_path:
        flash("Please provide a title and an image.", "error")
        return render_template('admin_offer_form.html', offer=None)

    db.session.add(Offer(title=title, subtitle=subtitle, image_url=image_path, link_url=link_url, display_order=display_order))
    db.session.commit()
    flash("Offer created.", "success")
    return redirect(url_for('admin_offers'))


@app.route('/admin/offers/<int:offer_id>/edit', methods=['GET', 'POST'])
@admin_required
def admin_edit_offer(offer_id):
    offer = Offer.query.get_or_404(offer_id)
    if request.method == 'GET':
        return render_template('admin_offer_form.html', offer=offer)

    offer.title = request.form.get('title')
    offer.subtitle = request.form.get('subtitle')
    offer.link_url = request.form.get('link_url')
    offer.display_order = int(request.form.get('display_order') or 0)

    image = request.files.get('offer_image')
    if image and image.filename:
        image_path, error = validate_and_save_image(image)
        if error:
            flash(error, "error")
            return redirect(request.url)

    db.session.commit()
    flash("Offer updated.", "success")
    return redirect(url_for('admin_offers'))


@app.route('/admin/offers/<int:offer_id>/toggle', methods=['POST'])
@admin_required
def admin_toggle_offer(offer_id):
    offer = Offer.query.get_or_404(offer_id)
    offer.is_active = not offer.is_active
    db.session.commit()
    flash(f"Offer {'activated' if offer.is_active else 'deactivated'}.", "info")
    return redirect(url_for('admin_offers'))


@app.route('/admin/offers/<int:offer_id>/delete', methods=['POST'])
@admin_required
def admin_delete_offer(offer_id):
    offer = Offer.query.get_or_404(offer_id)
    db.session.delete(offer)
    db.session.commit()
    flash("Offer deleted.", "info")
    return redirect(url_for('admin_offers'))

#===================================== Admin: Review Moderation ====================================

@app.route('/admin/reviews')
@admin_required
def admin_reviews():
    page = request.args.get('page', 1, type=int)  # NEW
    pagination = Review.query.order_by(Review.created_at.desc()).paginate(page=page, per_page=12, error_out=False)  # NEW
    return render_template('admin_reviews.html', reviews=pagination.items, pagination=pagination)  # CHANGED


@app.route('/admin/reviews/<int:review_id>/delete', methods=['POST'])
@admin_required
def admin_delete_review(review_id):
    review = Review.query.get_or_404(review_id)
    db.session.delete(review)
    db.session.commit()
    flash("Review removed.", "info")
    return redirect(url_for('admin_reviews'))



#===================================== Admin: Returns ====================================

@app.route('/admin/returns')
@admin_required
def admin_returns():
    returns = Return.query.filter_by(status='requested').order_by(Return.requested_at.asc()).all()
    return render_template('admin_returns.html', returns=returns)


@app.route('/admin/returns/<int:return_id>/approve', methods=['POST'])
@admin_required
def admin_approve_return(return_id):
    ret = Return.query.with_for_update().get_or_404(return_id)
    if ret.status != 'requested':
        flash("This return has already been resolved.", "error")
        return redirect(url_for('admin_returns'))

    ret.resolved_by_id = current_user.id
    success, message = process_return_refund(ret)
    db.session.commit()

    if success:
        send_return_email(ret, 'refunded')
        flash(f"Return #{ret.id} approved. {message}", "success")
    else:
        # ret.resolved_by_id was set but status stays 'requested' since refund failed — admin can retry
        db.session.rollback()
        flash(message, "error")

    return redirect(url_for('admin_returns'))

@app.route('/admin/returns/<int:return_id>/reject', methods=['POST'])
@admin_required
def admin_reject_return(return_id):
    ret = Return.query.get_or_404(return_id)
    if ret.status != 'requested':
        flash("This return has already been resolved.", "error")
        return redirect(url_for('admin_returns'))

    ret.status = 'rejected'
    ret.resolved_at = datetime.utcnow()
    ret.resolved_by_id = current_user.id
    db.session.commit()

    send_return_email(ret, 'rejected')
    flash(f"Return #{ret.id} rejected.", "info")
    return redirect(url_for('admin_returns'))


#===============================================Offer Landing Page===================================================================

@app.route('/offers/<int:offer_id>')
def offer_detail(offer_id):
    offer = Offer.query.get_or_404(offer_id)

    if not offer.is_active:
        flash("This offer is no longer active.", "error")
        return redirect(url_for('catalogue'))

    products = Product.query.filter_by(offer_id=offer.id, is_active=True).order_by(Product.created_at.desc()).all()

    wishlisted_ids = set()
    if current_user.is_authenticated and not getattr(current_user, 'is_vendor', False):
        wishlisted_ids = {w.product_id for w in Wishlist.query.filter_by(user_id=current_user.id).all()}

    return render_template('offer_detail.html', offer=offer, products=products, wishlisted_ids=wishlisted_ids)

#===================================== Admin: Product Discounts ====================================

@app.route('/admin/products')
@admin_required
def admin_products():
    search_q = request.args.get('q', '').strip()
    page = request.args.get('page', 1, type=int)  # NEW

    query = Product.query
    if search_q:
        query = query.filter(Product.name.ilike(f"%{search_q}%"))

    pagination = query.order_by(Product.created_at.desc()).paginate(page=page, per_page=12, error_out=False)  # NEW
    return render_template('admin_products.html', products=pagination.items, pagination=pagination, search_q=search_q)  # CHANGED


@app.route('/admin/products/<int:product_id>/discount', methods=['POST'])
@admin_required
def admin_update_discount(product_id):
    product = Product.query.get_or_404(product_id)
    discount = safe_int(request.form.get('discount_percent'), default=0, min_value=0, max_value=100)
    product.discount_percent = discount
    db.session.commit()
    flash(f"Discount for {product.name} set to {discount}%.", "success")
    return redirect(url_for('admin_products'))


@app.route('/admin/products/<int:product_id>/toggle-active', methods=['POST'])
@admin_required
def admin_toggle_product_active(product_id):
    product = Product.query.get_or_404(product_id)
    product.is_active = not product.is_active
    db.session.commit()
    flash(f"{product.name} {'activated' if product.is_active else 'deactivated'}.", "info")
    return redirect(url_for('admin_products'))


@app.route('/admin/products/<int:product_id>/delete', methods=['POST'])
@admin_required
def admin_delete_product(product_id):
    product = Product.query.get_or_404(product_id)
    name = product.name
    db.session.delete(product)
    db.session.commit()
    flash(f"{name} permanently deleted.", "info")
    return redirect(url_for('admin_products'))


#===============================================Search===================================================================


@app.route('/search')
def search():
    query = request.args.get('q', '').strip()
    sort = request.args.get('sort', 'newest')
    page = request.args.get('page', 1, type=int)

    wishlisted_ids = set()
    if current_user.is_authenticated and not getattr(current_user, 'is_vendor', False):
        wishlisted_ids = {w.product_id for w in Wishlist.query.filter_by(user_id=current_user.id).all()}

    if not query:
        return render_template('search_results.html', products=[], query='', pagination=None, active_sort=sort, wishlisted_ids=wishlisted_ids)

    if current_user.is_authenticated and not getattr(current_user, 'is_vendor', False):
        db.session.add(SearchHistory(user_id=current_user.id, query=query))
        db.session.commit()

    like_pattern = f"%{query}%"
    products_query = Product.query.filter(
        Product.is_active == True,
        or_(
            Product.name.ilike(like_pattern),
            Product.description.ilike(like_pattern),
            Product.category.ilike(like_pattern)
        )
    )

    sort_options = {
        'newest': Product.created_at.desc(),
        'price_low': Product.price.asc(),
        'price_high': Product.price.desc(),
    }
    products_query = products_query.order_by(sort_options.get(sort, Product.created_at.desc()))

    pagination = products_query.paginate(page=page, per_page=24, error_out=False)
    products = pagination.items

    return render_template('search_results.html', products=products, query=query, pagination=pagination, active_sort=sort, wishlisted_ids=wishlisted_ids)


#===============================================Search Autocomplete & History===================================================================

@app.route('/search/suggest')
def search_suggest():
    q = request.args.get('q', '').strip()
    if len(q) < 2:
        return {"products": [], "categories": []}

    like_pattern = f"%{q}%"

    product_matches = (
        Product.query
        .filter(Product.name.ilike(like_pattern))
        .order_by(Product.created_at.desc())
        .limit(5)
        .all()
    )
    products = [{"id": p.id, "name": p.name, "image_url": product_image(p.image_url)} for p in product_matches]

    category_matches = (
        db.session.query(Product.category)
        .filter(Product.category.ilike(like_pattern))
        .distinct()
        .limit(3)
        .all()
    )
    categories = [c[0] for c in category_matches]

    return {"products": products, "categories": categories}

@app.route('/search/history')
@login_required
def search_history():
    if getattr(current_user, 'is_vendor', False):
        return {"history": []}

    recent = (
        SearchHistory.query
        .filter_by(user_id=current_user.id)
        .order_by(SearchHistory.created_at.desc())
        .limit(20)
        .all()
    )

    # de-dupe by query text, preserving most-recent-first order, capped at 8
    seen = set()
    deduped = []
    for h in recent:
        key = h.query.lower()
        if key not in seen:
            seen.add(key)
            deduped.append(h.query)
        if len(deduped) >= 8:
            break

    return {"history": deduped}


@app.route('/search/history/clear', methods=['POST'])
@login_required
def search_history_clear():
    SearchHistory.query.filter_by(user_id=current_user.id).delete()
    db.session.commit()
    return {"success": True}

#===============================================Home===================================================================

@app.route('/')
def home():
    best_sellers = Product.query.filter_by(is_active=True).order_by(Product.created_at.desc()).limit(5).all()
    new_arrivals = Product.query.filter_by(is_active=True).order_by(Product.created_at.desc()).limit(2).all()
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
    
    
#===============================================CLI: Create/Promote Admin===================================================================

@app.cli.command('create-admin')
@click.option('--email', prompt=True, help='Email address for the admin account.')
@click.option('--name', prompt=True, default='Admin', help='Display name (only used if creating a new account).')
@click.password_option(help='Password for the admin account.')
def create_admin(email, name, password):
    """Create a new admin user, or promote an existing account to admin."""
    user = User.query.filter_by(email=email).first()

    if user:
        user.is_admin = True
        user.is_verified = True
        user.set_password(password)
        db.session.commit()
        click.echo(f"Existing account promoted to admin: {user.email}")
    else:
        user = User(name=name, email=email, is_admin=True, is_verified=True)
        user.set_password(password)
        db.session.add(user)
        db.session.commit()
        click.echo(f"New admin account created: {user.email}")
        
    
  #===============================================MAIN===================================================================
   
if __name__ == '__main__':
    with app.app_context():
        db.create_all()
    app.run(debug=True)