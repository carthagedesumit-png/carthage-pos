# carthage-pos

Enterprise-grade supermarket POS terminal engine for inventory management and sales tracking.

## Features

- Terminal-based cashier login and checkout flow
- SQLite inventory, sales, and sale item storage
- PBKDF2 password hashing for POS users
- Cashier-aware sales records
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

## Run tests

```powershell
python -m unittest discover -s tests
```