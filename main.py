import os
import uuid
from werkzeug.utils import secure_filename
from flask import Flask, request, render_template, redirect, url_for, session, flash
from flask_login import LoginManager, login_user, logout_user, login_required, current_user
from flask_jwt_extended import JWTManager
from config import Config
from functools import wraps
from models import db, User, UserProfile, Product, Offer, Vendor, Sale
from datetime import datetime, timedelta
from flask_migrate import Migrate
from authlib.integrations.flask_client import OAuth
from flask_mail import Mail, Message
from itsdangerous import URLSafeTimedSerializer, SignatureExpired, BadSignature


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


def send_verification_email(user):
    token = serializer.dumps(user.email, salt='email-verify')
    link = url_for('verify_email', token=token, _external=True)
    msg = Message(
        'Verify your ORLE account',
        recipients=[user.email],
        sender=app.config['MAIL_USERNAME']
    )
    msg.body = f'Welcome to ORLE. Click the link below to verify your email:\n\n{link}\n\nThis link expires in 1 hour.'
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

    if not name or not email or not password or not confirm_password:
        flash("Please enter the required credentials.", "error")
        return render_template('register.html')

    if password != confirm_password:
        flash("The passwords don't match.", "error")
        return render_template('register.html')

    existing_user = User.query.filter_by(email=email).first()
    if existing_user:
        flash("This email is already registered. Try logging in instead.", "error")
        return redirect(url_for('login'))

    new_user = User(name=name, email=email, phone_number=phone_number)
    new_user.set_password(password)

    db.session.add(new_user)
    db.session.commit()

    send_verification_email(new_user)
    flash("Account created! Check your email to verify before logging in.", "success")
    return render_template('check_email.html', email=email)


 #===============================================Email Verification===================================================================

@app.route('/verify/<token>')
def verify_email(token):
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
        return render_template('verify_result.html', success=True, message="Your email is already verified — you can log in.")

    user.is_verified = True
    db.session.commit()

    return render_template('verify_result.html', success=True, message="Your email has been verified. You can now log in.")


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

    user = User.query.filter_by(email=email).first()

    if not user:
        user = User(email=email, name=name, google_id=google_id, is_verified=True)
        db.session.add(user)
    elif not user.google_id:
        user.google_id = google_id

    db.session.commit()
    login_user(user)
    flash(f"Welcome, {user.name}.", "success")
    return redirect(url_for('onboarding'))


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
    return redirect(url_for('profile'))


 #===============================================Profile===================================================================

@app.route('/profile')
@login_required
def profile():
    return render_template('profile.html', user=current_user, profile=current_user.profile)


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


 #===============================================Dashboard===================================================================

@app.route('/dashboard')
def dashboard():
    offers = Offer.query.filter_by(is_active=True).order_by(Offer.display_order.asc()).all()
    latest_products = Product.query.order_by(Product.created_at.desc()).limit(8).all()
    all_products = Product.query.order_by(Product.created_at.desc()).all()

    return render_template(
        'dashboard.html',
        offers=offers,
        latest_products=latest_products,
        all_products=all_products
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

    return render_template('catalogue.html', products=products, categories=categories, active_category=category)


@app.route('/catalogue/<int:product_id>')
def product_detail(product_id):
    product = Product.query.get_or_404(product_id)
    return render_template('product_detail.html', product=product)


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
        return render_template('vendor_product_form.html', product=None)

    image = request.files.get("product_image")
    image_path = None

    if image and image.filename:

        if not allowed_file(image.filename):
            flash("Please upload a JPG, JPEG, PNG or WEBP image.", "error")
            return redirect(request.url)

        extension = image.filename.rsplit(".", 1)[1].lower()
        filename = f"{uuid.uuid4().hex}.{extension}"

        image.save(
            os.path.join(
                app.config["UPLOAD_FOLDER"],
                filename
            )
        )

        image_path = f"uploads/products/{filename}"

    product = Product(
        name=request.form.get('name'),
        description=request.form.get('description'),
        price=int(request.form.get('price') or 0),
        category=request.form.get('category'),
        image_url=image_path,
        best_for_body_types=request.form.get('best_for_body_types'),
        best_for_occasions=request.form.get('best_for_occasions'),
        fit_note=request.form.get('fit_note'),
        vendor_id=current_user.id
    )

    db.session.add(product)
    db.session.commit()

    flash("Product listed successfully.", "success")
    return redirect(url_for('vendor_dashboard'))


@app.route('/vendor/products/<int:product_id>/edit', methods=['GET', 'POST'])
@vendor_required
def vendor_edit_product(product_id):
    product = Product.query.get_or_404(product_id)

    if product.vendor_id != current_user.id:
        flash("You don't have permission to edit this product.", "error")
        return redirect(url_for('vendor_dashboard'))

    if request.method == 'GET':
        return render_template('vendor_product_form.html', product=product)

    product.name = request.form.get('name')
    product.description = request.form.get('description')
    product.price = int(request.form.get('price') or 0)
    product.category = request.form.get('category')
    product.best_for_body_types = request.form.get('best_for_body_types')
    product.best_for_occasions = request.form.get('best_for_occasions')
    product.fit_note = request.form.get('fit_note')

    image = request.files.get("product_image")

    if image and image.filename:

        if not allowed_file(image.filename):
            flash("Please upload a JPG, JPEG, PNG or WEBP image.", "error")
            return redirect(request.url)

        extension = image.filename.rsplit(".", 1)[1].lower()
        filename = f"{uuid.uuid4().hex}.{extension}"

        image.save(
            os.path.join(
                app.config["UPLOAD_FOLDER"],
                filename
            )
        )

        product.image_url = f"uploads/products/{filename}"    
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

    # Group totals by date for the chart
    daily_totals = {}
    for sale in sales:
        key = sale.sale_date.isoformat()
        daily_totals[key] = daily_totals.get(key, 0) + sale.amount

    chart_labels = list(daily_totals.keys())
    chart_values = list(daily_totals.values())

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


 #===============================================Home===================================================================

@app.route('/')
def home():
    return render_template("home.html")


 #===============================================MAIN===================================================================

if __name__ == '__main__':
    with app.app_context():
        db.create_all()
    app.run(debug=True)