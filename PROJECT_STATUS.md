# LEO PRODUCTS: Project Status

**Last updated:** 2026-10-31
**Current phase:** Phase 11 (Customer Store & UX Improvements): **COMPLETE**, except the PayHere sandbox test, which
needs your merchant credentials (see below). Phases 01–10 are complete; see the [final project report](#final-project-report).

---

## Phase 11: Customer Store & UX Improvements ✅

### Delivered (in the requested order)

1. **Products visible in the online store.** Cause found: the shop listed a product only when one of its variations
   had **stock recorded in Inventory**. The three products created by staff had no stock records, so the shop was
   empty. Now every Active product (in active categories, with an active variation) is listed, with image, name,
   category, short description, sizes and price; products with nothing in stock show an **"Out of stock"** badge and
   cannot be added to the cart (stock rules unchanged: only in-stock variations are buyable, quantities are
   limited by stock). Size options are labelled by size (e.g. "200g") with the staff name underneath. The staff
   product page has a new **"Online shop"** panel saying whether customers can buy the product and, if not, why,
   with a link to start tracking or add stock.
2. **Category structure:** LEO TEA › **Tea Bags**, **Tea Packets** (with **Black / Ginger / Cinnamon** variety
   filters on LEO TEA pages) and **LEO SWEETS** as its own main category. TEA BAGS is no longer a main category.
   Data migration `catalog/0004` moves products (ids, slugs, SKUs, variations, stock and history unchanged), points
   inventory items at the new categories, removes emptied old categories (or deactivates them if still referenced)
   and is safe to run twice. The development database was backed up first (`backup-before-categories.sqlite3`).
3. **Show/hide password** button on every password field (sign-in for both portals, registration, password change,
   password reset, staff accounts). Display only; the button is hidden without JavaScript and the field returns to
   hidden before the form is sent.
4. **Online payment (PayHere, Sri Lanka).** The existing integration was reviewed against PayHere's documented
   checkout hash and notification signature and kept (no duplicate workflow). Added: a **cancel return page**
   (logged; nothing charged; "Pay now" offered again), a clear message for failed payments, and tests for the
   cancelled (-1), pending (0) and chargeback (-3) codes and for paying again after a failure. Payments are marked
   paid **only** by the signature-verified server notification (merchant, amount and currency checked; duplicates
   ignored); the browser return is never trusted. No card data is stored. Cash on delivery/pickup and bank transfer
   are unchanged.
5. **Page width and spacing:** customer pages use the screen width fluidly (side padding 16–48 px, content up to
   1600 px) instead of Bootstrap's fixed steps (e.g. only 720 px of a 991 px tablet). Shop grid: 2/3/4/5 columns.
6. **Staff dashboard scrolling:** the top bar stays in view; on large screens the sidebar is its own scrolling
   column (scrolling the page doesn't move it; scrolling it doesn't move the page) and it **keeps its scroll
   position** when you open another section, with the current item kept in view. Phone drawer unchanged.

Also in this round: **home page hero** with a photo background and three slanted image cards that change one at a
time (Box 1 → Box 3 → Box 2, every 3.5 s), and an Owner-only **Staff portal → Administration → Home page images**
page to upload, replace, preview, reorder and remove the background and box images (validated, resized, stored in
`media/hero/`). Built-in samples (from the photos supplied) are used until images are uploaded.

### Database changes

- `core/0001`: `HomeHeroSettings` (background) and `HomeHeroImage` (box images).
- `catalog/0004`: data only (category restructure above).

### Verification performed (2026-10-31)

| Check | Result |
|---|---|
| `python manage.py test` | **565 tests, all passed** (34 new: hero, store listing, categories and migration, password toggle, PayHere cancel/codes, layout) |
| `check`, `makemigrations --check` | Clean |
| Real development data | Shop shows the 3 staff products (marked out of stock: no stock recorded yet); categories restructured, no product lost or duplicated |
| Browser (Edge) | Shop, category, product, cart, sign-in, account pages at 375/820/1024/1366/1920 px: no overflow or errors; add to cart with option + quantity; category chips and variety filters; password toggle then sign-in; staff sidebar scroll checks; home hero sequence 1→3→2 at 3.5 s; image upload/replace/remove |

### Needs your input

- **PayHere:** a sandbox Merchant ID and Merchant Secret (for your domain), and a public HTTPS address so PayHere
  can call `/payments/webhook/payhere/`. Steps are in `.env.example`. **Online payment has not been tested against
  PayHere** and must not be considered working until a sandbox payment succeeds.
- **Stock:** customers can only buy once stock is recorded (Staff portal → Inventory → Stock items, or the
  "start tracking stock" link on each product page).

### Known limitations (Phase 11)

- Variety filters (Black/Ginger/Cinnamon) search product names and descriptions; name products accordingly.
- Moving between staff pages is still a normal page load (the sidebar position is restored, not kept live).

---

## Phase 10: Final Testing, Security, Deployment & Installation ✅

### Delivered

- [x] **Security review** of authentication, permissions, CSRF, XSS, SQL injection, uploads, sessions, secrets and caching
      (findings and fixes below)
- [x] **Content-Security-Policy** on every page (`script-src 'self'`, no inline scripts anywhere: the last one, the
      payment redirect, moved to a static file), `frame-ancestors 'none'`, `object-src 'none'`, form targets limited to
      this site and the configured payment gateway; **Permissions-Policy** (no camera, microphone, location…)
- [x] **No caching of private pages:** `Cache-Control: private, no-store` on every response to a signed-in user
- [x] Uploaded **PDF** payment slips and expense receipts are downloaded, never displayed inside the site
- [x] **Production configuration:** WhiteNoise (compressed, cache-busting static files), PostgreSQL with persistent,
      health-checked connections, console logging, optional `SERVE_MEDIA` for single-PC installs, guarded
      `LOCAL_HTTP_ONLY` mode (refused for any host other than 127.0.0.1/localhost), `requirements-production.txt`
      (psycopg, WhiteNoise, Gunicorn on Linux / Waitress on Windows)
- [x] **Project deploy checks** in `check --deploy`: SQLite in production, default admin URL, console email, PayHere
      sandbox, private uploads inside a public folder (error)
- [x] **Deployment files** in `deploy/` (production `.env` template with empty placeholders, Gunicorn systemd service,
      Nginx with HTTPS, Windows start script); DEVELOPMENT_GUIDE §15–§16: PostgreSQL, moving data from SQLite, backups,
      Linux and Windows set-up, go-live checklist, updates
- [x] **Installable app (PWA):** manifest, icons from the official logo (192/512, maskable, Apple touch, favicon),
      standalone display, theme colours; service worker caching **static files only** plus a no-personal-data offline
      page; Apple/Android meta tags (DEVELOPMENT_GUIDE §17)
- [x] **Windows desktop app (Tauri 2) project** in `desktop/` with icons, config, capabilities and build guide;
      opens the same server (no separate database) — **installer not built** (no Rust toolchain on this PC)
- [x] New automated tests (`apps/core/tests_phase10.py`), README, ARCHITECTURE (§11, §20),
      DEVELOPMENT_GUIDE, this file

### Security review findings

| Area | Result |
|---|---|
| Authentication | Django password hashing; staff password rules stricter than customers'; sign-in throttle shared by both portals, admin and discount approvals; sessions 8 h, HttpOnly, SameSite=Lax; secure-only in production |
| Authorization | Every view checks a capability; automated sweep of **all** staff/admin/API URLs: customers and visitors never get a staff page; IT admin has no business pages |
| CSRF | On every form and JSON call; the only exemption is the signature-verified payment webhook |
| XSS | Auto-escaping everywhere; the only `|safe` is developer-written form help text; CSP now blocks inline/third-party scripts |
| SQL injection | No raw SQL in the project (ORM only) |
| Uploads | Size/type/content checks, random names, private folder for slips and receipts, permission-checked streaming, PDFs downloaded |
| Secrets | Only in `.env`/environment; Git history checked: no `.env`, database, private files or keys ever committed |
| **Fixed in this phase** | Signed-in pages could be cached by the browser (visible after sign-out/offline) → `no-store`; no CSP → enforced CSP; one inline script → static file; PDFs displayed inline → downloaded |

### Verification performed (2026-10-31)

| Check | Result |
|---|---|
| `python manage.py test` | **531 tests, all passed** (14 new Phase 10 tests + all Phase 01–09 tests) |
| `check`, `makemigrations --check` | Clean; no new migrations in Phase 10 |
| `check --deploy` (production settings) | Only expected warnings for the environment used (see "Not tested") |
| Production stack smoke test (Waitress + WhiteNoise + production settings, local mode) | 30/30 checks: hashed, compressed, long-cached static files; manifest and service worker; branded 404 with DEBUG off; debug pages hidden; Owner pages; Excel export; private media unreachable; customer blocked from staff/admin; POST without CSRF refused; session cookie HttpOnly + SameSite |
| Browser (Edge via DevTools protocol) on the production build | 20 pages as customer and Owner: **no console errors, CSP violations or failed requests**; fonts/icons load; dropdowns work |
| Service worker | Active for the whole site; cache holds 14 static files + the offline page only; offline page contains no user data; with the network off a private page shows the offline page |
| Responsive sweep (production build) | 43 pages × 5 widths (320–1366 px), all roles: no overflow, no broken images, all HTTP 200, navbar one row |
| End-to-end on production build | Till sale → receipt; online checkout (pickup, cash) → confirmation |
| Link crawl (automated test) | Every internal link and static file reachable for visitor, customer, cashier, manager, owner and IT admin |

### Not tested (honestly)

- **PostgreSQL**: not installed on this PC. The driver is installed and configuration is in place, but migrations and
  the test suite ran on SQLite only. Run the tests once on PostgreSQL before going live.
- **Linux/Gunicorn/Nginx and real HTTPS**: example files only; not run here. HSTS, secure cookies and the HTTPS redirect
  were verified as settings, not over a real certificate.
- **Windows installer**: the Tauri project was not built (no Rust); the JSON config was validated only.
- **PWA install on real phones** (Android/iPhone) and on a public HTTPS site; real receipt printers; real email (SMTP);
  PayHere sandbox (no credentials).

---

## Final project report

### Completed (Phases 01–11)

Foundation and branding · accounts with five roles and two portals · product catalogue · inventory, suppliers and
purchases · online shop and cart · checkout, orders, cash/bank transfer/online-gateway payments · point of sale with
cashier shifts, discounts, receipts and refunds · finance (expenses, supplier balances, COGS, profit & loss, cash flow,
11 reports with charts and CSV/Excel/A4) · notifications, business alerts, wishlist, reviews, search and activity
history · security hardening, production configuration, installable app, desktop-app project · store
improvements (all products visible, tea/sweets categories, password toggle, payment cancel handling, wider
layout, staff sidebar) and the managed home page hero.

### Readiness

| Area | Status |
|---|---|
| Automated tests | 565 passing |
| Deployment | **Ready to deploy** once a server, domain, PostgreSQL and SMTP are provided; guide and example files included |
| PWA | **Ready**: works on HTTPS (or 127.0.0.1); real-device install not yet tried |
| Windows installer | **Not built**: project ready; needs Rust + C++ Build Tools to build (`desktop/README.md`) |

### Manual steps before going live

1. Provide hosting (Linux server or a Windows shop PC), a domain with HTTPS, PostgreSQL and SMTP email.
2. Create the production `.env` from `deploy/env.production.example` (new SECRET_KEY, ADMIN_URL, hosts, database, email).
3. `pip install -r requirements-production.txt`, `check --deploy`, `migrate`, `collectstatic`, `bootstrap_owner`.
4. Run the test suite once against PostgreSQL.
5. Enter business data: products, **stock costs**, delivery areas, bank details, POS receipt details, alert settings.
6. Optional: PayHere (sandbox first), build the desktop installer, schedule `send_business_alerts` and backups.

### Remaining limitations (summary)

See the "Known limitations" lists of each phase above. The main ones: online payment untested against PayHere;
profit figures need stock costs; no tax/VAT, payroll or double-entry accounting; no live push notifications or SMS;
no barcode field (SKU scanning only); notifications and logs are not automatically cleaned up.

---

## Phase 09: Notifications & Advanced Features ✅

### Delivered

- [x] New `notifications` app: `Notification` (read/unread, category, level, internal link), `NotificationPreference`
      (muted categories; customers' order-email switch), `AlertSettings` (Owner thresholds and review approval)
- [x] **No duplicates:** each event has a key, and a database rule allows one notification per key and person; they are
      created after the database change commits (nothing for rolled-back work); a notification problem never breaks the action
- [x] **Hooked into existing services** (no business logic rewritten): new orders, customer cancellations, status changes,
      payment approved/rejected/cash/online, transfers to verify (online and till), stock crossing reorder level or running out,
      purchases received, expenses, POS voids, shifts closed short/over, reviews
- [x] **Role-based delivery** by capability; actors aren't notified about their own action; messages contain no costs or
      profit; customers only receive notifications about their own orders and reviews
- [x] **Bell** with unread badge and dropdown (five newest, mark all read) in the staff top bar and the public navbar for
      signed-in users (navbar stays one row, 68px, from 320 to 1366px); full history with filters, mark read/unread;
      sidebar and account-tab badges
- [x] **Preferences** per category (only categories the role can receive); customers can switch off order emails
- [x] **Business alerts** (live, by role): out of stock, low stock, transfers to verify, pending orders (flagged after N hours),
      long-unpaid orders, refunds due, open POS shifts (own shift for cashiers), products without cost, reviews to check;
      on every staff dashboard ("Needs attention") and an alerts page; `send_business_alerts` command for a daily digest
- [x] **Wishlist** (customers): save/remove on the product page, wishlist page
- [x] **Reviews:** verified purchasers only (paid, not cancelled), one per product, editable (re-checked), moderated by
      Owner/Manager with a reason shown to the customer, optional auto-publish; average rating and reviews on the product page;
      reviewer shown as first name + initial
- [x] **Staff search** across orders, payments, till sales, products, stock, suppliers, purchases, expenses, customers and
      staff, limited to what the role may open
- [x] **Activity history** combining the existing audit records (order events, payment events, stock ledger, POS shifts,
      cash movements, reprints, review decisions; finance and account entries for the Owner), with filters
- [x] Dashboards: "Needs attention" and "Latest notifications" panels; customer account tabs for Notifications and Wishlist
- [x] New capabilities `VIEW_ACTIVITY`, `MODERATE_REVIEWS` (Owner, Manager)
- [x] Docs: DEVELOPMENT_GUIDE §13, test table, README, ARCHITECTURE §19, this file
- [x] Development database backed up to `backup-before-phase09.sqlite3` before migrating

### Database changes

| Migration | Change |
|---|---|
| `notifications.0001` | `Notification` (unique per recipient and event key), `NotificationPreference`, `AlertSettings` |
| `shop.0002` | `WishlistItem` (one per customer and product), `ProductReview` (one per customer and product, rating 1–5) |

### Verification performed (2026-10-31)

| Check | Result |
|---|---|
| `python manage.py test` | **517 tests, all passed** (33 new Phase 09 tests + all Phase 01–08 tests) |
| `check`, `makemigrations --check` | Clean; migrations applied to the dev DB |
| Horizontal overflow (headless Edge), customer, owner, manager and cashier, 16 pages × 5 widths | 80/80 OK, all HTTP 200 |
| Public navbar height with bell, guest/customer/staff, 320–1366px | 68px everywhere (one row) |

**Issues found and fixed during Phase 09:**
- The brand tagline ran under the new bell on phones; it now shortens with "…"
- On phones the "Mark read" button squeezed notification text; it now wraps below

### Known limitations (Phase 09)

- In-app notifications appear when a page is opened or refreshed (no live push); there are no SMS or mobile push messages.
- Staff don't get emails for notifications (customers keep their order emails).
- The daily alert digest needs `send_business_alerts` to be scheduled (Windows Task Scheduler); it doesn't run by itself.
- Notification history is kept indefinitely; there is no automatic clean-up yet.
- Activity history reads up to 300 recent entries per area for the chosen period; very busy periods should be narrowed by dates.
- No public product search by rating, no review photos, no "helpful" votes; wishlist has no price-drop or back-in-stock alerts.
- Search is a simple text match (no fuzzy matching).

---

## Phase 08: Finance & Reports ✅

### Delivered

- [x] **Built on existing data:** sales from `orders.Order`/`OrderItem` (online and POS), money received from
      `payments.Payment`, purchases and suppliers from `inventory`, shifts from `pos`. New `finance` app only adds
      expenses, supplier payments, the audit log and the reporting layer
- [x] **Costs (the missing piece):** `InventoryItem.average_cost` (weighted average, updated automatically when a purchase
      is received, with unit conversion) and Owner-set costs for products made in-house; every change logged in
      `ItemCostChange`. Each sold line copies `unit_cost`/`cost_total` at the moment of sale. Older sales stay "without
      cost" and are reported as such; no historical cost is invented or back-filled
- [x] **Finance overview** (Owner): sales, revenue, discounts, COGS, gross profit, operating expenses, net operating
      profit, stock purchases, cash and bank/online collections for any period, plus a 12-month chart
- [x] **Expenses** (Owner, Manager record; Owner voids): categories (seeded, Owner-managed, deactivate not delete),
      date, amount, payment method, payee, reference, private receipt attachment (validated like payment slips)
- [x] **Supplier payments and balances** (Owner): payments on account or against a received purchase, never more than
      owed; balances, running statement per supplier; paid/outstanding shown on purchase and supplier pages
- [x] **Profit & loss** with one definition per figure: revenue = paid, non-cancelled sales by order date (discounts and
      delivery fees once); COGS from recorded costs; purchases kept out of expenses; refunds never counted as revenue;
      warnings when sales lack a cost
- [x] **11 reports:** sales (day/month/year), product sales, category sales, cashier sales, purchases, stock valuation,
      expenses, profit & loss, cash flow, supplier balances, customer balances
- [x] **Date filters** (presets and custom), **SVG charts** (no external library), **CSV** (UTF-8 for Excel) and real
      **Excel .xlsx** exports (written with the standard library, no new dependency), **A4 print** layout with logo;
      spreadsheet formula injection neutralised; exports logged
- [x] **Roles:** Owner everything; Manager operational reports without cost/profit columns or notes, and recording
      expenses; Cashier, IT Admin and customers no finance access (POS shift/sales pages unchanged). New capabilities
      `VIEW_FINANCE`, `RECORD_EXPENSES`; `MANAGE_FINANCE` and `VIEW_OPERATIONAL_REPORTS` now used
- [x] **Protection:** expenses, supplier payments, categories, cost history and the audit log can't be deleted (model and
      bulk-delete guards); corrections by void with reason; one-time form tokens stop double recording; conditional
      updates stop double voids; supplier balance checks run with the supplier row locked
- [x] **Finance audit log** (Owner): recorded/voided entries, cost changes, category changes, exports
- [x] Sidebar "Finance & reports", dashboard links, home roadmap (08 done)
- [x] Docs: DEVELOPMENT_GUIDE §12, test table, README, ARCHITECTURE §18, this file
- [x] Development database backed up to `backup-before-phase08.sqlite3` before migrating

### Database changes

| Migration | Change |
|---|---|
| `inventory.0004` | `InventoryItem.average_cost`, `cost_updated_at`; new `ItemCostChange` |
| `orders.0004` | `OrderItem.unit_cost`, `cost_total` (cost of goods sold, copied at sale) |
| `finance.0001` | `ExpenseCategory`, `Expense`, `SupplierPayment`, `FinanceEvent` |
| `finance.0002` | Seeds 10 expense categories (names only, no figures) |

### Verification performed (2026-10-31)

| Check | Result |
|---|---|
| `python manage.py test` | **484 tests, all passed** (37 new finance tests + all Phase 01–07 tests) |
| `check`, `makemigrations --check` | Clean; migrations applied to the dev DB |
| Hand-checked scenario | One period with discounted POS cash sale, approved and unverified till transfers, refunded sale, paid delivery order, unpaid order, expenses (one voided) and a supplier payment: revenue, discounts, delivery, COGS, gross/net profit, collections, cash flow, balances all match hand calculations |
| Horizontal overflow (headless Edge), Owner and Manager, 25 finance pages × 5 widths (320–1366px) | 125/125 OK, all HTTP 200 |
| A4 print | Wide reports fit the page after a fix (see below) |

**Issues found and fixed during Phase 08:**
- The product report's note about gross profit was visible to Managers; cost/profit notes are now Owner-only
- Wide reports were cut off on the A4 print page; the print table now wraps headings and fits
- Chart axis numbers were hidden behind the first bar

### Known limitations (Phase 08)

- **Profit is only as good as the stock costs.** Your existing products have no cost until a purchase is received or
  the Owner sets one; sales before that are "without cost" (flagged in the reports, not estimated).
- Stock valuation is current only (no "value as of a past date"); average cost isn't reduced for returns/damage.
- Order-level discounts are not allocated to individual products in the product/category reports (they are in the
  sales and P&L reports).
- Revenue is recognised on the order date once paid (cash basis per sale); a cash-on-delivery order paid next month
  is counted in the month it was ordered. There is no accrual accounting, VAT/tax, depreciation, payroll, bank
  reconciliation or double-entry ledger.
- Supplier advance payments, supplier credit notes and returns to suppliers aren't supported.
- Expenses paid from a POS drawer must also be recorded as a POS "cash out" to keep the drawer count right (not linked).
- Charts are simple bar charts; no interactive zooming.
- Responsive checks used headless Microsoft Edge; printing on a physical printer was not tested.

---

## Phase 07: POS (Point of Sale) & Cashier Management ✅

### Delivered

- [x] **Built on Phase 06, not beside it:** a POS sale is an `Order` with `channel = POS` (number `POS-YYYY-NNNNN`,
      fulfilment "In-store sale", no customer account needed). It reuses order lines (prices copied), the stock ledger
      (one "Sale (order)" movement per line, never below zero), `Payment`, cancellation/restock and refund services.
      The shared line-and-stock code was moved into `orders.services.add_items_and_deduct_stock` and is used by both
- [x] New `pos` app only for what didn't exist: `PosSettings`, `CashierShift`, `CashMovement`, `ReceiptPrint`
- [x] **Till** `/staff/pos/`: full-width workspace (staff top bar and logo kept), category chips, search by name or
      SKU, Enter/scanner adds an exact SKU, product tiles with price and stock, cart with +/−, quantity and remove,
      subtotal, discount and total in LKR, cash received with Exact/rounded buttons and change, bank transfer reference,
      optional customer name and phone, loading state, error messages, empty states, confirm before clearing
- [x] **Sales are one transaction:** shift checked, prices/stock re-read from the database, discount and total
      recalculated, payment validated, stock deducted, payment recorded. The browser's token makes a sale idempotent
      (double click or network retry returns the first sale); the total the cashier saw must match
- [x] **Cash:** must cover the total; tendered amount and change stored on the payment; sale Completed and Paid
- [x] **Bank transfer at the till:** reference required; payment stays **Pending verification** and the sale Pending
      until a Manager/Owner approves it (then Completed); never marked paid at the till
- [x] **Discounts:** fixed LKR or %, reason required, never above the sale or 100%; per-role limits in POS settings
      (Cashier 5%, Manager 20%, Owner unlimited by default); above the limit a Manager/Owner approves on the till with
      their sign-in (shared brute-force lock); applied-by and approved-by recorded on the sale
- [x] **Receipts:** printable page with the official logo, name, tagline, optional address/phone/footer from settings
      (no invented tax or registration details), receipt number, date/time, cashier, items, quantities, prices,
      discount, total, payment method, cash received and change, transfer note; 80 mm till layout and A4; prints
      automatically after a sale; reprints logged (who/when) and marked "COPY"; voided sales marked "VOIDED"
- [x] **Cashier shifts:** open with counted cash; one open shift per cashier (database constraint); sales only in an
      open shift; cash in/out with reasons (cash out limited to the drawer); expected cash = opening + cash sales +
      cash in − cash out − cash refunds; close with counted cash, difference calculated and fixed, note required when
      different; closed shifts can't be changed; Managers/Owner review all shifts and can close a forgotten one
- [x] **Sales history** `/staff/pos/sales/`: today's figures, search by receipt number, filter by date, cashier,
      payment method and status; sale details with items, stock movements, payment, discount, reprints, history
- [x] **Refunds / voids** (Manager, Owner): reason required; stock restored once (existing cancel service), paid payment
      marked refunded once (existing refund service), cash refund recorded against the open till that paid it (one per
      sale, database constraint); unverified transfers simply closed. Nothing is deleted
- [x] **Dashboards:** Owner, Manager and Cashier dashboards show today's POS sales, transactions, cash sales, bank-transfer
      sales (verified, plus awaiting check), open shifts and expected drawer cash; cashiers see their own figures only;
      sidebar "Point of sale" section and dashboard links
- [x] **Roles (enforced in views and services):** Cashier: till, own shift, own sales and reprints. Manager: all sales,
      discount approval, transfer verification, refunds, shift review; no selling. Owner: everything incl. POS settings.
      IT Admin and customers: no POS access
- [x] Online order screens list online orders only; opening a POS sale there goes to the POS page
- [x] Docs: DEVELOPMENT_GUIDE §11 (setup, a cashier's day, managers, permissions, printing), test table, this file
- [x] Development database backed up to `backup-before-phase07.sqlite3` before migrating

### Database changes

| Migration | Change |
|---|---|
| `orders.0002`, `orders.0003` | `Order`: `channel`, optional `customer`, `cashier`, `shift`, discount fields (type, value, amount, reason, applied by, approved by); fulfilment "In-store sale"; constraints: discount within subtotal, online orders must have a customer, pickup/in-store have no delivery fee |
| `payments.0002` | `Payment`: `cash_tendered`, `change_given` (non-negative) |
| `inventory.0003` | Sale movement label "Online order" → "Sale (order)" (used by both channels) |
| `pos.0001` | `PosSettings`, `CashierShift` (one open per cashier, closed shifts must have a count), `CashMovement` (one cash refund per sale), `ReceiptPrint` |

### Verification performed (2026-10-31)

| Check | Result |
|---|---|
| `python manage.py test` | **447 tests, all passed** (64 new POS tests + all Phase 01–06 tests) |
| `check`, `makemigrations --check` | Clean; new migrations applied to the dev DB |
| Horizontal overflow (headless Edge), cashier, manager and owner, 15 POS pages × 5 widths (320–1366px) | 75/75 OK, all HTTP 200 |
| Browser walkthrough of the till | Tap products, scan SKU, discount over the limit refused then approved by the Manager's sign-in, change shown, triple click sent one request and recorded one sale, receipt shown |

**Issues found and fixed during Phase 07:**
- Approver passwords would have had a second, separate throttle; approval now uses the existing sign-in lock (which
  Django reports as a failed sign-in, so the lock is checked first to give a clear message)
- The receipt's automatic print dialog blocked the headless browser test; the test now skips it (real browsers show it)

### Known limitations (Phase 07)

- **No barcode field exists** in the catalogue, so scanning works when the barcode printed on packs is the product's
  **SKU** (a scanner types it and presses Enter). Real EAN barcodes would need a barcode field (not added).
- No card terminal or online payment at the till; no split payments (part cash, part transfer).
- A rejected till bank transfer leaves the sale unpaid; the fix is to void it and sell again with another payment.
- Refunds are whole-sale voids; partial refunds/returns of single items are not supported.
- Shifts are per cashier, not per physical drawer; two cashiers sharing one drawer would need one shift between them.
- The till loads all sellable products into the page (fine for a small catalogue; a large one would need searching
  on the server).
- Concurrency is tested by simulating two tills that both saw the same stock; real parallel requests could not be
  run on the SQLite test database. The protection is the stock ledger's conditional update, as in Phase 06.
- Receipt printing uses the browser's print dialog; direct printing to a thermal printer without a dialog is not possible
  from a web page.
- A cashier who reloads the receipt within 15 minutes before any reprint still sees it without "COPY".
- No POS figures in finance or accounting reports yet (later phase).
- Responsive checks used headless Microsoft Edge; real tablets, phones and receipt printers were not tested.

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
| 07 | Point of sale (POS) and cashier shift management | ✅ Complete |
| 08 | Finance and reports (expenses, supplier balances, profit & loss, exports, charts) | ✅ Complete |
| 09 | Notifications, business alerts, wishlist, reviews, search, activity history | ✅ Complete |
| 10 | Final testing, security hardening, production deployment, PWA, Windows desktop project | ✅ Complete |
| Later | Business Settings (logo upload), technical settings, security log viewer | Optional |
| Later | Build and sign the Windows installer; real-device PWA and PostgreSQL testing | Manual step |

All planned phases are complete; optional later work is listed above. The home page shows a simplified version
(`templates/core/home.html`).
