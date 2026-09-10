# Supabase setup

1. Create a Supabase project.
2. In Authentication → Providers, enable:
   - Email/password
   - Google OAuth (add the Google client ID/secret and Supabase callback URL)
3. Run `sql/schema.sql` in the SQL editor.
4. Run `sql/rls.sql`.
5. Create the first profile manually using the authenticated user's UUID and set its role to `admin`.
6. Copy the project URL and public anon key into the frontend environment. Keep the service-role key backend-only.

Roles are stored in `profiles`. The first admin assigns `plus`, `pro`, or `admin` through the admin interface. The client may display a role, but backend authorization remains authoritative.

Required frontend variables:

```text
NEXT_PUBLIC_SUPABASE_URL=
NEXT_PUBLIC_SUPABASE_ANON_KEY=
```
