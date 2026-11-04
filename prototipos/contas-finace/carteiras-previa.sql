-- Armazenamento da prévia. As tabelas do app publicado não são usadas aqui.
create table public.finace_previa_carteiras (
    owner_id uuid primary key default auth.uid() references auth.users(id) on delete cascade,
    prefs jsonb not null check (
        jsonb_typeof(prefs) = 'object'
        and coalesce(prefs->>'snapshot', '') = '2'
        and coalesce(prefs->>'revision', '') ~ '^[0-9a-f]{8}(-[0-9a-f]{4}){3}-[0-9a-f]{12}$'
        and octet_length(prefs::text) <= 20000000
    )
);

create table public.finace_previa_versoes (
    id uuid primary key default gen_random_uuid(),
    owner_id uuid not null references public.finace_previa_carteiras(owner_id) on delete cascade,
    created_at timestamptz not null default clock_timestamp(),
    prefs jsonb not null
);

create index finace_previa_versoes_owner_created
    on public.finace_previa_versoes (owner_id, created_at desc, id desc);

alter table public.finace_previa_carteiras enable row level security;
alter table public.finace_previa_versoes enable row level security;

revoke all on public.finace_previa_carteiras, public.finace_previa_versoes
    from public, anon, authenticated;
grant select, insert (prefs), update (prefs) on public.finace_previa_carteiras to authenticated;
grant select on public.finace_previa_versoes to authenticated;

create policy finace_previa_carteira_select on public.finace_previa_carteiras
    for select to authenticated using ((select auth.uid()) = owner_id);
create policy finace_previa_carteira_insert on public.finace_previa_carteiras
    for insert to authenticated with check ((select auth.uid()) = owner_id);
create policy finace_previa_carteira_update on public.finace_previa_carteiras
    for update to authenticated using ((select auth.uid()) = owner_id)
    with check ((select auth.uid()) = owner_id);

create policy finace_previa_versao_select on public.finace_previa_versoes
    for select to authenticated using ((select auth.uid()) = owner_id);
create schema finace_previa_interno;
revoke all on schema finace_previa_interno from public, anon, authenticated;

create function finace_previa_interno.guardar_versao()
returns trigger
language plpgsql
security definer
set search_path = ''
as $$
begin
    -- Só uma alteração feita pelo próprio usuário pode gerar a cópia privada.
    if auth.uid() is distinct from old.owner_id then
        raise insufficient_privilege;
    end if;
    insert into public.finace_previa_versoes (owner_id, prefs)
        values (old.owner_id, old.prefs);
    delete from public.finace_previa_versoes as versao
    where versao.owner_id = old.owner_id
      and versao.id in (
          select anterior.id from public.finace_previa_versoes as anterior
          where anterior.owner_id = old.owner_id
          order by anterior.created_at desc, anterior.id desc
          offset 20
      );
    return new;
end;
$$;

revoke all on function finace_previa_interno.guardar_versao() from public, anon, authenticated;
create trigger finace_previa_guardar_versao
    after update of prefs on public.finace_previa_carteiras
    for each row when (old.prefs is distinct from new.prefs)
    execute function finace_previa_interno.guardar_versao();
