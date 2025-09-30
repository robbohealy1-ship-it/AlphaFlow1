# AlphaFlow Bot (MVP)

FastAPI web service + cron-based scanner posting alerts to Discord with Binance affiliate deep links.

## Deploy (quickest)
1. Create a GitHub repo and upload these files.
2. In Render: **New → Blueprint**, select your repo. It will create:
   - **alphaflow-worker** (Web Service)
   - **alphaflow-scanner** (Cron, every 10 minutes)
3. Set env vars on **alphaflow-worker**:
   - `DISCORD_BOT_TOKEN`, `DISCORD_CHANNEL_FREE`, `DISCORD_CHANNEL_PRO`
   - Optional: `BINANCE_REF` (default set in render.yaml)
4. Set env vars on **alphaflow-scanner**:
   - `SERVICE_URL` → your worker URL (e.g. https://alphaflow-worker.onrender.com)
5. Deploy, then **Run Now** the cron to test.

## Manual test
```bash
curl -X POST https://<alphaflow-worker>.onrender.com/send -H "Content-Type: application/json" -d '{
  "tier":"free",
  "source":"manual-test",
  "payload":{
    "symbol":"BTCUSDT","timeframe":"15m","side":"BUY",
    "price":65000,"stop":64500,"tp1":65500,"tp2":66500,
    "reason":"Manual sanity test",
    "technicals":{"rsi":58,"ema_fast":65050,"ema_slow":64990,"atr":80}
  }
}'
```
