[README.md](https://github.com/user-attachments/files/26981908/README.md)
# PMG Analyst Arena

Live, multiplayer stock pitch tournament. Host creates a room, players join with a code, each round teams pitch a ticker with direction + conviction + % of cash, and positions are scored on actual price movement. Final ranking is by portfolio return.

Think of it as MarketWatch's virtual exchange crossed with Kahoot, tailored for finance clubs.

## Features

- 6-character room codes, Kahoot-style join flow
- Three time modes:
  - **live_compressed** — real market prices, short real-time hold per round
  - **historical_replay** — re-run a past period (host picks start date)
  - **simulated_walk** — synthetic returns from each stock's own vol/drift
- Long/short positions with 1x–5x conviction
- Fixed $100k starting capital per team, allocated by % of remaining cash
- Head-to-head ranking with live leaderboard
- Optional judge scoring for pitch quality
- S&P 500, Nasdaq-100, Dow 30 universes with sector filters
- Built-in client-side countdown timer (non-blocking)
- CSV export of full results

## Project structure

```
pmg_arena/
├── app.py                # Streamlit entry + router
├── db.py                 # Supabase client + all DB operations
├── yahoo.py              # Price fetcher with fallbacks
├── universe.py           # S&P/Nasdaq/Dow constituent loaders
├── game.py               # Pure game logic (portfolio math, scoring)
├── formatting.py         # Shared formatters
├── ui/
│   ├── join.py           # Landing: join a room or host a new one
│   ├── host.py           # Host dashboard
│   └── player.py         # Player view
├── sql/schema.sql        # Paste into Supabase SQL editor once
├── requirements.txt
├── .streamlit/
│   └── secrets.toml.example
└── README.md
```

## Setup

### 1. Supabase project

1. Sign up at [supabase.com](https://supabase.com) (free tier is fine)
2. Create a new project
3. In the SQL Editor, paste the contents of `sql/schema.sql` and run it
4. In Settings → API, copy:
   - Project URL → `SUPABASE_URL`
   - anon public key → `SUPABASE_ANON_KEY`

### 2. Local dev

```bash
pip install -r requirements.txt

# Create your secrets file
mkdir -p .streamlit
cp .streamlit/secrets.toml.example .streamlit/secrets.toml
# Edit .streamlit/secrets.toml with your Supabase values

streamlit run app.py
```

### 3. Deploy to Streamlit Community Cloud (free)

1. Push this repo to GitHub
2. Go to [share.streamlit.io](https://share.streamlit.io), connect your GitHub, and pick this repo
3. In the app's settings, add the secrets under "Secrets":
   ```
   SUPABASE_URL = "https://your-project-ref.supabase.co"
   SUPABASE_ANON_KEY = "your-anon-key"
   ```
4. Deploy — you'll get a public URL like `https://pmg-arena.streamlit.app`
5. Share that URL with your club; anyone with the URL + room code can join

## How a game runs

**Host:**
1. Open the app → Host a Game tab → enter your name → get a 6-char room code
2. On the host dashboard, configure:
   - Universes (S&P / Nasdaq / Dow)
   - Time mode
   - Number of rounds
   - Pitch timer
   - Long/short rules, conviction cap, judges toggle
3. Share the room code with your club
4. Once teams have joined, click **Start Competition**
5. For each round: teams pitch → you click **Lock pitches** (freezes entries, captures entry prices) → wait the hold window → click **Resolve round**
6. After the final round, click **End competition**

**Player:**
1. Open the app → Join a Game tab → enter room code and team name
2. Wait in the lobby
3. When the round starts: pick a ticker, review the research panel, set direction + conviction + % cash + pitch notes, submit
4. After the host locks and resolves, see your P&L and the leaderboard
5. Repeat for each round

## Design notes for future iteration

- **Stock duplication:** Multiple teams can currently pitch the same ticker. If you want to prevent this, add a server-side check in `db.submit_position` querying the round for existing tickers. I left it open because uniqueness changes the game feel (draft-style vs free choice).
- **Live leaderboard updates:** The current implementation uses manual refresh buttons. For true real-time updates, wrap the leaderboard views with Supabase's Postgres changes subscription (JS side) and poll via `st_autorefresh` from `streamlit-extras`. Easy add if you want it.
- **Market hours awareness:** Live compressed mode uses current prices via `yfinance`. Outside of market hours, prices don't change, so a round won't produce interesting P&L. Add a `MARKET_OPEN` check in the host dashboard if you want to block starting rounds when closed.
- **Anti-collusion:** The anon key lets anyone with the code read/write. For a club game, fine. For a public release, lock down RLS policies to role-specific access.

## Where PRMU fits in

Nothing here talks to your PRMU Research Terminal yet, but the natural hook is: replace the lightweight research panel in `ui/player.py::_render_research_panel` with an iframe or link to a PRMU ticker page. That way teams can click "Open in PRMU" to get regime/volatility context before pitching.
