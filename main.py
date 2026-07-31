# ORLE

ORLE is a men's formalwear e-commerce and recommendation platform. This repo is the Flask web
backend — customer and vendor authentication, a style-profile onboarding flow, a full shopping
cart and checkout with Razorpay payments, a vendor-managed product catalogue, coupons, reviews,
returns/cancellations, an admin dashboard, and a rule-based recommendation engine that matches
products to a customer's body type, skin tone, and occasion.

A Flutter mobile app is being built alongside this as a separate client.

## Features

### Customers
- **Email/password authentication** — hashed passwords, session-based login via Flask-Login,
  rate-limited login/register endpoints
- **Google Sign-In** — OAuth login/signup via Authlib, auto-links to an existing account by email
- **Email verification** — signed, expiring email links (Google sign-ins are verified automatically)
- **Forgot / reset password** — signed, expiring reset links; deliberately non-committal about
  whether an email is registered, to avoid leaking account existence
- **Style profile onboarding** — age group, height range, body type, skin tone, undertone, and
  occasion preference
- **Profile management** — view account + style profile, edit name/phone (email locked), delete
  account
- **Saved addresses** — add, edit, delete, and set a default shipping address
- **Personalised recommendations** — a rule-based scoring engine ranks the catalogue against a
  customer's body type, color/undertone match, occasion, and height, with a visible match score
- **Product catalogue** — browsable and filterable by category, price range, size, and color,
  with pagination and sort (newest / price low–high / price high–low)
- **Search** — free-text search across product name, description, and category, with
  autocomplete suggestions and per-user recent search history
- **Wishlist** — save/remove products, with a live wishlist count in the nav
- **Shopping cart** — add/update/remove items (with per-size stock checks), apply/remove coupon
  codes, running totals
- **Checkout & payments** — Razorpay integration, stock re-validated at checkout time, saved or
  one-off shipping addresses, order confirmation and status emails
- **Order management** — order history and detail views, cancel a pending/placed order
  (auto-refund via Razorpay + restock), request a return on a delivered order
- **Product reviews** — rate and review products from delivered orders only, one review per
  purchased item

### Vendors
- **Separate vendor authentication** — its own registration/login/forgot-password flow,
  coexisting with customer auth via a shared Flask-Login session (differentiated by an
  `is_vendor` flag and a prefixed session identity so one `user_loader` can resolve either
  account type); accounts can be suspended by an admin
- **Product listing management** — add, edit, delete products, including cover + gallery image
  uploads with server-side validation (real image decode via Pillow, re-encoded and re-saved
  under a fresh filename — not just an extension check), per-size stock for sized items,
  category, color/undertone, and body-type/occasion tagging for the recommendation engine
- **Sales dashboard** — date-range-filterable revenue chart, units/revenue-by-product breakdown,
  sales-by-weekday breakdown, and a mutable sale log (Chart.js)
- **Order fulfilment** — view orders containing their products, update status (shipped /
  delivered / cancelled) with carrier/tracking info, triggers customer status emails and
  refund + restock on cancellation

### Admin
- **Dashboard** — revenue, order, user, vendor, and product totals; orders-by-status breakdown;
  30-day revenue chart; top products and top vendors by revenue; recent orders
- **User management** — search, paginate, and grant/revoke admin access
- **Vendor management** — search, paginate, suspend/reinstate vendor accounts, per-vendor
  product counts and revenue
- **Product moderation** — search/paginate all products, adjust discounts, activate/deactivate,
  or permanently delete
- **Coupon management** — create percent/flat coupons with minimum order value, usage caps, and
  expiry; activate/deactivate or delete
- **Offers** — homepage/landing offer banners with an image, title, subtitle, link, and display
  order, each with its own product landing page
- **Review moderation** — paginate and remove reviews
- **Returns** — review pending return requests, approve (issues a partial or full Razorpay
  refund and restocks) or reject

### Site-wide
- **Floating flash notifications** — toast-style, auto-dismissing based on message length
- **Responsive nav** — collapses into an animated hamburger menu on mobile, with a live wishlist
  count
- **Rate limiting** — Flask-Limiter on auth and other sensitive POST endpoints, backed by Redis
  in production (falls back to in-memory if `REDIS_URL` isn't set)
- **CSRF protection** — Flask-WTF, with an explicit exemption for the signature-verified
  Razorpay webhook endpoint
- **Error tracking** — optional Sentry integration (enabled when `SENTRY_DSN` is set)
- **JWT scaffolding** — Flask-JWT-Extended is wired in for a future API layer the Flutter app
  will call directly

## Tech stack

| Layer | Tool |
|---|---|
| Backend framework | Flask |
| ORM | Flask-SQLAlchemy |
| Migrations | Flask-Migrate (Alembic) |
| Web session auth | Flask-Login |
| OAuth | Authlib |
| Email | Flask-Mail |
| Signed tokens (verify/reset links) | itsdangerous |
| API auth (planned) | Flask-JWT-Extended |
| Password hashing | Werkzeug security |
| Payments | Razorpay (orders, signature-verified checkout, webhooks, refunds) |
| Rate limiting | Flask-Limiter (Redis-backed, falls back to in-memory) |
| CSRF protection | Flask-WTF |
| Image validation/processing | Pillow |
| Error tracking | Sentry SDK (optional) |
| Templating | Jinja2 |
| Charts | Chart.js |
| Database (local) | SQLite |
| Database (production) | PostgreSQL |

## Project structure

```
Orle-web/
├── main.py                    # App entry point — all routes
├── config.py                   # Reads secrets/config from environment
├── models.py                   # User, UserProfile, Product, Offer, Vendor, Sale,
│                                # Wishlist, CartItem, Order, OrderItem, Address, Review,
│                                # ProductImage, ProductSize, Coupon, SearchHistory, Return
├── recommendations.py           # Rule-based scoring engine
├── seed_data.py                 # Populates sample men's formalwear + offers
├── requirements.txt
├── .env                          # Local secrets — never committed
├── .env.example                   # Template of required env vars — safe to commit
├── .gitignore
├── static/
│   ├── styles.css
│   └── uploads/
│       └── products/             # Vendor-uploaded product images
└── templates/
    ├── base.html                  # Shared layout — nav, flash messages, footer
    ├── home.html
    ├── login.html / register.html
    ├── onboarding.html
    ├── profile.html / edit_profile.html / delete_account.html
    ├── forgot_password.html / reset_password.html / check_email.html / verify_result.html
    ├── addresses.html / address_form.html
    ├── dashboard.html
    ├── catalogue.html / product_detail.html / search_results.html
    ├── recommendations.html / _recommendation_grid.html
    ├── wishlist.html / cart.html
    ├── checkout.html / payment.html
    ├── orders.html / order_detail.html
    ├── offer_detail.html
    ├── vendor_login.html / vendor_register.html
    ├── vendor_forgot_password.html / vendor_reset_password.html
    ├── vendor_dashboard.html / vendor_product_form.html / vendor_profile.html
    ├── vendor_orders.html / vendor_order_detail.html
    ├── admin_login.html / admin_dashboard.html
    ├── admin_users.html / admin_vendors.html / admin_products.html
    ├── admin_coupons.html / admin_coupon_form.html
    ├── admin_offers.html / admin_offer_form.html
    ├── admin_reviews.html / admin_returns.html
    └── ...
```

## Getting started

### 1. Clone and set up a virtual environment

```bash
git clone https://github.com/rajan083/OrleWeb.git
cd Orle-web
python -m venv venv
venv\Scripts\Activate.ps1        # Windows PowerShell
# source venv/bin/activate       # macOS/Linux
```

### 2. Install dependencies

```bash
pip install -r requirements.txt
```

### 3. Configure environment variables

Copy `.env.example` to `.env` and fill in real values:

```
SECRET_KEY=some-random-string
JWT_SECRET_KEY=another-random-string
DATABASE_URL=                          # leave blank locally — falls back to SQLite

GOOGLE_CLIENT_ID=from-google-cloud-console
GOOGLE_CLIENT_SECRET=from-google-cloud-console

MAIL_USERNAME=your-gmail@gmail.com
MAIL_PASSWORD=your-16-character-app-password

RAZORPAY_KEY_ID=from-razorpay-dashboard
RAZORPAY_KEY_SECRET=from-razorpay-dashboard
RAZORPAY_WEBHOOK_SECRET=from-razorpay-webhook-settings

REDIS_URL=                             # optional — rate limiter falls back to in-memory storage if unset
SENTRY_DSN=                            # optional — error tracking is skipped entirely if unset
```

- `GOOGLE_CLIENT_ID` / `GOOGLE_CLIENT_SECRET` need an OAuth client in Google Cloud Console —
  authorized redirect URI must be `http://127.0.0.1:5000/login/google/callback` locally.
- `MAIL_PASSWORD` must be a Gmail **App Password** (requires 2-Step Verification), not your
  regular Gmail password.
- `RAZORPAY_KEY_ID` / `RAZORPAY_KEY_SECRET` come from the Razorpay dashboard; `RAZORPAY_WEBHOOK_SECRET`
  is generated when you configure the `/webhooks/razorpay` endpoint there — payment confirmation
  and stock decrement both rely on this webhook being correctly signed and reachable.

### 4. Set up the database

```bash
flask --app main db init        # only once, if migrations/ doesn't exist yet
flask --app main db migrate -m "initial tables"
flask --app main db upgrade
```

### 5. (Optional) Seed sample products and offers

```bash
python seed_data.py
```

### 6. Create an admin account

```bash
flask --app main create-admin
```

Prompts for email, display name, and password; promotes an existing account to admin if the
email already exists.

### 7. Run the app

```bash
python main.py
```

Visit `http://127.0.0.1:5000`.

## Routes

| Route | Method | Description |
|---|---|---|
| `/` | GET | Landing page |
| `/register` / `/login` | GET, POST | Customer auth |
| `/login/google` / `/login/google/callback` | GET | Google OAuth flow |
| `/verify/<token>` | GET | Confirm email via link |
| `/forgot-password` / `/reset-password/<token>` | GET, POST | Password reset flow |
| `/onboarding` | GET, POST | Style profile (requires login) |
| `/profile` / `/profile/edit` / `/profile/delete` | — | Account management (requires login) |
| `/addresses` / `/addresses/add` / `/addresses/<id>/edit` / `/addresses/<id>/delete` | — | Saved addresses (requires login) |
| `/dashboard` | GET | Personalised home — offers, new arrivals, ranked recommendations |
| `/catalogue` / `/catalogue/<int:product_id>` | GET | Browse / view a product |
| `/catalogue/<int:product_id>/review` | POST | Submit a review for a delivered purchase |
| `/search` / `/search/suggest` / `/search/history` / `/search/history/clear` | GET, POST | Product search, autocomplete, and history |
| `/recommendations` / `/recommendations/update` | GET, POST | Ranked products matched to the customer's style profile |
| `/wishlist` / `/wishlist/toggle/<id>` | GET, POST | Wishlist management (requires login) |
| `/cart` / `/cart/add/<id>` / `/cart/update/<id>` / `/cart/remove/<id>` | GET, POST | Shopping cart (requires login) |
| `/cart/apply-coupon` / `/cart/remove-coupon` | POST | Coupon application at cart level |
| `/checkout` | GET, POST | Address selection + Razorpay order creation (requires login) |
| `/payment/verify` | POST | Client-side payment confirmation (signature-verified) |
| `/webhooks/razorpay` | POST | Server-side payment confirmation (HMAC-verified, CSRF-exempt) |
| `/orders` / `/orders/<id>` | GET | Order history and detail (requires login) |
| `/orders/<id>/cancel` | POST | Cancel a pending/placed order (auto-refund + restock) |
| `/orders/<id>/return` | POST | Request a return on a delivered order |
| `/offers/<int:offer_id>` | GET | Offer landing page |
| `/logout` | GET | End session |
| `/vendor/register` / `/vendor/login` | GET, POST | Vendor auth |
| `/vendor/forgot-password` / `/vendor/reset-password/<token>` | GET, POST | Vendor password reset |
| `/vendor/dashboard` | GET | Vendor's own product listings (paginated) |
| `/vendor/products/add` / `/vendor/products/<id>/edit` / `/vendor/products/<id>/delete` | — | Product management (requires vendor login) |
| `/vendor/profile` | GET | Sales charts + filterable sale log |
| `/vendor/sales/add` / `/vendor/sales/<id>/delete` | POST | Log / remove a sale entry |
| `/vendor/orders` / `/vendor/orders/<id>` | GET | Orders containing the vendor's products |
| `/vendor/orders/<id>/status` | POST | Update order status (shipped/delivered/cancelled) |
| `/admin/login` | GET, POST | Admin auth |
| `/admin` | GET | Admin dashboard — revenue, orders, top products/vendors |
| `/admin/users` / `/admin/users/<id>/toggle-admin` | GET, POST | User management |
| `/admin/vendors` / `/admin/vendors/<id>/toggle-suspend` | GET, POST | Vendor management |
| `/admin/products` / `/admin/products/<id>/discount` / `/admin/products/<id>/toggle-active` / `/admin/products/<id>/delete` | — | Product moderation |
| `/admin/coupons` / `/admin/coupons/add` / `/admin/coupons/<id>/toggle` / `/admin/coupons/<id>/delete` | — | Coupon management |
| `/admin/offers` / `/admin/offers/add` / `/admin/offers/<id>/edit` / `/admin/offers/<id>/toggle` / `/admin/offers/<id>/delete` | — | Offer/banner management |
| `/admin/reviews` / `/admin/reviews/<id>/delete` | — | Review moderation |
| `/admin/returns` / `/admin/returns/<id>/approve` / `/admin/returns/<id>/reject` | GET, POST | Return request handling |

## How the recommendation engine works

`recommendations.py` is a transparent, rule-based scoring system — not a trained ML model. It
scores every product against a customer's saved `UserProfile` across four weighted factors:

- **Color match (35%)** — skin tone + undertone against a color-harmony table
- **Body type (30%)** — whether the product is tagged as suited to the customer's body type
- **Occasion (25%)** — whether the product matches the customer's stated occasion
- **Height (10%)** — a light adjustment based on silhouette (structured vs. relaxed)

This was a deliberate choice over ML for the current stage: there's no user interaction data
yet (clicks, saves, purchases) to train a model on, and a transparent rule-based system is
easier to debug and tune. Once real usage data exists, the natural next step is training a
lightweight model (e.g. logistic regression or gradient boosting) to re-rank these results,
rather than replacing the rules outright.

## Payments & order lifecycle

- Checkout re-validates stock immediately before creating a Razorpay order, since items can sit
  in a cart for a while.
- Payment confirmation happens on **two paths that both need to work**: the client-side redirect
  to `/payment/verify` (signature-verified) and the server-side `/webhooks/razorpay` (HMAC-verified).
  Whichever arrives first finalises the order (marks it paid, decrements stock, clears the cart,
  sends the confirmation email); the other is a no-op guarded by `payment_status == 'paid'`, so a
  retried or delayed webhook can't double-decrement stock.
- Cancellations and approved returns both restock inventory and issue a Razorpay refund
  (idempotency-keyed so a retried request can't double-refund), and both use `with_for_update()`
  row locking to avoid a race between a customer and a vendor/admin acting on the same order.

## Deployment notes

- Never run with `debug=True` in production.
- Use a production WSGI server (`gunicorn main:app`), not Flask's built-in dev server.
- Set every value from `.env.example` as an environment variable on the host, including the
  Razorpay keys/webhook secret, and `REDIS_URL` if you want persistent rate-limit state across
  restarts/instances instead of the in-memory fallback.
- Run `flask --app main db upgrade` once against the production database after first deploy.
- Update the Google OAuth client's authorized redirect URI to the production domain.
- Configure the Razorpay webhook endpoint (`/webhooks/razorpay`) in the Razorpay dashboard to
  point at the production domain, and confirm the webhook secret matches.
- Vendor-uploaded product images are stored on local disk (`static/uploads/products/`) — this
  won't persist on hosts with an ephemeral filesystem (see the SQLite-in-production note below,
  the same issue applies to uploaded files). Move to object storage (S3, Cloudinary, etc.)
  before a real production launch.
- **Never commit `.env`.** If a secret is ever accidentally committed, rotate it immediately.

## Roadmap

- [ ] Move product image storage to cloud object storage before production
- [ ] JWT-based API endpoints for the Flutter app
- [ ] Learned re-ranking model once real user interaction data exists
- [ ] Vendor two-factor authentication (deferred until there's a concrete need for it)
- [ ] Persistent rate-limit storage (Redis) as a standard part of the production deploy, not an
      optional fallback