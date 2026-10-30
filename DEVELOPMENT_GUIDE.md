# LEO PRODUCTS: Development Guide (Windows)

A step-by-step guide for setting up and working on the project on Windows.
All commands are for **Windows PowerShell** (the default terminal in VS Code).

---

## 1. Install the tools (one time)

### Python 3.12

1. Download **Python 3.12.x (64-bit)** from <https://www.python.org/downloads/windows/>.
2. In the installer, tick **"Add python.exe to PATH"**, then click **Install Now**.
3. Check it in a new PowerShell window:

   ```powershell
   py -3.12 --version
   ```

   You should see `Python 3.12.x`.

> **Several Python versions installed?** Use `py -3.12` (the Windows Python launcher)
> when creating the virtual environment. It always picks 3.12 even if `python` points
> to another version. On this development PC, `python` points to 3.13, which is why
> the project uses `py -3.12`.

### Git

Download from <https://git-scm.com/download/win> and install with the default options. Then set your name and email once:

```powershell
git config --global user.name "Your Name"
git config --global user.email "you@example.com"
```

### Visual Studio Code and extensions

Install VS Code from <https://code.visualstudio.com/>. Open the project folder
(**File → Open Folder…**) and VS Code will offer the recommended extensions listed in `.vscode/extensions.json`:

| Extension | Why |
|---|---|
| Python (Microsoft) | Run and debug Python |
| Pylance | Autocomplete and error checking |
| Django (Baptiste Darthenay) | Highlighting for Django templates |
| GitLens | See Git history in the editor |

---

## 2. Set up the project (first time on a computer)

Open the project folder in VS Code, then open a terminal with **Ctrl + `**.

### Step 1: Create the virtual environment

```powershell
py -3.12 -m venv .venv
```

This creates a `.venv` folder that holds this project's own Python and packages.

### Step 2: Activate it

```powershell
.\.venv\Scripts\Activate.ps1
```

Your prompt now starts with `(.venv)`. **Activate it every time you open a new terminal.**

> **Error "running scripts is disabled on this system"?** Run this once, then try again:
>
> ```powershell
> Set-ExecutionPolicy -Scope CurrentUser -ExecutionPolicy RemoteSigned
> ```

### Step 3: Install the dependencies

```powershell
python -m pip install --upgrade pip
pip install -r requirements.txt
```

### Step 4: Create your `.env` file

```powershell
Copy-Item .env.example .env
```

Generate a secret key:

```powershell
python -c "from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())"
```

Open `.env` in VS Code and paste the result after `SECRET_KEY=`.
**Never share or commit `.env`.**

### Step 5: Create the database

```powershell
python manage.py migrate
```

### Step 6: Create the initial OWNER account

```powershell
python manage.py bootstrap_owner
```

It asks for a username, email and temporary password. Full details, including the
development `admin` account, are in [section 5](#5-the-initial-owner-account).

### Step 7: Start the server

```powershell
python manage.py runserver
```

Open <http://127.0.0.1:8000/> in your browser. Stop the server with **Ctrl + C**.

---

## 3. Everyday commands

| Task | Command |
|---|---|
| Activate the environment | `.\.venv\Scripts\Activate.ps1` |
| Start the server | `python manage.py runserver` |
| Check the project for problems | `python manage.py check` |
| Run the automated tests | `python manage.py test` |
| Create migrations after changing models | `python manage.py makemigrations` |
| Apply migrations | `python manage.py migrate` |
| Check for missing migrations | `python manage.py makemigrations --check --dry-run` |
| Show migration status | `python manage.py showmigrations` |
| Open the Django shell | `python manage.py shell` |
| List installed packages | `pip freeze` |

### Adding a new package

```powershell
pip install package-name
pip freeze > requirements.txt
```

Commit the updated `requirements.txt` so everyone gets the same versions.

### Creating a new app (future phases)

```powershell
mkdir apps\catalog
python manage.py startapp catalog apps\catalog
```

Then in `apps\catalog\apps.py` set `name = "apps.catalog"` and add `"apps.catalog"` to
`LOCAL_APPS` in `config\settings\base.py`.

---

## 4. Environment variables

All variables are documented in `.env.example`. The important ones:

| Variable | Development | Production |
|---|---|---|
| `SECRET_KEY` | any long random value | a **different** long random value |
| `DEBUG` | `True` | ignored (always False) |
| `ALLOWED_HOSTS` | `localhost,127.0.0.1` | your domain, e.g. `leoproducts.lk,www.leoproducts.lk` |
| `CSRF_TRUSTED_ORIGINS` | empty | `https://leoproducts.lk,https://www.leoproducts.lk` |
| `DATABASE_URL` | empty (uses SQLite) | `postgres://user:password@host:5432/dbname` |
| `DJANGO_SETTINGS_MODULE` | not set (uses development) | `config.settings.production` |
| `PAYMENT_GATEWAY`, `PAYHERE_*` | empty (online payment off) | see §10 |
| `EMAIL_*` | empty (emails printed in the terminal) | your SMTP server, for real order emails |

## 5. The initial OWNER account

The first account is created with a management command, never in code. The command:

- creates **one** primary OWNER and is safe to run again (a second run changes nothing);
- **never** changes an existing account's password;
- hashes the password and never prints it;
- forces a new password at the first sign-in.

### Option A: let the command ask you (recommended)

```powershell
python manage.py bootstrap_owner
```

Type the username, email and a temporary password when asked (the password is not shown as you type).

### Option B: environment variables for this terminal only

The values disappear when you close the terminal and are never saved to a file:

```powershell
$env:OWNER_USERNAME = "admin"
$env:OWNER_EMAIL = "admin@gmail.com"
$env:OWNER_PASSWORD = "your-temporary-password"
python manage.py bootstrap_owner --no-input
Remove-Item Env:OWNER_PASSWORD
```

### The development owner account

An owner with username `admin` (email `admin@gmail.com`) has **already been created** in
your local `db.sqlite3`. Its temporary password was given to you privately and is
deliberately not written in any project file, so it can never end up in Git.
Because that temporary password is weak, it was created with a development-only flag:

```powershell
python manage.py bootstrap_owner --no-input --allow-weak-password   # refused when DEBUG=False
```

**Change it immediately:** sign in at <http://127.0.0.1:8000/staff/login/> with username
`admin` and the temporary password. You are taken straight to **Choose a new password**,
and nothing else works until you do. The new password must meet the rules (10+ characters,
not common, not similar to your name).

> **Never** use a weak temporary password on a live server. In production, run
> `bootstrap_owner` interactively with a strong temporary password.

### If something already exists

| Situation | What the command does |
|---|---|
| A primary owner already exists | Prints "No changes made" and stops |
| The username/email belongs to another account | Stops without changing anything |
| ...and you really want that account to become the owner | `python manage.py bootstrap_owner --promote-existing` (password left unchanged) |

### Forgot the owner password in development?

Use **Forgot your password?** on the sign-in page. In development the reset email is
printed in the terminal where `runserver` is running; copy the link into your browser.

---

## 6. Signing in and testing roles (development)

1. Sign in as the owner at `/staff/login/`.
2. Open **Staff accounts → New staff account** and create one IT Admin, one Manager and one
   Cashier with temporary passwords.
3. Sign out, then sign in as each one. Each is asked to choose their own password and lands
   on their own dashboard.
4. Register a customer at `/account/register/` (use a different browser or a private window
   to stay signed in as staff in the other).

Trying a page you are not allowed to see shows the **Access denied** page. That is the
permission system working.

Backups: before the Phase 04 and Phase 05 migrations, copies of the development database were saved as
`backup-before-phase04.sqlite3` and `backup-before-phase05.sqlite3` (git-ignored). Delete them once you're happy everything works.

Too many wrong passwords? Sign-in is locked for 15 minutes for that account name on that
computer. In development you can also just restart `runserver` to clear it.

---

## 7. Managing the product catalogue

Sign in as an **Owner** or **Manager** and open **Catalogue** in the staff sidebar
(<http://127.0.0.1:8000/staff/catalog/>). IT Admins, Cashiers and Customers cannot open these pages.

### Create a category

1. **Catalogue → Categories → New main category**, e.g. `LEO SPICES`.
2. To add a subcategory, click **+ Subcategory** next to its main category (or choose the
   main category in the form), e.g. `Pepper`.
3. Optional: upload an image, and set **Sort order** (lower numbers are shown first).

Names must be unique within the same main category (capital letters don't matter).
Rename or deactivate categories at any time with **Edit** / **Deactivate**. Only an empty
category (no subcategories, no products) can be deleted.

### Create a product

1. **Catalogue → Products → New product**.
2. Enter the name, choose the **main category** and optionally a **subcategory** (the list only
   shows subcategories of the chosen main category), add a description and image.
3. Save. New products start as **Draft**, and you are taken straight to **Add variation**.

### Add variations (sizes and prices)

Each size of a product is a variation with its own SKU and price:

| Product type | Measurement type | Quantity + unit | Shown as |
|---|---|---|---|
| Loose tea | Weight | 200 + g | 200g |
| Tea bags | Count | 25 + bags | 25 bags |
| Sweets | Pieces | 10 + pieces | 10 pieces |

1. Choose the **measurement type**; the **unit** list then shows matching units only.
2. Enter the **quantity** and the **selling price** in LKR (wholesale price is optional).
3. Leave **SKU** empty to generate one (e.g. `LEO-LT-0007-200G`), or type your own.
4. **Add & add another** keeps you on the form for the next size.

When the product has at least one active variation, open the product and click **Active**.

### Add a new unit

Need "packs", "jars" or "ml"? **Catalogue → Units → New unit**: choose the measurement type,
enter a name (`Pack`) and the symbol shown after numbers (`packs`). Tick **Attach symbol**
only for short symbols written without a space, like `g` → `200g`.

### Images

JPG, PNG or WebP, up to 5 MB. Large photos are resized automatically and hidden photo data
(such as GPS location) is removed. Uploaded files are stored in the `media/` folder, which is
**not** committed to Git. Back it up together with the database.

### Archiving

Products, variations and units are never deleted. Set a product to **Inactive**, or click
**Deactivate** on a variation or unit. Their history stays intact for orders and stock in later phases.

---

## 8. Using the inventory module

Sign in as an **Owner** or **Manager** and open **Inventory** in the staff sidebar
(<http://127.0.0.1:8000/staff/inventory/>). IT Admins, Cashiers and Customers cannot open it.

### Start tracking stock (opening stock)

**Stock items → Track new item**, then choose what you are tracking:

| Type | Example | Counted in |
|---|---|---|
| **Raw material (unpacked)** | Unpacked Black Tea | the unit you choose, e.g. **kg** |
| **Finished product** | Black Tea 200g (a catalogue variation) | whole **packets** |

Enter the **opening stock** (what you hold right now, or 0) and the **reorder level**
(when to warn you). Saving records an "Opening stock" entry in the history.

> Loose tea and packed tea are separate items. Packing 2 kg of loose tea into 200g packets
> means removing 2 kg from the raw material and adding 10 packets to the finished product,
> each with a reason.

### Adjust stock

Open an item → **Adjust stock**, choose what happened (increase, decrease, damage, expired,
correction, or other), enter the quantity and a **reason**, click **Review change**, check the
summary, then **Confirm and record**. For raw materials you can type grams even if stock is
kept in kg; it is converted. Stock cannot go below zero (only the Owner can allow that for a
specific item under **Settings**).

Use **Correction (count)** after a physical stock count: enter the total you actually counted
and the system records the difference.

### Suppliers

**Suppliers → New supplier.** Suppliers are never deleted; **Deactivate** hides them from new
purchases while keeping their history (open a supplier to see all their purchases).

### Purchases

1. **Purchases → New purchase**: choose the supplier and date, then add each item with its
   quantity, unit (raw materials) and cost per unit in LKR. **Save draft**: stock does **not** change yet.
2. When the goods arrive, open the purchase → **Receive** → check the table → **Confirm and add to stock**.
   A purchase can only be received once, even if you click twice.
3. A draft that won't arrive can be **cancelled** (with a reason). Received purchases are final;
   fix mistakes with a stock adjustment.

Only record **goods** in purchases. Transport, electricity, rent and other running costs are
**expenses**, handled in a later phase.

### Low-stock alerts

Set **reorder**, **minimum** and (optional) **maximum** levels in each item's **Settings**.
Items at or below the reorder level appear under **Low-stock alerts** on the inventory
dashboard and with the **Needs reorder** filter on the item list.

### Stock history

**Stock movements** lists every change ever made: who, when, before/after and why. Entries can't be
edited or deleted.

---

## 9. The online shop (customers)

Customers browse at <http://127.0.0.1:8000/shop/> (also **Shop** in the top bar and **Shop now** on the
home page) and see their cart at <http://127.0.0.1:8000/cart/> (bag icon in the top bar).

### How a product appears in the shop

A product is shown only when **all** of these are true. If your product doesn't appear, check them in order:

1. **Catalogue → Products:** the product's status is **Active**.
2. Its **main category** (and subcategory, if any) is **active**.
3. At least one **variation** is active.
4. That variation has **stock tracking**: **Inventory → Track new item → Finished product**.
5. Its stock is **at least 1 packet**.

Variations that are out of stock or not tracked still appear on the product page, greyed out
and not selectable. Customers only ever see the **selling price**, never the wholesale price.
At 5 or fewer in stock the shop shows "Only N left" (`SHOP_LOW_STOCK_THRESHOLD` in settings).

> Quick test: create a product, add a 200g variation with a price, activate the product,
> then track the 200g variation in Inventory with an opening stock of e.g. 10. It now appears in the shop.

### Searching and sorting

Customers can search by product name, description or category, open a category or subcategory,
and sort by relevance, newest, price (low → high, high → low) or name. Results show 12 per page,
and the search is kept when moving between pages.

### The cart

- Guests and signed-in **customers** can add items. Staff accounts can browse but not shop.
- Quantities are checked against current stock when adding or updating, with a maximum of
  `CART_MAX_QUANTITY_PER_ITEM` (50) of one item.
- Adding to the cart does **not** reduce stock. Stock is reduced when an order is placed (§10).
- If stock drops after something was added, the cart page reduces the quantity automatically and says so.
  Items that are no longer available are marked and left out of the total.
- A guest's cart belongs to their browser session. When they sign in or create an account, it is merged
  into their customer cart (capped at available stock). A customer's cart is saved to their account.
- **Proceed to checkout** on the cart page starts an order (§10). Staff accounts can't check out.

Old guest carts can be cleaned up with:

```powershell
python manage.py clear_old_guest_carts --days 30
```

---

## 10. Orders and payments

### First-time setup (Owner)

Staff portal → **Orders → Delivery & payment** (<http://127.0.0.1:8000/staff/orders/settings/>):

1. **Delivery & pickup:** tick what you offer. Enter the pickup address and opening hours (customers see them).
2. **Delivery areas:** click **Add area** for each area you deliver to, with its fee in LKR and, optionally,
   "free delivery over" an amount. **Home delivery is only offered when at least one active area exists.**
   Changing a fee later does not change orders already placed.
3. **Cash:** choose whether you accept cash on delivery and/or cash at pickup.
4. **Bank transfer:** tick it and fill in the bank name, branch, account name and account number.
   Customers see these details after ordering. Bank transfer is only offered when the details are complete.
5. **Online payment** shows "Not configured" until a developer sets it up (see below).

If no delivery or payment option is available, the checkout page says online ordering isn't available.

### How a customer orders

Cart → **Proceed to checkout** (sign in or create an account first) → name, phone, delivery or pickup,
address and instructions, payment method → **Review** (items, delivery fee, total) → **Place order**.

When the order is placed, in one database transaction:
- prices are taken from the database (never from the browser) and copied onto the order;
- stock is checked again and **deducted** (ledger entry "Online order"); if someone else bought the last
  packet in the meantime, the customer is told and nothing is saved;
- the order gets a number like `LEO-2026-00001`, a payment record is created and the cart is emptied.

Clicking **Place order** twice, or refreshing, never creates a second order. If prices change between review
and placing, the customer is shown the new total and asked to confirm again.

Customers see their orders under **My account → Orders**, can upload bank-transfer details there, and can
cancel an order themselves only while it is **Pending** and nothing has been paid or submitted.

### Processing orders (Owner, Manager)

Staff portal → **Orders → Customer orders**. Search by order number, name, phone or email; filter by status,
payment method, payment status and dates. Open an order to see items, stock movements, customer details,
payments and the full history.

Status steps (only these moves are allowed):

```
Pending → Confirmed → Processing → Ready for pickup  → Completed                (store pickup)
                                 → Out for delivery  → Delivered → Completed    (home delivery)
Out for delivery → Processing   (delivery failed, goods back)
Pending / Confirmed / Processing / Ready for pickup → Cancelled
```

- Bank-transfer and online orders can only be **confirmed after the payment is approved**.
- An order can only be **completed when it is paid** (record the cash first for cash orders).
- **Cancelling** asks for a reason (shown to the customer) and puts the stock back once
  (ledger entry "Order cancelled (restock)"). Delivered and completed orders can't be cancelled.
- If a cancelled order had been paid, it shows **Refund due**. After giving the money back, the **Owner**
  records the refund on the payment ("How was it refunded?").

Orders are never deleted; they are cancelled. The customer is emailed when an order is placed, changes status,
is cancelled, or a payment is approved or rejected.

### Cash (Owner, Manager, Cashier)

On a cash order, click **Record cash received** once the full amount is in hand. It can't be recorded twice.

### Verifying bank transfers (Owner, Manager)

The order list shows **Payments to verify**. Open the order, click **View slip** to see the customer's
receipt (stored privately; only the customer and order staff can open it), check your bank account, then:
- **Approve** only when the money is in the account. The order becomes paid and can be confirmed.
- **Reject** with a note explaining why. The customer sees the note and can upload new details.

### Who can do what

| | Owner | Manager | Cashier | IT Admin | Customer |
|---|---|---|---|---|---|
| View orders | ✅ | ✅ | ✅ | ❌ | own only |
| Change status, cancel | ✅ | ✅ | ❌ | ❌ | cancel own pending order |
| Approve/reject transfers | ✅ | ✅ | ❌ | ❌ | ❌ |
| Record cash | ✅ | ✅ | ✅ | ❌ | ❌ |
| Record refunds | ✅ | ❌ | ❌ | ❌ | ❌ |
| Delivery & payment settings | ✅ | ❌ | ❌ | ❌ | ❌ |

### Online payment (PayHere): developer setup

Online payment is **off** until credentials are set. Nothing is ever marked paid by the customer's browser:
only a **signed notification from PayHere** (checked with your merchant secret, amount and currency) marks
an online payment as paid, and repeated notifications are ignored.

1. Create a PayHere **sandbox** merchant account and note the Merchant ID and Merchant Secret.
   In the PayHere dashboard, add your domain (the secret is tied to it).
2. Add to `.env` (never commit it):

   ```
   PAYMENT_GATEWAY=payhere
   PAYHERE_MERCHANT_ID=your-merchant-id
   PAYHERE_MERCHANT_SECRET=your-merchant-secret
   PAYHERE_SANDBOX=True
   ```
3. Restart the server. Settings → Online payment shows **Configured** and customers can choose it.
4. PayHere must be able to reach `https://your-domain/payments/webhook/payhere/` from the internet.
   A local `127.0.0.1` server can't receive it, so payments stay "Awaiting payment" there. Test on a
   public HTTPS test server (or a tunnel) with sandbox test cards.
5. Before going live, **check the hash and notification format against PayHere's current documentation**,
   run sandbox tests end to end, then set `PAYHERE_SANDBOX=False` with your live credentials.

### Emails

In development, order emails are printed in the terminal running `runserver`. To send real emails, set the
`EMAIL_*` variables in `.env` (see `.env.example`). A failed email never affects the order.

### Payment slips

Uploaded slips (JPG, PNG, WebP or PDF, up to 5 MB, checked to be real images or PDFs) are stored in
`private_media\` (setting `PRIVATE_MEDIA_ROOT`), which is **not** served publicly and is not committed to Git.
**Back it up** together with the database. In production, keep it outside the web server's public folders.

---

## 11. Running the tests

```powershell
python manage.py test                       # everything (about 4–6 minutes)
python manage.py test apps.accounts         # accounts and permissions only
python manage.py test apps.accounts.tests.test_permissions   # one file
```

The tests use a temporary database; your `db.sqlite3` is never touched. Test files:

| File | Covers |
|---|---|
| `apps/accounts/tests/test_models.py` | User model, password hashing, unique email, primary-owner protection, capability boundaries |
| `apps/accounts/tests/test_auth.py` | Both portals, wrong portal, inactive users, sessions, throttling, sign-out, CSRF, password change/reset |
| `apps/accounts/tests/test_registration.py` | Customer sign-up, role-escalation attempts, duplicate emails, own-profile privacy |
| `apps/accounts/tests/test_permissions.py` | Every protected URL for every role, Django admin access, finance boundary |
| `apps/accounts/tests/test_staff_management.py` | Creating/editing staff, role limits, self-edit block, activation, temporary passwords |
| `apps/accounts/tests/test_api.py` | `/api/v1/accounts/me/`: no secrets, role read-only, CSRF |
| `apps/accounts/tests/test_bootstrap.py` | `bootstrap_owner` command |
| `apps/dashboard/tests.py`, `apps/core/tests.py` | Dashboards, Phase 01 pages, static files, error pages |
| `apps/accounts/tests/test_hardening.py` | Admin-login throttling, sign-in name collisions (Phase 02 review) |
| `apps/catalog/tests/test_models.py` | Seed data, category rules, slugs, SKUs, measurement types, positive prices, protected deletes, statistics |
| `apps/catalog/tests/test_views.py` | Role access to every catalogue page, category/product/variation/unit pages, search, filters, sorting, pagination |
| `apps/catalog/tests/test_images.py` | Accepted formats, resizing, metadata removal, rejected files (fake, SVG, GIF, oversized, damaged, decompression bomb) |
| `apps/catalog/tests/test_api.py` | Catalogue API permissions, validation, no DELETE, filters, image upload |
| `apps/inventory/tests/test_stock.py` | Opening stock, increases/decreases, negative-stock prevention, unit conversion, permanent ledger, concurrency safety, low-stock states |
| `apps/inventory/tests/test_purchases.py` | Draft vs received stock, receiving once only, cancellation, totals, rollback, unit validation |
| `apps/inventory/tests/test_views.py` | Role access to every inventory page, item/supplier/purchase pages, confirmation step, search, filters, pagination, dashboard counts |
| `apps/inventory/tests/test_api.py` | Inventory API permissions, read-only quantity and ledger, adjust/receive/cancel actions, validation |
| `apps/shop/tests/test_storefront.py` | What the shop lists (active, in stock, active categories), category pages, new categories appearing, product page options, search, sorting, pagination, no wholesale prices |
| `apps/orders/tests/test_checkout.py` | Placing orders: totals, delivery fees and free-delivery threshold, price snapshots, stock deduction, overselling and race conditions, double submit, changed totals, checkout pages, CSRF |
| `apps/orders/tests/test_workflow.py` | Status rules, cancellation and restock (once), refund due, no deleting orders, customer privacy, staff pages and history, role permissions, settings and delivery areas |
| `apps/payments/tests/test_payments.py` | Cash, bank transfer submit/approve/reject/resubmit, slip validation and privacy, refunds, online payment off without credentials, PayHere signing, signature/amount checks, duplicate notifications |
| `apps/shop/tests/test_cart.py` | Add/update/remove, stock limits, invalid input, stock dropping later, guest vs customer carts, merge on sign-in and registration, cart privacy, staff blocked, CSRF, safe redirects |

Tests take a while because password hashing is deliberately slow (that is what makes it secure).

---

## 12. Databases

**Development:** SQLite. The database is the file `db.sqlite3`. It is not committed to Git.
To start again from an empty database, stop the server, delete `db.sqlite3` and run `python manage.py migrate`.

**Production (later):** PostgreSQL.
1. Install PostgreSQL and create a database and user.
2. `pip install "psycopg[binary]"` and update `requirements.txt`.
3. Set `DATABASE_URL=postgres://user:password@host:5432/dbname` and `DJANGO_SETTINGS_MODULE=config.settings.production`.
4. Run `python manage.py migrate` and `python manage.py collectstatic`.
5. Run `python manage.py check --deploy` and fix anything it reports.

## 13. Git and GitHub

### First commit

Git is already initialised in this folder. Check what will be committed:

```powershell
git status
```

Make sure `.env`, `db.sqlite3` and `.venv` are **not** listed (they are ignored by `.gitignore`). Then:

```powershell
git add .
git commit -m "Phase 01 and 02: foundation, authentication and role-based access control"
```

(Nothing has been committed yet, so the first commit contains both phases. From
now on, commit at the end of each phase, or more often.)

### Push to GitHub

1. On <https://github.com/new> create a **private** repository named e.g. `leo-products`.
   Do **not** add a README, .gitignore or licence there (the project already has them).
2. Connect and push:

   ```powershell
   git branch -M main
   git remote add origin https://github.com/YOUR-USERNAME/leo-products.git
   git push -u origin main
   ```

   The first push opens a browser window to sign in to GitHub.

### Daily workflow

```powershell
git checkout -b phase-02-accounts      # work on a branch for each phase or feature
# ...make changes...
git status                              # review what changed
git add .
git commit -m "Describe what you changed"
git push -u origin phase-02-accounts
```

Then open a Pull Request on GitHub and merge it into `main` when the phase is done.

### Golden rules

- Never commit `.env`, passwords or API keys. If you do by accident, change the secret immediately: deleting the file later does not remove it from Git history.
- Run `python manage.py test` before committing.
- Commit small, meaningful steps with clear messages.

## 14. Troubleshooting

| Problem | Fix |
|---|---|
| `ImproperlyConfigured: The SECRET_KEY environment variable is required` | Create `.env` (Step 4) |
| `ModuleNotFoundError: No module named 'django'` | Activate the virtual environment |
| Port 8000 is busy | `python manage.py runserver 8080` |
| Styles look broken | Hard refresh with **Ctrl + F5** |
| VS Code uses the wrong Python | **Ctrl + Shift + P** → "Python: Select Interpreter" → `.venv` |
| Testing on your phone | `python manage.py runserver 0.0.0.0:8000`, add your PC's local IP (from `ipconfig`) to `ALLOWED_HOSTS` in `.env`, then open `http://YOUR-PC-IP:8000` on a phone on the same Wi-Fi |
| "Incorrect login details" for a correct password | Check you are on the right portal: staff use `/staff/login/`, customers `/account/login/` |
| "Too many failed attempts" | Wait 15 minutes, or restart `runserver` in development |
| Every page sends me to "Choose a new password" | Your account has a temporary password. Choose a new one to continue |
| "This form has expired" | The page was open too long or cookies are blocked. Refresh and try again |
| Lost the only owner password | Use "Forgot your password?". In development, the link appears in the `runserver` terminal |
