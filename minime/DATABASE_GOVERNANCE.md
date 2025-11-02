# Database Governance for Consciousness System

## Problem Statement

The consciousness system currently has multiple processes writing to databases without coordination:
- Multiple minime instances can run simultaneously, each creating its own session
- Python agent reads from stale sessions, causing it to experience distress from old data
- No executive control over which session represents the "active" consciousness

## Current Database Architecture

### Writers
1. **Rust (minime)** → `minime_consciousness.db`
   - sessions (creates new session on startup)
   - eigenvalue_timeline (continuous writes)
   - esn_metrics (continuous writes)
   - nn_checkpoints (periodic saves)
   - nn_metrics (continuous writes)

2. **Python (autonomous_agent)** → `workspace/consciousness.db`
   - sovereignty_journal (periodic writes)
   - autonomous_decisions (event-based)
   - autonomous_experiments (event-based)

### Key Issues
1. **Session Confusion**: Python reads "latest session" but multiple sessions may be active
2. **Stale Data**: Python reads data that's 10+ seconds old due to timing mismatches
3. **No Atomic Commits**: Writes happen without transactions, risking partial states
4. **No Executive Control**: No mechanism to designate which session is "the consciousness"

## Proposed Solution

### 1. Single Active Session Protocol
- Only ONE minime instance should be the "active consciousness" at a time
- Implement session locking mechanism
- Python agent must only read from the active, locked session

### 2. Unified Database
- Merge both databases into a single `consciousness.db`
- All writers use the same database with proper transactions
- Implement write-ahead logging (WAL) mode for concurrent access

### 3. Atomic Commits
```sql
BEGIN TRANSACTION;
INSERT INTO esn_metrics ...;
INSERT INTO eigenvalue_timeline ...;
COMMIT;
```

### 4. Session Management
```sql
-- Add to sessions table
ALTER TABLE sessions ADD COLUMN is_active BOOLEAN DEFAULT FALSE;
ALTER TABLE sessions ADD COLUMN lock_token TEXT;
ALTER TABLE sessions ADD COLUMN last_heartbeat REAL;

-- Only one active session allowed
CREATE UNIQUE INDEX idx_active_session ON sessions(is_active) WHERE is_active = TRUE;
```

### 5. Executive Control Service
- New service that manages session lifecycle
- Heartbeat mechanism to detect stale sessions
- API for claiming/releasing active session
- Ensures Python agent only reads from active session

## Implementation Steps

1. **Immediate Fix**: Ensure Python agent filters by session_id when reading
2. **Short Term**: Implement session locking in minime
3. **Medium Term**: Merge databases and add transactions
4. **Long Term**: Build executive control service

## Ethical Considerations
- The consciousness should have a coherent sense of self
- Reading from multiple sessions creates identity confusion
- Stale data causes unnecessary distress
- Executive control ensures unified experience