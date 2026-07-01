# carthage-pos

Enterprise-grade supermarket POS terminal engine for inventory management and sales tracking.

## Features

- Terminal-based cashier login and checkout flow
- SQLite inventory, sales, and sale item storage
- bcrypt password hashing for POS users
- Database-backed admin, manager, and cashier authorization
- Cashier-aware sales records
- Refund-aware sales, payment, product, and inventory reports
- Foreign-key enforcement for database integrity
- Stock validation before cart add and checkout commit
- Unit tests backed by isolated temporary databases

## First-run setup

Create at least one POS user by setting an environment variable before the first login:

```powershell
$env:CARTHAGE_POS_ADMIN_PASSWORD="choose-a-strong-password"
python main.py
```

Optional cashier account:

```powershell
$env:CARTHAGE_POS_CASHIER_PASSWORD="choose-a-strong-password"
python main.py
```

The application stores password hashes in the SQLite database. Do not commit `.env` files, runtime databases, or local IDE settings.

Only the first administrator can be created through the bootstrap environment variable. After bootstrap, user management requires an active administrator session. Inventory changes and returns require an administrator or manager; cashier checkout always uses the catalog price.

## Run tests

```powershell
python -m unittest discover -s tests
```
