-- PMG Analyst Arena - Supabase Schema
-- Paste this into Supabase SQL Editor on first setup.
-- Safe to re-run: uses CREATE TABLE IF NOT EXISTS and DROP/CREATE for policies.

-- ============================================================
-- competitions: one row per game session
-- ============================================================
create table if not exists competitions (
    id uuid primary key default gen_random_uuid(),
    room_code text unique not null,
    host_name text not null,
    status text not null default 'lobby',  -- lobby | active | finished
    config jsonb not null default '{}'::jsonb,
    current_round int not null default 0,
    created_at timestamptz not null default now(),
    started_at timestamptz,
    finished_at timestamptz
);

create index if not exists idx_competitions_room_code on competitions(room_code);
create index if not exists idx_competitions_status on competitions(status);

-- ============================================================
-- teams: one row per team per competition
-- ============================================================
create table if not exists teams (
    id uuid primary key default gen_random_uuid(),
    competition_id uuid not null references competitions(id) on delete cascade,
    team_name text not null,
    starting_capital numeric not null default 100000,
    cash_remaining numeric not null default 100000,
    joined_at timestamptz not null default now(),
    unique(competition_id, team_name)
);

create index if not exists idx_teams_competition on teams(competition_id);

-- ============================================================
-- rounds: one row per round in a competition
-- ============================================================
create table if not exists rounds (
    id uuid primary key default gen_random_uuid(),
    competition_id uuid not null references competitions(id) on delete cascade,
    round_number int not null,
    phase text not null default 'setup',  -- setup | pitch | locked | resolved
    pitch_deadline timestamptz,
    resolution_time timestamptz,
    hold_start_price_date date,
    hold_end_price_date date,
    created_at timestamptz not null default now(),
    unique(competition_id, round_number)
);

create index if not exists idx_rounds_competition on rounds(competition_id);

-- ============================================================
-- positions: one row per team's pitch in a given round
-- ============================================================
create table if not exists positions (
    id uuid primary key default gen_random_uuid(),
    competition_id uuid not null references competitions(id) on delete cascade,
    round_id uuid not null references rounds(id) on delete cascade,
    team_id uuid not null references teams(id) on delete cascade,
    ticker text not null,
    company text,
    sector text,
    direction text not null,           -- long | short
    conviction int not null default 1, -- 1x | 2x | 3x
    pct_of_cash numeric not null,      -- 0..100
    notional_allocated numeric not null,
    entry_price numeric,
    exit_price numeric,
    return_pct numeric,                -- signed pct return on the position
    pnl_dollars numeric,
    thesis text,
    what_it_does text,
    metric text,
    catalyst text,
    submitted_at timestamptz not null default now(),
    resolved_at timestamptz,
    unique(round_id, team_id)
);

create index if not exists idx_positions_competition on positions(competition_id);
create index if not exists idx_positions_team on positions(team_id);
create index if not exists idx_positions_round on positions(round_id);

-- ============================================================
-- judge_scores: optional pitch-quality scoring
-- ============================================================
create table if not exists judge_scores (
    id uuid primary key default gen_random_uuid(),
    competition_id uuid not null references competitions(id) on delete cascade,
    position_id uuid not null references positions(id) on delete cascade,
    judge_name text not null,
    clarity int not null,
    logic int not null,
    metric_use int not null,
    catalyst_strength int not null,
    confidence int not null,
    total int generated always as
        (clarity + logic + metric_use + catalyst_strength + confidence) stored,
    submitted_at timestamptz not null default now()
);

create index if not exists idx_judge_scores_position on judge_scores(position_id);

-- ============================================================
-- price_cache: daily snapshot so we don't re-hit yahoo 1000x
-- ============================================================
create table if not exists price_cache (
    ticker text not null,
    price_date date not null,
    open numeric,
    high numeric,
    low numeric,
    close numeric,
    volume bigint,
    cached_at timestamptz not null default now(),
    primary key (ticker, price_date)
);

create index if not exists idx_price_cache_ticker on price_cache(ticker);

-- ============================================================
-- Row-level security: permissive for a club game, tighten later
-- ============================================================
alter table competitions enable row level security;
alter table teams enable row level security;
alter table rounds enable row level security;
alter table positions enable row level security;
alter table judge_scores enable row level security;
alter table price_cache enable row level security;

-- Permissive policies (anyone with the anon key can read/write).
-- Fine for a closed club game; lock down before shipping public.
drop policy if exists anon_all_competitions on competitions;
create policy anon_all_competitions on competitions for all using (true) with check (true);

drop policy if exists anon_all_teams on teams;
create policy anon_all_teams on teams for all using (true) with check (true);

drop policy if exists anon_all_rounds on rounds;
create policy anon_all_rounds on rounds for all using (true) with check (true);

drop policy if exists anon_all_positions on positions;
create policy anon_all_positions on positions for all using (true) with check (true);

drop policy if exists anon_all_judge_scores on judge_scores;
create policy anon_all_judge_scores on judge_scores for all using (true) with check (true);

drop policy if exists anon_all_price_cache on price_cache;
create policy anon_all_price_cache on price_cache for all using (true) with check (true);
