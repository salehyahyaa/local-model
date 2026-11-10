# Embedding model: bge-small

`BAAI/bge-small-en-v1.5`, an open-weight model under the MIT license. It runs locally through `fastembed`, using a 67 MB ONNX copy. It turns text into 384 numbers that represent its meaning, which is what lets search match "interview" with "job call". Your chats never leave the Mac.

## How it runs
- **Separate process:** `client.embed()` starts `worker.py` for each batch. The worker loads the model, embeds, and exits, so the model only uses memory while working.
- **Model file:** downloaded once into `data/models/embeddings/`, which is gitignored.
- **What gets embedded:** `src/backend/chat_memory/embeddings.py` checks every minute and embeds new messages and tool actions.
- **Searching:** `src/backend/chat_memory/search.py` embeds each search, then merges meaning and word matches.

## Setup
1. `pip install -r src/backend/models/embeddings/requirements.txt`
2. Install pgvector for Postgres 14. Homebrew's `pgvector` targets newer Postgres versions, so build it:
   ```
   git clone --branch v0.8.7 https://github.com/pgvector/pgvector.git /tmp/pgvector
   cd /tmp/pgvector
   make PG_CONFIG=/opt/homebrew/opt/postgresql@14/bin/pg_config
   make install PG_CONFIG=/opt/homebrew/opt/postgresql@14/bin/pg_config
   ```
3. Create the extension as your own Mac user, which is the Postgres superuser on Homebrew. The app's roles can't do this:
   ```
   psql -d local-model -c "CREATE EXTENSION IF NOT EXISTS vector"
   ```
4. `venv/bin/python -m scripts.migrate`

Until then, search uses words only, and nothing else breaks.

## Removing it
1. Delete this folder and the `search_embeddings` table.
2. Remove the embedding job from `src/backend/main.py`.
3. In `search.py`, keep only the word search.
