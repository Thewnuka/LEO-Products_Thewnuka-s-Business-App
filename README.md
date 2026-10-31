# LEO PRODUCTS

> *taste of tradition, zip of purity*

Business management system and e-commerce platform for LEO PRODUCTS, built with
Django. One backend and one database will serve the website, a Windows desktop
app (Tauri) and an installable mobile app (PWA).

**Current status:** all planned phases (01–10) are complete: foundation, accounts and roles, product catalogue,
inventory, online shop, orders and payments, point of sale, finance and reports, notifications, and final
security/deployment work. What still needs doing before going live is listed in
[PROJECT_STATUS.md](PROJECT_STATUS.md#final-project-report). See [PROJECT_STATUS.md](PROJECT_STATUS.md).

---

## Technology stack (installed versions)

| Area | Technology | Version |
|---|---|---|
| Language | Python | 3.12.10 |
| Backend | Django (LTS) | 5.2.18 |
| API | Django REST Framework | 3.18.3 |
| API docs | drf-spectacular | 0.30.0 |
| Images | Pillow | 13.0.0 |
| Environment variables | python-dotenv | 1.2.4 |
| Database URL parsing | dj-database-url | 3.1.2 |
| UI framework | Bootstrap (stored locally) | 5.3.8 |
| Icons | Bootstrap Icons (stored locally) | 1.13.1 |
| Fonts | Playfair Display + Inter (Google Fonts) | n/a |
| Database (development) | SQLite | built into Python |
| Database (production) | PostgreSQL (driver: psycopg) | 3.3.6 |
| Static files (production) | WhiteNoise | 6.12.0 |
| App server (production) | Gunicorn (Linux) / Waitress (Windows) | 23.0.0 / 3.0.2 |
| Installable app | PWA (manifest + service worker, no library) | n/a |
| Windows desktop app | Tauri 2 (project in `desktop/`, installer not yet built) | 2.x |

Charts are drawn as SVG on the server (no chart library). The pinned lists are in
[requirements.txt](requirements.txt) (development) and [requirements-production.txt](requirements-production.txt)
(adds PostgreSQL driver, WhiteNoise and the app server).

---

## Quick start (Windows PowerShell)

Already set up before? Open the folder in VS Code, open a terminal (**Ctrl + `**) and run:

```powershell
.\.venv\Scripts\Activate.ps1
python manage.py runserver
```

Then open <http://127.0.0.1:8000/> in your browser.

**Setting up on a new computer?** Follow [DEVELOPMENT_GUIDE.md](DEVELOPMENT_GUIDE.md) step by step.

---

## Useful pages while developing

| URL | What it is |
|---|---|
| <http://127.0.0.1:8000/> | Home page (brand preview) |
| <http://127.0.0.1:8000/shop/> | **Online shop** (everyone): browse, search, product pages |
| <http://127.0.0.1:8000/cart/> | Shopping cart (guests and customers) |
| <http://127.0.0.1:8000/account/orders/> | A customer's own orders |
| <http://127.0.0.1:8000/staff/orders/> | **Customer orders**: status, payments, bank-transfer verification (Owner, Manager, Cashier) |
| <http://127.0.0.1:8000/notifications/> | Your notifications (everyone signed in); business alerts at `/staff/alerts/` |
| <http://127.0.0.1:8000/staff/dashboard/search/> | Staff search; activity history at `/staff/dashboard/activity/` (Owner, Manager) |
| <http://127.0.0.1:8000/staff/finance/> | **Finance overview** (Owner); reports at `/staff/finance/reports/` (Owner, Manager) |
| <http://127.0.0.1:8000/staff/pos/> | **Point of sale** till (Cashier, Owner); sales, shifts and POS settings under the same menu |
| <http://127.0.0.1:8000/staff/orders/settings/> | Delivery areas and fees, pickup, cash and bank details (Owner) |
| <http://127.0.0.1:8000/staff/home-images/> | **Home page images**: hero background and the three image boxes (Owner) |
| <http://127.0.0.1:8000/staff/login/> | **Staff portal** sign-in (Owner, IT Admin, Manager, Cashier) |
| <http://127.0.0.1:8000/account/login/> | **Customer** sign-in |
| <http://127.0.0.1:8000/account/register/> | Customer registration |
| <http://127.0.0.1:8000/staff/users/> | Staff account management (Owner, IT Admin) |
| <http://127.0.0.1:8000/staff/catalog/> | **Product catalogue**: products, variations, categories, units (Owner, Manager) |
| <http://127.0.0.1:8000/staff/inventory/> | **Inventory**: stock, adjustments, stock history, suppliers, purchases (Owner, Manager) |
| <http://127.0.0.1:8000/admin/> | Django admin (Owner accounts only) |
| <http://127.0.0.1:8000/style-guide/> | All shared UI components (only when `DEBUG=True`) |
| <http://127.0.0.1:8000/api/v1/health/> | API health check |
| <http://127.0.0.1:8000/api/v1/accounts/me/> | The signed-in user's own profile (API) |
| <http://127.0.0.1:8000/api/v1/catalog/products/> | Catalogue API (Owner, Manager) |
| <http://127.0.0.1:8000/api/v1/inventory/items/> | Inventory API (Owner, Manager) |
| <http://127.0.0.1:8000/api/docs/> | Interactive API documentation (only when `DEBUG=True`) |

---

## Signing in during development

The initial OWNER account is created with a one-time command (details in
[DEVELOPMENT_GUIDE.md](DEVELOPMENT_GUIDE.md#5-the-initial-owner-account)):

| | |
|---|---|
| Sign-in page | <http://127.0.0.1:8000/staff/login/> |
| Username | `admin` (or email `admin@gmail.com`) |
| Temporary password | the one you set when running `bootstrap_owner` |

On first sign-in you **must** choose a new, strong password before anything else works.
From the Owner dashboard you can then create IT Admin, Manager and Cashier accounts
under **Staff accounts**. Customers create their own accounts at `/account/register/`.

## User roles at a glance

| Role | Signs in at | Can do (now) | Will do (later phases) |
|---|---|---|---|
| **Owner** | Staff portal | Everything; manage all staff; product catalogue; inventory, suppliers and purchases (and may allow negative stock per item); Django admin; view every dashboard; POS till, all sales, refunds, shifts and POS settings; finance overview, profit & loss, expenses, supplier payments, stock costs, all reports | Business settings |
| **IT Admin** | Staff portal | Manage Manager and Cashier accounts | Technical settings, maintenance, security log. **No finance** |
| **Manager** | Staff portal | Product catalogue; inventory and stock adjustments; suppliers; purchases (create and receive); customer orders, order status, bank-transfer verification, cash; POS sales, discount approval, refunds, shift review; operational reports and recording expenses | Customers |
| **Cashier** | Staff portal | POS till, own shift and cash drawer, own sales and receipt reprints; view customer orders and record cash received | — |
| **Customer** | Customer portal | Register, own profile; shop, keep a cart, check out, own orders and payments | Notifications, mobile app |

Full details: [ARCHITECTURE.md §12](ARCHITECTURE.md#12-authentication-and-role-based-access-control).

---

## Project structure

```text
LEO PRODUCTS SYSTEM/
├── config/                  Project configuration
│   ├── settings/
│   │   ├── base.py          Shared settings
│   │   ├── development.py   Your computer (SQLite, DEBUG on)
│   │   └── production.py    Live server (PostgreSQL, DEBUG off, HTTPS)
│   ├── urls.py              Root URL routes and error-page handlers
│   ├── wsgi.py / asgi.py    Entry points for production web servers
├── apps/                    One folder per business area
│   ├── core/                Shared base model, brand context, home page, error pages, health API
│   ├── accounts/            Users, roles, sign-in, registration, passwords, staff management
│   │   ├── roles.py         Roles and capabilities: WHO MAY DO WHAT (single source of truth)
│   │   ├── permissions.py   Backend checks for pages and API (mixins, decorator, DRF class)
│   │   └── management/commands/bootstrap_owner.py   Creates the initial OWNER
│   ├── dashboard/           Role-based staff dashboards
│   ├── catalog/             Categories, products, variations (sizes/SKUs/LKR prices), units, safe image uploads
│   ├── inventory/           Stock items, stock movement ledger, adjustments, suppliers, purchases
│   ├── shop/                Customer storefront and shopping cart
│   ├── orders/              Checkout, orders, status workflow, delivery settings
│   ├── payments/            Payment records, cash, bank transfer, refunds, online gateway (PayHere)
│   ├── pos/                 Point of sale: cashier shifts, cash drawer, receipts, POS settings
│   ├── finance/             Expenses, supplier payments, reports, profit & loss, exports, finance audit log
│   └── notifications/       In-app notifications, preferences, business alerts, alert settings
├── templates/
│   ├── base.html            Master layout every page extends
│   ├── layouts/             sidebar.html, staff.html (staff portal), auth.html (sign-in pages)
│   ├── partials/            Reusable pieces: _logo, _navbar, _footer, _alert, _messages, _form_field…
│   ├── accounts/            Sign-in, registration, password, customer and staff-management pages
│   ├── dashboard/           Role dashboard page
│   ├── catalog/             Catalogue pages (overview, products, variations, categories, units)
│   ├── inventory/           Inventory, stock, supplier and purchase pages
│   ├── errors/              Shared error-page layout
│   ├── core/                Home page and style guide
│   └── 400/403/404/500.html Branded error pages (+ 403_csrf.html for expired forms)
├── static/
│   ├── css/leo.css          Brand stylesheet (colour variables at the top)
│   ├── js/leo.js            Site JavaScript
│   ├── images/leo-logo.png  Official LEO PRODUCTS logo
│   └── vendor/              Bootstrap and Bootstrap Icons
├── media/                   User uploads (not committed to Git)
├── manage.py
├── requirements.txt
├── .env.example             Template for your private .env file
├── README.md  ARCHITECTURE.md  DEVELOPMENT_GUIDE.md  PROJECT_STATUS.md
```

---

## Logo

The **official LEO PRODUCTS logo** is `static/images/leo-logo.png` (the original file, 971 × 971 PNG,
unchanged). It is shown by one template, `templates/partials/_logo.html`, which every page uses:
navbar, footer, home page, sign-in and registration pages, staff portal, customer portal, error pages
and the browser tab icon. On screen it keeps its proportions (`object-fit: contain`) inside a white
circle so it stays clear on the dark green bars.

To update the logo later, replace that file and keep the same name. No template changes are needed.
In development, press **Ctrl + F5** if your browser still shows the old image.

---

## Product catalogue at a glance

- **Categories** are managed in the app (main category → subcategory). Starting set:
  LEO TEA, TEA BAGS and LEO SWEETS with their subcategories, all editable.
- **Products** belong to a main category (and optionally a subcategory) and start as Draft.
- **Variations** are the sellable sizes of a product, each with its own unique **SKU** and
  **LKR prices**, measured by **weight** (200g), **count** (25 bags) or **pieces** (10 pieces).
  New units can be added at any time.
- **Images** are checked, resized and cleaned automatically. A placeholder is shown when there is none.
- Nothing is deleted: products, variations and units are archived by deactivating them.

How-to: [DEVELOPMENT_GUIDE.md §7](DEVELOPMENT_GUIDE.md#7-managing-the-product-catalogue).
Design: [ARCHITECTURE.md §13](ARCHITECTURE.md#13-product-catalogue).

## Inventory at a glance

- **Two kinds of stock:** *raw materials* (e.g. unpacked tea in kg) and *finished products*
  (a catalogue variation such as Black Tea 200g, counted in packets). They are never mixed.
- **Every change is recorded** in a permanent stock history (who, when, before/after, why).
  Stock can't go below zero unless the Owner explicitly allows it for an item.
- **Adjustments** (increase, decrease, damage, expired, count correction) need a reason and a confirmation.
- **Purchases** from suppliers start as drafts; stock only increases when a purchase is **received**,
  and it can only be received once. Purchases record goods only, not operating expenses.
- **Low-stock alerts** use each item's reorder, minimum and maximum levels.

How-to: [DEVELOPMENT_GUIDE.md §8](DEVELOPMENT_GUIDE.md#8-using-the-inventory-module).
Design: [ARCHITECTURE.md §14](ARCHITECTURE.md#14-inventory-stock-suppliers-and-purchases).

## Online shop at a glance

- Products appear in the shop automatically when they are **Active**, in an active category, with at least one
  active size. Customers can buy a size once it is **in stock** (tracked in Inventory); otherwise the product is
  shown as "Out of stock". Categories: LEO TEA (Tea Bags, Tea Packets) and LEO SWEETS.
- Customers choose a size (weight, tea-bag count or pieces), see its price and availability, and add it to the cart.
- The cart checks stock on every change, never reduces stock, and is private: guests' carts belong to
  their browser session and merge into their account when they sign in.
- Checkout: delivery (fee per area) or store pickup; pay by cash, bank transfer (slip checked by staff) or,
  once configured, online (PayHere). Stock is deducted when the order is placed and returned if it is cancelled.
  Setup and daily use: [DEVELOPMENT_GUIDE.md §10](DEVELOPMENT_GUIDE.md#10-orders-and-payments).

How-to: [DEVELOPMENT_GUIDE.md §9](DEVELOPMENT_GUIDE.md#9-the-online-shop-customers).
Design: [ARCHITECTURE.md §15](ARCHITECTURE.md#15-customer-storefront-and-cart).

## Documentation

- [DEVELOPMENT_GUIDE.md](DEVELOPMENT_GUIDE.md): installation, daily use of every module, testing, going live (§16),
  installable app (§17), Windows desktop app (§18), Git and GitHub
- [ARCHITECTURE.md](ARCHITECTURE.md): how the project is organised and why
- [PROJECT_STATUS.md](PROJECT_STATUS.md): what is done, what is next
- [deploy/README.md](deploy/README.md): example server files (no real credentials)
- [desktop/README.md](desktop/README.md): building the Windows desktop installer

## Going live in short

1. `pip install -r requirements-production.txt`
2. Create `.env` from `deploy/env.production.example` (new `SECRET_KEY`, your domain, PostgreSQL `DATABASE_URL`,
   email, a private `ADMIN_URL`).
3. `python manage.py check --deploy`, `migrate`, `collectstatic`, `bootstrap_owner`.
4. Run with Gunicorn behind Nginx (Linux) or `deploy/windows/start-server.ps1` (Windows PC).

Full steps and the go-live checklist: [DEVELOPMENT_GUIDE.md §16](DEVELOPMENT_GUIDE.md#16-going-live-production).
