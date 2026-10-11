from pathlib import Path
from threading import RLock
from typing import Literal
import pandas as pd
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field
from sklearn.metrics.pairwise import cosine_similarity

HERE = Path(__file__).resolve()
DATA = HERE.parents[2] / "data"
if not DATA.exists():
    DATA = HERE.parents[1] / "data"
app = FastAPI(title="StreamGen Recommendation Service", version="1.0.0")
lock = RLock()

class HistoryEntry(BaseModel):
    item_id: str
    rating: float = Field(ge=1, le=5)

class RecommendRequest(BaseModel):
    user_id: str = Field(min_length=1, max_length=80)
    history: list[HistoryEntry] = Field(min_length=1, max_length=100)
    limit: int = Field(default=8, ge=5, le=20)

class FeedbackRequest(BaseModel):
    user_id: str = Field(min_length=1, max_length=80)
    item_id: str
    rating: int = Field(ge=1, le=5)


def clean_data():
    history = pd.read_csv(DATA / "viewing_history.csv")
    catalog = pd.read_csv(DATA / "catalog.csv")
    history = history.drop_duplicates(subset=["user_id", "item_id"], keep="last")
    history["rating"] = pd.to_numeric(history["rating"], errors="coerce")
    history = history.dropna(subset=["user_id", "item_id", "rating"])
    history = history[history["rating"].between(1, 5)]
    history = history[history["item_id"].isin(catalog["item_id"])]
    history["user_id"] = history["user_id"].astype(str).str.strip()
    history = history[history["user_id"] != ""]
    return history, catalog

ratings, catalog = clean_data()
# The in-memory event overlay keeps feedback isolated by user while allowing fast recomputation.
feedback: dict[tuple[str, str], int] = {}


def make_matrix():
    with lock:
        rows = ratings.copy()
        if feedback:
            extra = pd.DataFrame([{"user_id": u, "item_id": i, "rating": r} for (u, i), r in feedback.items()])
            rows = pd.concat([rows, extra], ignore_index=True).drop_duplicates(["user_id", "item_id"], keep="last")
        return rows.pivot_table(index="user_id", columns="item_id", values="rating", fill_value=0)


def recommend(user_id: str, history: list[HistoryEntry], limit: int):
    matrix = make_matrix()
    user_ratings = dict(zip([x.item_id for x in history], [x.rating for x in history]))
    with lock:
        for (uid, item), rating in feedback.items():
            if uid == user_id:
                user_ratings[item] = rating
    known_items = set(catalog.item_id)
    user_ratings = {k: v for k, v in user_ratings.items() if k in known_items}
    if not user_ratings:
        raise HTTPException(400, "Add at least one valid item from the catalogue.")
    # Item-item collaborative filtering: weighted ratings from items co-rated by other users.
    sim = cosine_similarity(matrix.T) if len(matrix.columns) else None
    item_ids = list(matrix.columns)
    sim_df = pd.DataFrame(sim, index=item_ids, columns=item_ids) if sim is not None else pd.DataFrame()
    scores = {}
    seen = set(user_ratings)
    for candidate in catalog.item_id:
        if candidate in seen:
            continue
        score, weight = 0.0, 0.0
        for watched, rating in user_ratings.items():
            if watched in sim_df.index and candidate in sim_df.columns:
                similarity = max(0.0, float(sim_df.loc[candidate, watched]))
                score += similarity * (rating - 2.5)
                weight += similarity
        # Small popularity prior ensures cold-start and sparse-history users still receive results.
        popularity = float((ratings.item_id == candidate).sum())
        scores[candidate] = (score / weight if weight else 0.0) + 0.035 * popularity
    # Incorporate current user's feedback even when item was absent from the original matrix.
    ranked = sorted(scores, key=lambda item: scores[item], reverse=True)
    results = catalog[catalog.item_id.isin(ranked)].copy()
    results["_rank"] = results.item_id.map({item: idx for idx, item in enumerate(ranked)})
    results = results.sort_values("_rank").head(limit)
    return [{**row, "score": round(max(0.0, min(1.0, 0.5 + scores[row["item_id"]] / 5)), 3)} for row in results.drop(columns="_rank").to_dict("records")]

@app.get("/health")
def health():
    return {"status": "ok", "clean_interactions": int(len(ratings)), "catalog_items": int(len(catalog))}

@app.get("/catalog")
def get_catalog():
    return catalog.to_dict("records")

@app.post("/recommend")
def get_recommendations(body: RecommendRequest):
    valid = set(catalog.item_id)
    clean_history = [entry for entry in body.history if entry.item_id in valid]
    if not clean_history:
        raise HTTPException(400, "No valid catalogue items found in your viewing history.")
    items = recommend(body.user_id.strip(), clean_history, body.limit)
    if len(items) < 5:
        # Safe fallback: popular unseen catalogue entries, still excluding watched titles.
        seen = {x.item_id for x in clean_history}
        fallback = catalog[~catalog.item_id.isin(seen)].head(5).to_dict("records")
        existing = {x["item_id"] for x in items}
        items += [{**x, "score": 0.25} for x in fallback if x["item_id"] not in existing][:5-len(items)]
    return {"user_id": body.user_id, "recommendations": items[:body.limit], "method": "item-item cosine collaborative filtering + popularity fallback"}

@app.post("/feedback")
def submit_feedback(body: FeedbackRequest):
    if body.item_id not in set(catalog.item_id):
        raise HTTPException(404, "Unknown catalogue item.")
    with lock:
        feedback[(body.user_id.strip(), body.item_id)] = body.rating
    return {"message": "Feedback saved; future recommendations will reflect this rating.", "user_id": body.user_id, "item_id": body.item_id, "rating": body.rating}
