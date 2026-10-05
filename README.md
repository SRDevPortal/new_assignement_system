# New Assignement System

Session-based CRM Lead assignment system for Frappe CRM.

The app keeps `CRM Lead.lead_owner` as the source of truth and syncs helper
records such as ToDo and DocShare through a central assignment service.

Assignment rules contain their own user pool. A user is eligible only when the
user account is enabled and an active, non-expired Frappe session exists.

## Customer number privacy

When Customer Number Privacy is enabled, the assignment system keeps original
CRM Lead values available only for internal rule matching. Browser responses are
projected for restricted users. Queue errors, audit text, CRM Lead assignment
status text, and exception traces are sanitized before storage. Assignment
metadata snapshots deliberately exclude mobile_no while preserving operational
IDs and timestamps.
