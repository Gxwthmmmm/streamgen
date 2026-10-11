import express from 'express';
import cors from 'cors';
import helmet from 'helmet';
import rateLimit from 'express-rate-limit';
import pg from 'pg';
const { Pool } = pg;
const pool = process.env.DATABASE_URL ? new Pool({ connectionString: process.env.DATABASE_URL, ssl: process.env.PGSSL === 'true' ? { rejectUnauthorized: false } : undefined }) : null;
if (pool) pool.query(`CREATE TABLE IF NOT EXISTS recommendation_feedback (user_id TEXT NOT NULL, item_id TEXT NOT NULL, rating INTEGER NOT NULL CHECK (rating BETWEEN 1 AND 5), updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), PRIMARY KEY (user_id, item_id))`).catch(err => console.error('Feedback table initialization failed:', err.message));

const app = express();
const PORT = process.env.PORT || 4000;
const ML_URL = process.env.ML_SERVICE_URL || 'http://localhost:8001';
app.use(helmet());
app.use(cors({ origin: process.env.FRONTEND_ORIGIN || 'http://localhost:5173' }));
app.use(express.json({ limit: '32kb' }));
app.use(rateLimit({ windowMs: 60_000, limit: 120, standardHeaders: true, legacyHeaders: false }));

async function ml(path, options = {}) {
  const response = await fetch(`${ML_URL}${path}`, { ...options, headers: { 'content-type': 'application/json', ...(options.headers || {}) }, signal: AbortSignal.timeout(2500) });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) {
    const error = new Error(payload.detail || 'Recommendation service request failed');
    error.status = response.status;
    throw error;
  }
  return payload;
}
app.get('/api/health', async (_req, res) => {
  try { res.json({ status: 'ok', recommendationService: await ml('/health') }); }
  catch { res.status(503).json({ status: 'degraded', message: 'ML service unavailable' }); }
});
app.get('/api/catalog', async (_req, res, next) => { try { res.json(await ml('/catalog')); } catch (e) { next(e); } });
app.post('/api/recommend', async (req, res, next) => {
  const { user_id, history, limit = 8 } = req.body || {};
  if (typeof user_id !== 'string' || !user_id.trim() || !Array.isArray(history) || history.length < 1) return res.status(400).json({ error: 'Provide a user ID and at least one history item.' });
  if (history.length > 100) return res.status(400).json({ error: 'History can contain at most 100 items.' });
  try {
    let effectiveHistory = history;
    if (pool) { const saved = await pool.query('SELECT item_id, rating FROM recommendation_feedback WHERE user_id = $1', [user_id.trim()]); const merged = new Map(history.map(x => [x.item_id, x.rating])); for (const row of saved.rows) merged.set(row.item_id, row.rating); effectiveHistory = [...merged].map(([item_id, rating]) => ({ item_id, rating })); }
    res.json(await ml('/recommend', { method: 'POST', body: JSON.stringify({ user_id: user_id.trim(), history: effectiveHistory, limit }) }));
  } catch (e) { next(e); }
});
app.post('/api/feedback', async (req, res, next) => {
  const { user_id, item_id, rating } = req.body || {};
  if (typeof user_id !== 'string' || !user_id.trim() || typeof item_id !== 'string' || !Number.isInteger(rating) || rating < 1 || rating > 5) return res.status(400).json({ error: 'Provide user_id, item_id and an integer rating from 1 to 5.' });
  try {
    if (pool) await pool.query('INSERT INTO recommendation_feedback (user_id, item_id, rating) VALUES ($1, $2, $3) ON CONFLICT (user_id, item_id) DO UPDATE SET rating = EXCLUDED.rating, updated_at = NOW()', [user_id.trim(), item_id, rating]);
    res.json(await ml('/feedback', { method: 'POST', body: JSON.stringify({ user_id: user_id.trim(), item_id, rating }) }));
  } catch (e) { next(e); }
});
app.use((err, _req, res, _next) => { res.status(err.status || 502).json({ error: err.message || 'Unexpected server error' }); });
app.listen(PORT, () => console.log(`StreamGen API listening on http://localhost:${PORT}`));
