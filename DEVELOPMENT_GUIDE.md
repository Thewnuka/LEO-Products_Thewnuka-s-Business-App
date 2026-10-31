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

A product is **listed** when all of these are true. If your product doesn't appear, check them in order
(the product's page in the staff portal has an **Online shop** panel that tells you which one is missing):

1. **Catalogue → Products:** the product's status is **Active**.
2. Its **main category** (and subcategory, if any) is **active**.
3. At least one **variation** is active.

Customers can **buy** a size only when, in addition:

4. That variation has **stock tracking**: **Inventory → Track new item → Finished product**
   (or "start tracking stock" in the product's Online shop panel).
5. Its stock is **at least 1 packet**.

A listed product with nothing in stock shows an **"Out of stock"** badge and cannot be added to the cart
(Phase 11; before that it was hidden completely). Sizes that are out of stock or not tracked appear on the
product page greyed out and not selectable. Customers only ever see the **selling price**, never the wholesale price.
At 5 or fewer in stock the shop shows "Only N left" (`SHOP_LOW_STOCK_THRESHOLD` in settings).

> Quick test: create a product, add a 200g variation with a price and activate the product: it appears
> in the shop as "Out of stock". Track the 200g variation in Inventory with an opening stock of e.g. 10:
> customers can now add it to the cart.

### Categories in the shop

LEO TEA (subcategories **Tea Bags** and **Tea Packets**) and **LEO SWEETS** are separate main categories; their
products are never mixed. Put each tea product in LEO TEA › Tea Bags or Tea Packets and name it by its variety
(e.g. "Black Tea", "Ginger Tea Bags"): the **Black / Ginger / Cinnamon** buttons on LEO TEA pages search product
names and descriptions. The list of variety buttons is `VARIETY_FILTERS` in `apps/shop/services.py`.

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

What the customer sees: **Pay now** on the order page opens PayHere's secure page. If they **cancel** there, they
come back to the order with "You cancelled the online payment… use Pay now whenever you're ready" (logged in the
payment's history; nothing charged). If PayHere reports the payment **failed or cancelled**, the order stays
unpaid and **Pay now** can be used again (a new payment record is created). Successful payments are shown as paid
only after PayHere's verified notification arrives.

### Emails

In development, order emails are printed in the terminal running `runserver`. To send real emails, set the
`EMAIL_*` variables in `.env` (see `.env.example`). A failed email never affects the order.

### Payment slips

Uploaded slips (JPG, PNG, WebP or PDF, up to 5 MB, checked to be real images or PDFs) are stored in
`private_media\` (setting `PRIVATE_MEDIA_ROOT`), which is **not** served publicly and is not committed to Git.
**Back it up** together with the database. In production, keep it outside the web server's public folders.

---

## 11. Point of sale (in-store sales)

Staff portal → **Point of sale**. The **Till** is for Cashiers (and the Owner). Managers don't sell; they review
sales and shifts, approve discounts and bank transfers, and handle refunds.

### First-time setup (Owner)

Staff portal → **Point of sale → POS settings** (<http://127.0.0.1:8000/staff/pos/settings/>):
- **Receipt:** shop address, phone and a short footer message. Only enter real details; empty fields are left off.
  The receipt always shows the official logo, name and tagline. No tax or registration numbers are printed.
- **Discount limits:** the largest discount (as a % of the sale) a Cashier may give alone (default 5%) and that a
  Manager may give or approve (default 20%). The Owner has no limit.

Products appear on the till automatically when they can be sold online too: active product and category, active
size, tracked in Inventory, at least 1 in stock (§9).

### A cashier's day

1. **Open shift:** Till → count the cash in the drawer → **Open shift**. You can't sell without an open shift,
   and you can only have one open at a time.
2. **Sell:** tap products (or type/scan the SKU and press Enter; a barcode scanner that types the SKU works),
   adjust quantities, then:
   - **Cash:** enter the cash received (or tap **Exact**/a rounded amount). The change is shown. **Complete sale**.
   - **Bank transfer:** enter the customer's transfer reference. The sale is saved as **awaiting verification**;
     it is not paid until a Manager or the Owner confirms the money arrived (see below).
   - **Discount (optional):** % or LKR, with a reason. Above your limit, a Manager or the Owner types their
     user name and password on the till to approve it. Wrong passwords count towards the normal sign-in lock
     (5 failures lock that person's approvals and sign-ins from this computer for 15 minutes).
3. The **receipt** opens and the print dialog appears (80 mm till printer layout; **A4 size** is one click away).
   Press **New sale** for the next customer.
4. **Cash in / cash out:** My shift → record float added or cash removed (e.g. bank deposit) with a reason.
   You can't take out more than the drawer should hold.
5. **Close shift:** My shift → **Close shift** → count the drawer → enter the total. The system shows the expected
   amount and saves the difference; if they differ, a note is required. **A closed shift can't be changed.**

Expected cash = opening cash + cash sales + cash added − cash taken out − cash refunds.
Bank-transfer sales never count towards the drawer.

Each sale is saved in one database transaction: prices come from the database, stock is checked and deducted
(ledger entry "Sale (order)"), and the payment is recorded. Clicking **Complete sale** twice, or a network retry,
never records the sale twice.

### Managers and the Owner

- **POS sales** (<http://127.0.0.1:8000/staff/pos/sales/>): today's totals, search by receipt number, filter by
  date, cashier, payment method and status. Cashiers see only their own sales.
- **Verify a till bank transfer:** open the sale (status "Transfer to check") → **Approve** when the money is in the
  account (the sale becomes Completed and Paid) or **Reject** with a note. A rejected sale stays unpaid: collect
  payment another way by voiding it and selling again.
- **Void / refund:** open the sale → **Void / refund this sale** → reason (and, for cash, the open till the money is
  paid from). Stock goes back once, the payment is marked refunded, and the cash refund is recorded in that till's
  drawer. The sale stays in the history marked "Voided/Refunded". Cashiers can't refund.
- **Cashier shifts:** see every shift's expected cash, count and difference; a Manager or the Owner can close a shift
  a cashier forgot to close.
- **Reprint receipts:** sale page → **Reprint**. Every reprint is logged (who and when) and printed with "COPY".
  Cashiers may reprint their own sales.

### Who can do what

| | Owner | Manager | Cashier | IT Admin | Customer |
|---|---|---|---|---|---|
| Use the till, own shift, cash in/out | ✅ | ❌ | ✅ | ❌ | ❌ |
| View sales and receipts | all | all | own | ❌ | ❌ |
| Discount without approval | any | up to manager limit | up to cashier limit | ❌ | ❌ |
| Approve discounts at the till | ✅ | ✅ (up to manager limit) | ❌ | ❌ | ❌ |
| Verify till bank transfers | ✅ | ✅ | ❌ | ❌ | ❌ |
| Void / refund sales | ✅ | ✅ | ❌ | ❌ | ❌ |
| Review / close any shift | ✅ | ✅ | own only | ❌ | ❌ |
| POS settings | ✅ | ❌ | ❌ | ❌ | ❌ |

The dashboards of the Owner, Manager and Cashier show today's POS sales, number of transactions, cash and bank-transfer
sales, open shifts and what their drawers should hold (cashiers see their own figures only).

### Printing tips

Use the browser's print dialog: choose the receipt printer, paper 80 mm, margins "None", and turn off headers and
footers. For A4, choose **A4 size** on the receipt page first.

---

## 12. Finance and reports

Staff portal → **Finance & reports**. The Owner sees everything. Managers see the operational reports (without
cost and profit columns) and can record expenses. Cashiers, IT Admins and customers have no finance access.

### How the figures are worked out (no double counting)

| Figure | Comes from | Rule |
|---|---|---|
| Revenue | Orders (online and POS) | Only **paid** sales that aren't cancelled, dated by the order date. Product sales − discounts + delivery fees = order total. Unpaid, cancelled and refunded sales are **not** revenue. |
| Cost of goods sold (COGS) | The stock cost copied onto each sold line **at the moment of sale** | Sales made before a cost was known have no cost; they are shown separately ("sales without cost") and are never filled in afterwards. |
| Operating expenses | Expenses | Voided entries don't count. **Stock purchases are not expenses**: they become cost of goods when the goods are sold. |
| Gross profit | Revenue − COGS | |
| Net operating profit | Gross profit − operating expenses | Before tax; tax is not calculated. |
| Collections / cash flow | Payments received, refunds paid, supplier payments, expenses | Money that actually moved, by its date. Cash moved into or out of POS drawers is an internal transfer and isn't shown. |

### Stock costs (Owner): set these first

Profit can only be correct when stock items have a cost.
- **Bought goods:** receiving a purchase updates the item's **weighted average cost** automatically
  (`(stock before × old cost + purchase amount) ÷ (stock before + quantity received)`). If the item had no cost yet,
  the purchase cost becomes its cost.
- **Products made in-house** (e.g. packed tea): Finance & reports → **Stock costs** → **Set cost**, with where the
  figure comes from (e.g. your costing sheet). The page lists items with **missing cost**.
- A new cost applies to sales **from then on**; past sales keep the cost they were sold at. Every change is logged
  in the item's cost history.

### Expenses (Owner, Manager)

Finance & reports → **Expenses → Record expense**: date, category, amount, how it was paid (cash, bank transfer,
card, cheque, other), description, optional payee, bill number and receipt (JPG, PNG, WebP or PDF up to 5 MB,
stored privately like payment slips). Saved expenses can't be edited; the **Owner voids** a mistake (with a reason)
and it is entered again. Categories (seeded: Transport & delivery, Utilities, Rent, Salaries & wages, …) are managed
by the Owner and can be made inactive but not deleted.

### Suppliers: balances and payments (Owner)

Finance & reports → **Supplier balances** shows, for each supplier, received purchases, payments and what is owed.
**Pay a supplier** records a payment (optionally against one purchase). A payment can't be more than the supplier is
owed (or what is left on that purchase); advance payments aren't recorded. Each supplier has a **statement** with a
running balance, also linked from the supplier and purchase pages in Inventory. Draft purchases are not owed.

### Reports

Finance & reports → **Reports**. Each has date filters (today, this week, this month, last month, this year, last
year or custom dates), a chart where useful, **CSV** and **Excel (.xlsx)** export and an **A4 print** layout with the
logo.

| Report | Who | Shows |
|---|---|---|
| Sales | Owner, Manager | Revenue by day, month or year; online vs in store; discounts; delivery fees |
| Product sales / Category sales | Owner, Manager | Quantities and sales; cost, gross profit and sales without cost for the Owner |
| Cashier sales | Owner, Manager | POS sales per cashier: cash, transfers, transfers to check, discounts, voids |
| Purchases | Owner, Manager | Received purchases; paid and still to pay for the Owner |
| Stock valuation | Owner, Manager | Current stock × average cost; items without a cost are listed and left out of the total |
| Expenses | Owner, Manager | By category and payment method |
| Profit & loss | Owner | Revenue, COGS, gross profit, expenses by category, net operating profit, with warnings |
| Cash flow | Owner | Money in and out, cash vs bank/online |
| Supplier balances / Customer balances | Owner | What is owed to suppliers; unpaid customer orders and refunds owed |

The **Finance overview** (Owner) shows the period's sales, revenue, COGS, gross profit, expenses, net operating profit,
stock purchases, cash and bank collections, and a 12-month chart.

### Audit trail

Finance & reports → **Finance audit log** (Owner): every expense, supplier payment, void, stock cost change, category
change and report export, with who and when. Financial records, cost history and the log can't be deleted.

### Getting correct figures: checklist

1. Set a cost for every product (Stock costs → Missing cost).
2. Record stock bought from suppliers as **purchases** (Inventory), not expenses, and receive them.
3. Record every operating cost as an **expense**, and supplier payments under Supplier balances.
4. Confirm payments (cash received, bank transfers approved) so sales count as revenue.

---

## 13. Notifications, alerts and other tools

### Notifications (everyone who signs in)

The **bell** in the top bar (staff) or next to the cart (customers) shows how many notifications are unread and the
five newest. **See all notifications** opens the full history with **All / Unread** and category filters, **Mark read**,
**Mark unread** and **Mark all read**. Opening a notification marks it read and goes to the related page.

Who is told about what (chosen by role; customers only ever hear about their own orders and reviews):

| Event | Notified |
|---|---|
| New online order; order cancelled by the customer; online payment confirmed | Owner, Manager |
| Bank transfer waiting for verification (online or at the till) | Owner, Manager |
| Stock drops to its reorder level, or runs out (once, when it crosses the line) | Owner, Manager |
| Purchase received; expense recorded by someone else; till sale voided | Owner |
| POS shift closed short or over | Owner, Manager |
| New customer review to check | Owner, Manager |
| Order placed, status changes, cancelled; payment received or transfer rejected | The order's customer |
| Review published / not published | The customer who wrote it |

Each event notifies each person **once** (a database rule), even if the action is repeated or retried.

**Preferences:** bell page → **Preferences** (or the user menu). Staff and customers can switch off the categories they
don't want. Customers can also switch off order emails; their in-app notifications continue.

### Business alerts (staff)

Staff portal → **Business alerts** (also "Needs attention" on every dashboard) shows live counts for the user's role:
out-of-stock and low-stock items, bank transfers to verify, orders waiting to be confirmed (flagged when older than the
set number of hours), orders unpaid for several days, refunds owed, POS shifts left open (a cashier sees their own),
products without a cost (Owner) and reviews to check.

**Alert settings** (Owner, Staff portal → Administration): hours before a pending order is flagged, days before an
unpaid order is flagged, hours before an open shift is flagged, and whether reviews need approval.

Optional daily reminder: `python manage.py send_business_alerts` turns the current alerts into notifications, at most
once per alert, person and day. Schedule it with Windows Task Scheduler if wanted (e.g. 8:00 every morning).

### Wishlist and reviews (customers)

- **Save to wishlist** on a product page; **My account → Wishlist** lists saved products.
- **Reviews:** only customers who **bought and paid for** a product can review it (one review each, editable). The
  public page shows their first name and last initial and "Verified purchase", never their email.
- New and edited reviews wait for approval (unless the Owner turned approval off). **Customer reviews** in the staff
  sidebar (Owner, Manager): **Publish** or **Don't publish** with a reason, which is sent to the customer.

### Search (staff)

Staff portal → **Search**: one box for order and receipt numbers, customer names/phones/emails, payment and bank
references, products and SKUs, stock items, suppliers, purchases, expenses and staff accounts. It only searches the
areas the user's role can open (a cashier finds their own till sales, not other cashiers').

### Home page images (Owner)

Staff portal → **Administration → Home page images** (<http://127.0.0.1:8000/staff/home-images/>). Only the Owner
can open it.

- **Background photo:** choose a photo, pick which part to keep in view, **Save background**. Wide (landscape)
  photos with a calm area on the left work best; the dark green shading is added automatically so the text stays
  readable. **Remove uploaded background** brings back the sample.
- **Box 1, Box 2, Box 3** (the slanted cards on the right): **Add image** with a short description (read out by
  screen readers). Upright (portrait) photos fit best. For each uploaded image you can change the description and
  **Position** (lower first), **Replace photo**, or **Remove** it. Up to 8 images per box.
- A box with no uploaded images shows its sample images (`static/images/hero/`); your first upload replaces them.
- Photos: JPG, PNG or WebP, up to 5 MB; they are checked, resized and stored under `media/hero/`. A preview
  appears as soon as you choose a file. The home page changes as soon as you save.
- The order the boxes change in (Box 1 → Box 3 → Box 2) and the time between changes (3.5 s) are
  `CHANGE_ORDER` and `INTERVAL_SECONDS` in `apps/core/hero.py`.

### Activity history (Owner, Manager)

Staff portal → **Activity history**: one timeline of order status changes, payment events, stock movements, POS shifts,
cash movements and reprints, and review decisions, read from the records each area already keeps. The Owner also sees
finance entries (expenses, voids, cost changes, exports) and account changes. Filter by dates, area, person and text.

---

## 14. Running the tests

```powershell
python manage.py test                       # everything (about 8–10 minutes)
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
| `apps/pos/tests/test_services.py` | Shifts (one open per cashier, expected cash, closing count and difference, closed shifts locked), cash in/out, cash and bank-transfer sales, change, stock deducted once, duplicate submissions, race for the last items, discounts and approval limits, refunds/voids, today's figures |
| `apps/pos/tests/test_views.py` | Role access to every POS page, till product list, checkout endpoint (errors, double submit, CSRF, manager approval and throttling), receipts and logged reprints, sales history and filters, transfer verification, refunds, shift pages, dashboards, POS settings |
| `apps/finance/tests/test_finance.py` | Weighted average cost and unit conversion, cost copied at sale (never back-filled), Owner-set costs, expenses (validation, receipts, one-time tokens, void once, no deleting), supplier payments and balances, every headline figure counted once (revenue, discounts, delivery, COGS, expenses, collections, refunds, unpaid and cancelled orders), profit & loss, cash flow, all reports, date periods |
| `apps/finance/tests/test_views.py` | Role access to every finance page, hidden cost/profit columns for Managers, every report as page/print/CSV/Excel, export logging, formula-injection protection, expense and supplier payment pages (double submit, errors, voids), stock cost page |
| `apps/notifications/tests/test_notifications.py` | Who is notified for each event (and who isn't), no duplicates, mutes and customer email switch, unsafe links dropped, stock crossing alerts, own-inbox privacy, read/unread, bell, preferences, business alerts by role, alert settings, daily alert command |
| `apps/shop/tests/test_reviews.py` | Wishlist (customers only), reviews only after a paid purchase, moderation, notifications, one review per customer, edits re-checked, auto-publish setting, no emails shown |
| `apps/dashboard/tests_phase09.py` | Staff search limited by role, activity history by role and filters |
| `apps/core/tests_hero.py` | Home page hero: sample fallback, cards inside the hero, order 1→3→2 and 3.5 s, uploads (valid, wrong type, fake image, too large), replace/remove delete old files, background, Owner-only access |
| `apps/core/tests_phase11.py`, `apps/shop/tests/test_categories.py`, `apps/accounts/tests/test_password_toggle.py` | Phase 11: page width and staff sidebar hooks; LEO TEA › Tea Bags/Tea Packets and LEO SWEETS, variety filters, the category data migration (nothing lost or duplicated, safe twice); password show/hide on every password field (out-of-stock listing and PayHere cancel/codes are in the shop and payments tests) |
| `apps/core/tests_phase10.py` | Security headers (CSP, Permissions-Policy, no-store for signed-in pages), no inline scripts, PDF slips downloaded, PWA manifest/service worker/offline page, every staff/admin/API URL refused to customers and visitors, IT admin limits, deploy checks, production settings and the local-only mode guard, a link crawl for every role (no errors, no broken links or missing static files) |
| `apps/shop/tests/test_cart.py` | Add/update/remove, stock limits, invalid input, stock dropping later, guest vs customer carts, merge on sign-in and registration, cart privacy, staff blocked, CSRF, safe redirects |

Tests take a while because password hashing is deliberately slow (that is what makes it secure).

---

## 15. Databases

**Development:** SQLite. The database is the file `db.sqlite3`. It is not committed to Git.
To start again from an empty database, stop the server, delete `db.sqlite3` and run `python manage.py migrate`.

**Production:** PostgreSQL (see §16). The same migrations create the same tables; nothing in the code is
SQLite-specific. Set `DATABASE_URL=postgres://USER:PASSWORD@HOST:5432/DATABASE`.

**Moving existing data from SQLite to PostgreSQL** (only if you already have real data in `db.sqlite3`):

```powershell
# 1. With the OLD (SQLite) settings: export everything except tables Django rebuilds itself
python manage.py dumpdata --natural-foreign --natural-primary -e contenttypes -e auth.permission -e sessions --indent 2 -o leo-data.json
# 2. Point .env at PostgreSQL (DATABASE_URL=postgres://...), then:
python manage.py migrate
python manage.py loaddata leo-data.json
```

Copy the `media\` and `private_media\` folders too. Keep `leo-data.json` private (it contains customer data) and
delete it when done.

**Backups (both databases):** back up the database **and** the `media\` and `private_media\` folders together.
PostgreSQL: `pg_dump -Fc leo_products > leo-YYYYMMDD.dump`; restore with `pg_restore -d leo_products leo-YYYYMMDD.dump`.
SQLite: stop the server and copy `db.sqlite3`.

---

## 16. Going live (production)

Production uses `config.settings.production`: `DEBUG` is always off, HTTPS is enforced, cookies are
secure-only, static files are served by WhiteNoise, and `check --deploy` must be clean. Nothing below contains
real hosts or passwords: use your own. Example files are in `deploy\` (see `deploy\README.md`).

### Option A: Linux server (recommended for a public website)

1. A server with Python 3.12, PostgreSQL and Nginx, and a domain name pointing to it.
2. PostgreSQL: create a database and user, e.g. `CREATE USER leo WITH PASSWORD '...'; CREATE DATABASE leo_products OWNER leo;`
3. Copy the project to e.g. `/srv/leo-products`, then:

   ```bash
   python3.12 -m venv .venv
   .venv/bin/pip install -r requirements-production.txt
   cp deploy/env.production.example .env   # fill in every value, then: chmod 600 .env
   .venv/bin/python manage.py check --deploy
   .venv/bin/python manage.py migrate
   .venv/bin/python manage.py collectstatic --noinput
   .venv/bin/python manage.py bootstrap_owner     # first time only (§5)
   ```
4. Gunicorn as a service: `deploy/linux/gunicorn.service.example`. Nginx with HTTPS: `deploy/linux/nginx.conf.example`
   (certificates e.g. with certbot). Set `USE_X_FORWARDED_PROTO=True` behind Nginx.
5. Open the site, sign in as the Owner, and work through the checklist below.

### Option B: one Windows PC in the shop (no public website)

For using the system only inside the shop (till, stock, finance), on the PC that runs it or through the desktop app.

1. Install Python 3.12 and PostgreSQL for Windows (or keep SQLite for a single PC, see the note below).
2. In the project folder:

   ```powershell
   .\.venv\Scripts\pip install -r requirements-production.txt
   Copy-Item deploy\env.production.example .env    # then edit .env:
   ```
   `ALLOWED_HOSTS=127.0.0.1,localhost`, `LOCAL_HTTP_ONLY=True`, `SERVE_MEDIA=True`, `SECURE_SSL_REDIRECT=False`,
   `USE_X_FORWARDED_PROTO=False`, plus `SECRET_KEY`, `DATABASE_URL`, `ADMIN_URL`, `PRIVATE_MEDIA_ROOT`.
3. Start it: `powershell -ExecutionPolicy Bypass -File deploy\windows\start-server.ps1` (runs the checks, migrations and
   `collectstatic`, then serves on `http://127.0.0.1:8000`). To start it automatically, create a Windows Task Scheduler
   task "At log on" running that command.

`LOCAL_HTTP_ONLY=True` turns off HTTPS-only cookies because there is no HTTPS on `127.0.0.1`. It is refused unless
`ALLOWED_HOSTS` contains only `127.0.0.1`/`localhost`, so it can't accidentally be used on a public server.
SQLite works for one PC (`DATABASE_URL=sqlite:///C:/LEO/leo.sqlite3`), but `check --deploy` will warn; PostgreSQL is
safer for multiple users at once.

### Go-live checklist

- [ ] `python manage.py check --deploy` shows no errors (warnings only for things you chose deliberately)
- [ ] New `SECRET_KEY`; `.env` is not readable by other users and is not in Git
- [ ] `ADMIN_URL` changed from `admin/`; the Owner's password is strong and changed after `bootstrap_owner`
- [ ] Email sends (try "Forgot password"); order emails arrive
- [ ] Delivery & payment settings, POS settings (receipt address/phone), stock costs and alert settings filled in (§10–§13)
- [ ] Online payment left off, or PayHere tested in sandbox first (§10)
- [ ] Backups of the database and `media\` + `private_media\` scheduled and a restore tested
- [ ] Staff accounts created with the right roles; test sign-in for each role

### Updating to a new version

```bash
git pull
.venv/bin/pip install -r requirements-production.txt
.venv/bin/python manage.py migrate
.venv/bin/python manage.py collectstatic --noinput
sudo systemctl restart leo-products        # Windows: stop and start start-server.ps1
```

Back up first. Migrations only add or change tables; they never delete business data.

---

## 17. Install as an app (phones, tablets, computers)

The website can be installed like an app (a "PWA") from the browser, with the LEO PRODUCTS icon and its own window.
It needs **HTTPS** (or `http://127.0.0.1` on the same PC).

* **Android (Chrome):** open the site → menu ⋮ → **Install app** / **Add to Home screen**.
* **iPhone/iPad (Safari):** open the site → Share → **Add to Home Screen**.
* **Windows/Mac (Chrome or Edge):** the install icon in the address bar, or menu → **Install LEO PRODUCTS**.

What it stores on the device: **only** the site's design files (CSS, JavaScript, icons, fonts) and a small "You're
offline" page, so it opens quickly. **Pages, orders, payments, reports and customer data are never stored**; they always
come from the server, and pages for signed-in users are sent with "do not store" instructions. Without a connection the
app shows the offline page. After an update, the app picks up the new files automatically on the next visit.

Files: `apps/core/pwa.py` (manifest, service worker, offline page), `templates/pwa/`, `static/js/pwa.js`,
`static/icons/` (made from the official logo).

---

## 18. Windows desktop app

`desktop\` contains a Tauri project that opens the LEO PRODUCTS server in its own window (Start menu icon, no browser
tabs). It uses the same server and database; the desktop app stores no business data. See **`desktop\README.md`** for the
server address setting, the build tools (Rust, C++ Build Tools, Node.js) and the build command. **The installer has not
been built yet** (the development PC had no Rust toolchain). If the server is hosted, the desktop app needs internet access.

An alternative that needs no build: install the site as an app from Edge or Chrome (§17); it also gets its own window
and Start menu entry.

---

## 19. Git and GitHub

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

## 20. Troubleshooting

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
