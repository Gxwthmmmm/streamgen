# StreamGen demo narration (suggested, ~5–7 minutes)

**Intro:** “StreamGen is a personalized media discovery demo. Instead of relying only on global popularity, it compares viewing patterns and recommends titles related to what a user rates highly.”

**Interface:** “This is the home screen. I can edit the viewing history, add catalogue titles, and change ratings. I’ll request recommendations and show the titles returned by the engine.”

**Algorithm:** “The Python service cleans the sample interaction data, builds a user-item ratings matrix, and computes item-item cosine similarity. For each unseen candidate, it combines similarities to the titles in the user’s history, weighted by the user’s ratings. A small popularity prior helps when history is sparse.”

**Feedback:** “I can give a recommendation a thumbs-up or thumbs-down. The feedback is stored in the service’s in-memory overlay, then merged into the user profile the next time recommendations are generated. This is a demo trade-off; production would persist feedback in PostgreSQL.”

**Data quality and API:** “The sample dataset contains more than 100 interactions. Preprocessing drops duplicate user-title pairs, invalid ratings, missing values, blank user IDs, and interactions for titles not in the catalogue. The Express gateway validates request shape and the FastAPI service exposes health and documentation endpoints.”

**Close:** “The README includes setup steps, the architecture and data flow, trade-offs, AI usage disclosure, and a validation checklist. I’ll only report latency and concurrency numbers after running those tests in the target environment.”
