# LEO PRODUCTS: Project Status

**Last updated:** 2026-10-31
**Current phase:** Phase 06 (Orders & Payments): **COMPLETE**. Waiting for approval before Phase 07.

---

## Phase 06: Orders & Payments ✅

### Delivered

- [x] New apps `orders` (checkout, orders, status workflow, delivery settings) and `payments`
      (payment records, bank transfer, cash, refunds, online gateway adapter)
- [x] **Checkout** (signed-in customers): name and phone, Home Delivery or Store Pickup, delivery area,
      address and instructions, payment method, then a **review** step before placing the order
- [x] **Delivery & payment settings** (Owner): delivery/pickup on or off, pickup address and hours, delivery
      areas with LKR fee and optional free-delivery amount, cash on delivery/pickup, bank transfer with bank details.
      Pickup never has a delivery fee; delivery is offered only when an active area exists
- [x] **Orders:** unique numbers `LEO-YYYY-NNNNN`; product name, size, SKU and unit price **copied** onto the order;
      subtotal, delivery fee and total calculated on the server; payment method and status; status timestamps;
      cancellation reason and who cancelled. Orders, order lines and history **can't be deleted**
- [x] **Status workflow** Pending → Confirmed → Processing → Ready for pickup / Out for delivery → Delivered →
      Completed, plus Cancelled, with validated transitions (pickup vs delivery steps, non-cash orders confirmed
      only when paid, completion only when paid) and a full history of who changed what and when
- [x] **Stock policy:** deducted when the order is placed, in the same transaction (ledger type "Online order");
      overselling prevented by the ledger's conditional update; restored **once** on cancellation
      ("Order cancelled (restock)"). Database constraints allow one sale and one restock per order line
- [x] **Payments:** one record per attempt with reference, method, amount, status (Pending, Pending verification,
      Paid, Failed, Rejected, Refunded) and an event log. Database constraints: one paid payment and one open
      attempt per order, unique gateway transaction ids. Every change is a conditional update, so double clicks,
      two staff members or repeated gateway notifications can't process a payment twice
- [x] **Cash:** staff record the cash received (once)
- [x] **Bank transfer:** customer sees the bank details from settings, submits reference and slip (JPG/PNG/WebP/PDF,
      max 5 MB, content checked); stays **Pending verification** until a Manager/Owner approves or rejects
      (reason required; customer sees it and can resubmit); who and when recorded
- [x] **Slips stored privately** (`PRIVATE_MEDIA_ROOT`, not publicly served), opened only through a
      permission-checked view (order's customer or order staff; others get 404), `no-store` caching
- [x] **Online payment:** gateway adapter interface with a **PayHere** adapter (signed checkout request,
      `md5sig` notification verification, amount/currency check). Off and shown as "Not configured" until
      `PAYMENT_GATEWAY` and credentials are set in `.env`; the browser return page never marks anything paid
- [x] **Refunds** (Owner): cancelled paid orders show "Refund due"; the Owner records how the refund was made
- [x] **Customer pages:** confirmation page, My orders (account tab), order details with status, payment status,
      items, totals, delivery/pickup details, progress history, bank-transfer upload, cancel while pending and unpaid;
      own orders only (404 for others); recent orders and payments on the account overview
- [x] **Staff pages:** order list with search and filters (status/open, payment method, payment status, dates),
      "new" and "payments to verify" counts; order detail with allowed actions per role, slips, stock movements and
      one combined order/payment history; sidebar "Orders" section and dashboard links
- [x] **Roles:** Owner everything; Manager orders, status, cancel, verify, cash; Cashier view orders and record cash
      only; IT Admin no access; customers their own orders only. Enforced in views and services, not just hidden buttons
- [x] **Notifications:** emails to the customer when an order is placed, changes status, is cancelled, or a payment is
      approved/rejected; sent after the transaction commits; failures logged, never breaking the order
      (console output in development; no paid services)
- [x] **Security:** CSRF on every form (webhook exempt but signature-verified), server-side prices and totals, customers
      can't change statuses, checkout token against double orders, "Place order" disabled after the first click,
      changed totals must be re-confirmed
- [x] Cart "Proceed to checkout", shop texts, home roadmap and dashboards updated
- [x] Docs: DEVELOPMENT_GUIDE §10 (setup, processing, verification, PayHere configuration), test table, this file
- [x] Development database backed up to `backup-before-phase06.sqlite3` before migrating

### Verification performed (2026-10-31)

| Check | Result |
|---|---|
| `python manage.py test` | **383 tests, all passed** (88 new orders/payments tests + all Phase 01–05 tests) |
| `check`, `makemigrations --check` | Clean; migrations `orders.0001`, `payments.0001`, `inventory.0002` applied to the dev DB |
| `check --deploy` (production settings) | Only the two optional HSTS warnings (subdomains/preload), as in earlier phases |
| Horizontal overflow (headless Edge), customer, owner and cashier, 17 pages × 5 widths (320–1366px) | 85/85 OK, all HTTP 200 |
| Browser walkthrough | Checkout hides the address for pickup and shows only allowed payment methods; review; double-clicked "Place order" created one order; confirmation page shown |

**Issues found and fixed during Phase 06:**
- The "only N left" message after a failed stock check showed the stale number from the cart; it now re-reads stock
- The PayHere redirect page broke because one gateway field is called `items` (a Django template clash)
- Order lists had no guaranteed order for pagination; now newest first
- The home-page test that forbade the word "Checkout" was updated for Phase 06
- An arrow character in emails could not be printed by the development email console on Windows
- Staff history showed raw event codes and listed payment events after order events; now readable and in time order
- Two orders placed at the same instant could get the same number and show an error; the second now retries

### Known limitations (Phase 06)

- **Online payment is not live:** the PayHere adapter is tested against PayHere's documented signature format
  but has not been run against PayHere's sandbox. Needs merchant credentials, a public HTTPS address for the
  notification URL, and a check against PayHere's current documentation (DEVELOPMENT_GUIDE §10).
- **Emails are only printed in the terminal** until SMTP settings are added to `.env`. No SMS or in-app
  notifications (planned with the notifications module).
- Refunds are recorded, not executed: money is returned outside the system (bank, cash, or the gateway's portal).
- Partial payments, partial cancellations and editing an order's items are not supported; cancel and re-order instead.
- Delivery fees are per area only (no weight- or distance-based fees); customers choose their area themselves.
- No POS, expenses or accounting reports (later phases). Order and payment APIs for the future apps are not built yet.
- Payment slips in `private_media\` must be backed up with the database.
- Responsive checks used headless Microsoft Edge; real phones not tested.

---

## Phase 05: Customer E-commerce (storefront and cart) ✅

### Delivered

- [x] New `shop` app (storefront + cart). The planned `cart` app is merged into it.
- [x] Shop home `/shop/`: products grouped under their database categories (LEO TEA, TEA BAGS,
      LEO SWEETS and any new ones), subcategory chips, "View all" per category
- [x] Category and subcategory pages `/shop/category/<slug>/`
- [x] Only **active, available** products are shown: active product, active category and subcategory,
      and at least one active variation with ≥ 1 in stock (Phase 04 inventory)
- [x] Product cards: image (or placeholder), category, name, "From" price (LKR), size selector, **Add to cart**
      and **Details**; hover lift/zoom on mouse, highlight on tap
- [x] Product page `/shop/product/<slug>/`: image, description, all sizes (weight, tea-bag count, pieces) with
      price; out-of-stock or untracked sizes disabled; the price, availability ("In stock" / "Only N left"),
      quantity limit and image update when a size is chosen; related products
- [x] Search (name, description, category), sorting (most relevant, newest, price low → high and
      high → low, name), 12 per page, search kept across pages, helpful "no results" and empty-shop messages
- [x] Cart `/cart/`: add, change quantity (0 removes), remove; line totals, subtotal and total in LKR
- [x] Stock checked on every add and update (never more than in stock, maximum 50 per item); if stock drops
      later, the cart reduces the quantity and says so; unavailable items flagged and excluded from the total
- [x] **Cart never changes inventory** (deduction happens at order time in Phase 06)
- [x] Guest carts (server-side session) and customer carts (saved to the account); guest cart merged on
      sign-in **and** on registration (capped at stock)
- [x] Privacy: no cart ids in URLs; line actions only within the visitor's own cart (404 otherwise);
      sessions can't point at a customer's cart; staff can browse but can't shop
- [x] POST-only cart actions with CSRF; server-side validation of all ids and quantities; safe `next` redirects
- [x] Navbar **Shop** link and bag icon with item count (always visible on phones); home hero **Shop now**;
      footer Shop link; home roadmap and customer account page text updated
- [x] Admin: read-only cart view; `clear_old_guest_carts` management command
- [x] Docs: README, ARCHITECTURE §15, DEVELOPMENT_GUIDE §9, this file
- [x] Development database backed up to `backup-before-phase05.sqlite3` before migrating

### Verification performed (2026-10-31)

| Check | Result |
|---|---|
| `python manage.py test` | **295 tests, all passed** (40 new shop tests + all Phase 01–04 tests) |
| `check`, `makemigrations --check` | Clean; migration `shop.0001` applied to the dev DB |
| Horizontal overflow (headless Edge), guest, customer and staff, 15 page sets × 6 widths | 90/90, then re-check after fixes 36/36: no overflow |
| Browser walkthrough | Size switching updates price, availability and quantity limit; a sold-out size can't be chosen; add to cart; badge count; above-stock update refused; guest cart kept after customer sign-in |
| Navbar height with the new cart icon | 68px at every width from 320 to 1366px |

**Issues found and fixed during Phase 05:**
- Adding the cart icon made the navbar wrap to two rows on phones (112px tall); the brand now shrinks
  instead, so the bar stays one row (68px) at all widths
- Product-card buttons were squeezed on two-column phone layouts; they now stack on narrow cards
- Breadcrumb separators overlapped text on narrow screens (also affected catalogue and inventory breadcrumbs)
- Cart lines squeezed the product name at tablet/laptop widths; one-row layout now only from 1200px
- A hard-coded low-stock number in a template replaced by the `SHOP_LOW_STOCK_THRESHOLD` setting
- "Newest" sorting put products created in the same instant oldest-first (found by an intermittent test
  failure); ties now follow the sort direction, in the shop and in the Phase 03 catalogue list

### Known limitations (Phase 05)

- **Your database has no products yet**, so the live shop shows "Our shop is getting ready". Add products,
  variations and stock (DEVELOPMENT_GUIDE §9) to see them.
- No checkout, orders, delivery or payment (Phase 06). Prices shown are current prices; orders will snapshot them.
- The cart doesn't reserve stock: two customers can hold the last packet in their carts; the order step must
  re-check stock atomically (planned for Phase 06).
- Product lists check variation availability per product (fine for a small catalogue; may need optimising
  for many hundreds of products).
- No public catalogue API for the future PWA/desktop shop yet; no wish lists, reviews or promotions.
- Responsive checks used headless Microsoft Edge; real phones not tested.

---

## Official logo installed (2026-10-30)

- The official LEO PRODUCTS logo (original 971 × 971 PNG, byte-for-byte unchanged) now replaces the
  placeholder at `static/images/leo-logo.png`, used everywhere via `templates/partials/_logo.html`.
- Display only: `object-fit: contain`, square proportions, shown inside a white circle (the image has a
  white background; all artwork lies inside the circle, verified). `BRAND["LOGO_IS_PLACEHOLDER"] = False`.
- Verified in headless Edge at 375 and 1366px: home, staff and customer sign-in, registration, staff
  dashboard and customer portal all load the new 971 × 971 image, undistorted, with no placeholder text.

---

## Phase 04: Inventory, Stock & Supplier Management ✅

### Delivered

- [x] New `inventory` app on the existing role system; new capabilities `MANAGE_PURCHASES`
      (Owner, Manager) and `CONFIGURE_STOCK_RULES` (Owner); existing `MANAGE_INVENTORY`, `MANAGE_SUPPLIERS`
- [x] Two kinds of stock record: **raw materials** (any unit, e.g. kg) and **finished goods**
      (one per catalogue variation, whole packets); never mixed
- [x] Stock per item: quantity, unit, reorder / minimum / optional maximum level, last change, active flag
- [x] g ↔ kg conversion via new optional `catalog.Unit.base_quantity` (g = 1, kg = 1000); no other catalogue change
- [x] Permanent stock movement ledger (8 movement types) with before/after, entered unit, reason, user, purchase link
- [x] All stock changes through one service (`record_movement`): transaction + row lock + conditional
      `F()` update; negative stock refused by default (and by a DB constraint); Owner-only per-item override
- [x] Adjustments (increase, decrease, damage, expired, correction, other) with required reason and a
      **confirmation page** showing before → after
- [x] Opening stock when an item is first tracked (once per item)
- [x] Suppliers: create, view, edit, search, filter, purchase history, activate/deactivate; never deleted
- [x] Purchases (PO-YYYY-NNNN): draft → received / cancelled, line items with units and LKR costs, totals;
      editing only while draft; receive confirmation page; **receive-once guarantee**
- [x] Purchases kept separate from operating expenses (documented, shown in the UI)
- [x] Low-stock detection (out / below minimum / low / above maximum) with dashboard alerts and filters
- [x] Inventory dashboard from real data: items, active suppliers, low and out of stock, draft purchases,
      recent movements and purchases, 30-day adjustment summary, variations not yet tracked
- [x] Search, filters, sorting and paging (keeping filters) for items, movements, suppliers and purchases
- [x] REST API `/api/v1/inventory/` (items + adjust, movements read-only, suppliers, purchases + receive/cancel), no DELETE
- [x] Admin: ledger and purchases read-only; no deletes
- [x] Sidebar section, Owner/Manager dashboard links, home roadmap updated
- [x] Docs: README, ARCHITECTURE §14, DEVELOPMENT_GUIDE §8, this file
- [x] Development database backed up to `backup-before-phase04.sqlite3` before migrating; users,
      categories and units preserved

### Verification performed (2026-10-30)

| Check | Result |
|---|---|
| `python manage.py test` | **255 tests, all passed** (69 new inventory tests + all Phase 01–03 tests) |
| `check`, `makemigrations --check` | Clean; migrations `catalog.0003` and `inventory.0001` applied to the dev DB |
| `check --deploy` (production) | Only the two known HSTS warnings (an API-docs warning found during the phase was fixed) |
| API schema (`spectacular --validate`) | Valid; 11 inventory paths |
| Real-browser role checks (headless Edge) | Owner/Manager 200; Cashier, IT Admin, Customer 403 on inventory, supplier and purchase pages |
| Horizontal overflow, 26 page/role combinations × 6 widths | 156/156 without overflow; re-check after fixes 24/24 |
| Browser test of form scripts | Unit filtering (g/kg only for loose tea), add-line, packets label, live total (LKR 7,350.00), save as draft, type and direction toggles all correct |

**Issues found and fixed during Phase 04:**
- *Race condition (my design):* saving an item's settings would have written back the quantity loaded
  with the page, silently undoing stock changes made meanwhile; `InventoryItem.save()` now never writes quantity
- *SQLite pitfall:* a planned "after = before + change" database check would fail on float rounding;
  replaced by exact Decimal arithmetic in the service
- *JavaScript bug:* the purchase form's "packets" label selector also matched item options and blanked the
  first finished product in the list (so it couldn't be chosen); found in browser testing, selector fixed
- Opening-stock form check ran before the item type was known (would have crashed); rewritten
- Adjust page "Back to edit" re-showed the confirmation instead of the form
- API docs warning for untyped `{id}` paths; phone layouts of purchase lines, adjust form and dashboard table

### Known limitations (Phase 04)

- Packing loose tea into packets is two manual adjustments (raw decrease + packets increase); no automatic
  production/packing run yet.
- One stock location only (no warehouses or branches).
- No batch / expiry-date tracking per lot; expired stock is recorded as a movement.
- Received purchases can't be reversed; corrections are stock adjustments. No supplier returns.
- No supplier payments, credit or accounting entries (Phase 08); no tax/discount lines on purchases.
- On SQLite, row locks are not available (SQLite allows one writer at a time); full row locking applies on PostgreSQL.
  The conditional updates protect stock on both.
- Low-stock alerts are on screen only (no email/SMS).
- Responsive checks used headless Microsoft Edge; real phones not tested.

---

## Small updates after Phase 03 (2026-10-30)

- **Sticky top navigation:** the public site header (logo, name, tagline, Home, About, Roadmap,
  Sign in, Create account) stays at the top while scrolling. Pure CSS (`position: sticky`), no
  JavaScript. Same-page links stop below the bar, and the mobile menu still works and scrolls on short
  screens. Verified in headless Edge at 320–1366px. The staff portal top bar is unchanged.
- **Simpler customer passwords:** customer registration now only requires 6+ characters
  (e.g. `123456`, `leo123`, `mypassword`), checked in the browser and on the server. Staff accounts,
  temporary passwords and password change/reset keep the strict rules. Hashing (PBKDF2), CSRF,
  confirmation and uniqueness checks are unchanged. 6 new tests.

---

## Phase 03: Product & Category Management ✅

### Delivered

- [x] New `catalog` app integrated with the Phase 02 role system (`Capability.MANAGE_CATALOG`; no auth changes)
- [x] Database-driven categories: main category → subcategory, images, sort order, activate/deactivate,
      rename, delete only when empty; no duplicate names within a parent (ignoring case)
- [x] Initial categories via data migration: LEO TEA (Black, Ginger, Cinnamon Tea), TEA BAGS
      (Black, Ginger, Cinnamon Tea Bags), LEO SWEETS (Kokis); all editable in the app
- [x] Products: name, slug (auto), description, main category, subcategory, image, status
      (Draft / Active / Inactive), created/updated date and by whom
- [x] Flexible variations: measurement type (Weight / Count / Pieces) + quantity + **unit from a
      database table** (g, kg, bags, pieces seeded; new units addable), unique SKU (generated or custom),
      selling price and optional wholesale price (Decimal, LKR), active flag, optional image
- [x] Business rules: prices/quantities > 0 (validators + DB CHECK constraints); wholesale ≤ selling;
      unit must match measurement type; one variation per size per product; product can only be
      Active with an active variation (enforced in forms, API and model)
- [x] Safe image uploads (Pillow): JPEG/PNG/WebP only, 5 MB limit, decompression-bomb guard,
      re-encoding (strips metadata), resize to 1600 px, random file names, old files cleaned up,
      live preview, placeholder when missing
- [x] Catalogue overview with live database counts (products total/active/inactive/draft,
      main categories, subcategories, variations), recent product cards, category summary
- [x] Product list: search by name **or SKU**, filters (main category, subcategory, status,
      measurement type), 7 sort options, pagination that keeps filters, card and table views
- [x] Pages: product list/create/edit/detail, variation management/create/edit, category
      list/create/edit, unit list/create/edit; success and error messages throughout
- [x] Product cards: hover lift, soft shadow, gold border, image zoom (mouse); same highlight on tap/focus (touch, keyboard)
- [x] REST API `/api/v1/catalog/` (categories, units, products, variations): same validation as forms,
      `MANAGE_CATALOG` required, paginated, no DELETE
- [x] Archive-not-delete: products, variations, units have no delete; categories with content are
      `PROTECT`ed; ready for future `PROTECT` links from orders and stock
- [x] No stock fields or stock figures (inventory is Phase 04)
- [x] Owner/Manager dashboards and staff sidebar link to the catalogue; home roadmap updated
- [x] Docs: README, ARCHITECTURE §13, DEVELOPMENT_GUIDE §7, this file

### Verification performed (2026-10-30)

| Check | Result |
|---|---|
| `python manage.py test` | **180 tests, all passed** (67 new catalogue tests + all 113 Phase 01/02 tests) |
| Existing authentication | All Phase 02 tests pass unchanged; `admin` user untouched |
| `check`, `makemigrations --check` | Clean; migrations `catalog.0001` (schema) and `0002` (seed) applied to the dev DB |
| `check --deploy` (production settings) | Only the two known HSTS warnings |
| API schema (`spectacular --validate`) | Valid; 8 catalogue paths |
| Test uploads | Written to a temporary folder and removed; project `media/` untouched |
| Role access in a real browser (headless Edge) | Owner/Manager 200 on all catalogue pages; Cashier, IT Admin 403 |
| Horizontal overflow, 18 catalogue pages × 6 widths (320–1366px), plus re-check after fixes | 108/108 and 78/78: no overflow |
| Visual inspection (screenshots) at 320, 375 and 1366px | Done; issues found and fixed (below) |

**Issues found and fixed during Phase 03:**
- Product list crashed when opened with no filters (filter form had no cleaned data)
- Duplicate-size rule would only fail at the database (Django skips constraints on fields not in a
  form); now checked in the form and API
- "Last active variation" rule was only on the toggle button; moved into the model so edit form and API obey it
- Table thumbnails collapsed to a thin line (global `img { max-width:100% }` inside table cells)
- Product table scrolled sideways on desktop; long name/category columns now wrap
- Stacked table labels broke mid-word on phones ("Produ ct"); side-by-side fields had no gap on phones
- A Phase 01 settings comment wrongly claimed `FILE_UPLOAD_MAX_MEMORY_SIZE` rejects large uploads;
  corrected, and real size limits are enforced by the image validator

### Known limitations (Phase 03)

- Media files must be served by the web server (or cloud storage) in production; set up at deployment.
- Categories are limited to two levels by design (change point documented in ARCHITECTURE §13.1).
- No price-change history yet (`updated_by`/`updated_at` are recorded); can be added with reports/finance.
- No public storefront or customer-facing catalogue API yet (Phase 05).
- Cashiers have no catalogue view yet; read-only access for POS comes in Phase 06.
- No bulk import/export of products.
- Responsive checks used headless Microsoft Edge; real phones not tested.

---

## Phase 02: Authentication, User Management & RBAC ✅

### Delivered

- [x] Five roles (OWNER, IT_ADMIN, MANAGER, CASHIER, CUSTOMER); one primary role per user
- [x] Capability-based permission map (`apps/accounts/roles.py`) enforced on the backend for pages and API
- [x] Separate **staff portal** (`/staff/login/`) and **customer portal** (`/account/login/`); wrong-portal sign-ins rejected
- [x] Sign in with username or email; sign out with confirmation (POST + CSRF)
- [x] Customer registration (first name, last name, email, phone, password ×2), always creates CUSTOMER
- [x] Forgot password / reset by emailed link (1-hour, single-use); change password
- [x] Forced password change for new staff, the bootstrapped owner and admin-set passwords
- [x] Login throttling (5 failures per account name + IP → 15-minute lock)
- [x] Staff management: list (search, filter, paging), create, view, edit details/role, activate/deactivate, set temporary password
- [x] Role limits: Owner assigns IT Admin/Manager/Cashier; IT Admin assigns Manager/Cashier; nobody manages themselves
- [x] Primary owner protected from deletion, deactivation and demotion (model, signal, admin and UI)
- [x] `bootstrap_owner` management command (idempotent, never resets passwords, no plaintext in code or logs)
- [x] Account audit log (`AccountAuditLog`) for staff/account changes, shown on staff detail pages and in the admin (read-only)
- [x] Role-based dashboard routing + placeholder dashboards for Owner, IT Admin, Manager, Cashier (no fake figures)
- [x] Customer home and profile pages (orders/payments sections are honest placeholders)
- [x] Staff profile page; `/api/v1/accounts/me/` API (role read-only, no secrets)
- [x] Branded "form expired" (CSRF) page; 403 page links back to the user's own home
- [x] Django admin restricted to OWNER accounts; `is_staff`/`is_superuser` derived from role
- [x] Data migration: any pre-existing superuser becomes OWNER
- [x] Initial OWNER created in the local development database: username `admin`, email `admin@gmail.com`, temporary password as requested (not recorded in any file), **must change on first sign-in**
- [x] Documentation updated (README, ARCHITECTURE §12, DEVELOPMENT_GUIDE §5–7, this file)

### Verification performed (2026-10-30)

| Check | Result |
|---|---|
| `python manage.py check` | No issues |
| `makemigrations --check --dry-run` | No changes detected (migration `accounts.0002` applied) |
| `python manage.py test` | **106 tests, all passed** (up from 12 in Phase 01) |
| `check --deploy` (production settings) | Only the two deliberate HSTS subdomain/preload warnings (unchanged from Phase 01) |
| API schema `spectacular --validate` | Valid; includes `/api/v1/accounts/me/` |
| `bootstrap_owner` on the dev database | Created `admin`; weak password refused without the dev flag; second run changed nothing |
| Real `admin` account sign-in | Staff portal → forced "Choose a new password"; dashboard blocked until changed; customer portal rejects it |
| Real-browser sign-in (headless Edge) for every role, using actual forms with CSRF tokens | Worked; cashier/manager get 403 on staff management |
| Horizontal overflow, 24 pages × 6 widths (320, 375, 430, 768, 1024, 1366) | None after fixes |
| Visual inspection (screenshots) at 320, 375, 1024 and 1366px | Done; issues found and fixed (below) |

**Security tests (all automated, all passing):** customer → staff dashboard (403); customer → create
staff (403, nothing created); customer role change via form and API (ignored); cashier → owner pages
(403); manager → owner functions and staff management (403); IT Admin → finance capability and
financial API view (403); anonymous → every protected URL (redirect to sign-in); inactive accounts
cannot sign in and lose existing sessions; passwords stored as PBKDF2 hashes and never rendered;
CSRF enforced on sign-in, sign-out, staff creation and the API; role fields in requests ignored or
rejected; customers cannot see other users' data; customer IDs unreachable through staff URLs (404).

**Issues found and fixed during Phase 02 verification:**
- Set-temporary-password page crashed on GET (target not loaded before the page context was built)
- Bootstrap command printed garbled quotes in the Windows console (now plain quotes)
- Auth pages: logo and eyebrow label sat side by side; staff sign-in background left a gap on tall screens
- Staff list sorted roles alphabetically (now by seniority)
- Staff table squeezed and broke emails at tablet widths (now scrolls inside its card); a hidden
  screen-reader label made the page 33px too wide
- Customer details list broke the email mid-word in a narrow card (now switches by card width)
- Long badges ("Phase 08") wrapped; filter selects truncated at 320px

**Development note:** while creating the `admin` account, an idempotency check I ran
accidentally created it with a different temporary password first. This was corrected
immediately, so the temporary password is the one requested (hashed, change still required), and
verified by signing in.

### Phase 02 security review (2026-10-30)

Code review plus live testing of all five roles. **Two issues found and fixed**,
each with regression tests (`apps/accounts/tests/test_hardening.py`, 7 tests):

| # | Severity | Issue | Fix |
|---|---|---|---|
| 1 | Medium | Brute-force lock only covered the two portals; **`/admin/login/` had no attempt limit**, so the owner's password could be guessed there without limit | Throttle moved into the authentication backend; the portals and Django admin now share one lock |
| 2 | Low–Medium | **Sign-in names could collide.** A staff username could equal a customer's email (that customer could then no longer sign in), the `/me` API could set an email equal to another account's username, and usernames differing only by case ("Owner"/"owner") were allowed | `User.clean()` now rejects any username/email that matches another account's username or email, ignoring case. This covers every form and the Django admin; the API uses the same check |

| Review check | Method | Result |
|---|---|---|
| All automated tests | `python manage.py test` | **113 passed** (106 + 7 new) |
| Unauthorized URL access, all 5 roles × 11 protected URLs + anonymous | Live HTTP with real cookies and CSRF | Every result as designed (see matrix in the review report) |
| Customer role escalation | Live registration POST with `role=OWNER`, `is_staff`, `is_superuser` | Created as CUSTOMER; blocked from staff pages and the admin |
| Staff creation restrictions | Live: customer POST → 403; IT Admin creating IT Admin/Owner → rejected | Pass |
| Separate portals | Live: customer at staff portal, owner at customer portal | Both rejected |
| Inactive accounts | Live sign-in attempt | Rejected |
| CSRF | Live sign-in POST without token | 403 |
| Brute force (after fix) | Live: 5 bad admin logins, then correct password at staff portal | Refused with "Too many failed attempts" |
| Password storage | DB inspection | PBKDF2-SHA256 hashes only |
| OWNER bootstrap | Live on a scratch DB: weak refused, strong created, re-run unchanged | Pass; original password kept, 1 primary owner, audit entry written |
| Mobile responsiveness | Headless Edge, 18 pages across all roles × 6 widths (320–1366px) | 108/108 without horizontal overflow |
| `check`, migrations | `manage.py check`, `makemigrations --check` | Clean; no new migration needed |

Accepted by design (not defects): Owner and IT Admin can set temporary passwords for
accounts they manage, so they could sign in as that person once. This is recorded in the
audit log, and the person must then choose a new password. A non-primary Owner can change
roles in the Django admin (Owner has full access by definition).

### Known limitations

- **Login throttling uses an in-memory cache** per server process. Production with several
  worker processes needs a shared cache (database or Redis) configured at deployment.
- **Email is printed to the terminal** in development. A real SMTP service is needed before
  customers can reset passwords on the live site.
- No email verification on registration yet (customers can sign in immediately).
- Capabilities for future modules (catalog, POS, finance…) are defined but have no pages yet.
- Customer accounts cannot yet be managed by staff (Manager "manage customers" arrives with the customers module).
- "Forgot password" has no rate limit, so someone could repeatedly send reset emails to a known
  address (no account access is gained). Add a limit when a real email service is configured.
- Audit log covers account changes only; it is not yet a system-wide audit trail, and sign-in
  attempts are not logged there.
- Responsive checks used headless Microsoft Edge (Chromium). Real Android/iPhone devices have **not** been tested.
- ~~Logo is still the temporary placeholder.~~ Replaced by the official logo (see below).
- The weak development owner password must be changed at first sign-in and never used in production.

---

## Phase 01: Foundation and Architecture ✅

Delivered: Python 3.12 venv; Django 5.2 LTS with split settings; environment configuration;
SQLite/PostgreSQL-ready database config; custom User model before the first migration;
`TimeStampedModel`; security foundations; centralised placeholder logo; design system
(CSS variables, buttons, cards, forms, alerts, tables); responsive sidebar layout; home page;
style guide; branded error pages; DRF + drf-spectacular with health endpoint; documentation.
Verified 2026-10-30 (12 tests, deploy checks, overflow checks at six widths).

**Final Phase 01 audit (2026-10-30): PASS.** Server starts; `check` clean; all migrations
applied, none missing; `accounts.User` active (no `auth_user` table); `requirements.txt`
matches installed packages; `.env`/`db.sqlite3`/`.venv` git-ignored; logo rendered only via
`partials/_logo.html`; home, static files and error pages load (core tests 10/10); viewport
meta, mobile menu and responsive CSS present. No changes required.

---

## Proposed roadmap

| Phase | Scope | Status |
|---|---|---|
| 01 | Foundation and architecture | ✅ Complete |
| 02 | Authentication, user roles and permissions, staff dashboard shell | ✅ Complete |
| 03 | Product catalogue: categories, products, variations, images | ✅ Complete |
| 04 | Inventory, stock, suppliers and purchases | ✅ Complete |
| 05 | Customer storefront and shopping cart | ✅ Complete |
| 06 | Checkout, orders and payments (cash, bank transfer, online gateway) | ✅ Complete |
| 06b | Point of sale (POS) | Planned |
| 07 | Finance, reports and dashboard charts (Chart.js) | Planned |
| 08 | Notifications, Business Settings (logo upload), technical settings, security log viewer | Planned |
| 09 | PWA (manifest, service worker, icons) | Planned |
| 10 | Tauri Windows desktop app and production deployment | Planned |

The roadmap is a proposal and can be reordered. The home page shows a simplified version
(`templates/core/home.html`).
