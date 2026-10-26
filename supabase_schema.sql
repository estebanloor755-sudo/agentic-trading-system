-- ==============================================================================
-- SCHEMA SUPABASE: TABLA EN TIEMPO REAL PARA EL SISTEMA CUANTITATIVO NQ (MT5)
-- Pega este script en el "SQL Editor" de tu proyecto en Supabase y haz clic en RUN.
-- ==============================================================================

-- 1. Crear la tabla de snapshots cuantitativos
create table if not exists public.nq_snapshots (
    id text primary key default 'latest',
    spot numeric not null,
    symbol text default 'US100-DEC26',
    timestamp_ny text not null,
    session_status text not null,
    source_feed text not null,
    elapsed_sec numeric,
    
    -- Fechas y rango histórico cargado
    data_start text,
    data_end text,
    data_range text,

    -- Objetos estructurados JSONB con las 4 secciones
    kpis jsonb not null default '{}'::jsonb,
    decisions jsonb not null default '{}'::jsonb,
    cone_table jsonb not null default '[]'::jsonb,
    tail_table jsonb not null default '[]'::jsonb,
    gex_table jsonb not null default '[]'::jsonb,
    gex_summary jsonb not null default '[]'::jsonb,
    log_anom_table jsonb not null default '[]'::jsonb,
    micro_table jsonb not null default '[]'::jsonb,
    exec_matrix jsonb not null default '[]'::jsonb,
    
    -- Datos de series para gráficos dinámicos en Vercel
    chart_series jsonb not null default '{}'::jsonb,
    
    updated_at timestamptz not null default now()
);

-- Asegurar columnas si la tabla ya existía previamente
alter table public.nq_snapshots add column if not exists data_start text;
alter table public.nq_snapshots add column if not exists data_end text;
alter table public.nq_snapshots add column if not exists data_range text;

-- 2. Habilitar Row Level Security (RLS)
alter table public.nq_snapshots enable row level security;

-- 3. Políticas de acceso:
-- Permitir lectura pública (para que el frontend en Vercel pueda leer sin login)
drop policy if exists "Permitir lectura publica" on public.nq_snapshots;
create policy "Permitir lectura publica"
    on public.nq_snapshots
    for select
    using (true);

-- Permitir inserción/actualización desde el publicador de Python con la API key anon/service
drop policy if exists "Permitir escritura anonima y autenticada" on public.nq_snapshots;
create policy "Permitir escritura anonima y autenticada"
    on public.nq_snapshots
    for all
    using (true)
    with check (true);

-- 4. Otorgar permisos al rol anon y authenticated de Supabase
grant all on public.nq_snapshots to anon, authenticated, service_role;

-- 5. Habilitar Supabase Realtime de forma segura (sin error si ya está agregada)
do $$
begin
  if not exists (
    select 1 from pg_publication_tables 
    where pubname = 'supabase_realtime' 
      and schemaname = 'public' 
      and tablename = 'nq_snapshots'
  ) then
    alter publication supabase_realtime add table public.nq_snapshots;
  end if;
end $$;
