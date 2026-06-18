# New Assignement System

Session-based CRM Lead assignment system for Frappe CRM.

The app keeps `CRM Lead.lead_owner` as the source of truth and syncs helper
records such as ToDo and DocShare through a central assignment service.

Assignment rules contain their own user pool. A user is eligible only when the
user account is enabled and an active, non-expired Frappe session exists.
