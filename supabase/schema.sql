-- Rode isto no SQL Editor do projeto Supabase (uma única vez).

create table if not exists cargas (
  id text primary key,                 -- mesmo id estável já usado hoje (sha1(cd|data|forn|carga)[:12])
  cd text not null,
  data date not null,
  dpto text,
  fornecedor text not null,
  carga text not null,
  status text not null default 'pendente'
    check (status in ('pendente','recebido','nao_compareceu','reagendado')),
  status_por text,
  status_em timestamptz,
  atualizado_em timestamptz not null default now()  -- tocado pelo script de sync a cada rodada
);

create table if not exists dias_revisao (
  chave text primary key,              -- "<CD>|<data-iso>", ex: "GO|2026-08-01"
  cd text not null,
  data date not null,
  revisado boolean not null default false,
  revisado_por text,
  revisado_em timestamptz
);

alter table cargas enable row level security;
alter table dias_revisao enable row level security;
-- Sem políticas: só a chave service_role (que ignora RLS) acessa essas tabelas.
-- Nem a chave "anon" nem o navegador conseguem ler/escrever nada aqui.
