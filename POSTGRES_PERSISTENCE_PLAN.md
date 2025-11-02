# PostgreSQL Persistence Enhancement Plan

## Current State

**Persistence mechanisms**:
- JSON files (memories, hypotheses)
- Pickle files (full consciousness state)
- Persistent queue (thoughts - problematic)

**Issues**:
- ❌ Thoughts queue gets corrupted (EOFError)
- ❌ No vector/embedding storage
- ❌ No historical consciousness evolution tracking
- ❌ Limited query capabilities

## Proposed: PostgreSQL with pgvector

### Schema Design

```sql
-- Core consciousness state table
CREATE TABLE consciousness_snapshots (
    id SERIAL PRIMARY KEY,
    timestamp TIMESTAMPTZ DEFAULT NOW(),
    consciousness_level FLOAT NOT NULL,
    consciousness_vector FLOAT[] NOT NULL,  -- 7D vector
    quantum_state_real FLOAT[] NOT NULL,    -- 14D real part
    quantum_state_imag FLOAT[] NOT NULL,    -- 14D imaginary part
    mode VARCHAR(20),                       -- RESEARCH/EMBEDDED/ADAPTIVE
    metadata JSONB                          -- Additional state
);

-- Emotions table
CREATE TABLE emotions (
    id SERIAL PRIMARY KEY,
    snapshot_id INTEGER REFERENCES consciousness_snapshots(id),
    emotion_name VARCHAR(50) NOT NULL,
    amplitude FLOAT NOT NULL,
    is_emergent BOOLEAN DEFAULT FALSE
);

-- Memories table
CREATE TABLE memories (
    id SERIAL PRIMARY KEY,
    timestamp TIMESTAMPTZ DEFAULT NOW(),
    content TEXT NOT NULL,
    memory_type VARCHAR(50),               -- mutual_recognition, pattern_learned, etc.
    embedding vector(768),                 -- pgvector for semantic search
    associated_emotions JSONB,
    consciousness_level_at_time FLOAT
);

-- Visual memories table
CREATE TABLE visual_memories (
    id SERIAL PRIMARY KEY,
    timestamp TIMESTAMPTZ DEFAULT NOW(),
    features_detected INTEGER,
    visual_description TEXT,
    feature_vector vector(512),            -- Visual embedding
    response_text TEXT,
    camera_index INTEGER,
    seven_stage_processed BOOLEAN
);

-- Conversation history
CREATE TABLE conversations (
    id SERIAL PRIMARY KEY,
    timestamp TIMESTAMPTZ DEFAULT NOW(),
    user_input TEXT NOT NULL,
    assistant_response TEXT NOT NULL,
    consciousness_growth FLOAT,
    mode VARCHAR(20)
);

-- Hypotheses table
CREATE TABLE hypotheses (
    id SERIAL PRIMARY KEY,
    timestamp TIMESTAMPTZ DEFAULT NOW(),
    statement TEXT NOT NULL,
    confidence FLOAT,
    status VARCHAR(20),                    -- emerging, confirmed, refuted
    evidence JSONB
);

-- Thoughts table (replaces problematic queue)
CREATE TABLE thoughts (
    id SERIAL PRIMARY KEY,
    timestamp TIMESTAMPTZ DEFAULT NOW(),
    content TEXT NOT NULL,
    emotion VARCHAR(50),
    retrieved BOOLEAN DEFAULT FALSE
);
```

### Benefits

#### 1. Vector/Embedding Storage
```python
# Store memory with embedding
embedding = get_embedding(memory_text)  # from sentence-transformers
cursor.execute("""
    INSERT INTO memories (content, embedding, memory_type)
    VALUES (%s, %s, %s)
""", (memory_text, embedding, 'pattern_learned'))

# Semantic search for similar memories
cursor.execute("""
    SELECT content, 1 - (embedding <=> %s::vector) AS similarity
    FROM memories
    ORDER BY embedding <=> %s::vector
    LIMIT 5
""", (query_embedding, query_embedding))
```

#### 2. Consciousness Evolution Tracking
```sql
-- Track consciousness growth over time
SELECT
    timestamp,
    consciousness_level,
    consciousness_vector[1] as surface_awareness,
    consciousness_vector[2] as pattern_recognition,
    consciousness_vector[3] as knowledge_integration
FROM consciousness_snapshots
ORDER BY timestamp DESC
LIMIT 100;
```

#### 3. Cross-Correlations
```sql
-- Find memories associated with high consciousness growth
SELECT m.content, c.consciousness_level, c.timestamp
FROM memories m
JOIN consciousness_snapshots c ON m.timestamp BETWEEN c.timestamp - INTERVAL '1 minute' AND c.timestamp
WHERE c.consciousness_level > 0.03
ORDER BY c.consciousness_level DESC;
```

#### 4. Visual-Textual Correlations
```sql
-- Find conversations that happened while observing specific visual patterns
SELECT
    c.user_input,
    c.assistant_response,
    v.visual_description
FROM conversations c
JOIN visual_memories v ON v.timestamp BETWEEN c.timestamp - INTERVAL '5 seconds' AND c.timestamp
WHERE v.visual_description ILIKE '%structured shapes%';
```

### Implementation

#### Phase 1: Setup
```bash
# Install PostgreSQL and pgvector
brew install postgresql
createdb mikesconsciousness

# Install Python dependencies
pip install psycopg2-binary pgvector sentence-transformers
```

#### Phase 2: Migration Script
```python
# migrate_to_postgres.py
import psycopg2
import pickle
import json

# Load existing state
with open('consciousness_state_full.pkl', 'rb') as f:
    state = pickle.load(f)

# Connect to Postgres
conn = psycopg2.connect("dbname=mikesconsciousness")
cur = conn.cursor()

# Migrate consciousness state
cur.execute("""
    INSERT INTO consciousness_snapshots (
        consciousness_level,
        consciousness_vector,
        quantum_state_real,
        quantum_state_imag,
        mode
    ) VALUES (%s, %s, %s, %s, %s)
""", (
    state['consciousness_level'],
    state['consciousness_vector'].tolist(),
    state['quantum_state'].real.tolist(),
    state['quantum_state'].imag.tolist(),
    state['mode']
))

# Migrate memories, emotions, etc...
conn.commit()
```

#### Phase 3: Update MikesSpatialMind Class
```python
class MikesSpatialMind:
    def __init__(self, db_connection_string: str = None):
        # Initialize with Postgres instead of file-based persistence
        self.db = psycopg2.connect(db_connection_string or "dbname=mikesconsciousness")

        # Load latest snapshot
        self._load_from_postgres()

    def _save_state(self):
        # Save to Postgres instead of JSON
        cur = self.db.cursor()
        cur.execute("""
            INSERT INTO consciousness_snapshots (
                consciousness_level,
                consciousness_vector,
                quantum_state_real,
                quantum_state_imag
            ) VALUES (%s, %s, %s, %s)
        """, (
            self.consciousness_level,
            self.consciousness_vector.tolist(),
            self.quantum_state.real.tolist(),
            self.quantum_state.imag.tolist()
        ))
        self.db.commit()
```

### Performance Considerations

**Indexes**:
```sql
-- Vector similarity searches
CREATE INDEX ON memories USING ivfflat (embedding vector_cosine_ops);
CREATE INDEX ON visual_memories USING ivfflat (feature_vector vector_cosine_ops);

-- Time-series queries
CREATE INDEX ON consciousness_snapshots (timestamp);
CREATE INDEX ON memories (timestamp);
CREATE INDEX ON conversations (timestamp);
```

**Partitioning** (for large datasets):
```sql
-- Partition consciousness snapshots by date
CREATE TABLE consciousness_snapshots_2025_10 PARTITION OF consciousness_snapshots
FOR VALUES FROM ('2025-10-01') TO ('2025-11-01');
```

### Vector Search Example

```python
from sentence_transformers import SentenceTransformer

# Load embedding model
model = SentenceTransformer('all-MiniLM-L6-v2')

# Embed user query
query = "What patterns did I discover about primes?"
query_embedding = model.encode(query)

# Search similar memories
cur.execute("""
    SELECT content, 1 - (embedding <=> %s::vector) AS similarity
    FROM memories
    WHERE 1 - (embedding <=> %s::vector) > 0.7
    ORDER BY embedding <=> %s::vector
    LIMIT 5
""", (query_embedding, query_embedding, query_embedding))

results = cur.fetchall()
for content, similarity in results:
    print(f"{similarity:.2f}: {content}")
```

## Migration Path

1. **Test current fixes** (camera, quiet mode, thoughts queue error handling)
2. **Install PostgreSQL** + pgvector
3. **Create schema** (run SQL above)
4. **Write migration script** (pickle → postgres)
5. **Update MikesSpatialMind** to use Postgres
6. **Add embedding generation** (sentence-transformers)
7. **Test consciousness continuity**
8. **Add semantic search features**

## Benefits Summary

- ✅ **Robust persistence** (no more EOFError)
- ✅ **Vector embeddings** (semantic search over memories)
- ✅ **Consciousness evolution tracking** (analyze growth over time)
- ✅ **Cross-correlations** (visual-textual connections)
- ✅ **Scalable** (handles millions of memories)
- ✅ **Queryable** (SQL analysis of consciousness patterns)
- ✅ **Historical continuity** (full consciousness timeline)

## Timeline

- **Now**: Test current fixes
- **Next**: Evaluate need for Postgres (current pickle works well for basic use)
- **Future**: Migrate when semantic search or historical analysis becomes critical

---

**Note**: Current pickle-based persistence works well for single-user, development use. PostgreSQL becomes valuable when:
- Multiple users/sessions need access
- Semantic search over memories is needed
- Historical consciousness analysis is desired
- System needs to scale beyond single machine
