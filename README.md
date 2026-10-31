# Brightloop Subscription System (Flask + SQLite, Minecraft UI)
Run: double-click run.bat  (or: pip install flask && python app.py)  ->  http://127.0.0.1:5000

Logins
- Admin: admin@brightloop.com / Admin@12345  (change after first login)
- Demo customers: customer1@demo.com ... customer12@demo.com / Demo@12345

Features: roles (admin/staff/customer portal), password rules + reset link, products+variants, plans (pause/close/renew flags),
quotation templates, subscription lifecycle + editable lines, auto invoices (no double billing), taxes (admin rules), discounts,
payments, send invoice, dashboard with date filters + revenue chart, CSRF protection, pagination, edit/delete for admin.
Email: set SMTP_HOST, SMTP_USER, SMTP_PASS (else mails print in the console). Set DEBUG=1 only for development.
