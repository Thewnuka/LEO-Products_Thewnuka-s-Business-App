# LEO PRODUCTS: Architecture

This document explains how the project is organised and the reasons behind each decision.

## 1. Big picture

```text
   Website (browser)   Windows desktop (Tauri)   Mobile (PWA)
            \                   |                    /
             \                  |                   /
              ---------> Django backend <-----------
                     (templates + REST API)
                               |
                         One database
              (SQLite on your PC / PostgreSQL live)
```

- **Django templates** render the website pages (server-side HTML, Bootstrap, vanilla JS).
- **Django REST Framework** provides the JSON API under `/api/v1/` for features
  that need it (the desktop and mobile apps, live updates, POS screens).
- The **Tauri desktop app** and the **PWA** will be thin clients of the same deployed
  backend. There are **no separate databases** for desktop or mobile.

## 2. Folder layout and why

| Folder | Purpose | Notes |
|---|---|---|
| `config/` | Settings, root URLs, WSGI/ASGI | Named `config` (not `leo_products`) so it is obviously "configuration". |
| `config/settings/` | `base.py`, `development.py`, `production.py` | Split so production can never accidentally run with development defaults. |
| `apps/` | All business apps | Keeps the project root clean as the number of apps grows. Apps are imported as `apps.<name>`. |
| `templates/` | Project-wide templates | One place for layouts, partials and error pages. |
| `static/` | CSS, JS, images, vendor libraries | Bootstrap is stored locally (not loaded from a CDN) so the UI works offline and inside Tauri. |
| `media/` | User uploads | Ignored by Git. |

**Changes from the suggested structure:**

- The project root is the existing `LEO PRODUCTS SYSTEM` folder rather than a new
  `leo-products/` subfolder, so there is no extra level of nesting.
- `config/settings/` is a package (three files) instead of one `settings.py`, to separate development and production.
- `static/vendor/` holds Bootstrap and Bootstrap Icons.
- `templates/partials/`, `templates/layouts/` and `templates/errors/` keep reusable pieces organised.
- `.vscode/` contains recommended extensions and the interpreter path (safe to commit; no secrets).

## 3. Django apps

Only apps needed now are created. The others are planned and will be added in their
own phase (`python manage.py startapp <name> apps/<name>`), which avoids empty code.

| App | Status | Responsibility |
|---|---|---|
| `core` | **Created** | `TimeStampedModel` base class, brand context processor, home page, error pages, health-check API |
| `accounts` | **Created** (Phase 02) | Custom `User` model, roles and capabilities, sign-in portals, registration, passwords, staff management, account audit log, `/api/v1/accounts/me/` |
| `dashboard` | **Created** (Phase 02) | Role router and one placeholder dashboard per staff role (Chart.js later) |
| `catalog` | **Created** (Phase 03) | Categories, products, variations (sizes, SKUs, LKR prices), units, images (see §13) |
| `inventory` | **Created** (Phase 04) | Stock items (raw materials and finished goods), movement ledger, adjustments, suppliers, purchases (see §14) |
| `suppliers` | Merged into `inventory` | Suppliers and purchases live in the inventory app because they exist to bring stock in |
| `customers` | Planned | Customer profiles and addresses |
| `shop` (incl. `cart`) | **Created** (Phase 05) | Customer storefront (browse, search, product pages) and shopping cart (see §15) |
| `orders` | **Created** (Phase 06) | Checkout, orders, status workflow, delivery settings (see §16) |
| `payments` | **Created** (Phase 06) | Payment records, cash, bank transfer, refunds, online gateway adapters (see §16) |
| `pos` | **Created** (Phase 07) | Till, cashier shifts, cash drawer movements, receipts, POS settings; sales are `orders.Order` rows (see §17) |
| `finance` | **Created** (Phase 08) | Expenses, supplier payments, reports, profit & loss, exports, audit log (see §18) |
| `notifications` | Planned | Email and in-app notifications |
| `reports` | Planned | Business reports and exports |

### Inside each app (convention for future phases)

```text
apps/<name>/
    models.py        Database tables (inherit TimeStampedModel)
    services.py      Business logic (calculations, workflows): keep it out of views
    views.py         Page views: thin, call services
    urls.py          Page routes (app_name = "<name>")
    serializers.py   API input/output
    api.py           API views
    api_urls.py      API routes, included from apps/core/api_urls.py under /api/v1/
    admin.py         Django admin registration
    tests.py         Automated tests
templates/<name>/    That app's templates
```

## 4. Database

- Configured with a single `DATABASE_URL` environment variable (parsed by `dj-database-url`).
  - Empty → SQLite file `db.sqlite3` (development).
  - `postgres://user:password@host:5432/dbname` → PostgreSQL (production).
- **Why `dj-database-url`?** It is a very small, widely used package. One variable is
  simpler and less error-prone than five separate `DB_*` variables, and it is the format
  hosting providers give you.
- Only the Django ORM is used; no raw SQL. Code written now works on both SQLite and PostgreSQL.
- `apps.core.models.TimeStampedModel` is an **abstract** base model (it creates no table)
  that gives future models `created_at` and `updated_at`.
- Production needs a PostgreSQL driver (`psycopg`). It will be added and pinned in the
  deployment phase. It is not installed now because development does not need it.

## 5. Custom User model

- `apps.accounts.models.User` extends Django's `AbstractUser`, plus an `updated_at` field.
- `AUTH_USER_MODEL = "accounts.User"` was set **before the first migration**. The
  database contains `accounts_user` and no default `auth_user` table.
- **Why now?** Django does not support switching to a custom user model after the
  first migration without rebuilding the database.
- **Roles (Phase 02):** each user has one primary `role` field. Access rules are defined in
  code as *capabilities* (see §12). Django Groups and Permissions remain available for
  extra per-person exceptions in later phases. Phase 01 planned to use Groups as the
  main mechanism; a role field plus capability map was chosen instead because "one clear
  primary role per user" is a requirement and is simpler to reason about and test.

## 6. Brand and logo

- All brand values live in `BRAND` in `config/settings/base.py`.
- `apps.core.context_processors.brand` makes them available to every template as `{{ brand.name }}`,
  `{{ brand.tagline }}`, `{{ brand.logo }}` and `{{ brand.logo_is_placeholder }}`.
- The logo image is rendered **only** by `templates/partials/_logo.html`. The navbar,
  footer, home page and error pages all include that partial.
- **Future Business Settings:** a later phase can add a settings model with an uploadable
  logo. Only the context processor changes (read from the database, fall back to `BRAND`);
  no template needs editing. The same logo will be used for receipts and the PWA icon.

## 7. Front end

- `templates/base.html` is the master layout (navbar, messages, content, footer, scripts).
- `templates/layouts/sidebar.html` adds a responsive sidebar: a slide-in drawer below
  992px and a fixed column at 992px and above. This is the base for the dashboard.
- `static/css/leo.css` contains:
  - **Design tokens** (CSS variables) in `:root`: colours, shadows, radius, fonts. Change brand colours here only.
  - Reusable classes: `.btn-leo-primary`, `.btn-leo-gold`, `.btn-leo-outline`, `.leo-card`,
    `.leo-card--interactive` (future product cards), `.leo-badge`, `.leo-table`, `.leo-table--stack`, alerts and forms.
- **Mobile first:** base styles target phones; `min-width` media queries add layout for
  576 / 768 / 992 / 1200px (the same breakpoints as Bootstrap).
- **Touch:** all buttons and inputs are at least 44px tall. Hover effects (lift, zoom)
  only apply on devices with a mouse (`@media (hover: hover) and (pointer: fine)`).
  Touch users get the same highlight on tap (`:active`), keyboard users on focus.
- Inputs use 16px text so iPhones do not zoom in when a field is tapped.
- The development-only `/style-guide/` page shows every component.

## 8. Security foundations

| Area | Setting |
|---|---|
| Secrets | `SECRET_KEY` and credentials come only from environment variables; `.env` is git-ignored; startup fails if `SECRET_KEY` is missing |
| DEBUG | `production.py` forces `DEBUG = False`, whatever the environment says |
| Hosts | Production refuses to start without `ALLOWED_HOSTS` and `DATABASE_URL` |
| CSRF | `CsrfViewMiddleware` on; `CSRF_TRUSTED_ORIGINS` from environment; secure CSRF cookie in production |
| Sessions | HttpOnly, SameSite=Lax, 8-hour age; Secure cookie in production |
| HTTPS | Production: SSL redirect, HSTS (1 hour by default; raise it after go-live), proxy-header support |
| Headers | `X-Frame-Options: DENY`, `nosniff`, `Referrer-Policy: same-origin` |
| Admin | URL path configurable (`ADMIN_URL`) |
| API | DRF defaults to **authenticated only**; public endpoints must opt out explicitly |
| Uploads | Request size limited to 5 MB |
| Passwords | Minimum length 10 plus Django's standard validators |

## 9. Error pages

`config/urls.py` connects `handler400/403/404/500` to views in `apps/core/views.py`.
Each error template (`templates/404.html` etc.) only sets its code, title and message;
the layout is shared in `templates/errors/_error_base.html`. They appear when `DEBUG=False`;
with `DEBUG=True` Django shows its detailed debug pages instead.

## 10. API

- Versioned under `/api/v1/` so future changes can live in `/api/v2/` without breaking the apps.
- `GET /api/v1/health/` returns `{"status": "ok", "app": "LEO PRODUCTS", "version": "0.1.0"}`
  for desktop and PWA clients to check connectivity.
- `/api/schema/` and `/api/docs/` (drf-spectacular) are available only when `DEBUG=True`.

## 11. Future platforms (prepared, not built)

- **PWA:** add a `manifest.json`, a service worker and icons generated from the
  central logo. The responsive layout and local Bootstrap files are already in place.
- **Tauri (Windows):** a Tauri shell that opens the deployed site URL, plus native
  features (printing receipts) where useful. The CSRF/session setup and the
  versioned API support this. `X_FRAME_OPTIONS` stays `DENY` because Tauri loads
  the site as a top-level page, not in a frame.

## 12. Authentication and role-based access control

*(Phase 02)*

### 12.1 Building blocks

| Piece | File | Purpose |
|---|---|---|
| Roles & capabilities | `apps/accounts/roles.py` | `Role` choices, `ROLE_CAPABILITIES` map, `has_capability()`, `assignable_roles()`, `can_manage_user()`. **The single source of truth for who may do what.** |
| User model | `apps/accounts/models.py` | `role`, `phone_number`, `must_change_password`, `is_primary_owner`; case-insensitive unique email; a username can never equal another account's username or email (ignoring case), and vice versa, so a sign-in name always means one account; `is_staff`/`is_superuser` derived from the role on every save |
| Enforcement | `apps/accounts/permissions.py` | `CapabilityRequiredMixin`, `RoleRequiredMixin`, `StaffRequiredMixin`, `CustomerRequiredMixin`, `@capability_required`, DRF `HasCapability` |
| Sign-in backend | `apps/accounts/backends.py` | Username **or** email; inactive users rejected; constant-time behaviour for unknown accounts; **applies the throttle**, so it covers every sign-in page including the Django admin |
| Throttling | `apps/accounts/throttling.py` | 5 failed sign-ins per account name + IP → 15-minute lock (shared by the staff portal, customer portal and `/admin/login/`) |
| Forced password change | `apps/accounts/middleware.py` | Users flagged `must_change_password` can only reach "change password" and "sign out" |
| Role landing pages | `apps/accounts/routing.py` | Where each role goes after sign-in |
| Audit log | `AccountAuditLog` model, `apps/accounts/audit.py` | Records account changes (never passwords) |
| Template helper | `apps/accounts/context_processors.py` | `{% if can.MANAGE_STAFF %}` to show/hide links |

**Rule:** code asks for a *capability* (`Capability.MANAGE_STAFF`), not a role name.
Changing what a role may do means editing one dictionary in `roles.py`.

### 12.2 The five roles and their boundaries

| Capability | Owner | IT Admin | Manager | Cashier | Customer |
|---|:-:|:-:|:-:|:-:|:-:|
| Staff portal & own dashboard | ✔ | ✔ | ✔ | ✔ | |
| View every role's dashboard | ✔ | | | | |
| View staff accounts | ✔ | ✔ | | | |
| Manage staff accounts | ✔ (IT Admin, Manager, Cashier) | ✔ (Manager, Cashier only) | | | |
| Manage user permissions | ✔ | | | | |
| Business settings | ✔ | | | | |
| Technical settings, maintenance, security log | ✔ | ✔ | | | |
| Products, inventory, suppliers, orders, customers | ✔ | | ✔ | | |
| Operational reports | ✔ | | ✔ | | |
| Payments config, finance, all reports | ✔ | | | | |
| POS: sell, receipts, take payments, own transactions | ✔ | | | ✔ | |
| Customer portal (own profile, orders, payments) | | | | | ✔ |
| Django admin site (`/admin/`) | ✔ | | | | |

Capabilities for modules not built yet (products, POS, finance…) are already defined so
the agreed boundaries are recorded; the modules will use them when they are created.

### 12.3 Two sign-in portals

| | Staff portal | Customer portal |
|---|---|---|
| URL | `/staff/login/` | `/account/login/` |
| Who | Owner, IT Admin, Manager, Cashier | Customer |
| Sign in with | Username or email | Email |
| After sign-in | Own role dashboard (`/staff/dashboard/<role>/`) | Customer home (`/account/`) |

A valid account used on the wrong portal gets the same generic message as a wrong
password ("Incorrect login details, or this account cannot sign in here"), so the forms
never reveal which accounts exist. Each portal links to the other.

### 12.4 How a request is protected

1. `SessionMiddleware` + `AuthenticationMiddleware` load the user from the session.
   Inactive users are treated as signed out on their next request.
2. `ForcePasswordChangeMiddleware` redirects users who must change their password.
3. The view's mixin checks the capability:
   - signed out → redirect to the right sign-in page (`?next=` keeps the destination);
   - signed in without the capability → branded **403** page.
4. Object-level checks (`can_manage_user`) stop actions on accounts outside the
   actor's authority, on their own account and on the primary owner.
5. Templates hide links the user cannot use. This is only for convenience; steps 1–4 are the real protection.

### 12.5 Preventing privilege escalation

- Every form lists its fields explicitly. `role`, `is_staff`, `is_superuser`,
  `is_active` and `is_primary_owner` are never self-editable.
- Public registration always saves `role = CUSTOMER`, whatever the request contains.
- Staff forms only offer the roles the signed-in manager may assign; any other submitted
  value is rejected by the form, and `save()` checks again.
- Nobody can edit, deactivate or reset themselves through staff management.
- The `/api/v1/accounts/me/` API marks `role` read-only and never returns password data.
- `is_staff`/`is_superuser` (Django admin access) are recalculated from the role on every save.

### 12.6 Primary owner protection

The account created by `bootstrap_owner` has `is_primary_owner = True`:

- cannot be deleted (a `pre_delete` signal blocks it, including bulk deletes and the admin site);
- cannot be deactivated or lose the OWNER role (`User.save()` refuses);
- cannot be managed through the staff screens by anyone;
- only one primary owner can exist (database constraint).

### 12.7 Passwords and sessions

- Hashing: Django's PBKDF2-SHA256 (with salt and many iterations). Plaintext is never stored or logged;
  sign-up and password views use `sensitive_post_parameters` so passwords are hidden from error reports.
- Validation for **staff** (and all password changes/resets): minimum 10 characters, not too similar
  to the user's details, not common, not all digits (`AUTH_PASSWORD_VALIDATORS`).
- Validation for **customer registration**: at least 6 characters, nothing else
  (`CUSTOMER_PASSWORD_VALIDATORS`). The browser checks the same minimum (`minlength="6"`) and the server
  checks it again; hashing, CSRF and password confirmation are unchanged.
- Forgot password: emailed link valid for **1 hour**, single use. The response is the same
  whether or not the email exists. Inactive accounts receive nothing.
- Change password: keeps you signed in on the current device; signs out other sessions.
- Temporary passwords set by Owner/IT Admin force a change at next sign-in and sign the
  user out everywhere.
- Sessions: new session key on every sign-in (prevents session fixation); 8-hour
  lifetime; HttpOnly, SameSite=Lax; Secure + HTTPS-only in production.
- Sign-out requires a POST with a CSRF token; `GET /logout/` shows a confirmation page.
- CSRF protection on every form and on session-authenticated API calls. A failed check
  shows the branded `403_csrf.html` page.

### 12.8 Audit log

`AccountAuditLog` records: primary owner created, customer registered, staff created,
staff details updated, role changed (old → new), activated, deactivated, temporary password
set, password changed, password reset, own profile updated. Each entry stores the actor,
target, time, IP address and non-secret details. It is read-only in the Django admin and
shown on each staff member's detail page. A later phase can move it into a system-wide audit log.

### 12.9 Adding protection to a future module (example)

```python
# apps/catalog/views.py
from apps.accounts.permissions import CapabilityRequiredMixin
from apps.accounts.roles import Capability

class ProductListView(CapabilityRequiredMixin, ListView):
    required_capability = Capability.MANAGE_CATALOG
```

```python
# apps/catalog/api.py
from apps.accounts.permissions import HasCapability

class ProductViewSet(ModelViewSet):
    permission_classes = [HasCapability]
    required_capability = Capability.MANAGE_CATALOG
```

## 13. Product catalogue

*(Phase 03, app `apps/catalog/`)*

### 13.1 Data model

```text
Category (main, parent = empty)          LEO TEA · TEA BAGS · LEO SWEETS · (any new ones)
  └─ Category (sub, parent = a main)     Black Tea · Ginger Tea Bags · Kokis · ...
Product                                  name, slug, description, image, status,
  ├─ category     → main Category          created/updated date and by whom
  ├─ subcategory  → sub Category (optional, must belong to `category`)
  └─ ProductVariation (1..n)             one sellable size of the product
        ├─ measurement_type  WEIGHT | COUNT | PIECE
        ├─ quantity + unit   e.g. 200 + g, 25 + bags, 10 + pieces
        ├─ sku               unique, case-insensitive
        ├─ selling_price     Decimal, LKR, > 0
        ├─ wholesale_price   Decimal, LKR, optional, > 0 and ≤ selling price
        ├─ is_active, image (optional), sort_order
Unit                                     measurement_type, name, symbol ("g", "bags"...),
                                         attach_symbol ("200g" vs "10 bags"), is_active
```

| Rule | Where it is enforced |
|---|---|
| Two category levels (main → sub) | `Category.clean()` |
| No duplicate category names in the same parent (ignoring case) | DB constraints + `clean()` |
| Subcategory belongs to the product's main category | `Product.clean()` |
| A product can only be **Active** with ≥ 1 active variation | `Product.clean()`; the last active variation of an active product cannot be deactivated |
| Unit matches the variation's measurement type | `ProductVariation.clean()` |
| One variation per size per product (product + unit + quantity) | DB constraint + form/API checks |
| Unique SKU (case-insensitive), 3–40 chars `A–Z 0–9 -` | DB constraint + validator |
| Prices and quantities > 0 | Validators + DB `CHECK` constraints |
| Money uses `DecimalField` (never float); currency `settings.CURRENCY_CODE = "LKR"` | Model fields; `{{ value\|money }}` template filter |

**Why two category levels?** The product form has exactly "main category" and
"subcategory". Deeper trees add complexity without a current need. `Category.MAX_DEPTH`
and `clean()` are the only places to change if that need arises.

**Why are units a table?** New sizes and units ("packs", "ml", "jars") can be added by
Owners/Managers without code changes. Measurement *types* (Weight, Count, Pieces) are a
fixed list because the system's rules depend on them. Adding a type is a small code change
in `MeasurementType` plus a migration.

### 13.2 Initial data

`apps/catalog/migrations/0002_initial_categories_and_units.py` creates the three starting
main categories with their subcategories, plus the units g, kg, bags and pieces. It is seed
data only: no application code refers to these names, and all of them can be renamed,
reordered or deactivated in the app.

### 13.3 SKU rules

- Every variation has its own SKU, stored in capitals and unique regardless of case.
- Leave the SKU empty to generate one: `LEO-<main category initials>-<product number>-<size>`,
  e.g. `LEO-LT-0007-200G` (LEO TEA), `LEO-TB-0012-25BAGS`, `LEO-LS-0003-10PIECES`,
  `LEO-LT-0007-1P5KG` (1.5 kg: the decimal point becomes `P`). If that code is taken, `-2`, `-3`… is added.
- Or type your own (3–40 letters, digits and hyphens). Lower-case input is converted to capitals.
- SKUs can be edited. Once POS and barcodes exist (Phase 06), treat SKUs as permanent.

### 13.4 Images

`apps/catalog/images.py` handles every category, product and variation image (web forms and API):

1. Size limit 5 MB (`CATALOG_IMAGE_MAX_BYTES`), and a pixel limit that blocks "decompression bombs".
2. Only real JPEG, PNG or WebP files are accepted. The file is decoded by Pillow, so a
   renamed script, SVG, GIF or damaged file is rejected whatever its name says.
3. The image is **re-encoded**: rotated upright, shrunk to fit 1600 × 1600 px
   (`CATALOG_IMAGE_MAX_SIDE`), and saved again. This strips metadata such as GPS location
   and anything hidden in the file.
4. It is stored as `media/catalog/<categories|products|variations>/<year>/<month>/<random>.<ext>`.
   The uploader's file name is never used.
5. When an image is replaced or removed, the old file is deleted after the database change is saved.
6. Without an image, the neutral placeholder `static/images/placeholder-product.svg` is shown.
   The brand logo itself still comes only from the central logo partial.

In development Django serves `media/`. In production the web server must serve `MEDIA_ROOT`
(or a cloud storage backend must be configured) during deployment (Phase 10).

### 13.5 Permissions

All catalogue pages (`/staff/catalog/...`) and API endpoints (`/api/v1/catalog/...`) require
`Capability.MANAGE_CATALOG`, which Phase 02 already granted to **OWNER** and **MANAGER** only.

| Role | Catalogue access |
|---|---|
| Owner | Full: products, variations, prices, categories, units |
| Manager | Full: products, variations, prices, categories, units |
| IT Admin | None (403), technical role only |
| Cashier | None (403) in this phase; read access for POS comes in Phase 06 |
| Customer | None (403); the public storefront comes in Phase 05 |
| Signed out | Redirected to the staff sign-in page |

No change to the authentication system was needed.

### 13.6 Archive, don't delete

| Record | Delete? | Instead |
|---|---|---|
| Category | Only when empty (no subcategories, no products); `on_delete=PROTECT` blocks the rest | Deactivate |
| Product | No (not in the UI, API or admin) | Status **Inactive** |
| Variation | No | Deactivate |
| Unit | No; `PROTECT` while variations use it | Deactivate (existing variations keep it) |

Future order lines and stock records will reference `ProductVariation` with `on_delete=PROTECT`,
so sold items can never disappear from history.

### 13.7 Ready for inventory (Phase 04)

Variations deliberately store **no stock numbers**. Phase 04 will add stock records that point
to `ProductVariation` (one stock level per variation and location) and stock movements. The
catalogue dashboard shows a note instead of any stock figure.

### 13.8 Pages and API

| Page | URL |
|---|---|
| Catalogue overview (live counts) | `/staff/catalog/` |
| Products: list (cards/table, search, filters, sort, paging) / new / detail / edit | `/staff/catalog/products/...` |
| Variations of a product: list / add / edit / (de)activate | `/staff/catalog/products/<id>/variations/...` |
| Categories: tree / new / edit / (de)activate / delete-if-empty | `/staff/catalog/categories/...` |
| Units: list / new / edit / (de)activate | `/staff/catalog/units/...` |

API (DRF, session auth, `MANAGE_CATALOG`, paginated, no DELETE):
`/api/v1/catalog/categories/`, `units/`, `products/` (same `q`, `category`, `subcategory`,
`status`, `measurement`, `sort` filters as the web list), `variations/` (`?product=<id>`).
The API runs the same model validation as the web forms.

Code layout: `models.py` (data + rules), `services.py` (slugs, SKUs, search, statistics),
`images.py` (upload safety), `forms.py`, `views.py`, `api.py`, `templatetags/catalog_tags.py`
(`money` filter, `catalog_image` tag).

## 14. Inventory, stock, suppliers and purchases

*(Phase 04, app `apps/inventory/`)*

### 14.1 Data model

```text
InventoryItem                       one stock record (quantity + levels)
  ├─ kind = RAW_MATERIAL            unpacked stock, e.g. "Unpacked Black Tea"
  │     stock_unit → catalog.Unit   kept in one unit (kg, g, ...); entries in g/kg are converted
  └─ kind = FINISHED_GOOD           exactly one catalog.ProductVariation, e.g. Black Tea 200g
        counted in whole "packets"  (label configurable, e.g. boxes)
  quantity, reorder_level, minimum_level, maximum_level (optional), allow_negative, is_active

StockMovement                       the ledger: one row per change, append-only
  item, movement_type, quantity_change (+/-), quantity_before, quantity_after,
  entered_quantity + entered_unit (what the user typed), reason, created_by, created_at,
  purchase / purchase_line (when it came from a purchase)

Supplier                            name (unique), contact, phone, email, address, reg. no., notes, is_active
Purchase  (PO-YYYY-NNNN)            supplier, date, invoice no., status DRAFT | RECEIVED | CANCELLED,
  └─ PurchaseLine                   item, quantity, unit, unit_cost (LKR), line_total; subtotal/total
```

**Raw materials vs finished goods.** They are separate stock records and are never mixed:
20 kg of loose tea is one raw-material item; "Black Tea 200g: 35 packets" is a finished-good
item linked to the 200g variation. Packing loose tea into packets is recorded as a decrease of
the raw material and an increase of the packets (two movements with reasons). Automated
production or packing runs could be added later.

**Units.** Each raw material keeps stock in one unit chosen when it is created (fixed once
stock exists). Quantities may be entered in any unit of the same measurement type that has a
conversion value (`catalog.Unit.base_quantity`: g = 1, kg = 1000), and the system converts them
(e.g. 1500 g → 1.5 kg) to 3 decimal places. Units without a conversion value (bags, pieces)
are never converted. Finished goods accept whole numbers only. All quantities use `DecimalField`.

### 14.2 The one rule: stock changes only through `services.record_movement()`

| Guarantee | How |
|---|---|
| Every change is recorded | `record_movement()` writes the `StockMovement` in the same transaction as the quantity change |
| No race conditions | The item row is locked (`select_for_update`); the quantity changes with a single `UPDATE … SET quantity = quantity + Δ` |
| No negative stock by default | That UPDATE only matches when enough stock exists; a DB `CHECK` constraint also forbids negatives unless `allow_negative` |
| Negative stock only by explicit Owner setting | `allow_negative` per item, editable only with `CONFIGURE_STOCK_RULES` (Owner) |
| Stale screens can't overwrite stock | Saving an item's settings never writes `quantity` (`InventoryItem.save()` excludes it) |
| Corrections use the real current figure | Computed from the locked row; refused if stock changed during the update |
| History is permanent | Movements can't be edited or deleted (model, bulk-delete signal, admin and API all refuse); items with history are `PROTECT`ed |
| Reasons | Required for every manual adjustment |

Movement types: Opening stock (once per item), Purchase received, Stock increase, Stock
decrease, Damage, Expired stock, Correction (enter the counted total), Other adjustment
(choose add or remove).

**Confirmation.** The adjust page shows "stock now → stock after" and only saves after
**Confirm and record**. If the change would go below zero, the confirm button is not offered.

### 14.3 Purchase workflow

```text
Create (DRAFT) ──edit──► DRAFT ──Receive──► RECEIVED   (stock increases once; movements written)
                           └────Cancel────► CANCELLED  (stock never changes)
```

- A draft never changes stock.
- **Receive** shows a confirmation table (on invoice → adds → stock after), then calls
  `services.receive_purchase()`.
- **Duplicate receiving is impossible.** The status changes with
  `UPDATE … SET status = RECEIVED WHERE id = … AND status = DRAFT`. A second click, a second
  tab or a second user updates 0 rows and stock is not touched. In addition, the database
  allows only **one** stock movement per purchase line (unique constraint).
- If any line fails (for example, a unit that can't be converted), the whole receive is rolled back.
- Received purchases cannot be edited or cancelled. Mistakes are corrected with a stock adjustment.
- Totals are `Decimal` (LKR), recalculated from the lines on every save.

**Purchases vs expenses.** A purchase records **goods** bought (raw materials and finished
stock) and their cost. Operating expenses (transport, electricity, packaging-related operating
costs, rent, …) are **not** purchases and must not be entered as purchase lines; they belong
to the expenses and accounting module (Phase 08). There are no supplier payments or accounting
entries yet.

### 14.4 Low-stock rules

| Status | Condition (active items) |
|---|---|
| Out of stock | quantity ≤ 0 |
| Below minimum | quantity < minimum level (when set) |
| Low stock | quantity ≤ reorder level |
| Above maximum | quantity > maximum level (when set) |
| In stock | otherwise |

Levels are set per item (**Settings**) and must satisfy minimum ≤ reorder ≤ maximum (whole
packets for finished goods). Alerts appear on the inventory dashboard and in the item list
(filter "Needs reorder"). No email or SMS is sent in this phase.

### 14.5 Permissions

| Capability | Owner | Manager | IT Admin | Cashier | Customer |
|---|:-:|:-:|:-:|:-:|:-:|
| `MANAGE_INVENTORY`: stock items, adjustments, movement history | ✔ | ✔ | | | |
| `MANAGE_SUPPLIERS`: suppliers | ✔ | ✔ | | | |
| `MANAGE_PURCHASES`: create, edit, receive, cancel purchases (new) | ✔ | ✔ | | | |
| `CONFIGURE_STOCK_RULES`: allow negative stock per item (new) | ✔ | | | | |

Enforced on every page (`CapabilityRequiredMixin`) and every API endpoint (`HasCapability`).

### 14.6 Pages and API

| Page | URL |
|---|---|
| Inventory dashboard (live counts, alerts, recent movements and purchases, adjustment summary) | `/staff/inventory/` |
| Stock items: list / track new item / detail / settings / adjust | `/staff/inventory/items/…` |
| Stock movement ledger (search, type, date range) | `/staff/inventory/movements/` |
| Suppliers: list / new / detail with purchase history / edit / (de)activate | `/staff/inventory/suppliers/…` |
| Purchases: list (reference or invoice search, supplier, status, dates) / new / detail / edit draft / receive / cancel | `/staff/inventory/purchases/…` |

API (`/api/v1/inventory/`, session auth, paginated, **no DELETE**): `items/` (plus
`POST items/<id>/adjust/`; `quantity` is read-only), `movements/` (read-only), `suppliers/`,
`purchases/` (nested lines; drafts editable; `POST purchases/<id>/receive/` and `/cancel/`).
They all use the same service functions as the web pages.

Code layout: `models.py`, `services.py` (all stock logic), `forms.py`, `views.py`, `api.py`,
`templatetags/inventory_tags.py` (`qty` filter) and `static/js/inventory.js` (form conveniences only).

### 14.7 Change to Phase 03

`catalog.Unit` gained an optional `base_quantity` field (migration `catalog.0003`, which sets
g = 1 and kg = 1000) so that weights can be converted. Nothing else in the catalogue changed.

## 15. Customer storefront and cart

*(Phase 05, app `apps/shop/`; the planned `cart` app is part of it)*

### 15.1 What customers see

`services.visible_products()` is the single definition of "shown in the shop":

| Condition | Source |
|---|---|
| Product status **Active** | catalogue (Phase 03) |
| Main category active; subcategory (if set) active | catalogue |
| At least one variation that is active **and** has an active inventory record with ≥ 1 in stock | inventory (Phase 04) |

Product pages list all active variations; ones that can't be bought (no stock record, 0 stock,
inactive record) are disabled. Only `selling_price` is ever rendered; wholesale prices, SKUs
and stock records stay internal. Categories, subcategories and products are all read from the
database: new ones appear automatically when the conditions are met.

Search covers name, description, category and subcategory. Sorts: relevance (name starts with
the term, then name contains it, then the rest), newest, price low/high (lowest purchasable
price) and name.

### 15.2 Cart model

```text
Cart        user (one-to-one, customers) OR no user (guest; id kept in the server-side session)
  └─ CartItem   variation, quantity (1–50 whole units), unique per cart and variation
```

- **Privacy:** carts are found only from the request (the customer's account, or the guest's
  session); no cart id ever appears in a URL. Line actions (`/cart/items/<id>/update|remove/`)
  look the line up *within the visitor's own cart* and return 404 otherwise. A session can't be
  pointed at a customer's cart (guest lookups require `user IS NULL`).
- **Stock:** every add or update is checked against current inventory (`available_stock`). The cart
  page re-checks each line: it lowers quantities that now exceed stock and flags unavailable items
  (left out of the total). The cart **never** reserves or reduces stock; placing an order does that
  inside a transaction, through `inventory.services.record_movement` (§16).
- **Prices:** not stored in the cart; lines use the variation's current selling price. Orders
  copy the prices when placed (§16).
- **Guest → customer:** the `user_logged_in` signal merges the guest cart into the customer's
  cart (quantities capped at stock) for sign-in and registration. Logging out ends the guest
  session; the customer's own cart stays in the database.
- **Who can shop:** guests and customers. Staff can browse but every cart action refuses them,
  so staff accounts never get carts.
- **Safety:** cart actions are POST-only with CSRF tokens; all ids and quantities are validated on the
  server; `next` redirects are restricted to this site.

### 15.3 Pages

| Page | URL |
|---|---|
| Shop home (products grouped by main category; results grid when searching or sorting) | `/shop/` |
| Category or subcategory | `/shop/category/<slug>/` |
| Product | `/shop/product/<slug>/` |
| Cart | `/cart/`, POST `cart/add/`, `cart/items/<id>/update/`, `cart/items/<id>/remove/` |

The navbar shows **Shop** and a bag icon with the item count (guests and customers only); the home hero
has **Shop now**. Code: `services.py` (all rules), `views.py`, `forms.py`, `signals.py` (merge on
sign-in), `context_processors.py` (cart badge), `static/js/shop.js` (product page option display).

---

## 16. Orders and payments

### 16.1 Models

| Model | App | Purpose |
|---|---|---|
| `CheckoutSettings` | orders | Single row: delivery/pickup on or off, pickup address and hours, cash options, bank-transfer details |
| `DeliveryZone` | orders | Delivery area, LKR fee, optional free-delivery amount, active flag |
| `Order` | orders | Number `LEO-YYYY-NNNNN`, customer, checkout token (unique), contact and address **copied**, zone name copied, subtotal/fee/total, payment method and summary status, order status and timestamps, cancellation details |
| `OrderItem` | orders | Product name, size, SKU, unit price and line total **copied** at ordering; FK to the variation is `PROTECT` |
| `OrderStatusEvent` | orders | Every status change: from, to, who, when, note |
| `Payment` | payments | One row per payment attempt: reference, method, amount, currency, status, bank reference and private slip, gateway transaction, who verified/refunded and when |
| `PaymentEvent` | payments | Append-only log of payment actions and gateway notifications (safe fields only) |

Orders, order lines and status events are never deleted (`PROTECT` foreign keys plus a `pre_delete` guard).

### 16.2 Rules (all in `services.py`)

- **Placing an order** (`orders.services.place_order`) runs in one transaction: re-quote the cart from the
  database, refuse if items changed or the total differs from what the customer reviewed, create the order and
  lines, deduct stock line by line with `record_movement(..., SALE, order_item=...)` (locked in a fixed order),
  create the first `Payment`, record the event, empty the cart. The checkout token makes the call idempotent;
  an `IntegrityError` (same token or same number at the same moment) is retried.
- **Stock policy:** deducted at placement; restored once on cancellation (`ORDER_CANCEL`). Constraints on
  `StockMovement` allow one `SALE` and one `ORDER_CANCEL` per order line.
- **Status workflow:** a transition table plus checks (pickup vs delivery steps, non-cash orders confirmed only when
  paid, completion only when paid). Cancellation is separate (reason required; customers only while pending and unpaid).
- **Payments:** every change is a conditional `UPDATE ... WHERE status IN (...)`, so a second click or repeated
  notification changes nothing. Constraints: one `PAID` payment per order, one open attempt per order, unique
  `(gateway, transaction_id)`. `Order.payment_status` is recalculated from the payments after each change
  (Paid becomes Refund due when the order is cancelled).
- **Slips:** validated by size, extension and content (Pillow / PDF header); stored with random names in
  `PRIVATE_MEDIA_ROOT` (`payments.storage.private_storage`, no URL) and streamed by `EvidenceView` only to the
  order's customer or users with `VIEW_ORDERS`.
- **Online gateways:** `payments/gateways/` defines `PaymentGateway` (`build_checkout`, `parse_notification`);
  `PayHereGateway` is the first adapter. `get_gateway()` returns `None` unless `PAYMENT_GATEWAY` and its credentials
  are set, which hides online payment everywhere. Only `GatewayWebhookView` (CSRF-exempt, signature-verified,
  amount and currency checked) can mark an online payment paid.
- **Notifications:** `orders.notifications.notify_customer` sends email templates from `templates/orders/email/`
  after commit; errors are logged, never raised.

### 16.3 Capabilities

`VIEW_ORDERS` (Owner, Manager, Cashier), `MANAGE_ORDERS` (Owner, Manager: status and cancel), `VERIFY_PAYMENTS`
(Owner, Manager), `RECORD_CASH_PAYMENTS` (Owner, Manager, Cashier), `MANAGE_PAYMENTS` (Owner: refunds),
`MANAGE_BUSINESS_SETTINGS` (Owner: delivery and payment settings). IT Admin has none of them.

### 16.4 Pages

| Page | URL |
|---|---|
| Checkout, review | `/checkout/`, `/checkout/review/` |
| My orders, order detail, cancel | `/account/orders/`, `/account/orders/<number>/`, `.../cancel/` |
| Bank transfer, online payment, gateway return | `/account/orders/<number>/pay/bank-transfer/`, `.../pay/online/`, `/payments/return/<reference>/` |
| Gateway notification (server to server) | `/payments/webhook/<gateway>/` |
| Payment slip | `/payments/<reference>/evidence/` |
| Staff order list, detail, status, cancel, cash | `/staff/orders/`, `/staff/orders/<number>/`, `.../status/`, `.../cancel/`, `.../cash/` |
| Staff verify transfer, record refund | `/staff/payments/<reference>/review/`, `.../refund/` |
| Delivery & payment settings, delivery areas | `/staff/orders/settings/`, `.../zones/new/`, `.../zones/<id>/edit/` |

---

## 17. Point of sale

- **No second sales model.** A till sale is an `orders.Order` with `channel=POS`, `fulfilment=IN_STORE`, an optional
  customer, the `cashier` and `shift`, and discount fields. Lines, price snapshots, stock deduction
  (`orders.services.add_items_and_deduct_stock`, shared with online checkout), `payments.Payment`, cancellation/restock
  and refunds are the Phase 06 code paths.
- **`pos` app:** `PosSettings` (receipt details, discount limits), `CashierShift` (one OPEN per cashier, unique
  constraint; expected/counted/difference fixed at closing), `CashMovement` (CASH_IN, CASH_OUT, REFUND; one REFUND
  per sale), `ReceiptPrint` (reprint log). All are protected from deletion.
- **Sale flow** (`pos.services.create_sale`): idempotent on the checkout token; inside one transaction it locks the
  cashier's open shift, re-reads prices and stock, applies the discount rules, checks the total the cashier saw,
  creates the order and lines, deducts stock, and creates the payment (cash: PAID with tendered/change; bank transfer:
  PENDING_VERIFICATION). `payments.services.review_bank_transfer` completes a POS sale when its transfer is approved.
- **Discounts:** limit by capability: `UNLIMITED_DISCOUNTS` (Owner), `APPROVE_DISCOUNTS` (Manager limit), `PROCESS_SALES`
  (Cashier limit). Approval re-authenticates the approver through the normal backend and its brute-force lock.
- **Refunds:** `pos.services.refund_sale` = `orders.services.cancel_order` (POS sales may be cancelled when completed)
  + `payments.services.record_refund` + a REFUND cash movement on an open shift for cash.
- **Capabilities added:** `VIEW_POS_SALES`, `APPROVE_DISCOUNTS`, `UNLIMITED_DISCOUNTS`, `MANAGE_SHIFTS`, `REFUND_POS_SALES`
  (existing `PROCESS_SALES`, `VIEW_OWN_TRANSACTIONS` etc. are now used). Cashiers' views are filtered to their own
  sales and shifts in `visible_sales` / `visible_shifts`.
- **Pages:** `/staff/pos/` (till), `/staff/pos/sale/` (JSON checkout), `/staff/pos/sales/…` (history, detail, receipt,
  reprint, refund), `/staff/pos/shifts/…` (list, detail, cash, close), `/staff/pos/settings/`. Front end:
  `static/js/pos.js`, `static/js/receipt.js`, `static/css/receipt.css`.

---

## 18. Finance and reports

- **Single definitions** (`finance/services.py`): revenue = `recognised_orders` (paid, not cancelled, by order date);
  COGS = `OrderItem.cost_total` of those orders; expenses = `Expense` RECORDED; purchases = received `Purchase` totals;
  collections/cash flow = `Payment.paid_at`, `Payment.refunded_at`, `SupplierPayment`, `Expense`. Purchases are never
  expenses. Every report and the dashboard use these functions.
- **Costs:** `InventoryItem.average_cost` (4 decimals) is updated by `inventory.services.update_average_cost` inside
  `receive_purchase`, or set by the Owner through `set_item_cost`; both write `ItemCostChange`.
  `orders.services.add_items_and_deduct_stock` copies the cost onto each `OrderItem` at sale (online and POS).
- **Records:** `Expense` and `SupplierPayment` share an abstract `VoidableRecord` (reference, RECORDED/VOID, unique
  `submission_token`, created/voided by). Creation is idempotent on the token; voiding is a conditional update.
  `pre_delete` guards block deleting financial records, categories, cost history and `FinanceEvent`.
- **Reports** (`finance/reports.py`): each builder returns a `Report` (columns with `financial` flag, rows, totals,
  notes, Owner-only `finance_notes`, warnings, chart). `ReportView` renders the page, the A4 print page, or exports
  (`finance/exports.py`: CSV with BOM, and .xlsx written with `zipfile`; formula-injection safe). Charts are SVG geometry
  from `finance/charts.py`.
- **Access:** `VIEW_FINANCE` (Owner) for money reports, dashboard, balances, audit; `VIEW_OPERATIONAL_REPORTS`
  (Owner, Manager) for sales/stock/purchase/expense reports; `RECORD_EXPENSES` (Owner, Manager);
  `MANAGE_FINANCE` (Owner) for voids, supplier payments, stock costs, categories.
