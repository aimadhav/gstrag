alter table profiles enable row level security;
alter table documents enable row level security;
alter table chunks enable row level security;

create or replace function public.current_profile_role()
returns text language sql stable security definer set search_path = public as $$
  select role from public.profiles where id = auth.uid();
$$;

create policy "users read own profile" on profiles for select using (id = auth.uid());
create policy "admins manage profiles" on profiles for all using (public.current_profile_role() = 'admin');
create policy "active documents readable" on documents for select using (status = 'active' and (source_type <> 'private_book' or public.current_profile_role() in ('admin','pro')));
create policy "admins manage documents" on documents for all using (public.current_profile_role() = 'admin');
create policy "permitted chunks readable" on chunks for select using (
  exists (select 1 from documents d where d.id = document_id and d.status = 'active' and (d.source_type <> 'private_book' or public.current_profile_role() in ('admin','pro')))
);
create policy "admins manage chunks" on chunks for all using (public.current_profile_role() = 'admin');
