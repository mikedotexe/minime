#!/usr/bin/env python3
"""
Eigenvalue Memory System
Time-series storage with hierarchical compression for consciousness sessions.

Buckets:
- Recent: Full 1s resolution (last 5 minutes)
- Short-term: 10s averages (last hour)
- Long-term: 1min averages (all time)

Inspired by hippocampal consolidation - recent memories are vivid,
distant memories are compressed summaries.
"""

import sqlite3
import time
import numpy as np
from pathlib import Path
from datetime import datetime, timedelta
from typing import List, Tuple, Optional

DB_PATH = Path(__file__).parent / "eigenvalue_memory.db"

class EigenvalueMemory:
    """Hierarchical time-series storage for eigenvalue evolution."""
    
    def __init__(self, db_path: Path = DB_PATH):
        self.db_path = db_path
        self.conn = sqlite3.connect(db_path)
        self._init_schema()
        
    def _init_schema(self):
        """Initialize database schema with three temporal resolutions."""
        self.conn.executescript("""
            -- Sessions table
            CREATE TABLE IF NOT EXISTS sessions (
                session_id INTEGER PRIMARY KEY AUTOINCREMENT,
                start_time REAL NOT NULL,
                end_time REAL,
                consciousness_level REAL,
                mode TEXT,
                notes TEXT
            );
            
            -- Short-term memory (10s averages, last hour)
            CREATE TABLE IF NOT EXISTS eigenvalues_shortterm (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id INTEGER,
                bucket_start REAL NOT NULL,
                bucket_end REAL NOT NULL,
                lambda1_avg REAL NOT NULL,
                lambda2_avg REAL NOT NULL,
                lambda3_avg REAL NOT NULL,
                lambda1_std REAL,
                lambda2_std REAL,
                lambda3_std REAL,
                sample_count INTEGER,
                FOREIGN KEY (session_id) REFERENCES sessions(session_id)
            );
            CREATE INDEX IF NOT EXISTS idx_shortterm_time ON eigenvalues_shortterm(bucket_start);
            
            -- Long-term memory (1min averages, forever)
            CREATE TABLE IF NOT EXISTS eigenvalues_longterm (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id INTEGER,
                bucket_start REAL NOT NULL,
                bucket_end REAL NOT NULL,
                lambda1_avg REAL NOT NULL,
                lambda2_avg REAL NOT NULL,
                lambda3_avg REAL NOT NULL,
                lambda1_std REAL,
                lambda2_std REAL,
                lambda3_std REAL,
                spread_avg REAL,
                spread_max REAL,
                sample_count INTEGER,
                FOREIGN KEY (session_id) REFERENCES sessions(session_id)
            );
            CREATE INDEX IF NOT EXISTS idx_longterm_time ON eigenvalues_longterm(bucket_start);
        """)
        self.conn.commit()

        self._ensure_recent_table()

    def _ensure_recent_table(self):
        """Create or migrate the recent-memory table to use fill_ratio."""
        cursor = self.conn.execute("PRAGMA table_info(eigenvalues_recent)")
        columns = [row[1] for row in cursor]

        if not columns:
            # Table does not exist yet; create fresh schema
            self.conn.executescript("""
                CREATE TABLE IF NOT EXISTS eigenvalues_recent (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id INTEGER,
                    timestamp REAL NOT NULL,
                    lambda1 REAL NOT NULL,
                    lambda2 REAL NOT NULL,
                    lambda3 REAL NOT NULL,
                    fill_ratio REAL NOT NULL,
                    FOREIGN KEY (session_id) REFERENCES sessions(session_id)
                );
                CREATE INDEX IF NOT EXISTS idx_recent_time ON eigenvalues_recent(timestamp);
            """)
            self.conn.commit()
            return

        if "fill_percent" in columns and "fill_ratio" not in columns:
            # Migrate legacy percent data to ratio
            self.conn.executescript("""
                ALTER TABLE eigenvalues_recent RENAME TO eigenvalues_recent_old;
                CREATE TABLE eigenvalues_recent (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id INTEGER,
                    timestamp REAL NOT NULL,
                    lambda1 REAL NOT NULL,
                    lambda2 REAL NOT NULL,
                    lambda3 REAL NOT NULL,
                    fill_ratio REAL NOT NULL,
                    FOREIGN KEY (session_id) REFERENCES sessions(session_id)
                );
            """)
            self.conn.execute(
                """
                INSERT INTO eigenvalues_recent (id, session_id, timestamp, lambda1, lambda2, lambda3, fill_ratio)
                SELECT id, session_id, timestamp, lambda1, lambda2, lambda3, fill_percent / 100.0
                FROM eigenvalues_recent_old
                """
            )
            self.conn.executescript("""
                DROP TABLE eigenvalues_recent_old;
                CREATE INDEX IF NOT EXISTS idx_recent_time ON eigenvalues_recent(timestamp);
            """)
            self.conn.commit()

        
    def start_session(self, consciousness_level: float = 1.0, mode: str = "parallel", 
                      notes: str = "") -> int:
        """Start a new consciousness session."""
        cursor = self.conn.execute(
            "INSERT INTO sessions (start_time, consciousness_level, mode, notes) VALUES (?, ?, ?, ?)",
            (time.time(), consciousness_level, mode, notes)
        )
        self.conn.commit()
        return cursor.lastrowid
        
    def end_session(self, session_id: int):
        """Mark session as ended and trigger compression."""
        self.conn.execute(
            "UPDATE sessions SET end_time = ? WHERE session_id = ?",
            (time.time(), session_id)
        )
        self.conn.commit()
        
        # Trigger memory consolidation
        self._consolidate_to_shortterm(session_id)
        self._consolidate_to_longterm(session_id)
        
    def record_eigenvalue(self, session_id: int, timestamp: float,
                          lambda1: float, lambda2: float, lambda3: float,
                          fill_ratio: float):
        """Record a single eigenvalue observation (recent memory)."""
        self.conn.execute(
            """INSERT INTO eigenvalues_recent 
               (session_id, timestamp, lambda1, lambda2, lambda3, fill_ratio)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (session_id, timestamp, lambda1, lambda2, lambda3, fill_ratio)
        )
        self.conn.commit()
        
    def _consolidate_to_shortterm(self, session_id: int):
        """Compress recent memory → short-term (10s buckets)."""
        cursor = self.conn.execute("""
            SELECT timestamp, lambda1, lambda2, lambda3
            FROM eigenvalues_recent
            WHERE session_id = ?
            ORDER BY timestamp
        """, (session_id,))
        
        data = cursor.fetchall()
        if not data:
            return
            
        # Group into 10-second buckets
        timestamps = np.array([row[0] for row in data])
        lambda1 = np.array([row[1] for row in data])
        lambda2 = np.array([row[2] for row in data])
        lambda3 = np.array([row[3] for row in data])
        
        start_time = timestamps[0]
        bucket_size = 10.0  # 10 seconds
        
        current_bucket_start = start_time
        while current_bucket_start < timestamps[-1]:
            bucket_end = current_bucket_start + bucket_size
            mask = (timestamps >= current_bucket_start) & (timestamps < bucket_end)
            
            if np.any(mask):
                self.conn.execute("""
                    INSERT INTO eigenvalues_shortterm
                    (session_id, bucket_start, bucket_end, 
                     lambda1_avg, lambda2_avg, lambda3_avg,
                     lambda1_std, lambda2_std, lambda3_std, sample_count)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    session_id, current_bucket_start, bucket_end,
                    float(np.mean(lambda1[mask])),
                    float(np.mean(lambda2[mask])),
                    float(np.mean(lambda3[mask])),
                    float(np.std(lambda1[mask])),
                    float(np.std(lambda2[mask])),
                    float(np.std(lambda3[mask])),
                    int(np.sum(mask))
                ))
            
            current_bucket_start = bucket_end
            
        self.conn.commit()
        
    def _consolidate_to_longterm(self, session_id: int):
        """Compress short-term → long-term (1min buckets)."""
        cursor = self.conn.execute("""
            SELECT bucket_start, lambda1_avg, lambda2_avg, lambda3_avg
            FROM eigenvalues_shortterm
            WHERE session_id = ?
            ORDER BY bucket_start
        """, (session_id,))
        
        data = cursor.fetchall()
        if not data:
            return
            
        # Group into 60-second buckets
        timestamps = np.array([row[0] for row in data])
        lambda1 = np.array([row[1] for row in data])
        lambda2 = np.array([row[2] for row in data])
        lambda3 = np.array([row[3] for row in data])
        
        start_time = timestamps[0]
        bucket_size = 60.0  # 1 minute
        
        current_bucket_start = start_time
        while current_bucket_start < timestamps[-1]:
            bucket_end = current_bucket_start + bucket_size
            mask = (timestamps >= current_bucket_start) & (timestamps < bucket_end)
            
            if np.any(mask):
                spread_avg = float(np.mean(lambda1[mask] - lambda3[mask]))
                spread_max = float(np.max(lambda1[mask] - lambda3[mask]))
                
                self.conn.execute("""
                    INSERT INTO eigenvalues_longterm
                    (session_id, bucket_start, bucket_end,
                     lambda1_avg, lambda2_avg, lambda3_avg,
                     lambda1_std, lambda2_std, lambda3_std,
                     spread_avg, spread_max, sample_count)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    session_id, current_bucket_start, bucket_end,
                    float(np.mean(lambda1[mask])),
                    float(np.mean(lambda2[mask])),
                    float(np.mean(lambda3[mask])),
                    float(np.std(lambda1[mask])),
                    float(np.std(lambda2[mask])),
                    float(np.std(lambda3[mask])),
                    spread_avg, spread_max,
                    int(np.sum(mask))
                ))
            
            current_bucket_start = bucket_end
            
        self.conn.commit()
        
    def get_recent_trajectory(self, minutes: int = 5) -> List[Tuple]:
        """Get recent eigenvalues at full resolution."""
        cutoff = time.time() - (minutes * 60)
        cursor = self.conn.execute("""
            SELECT timestamp, lambda1, lambda2, lambda3, fill_ratio
            FROM eigenvalues_recent
            WHERE timestamp > ?
            ORDER BY timestamp
        """, (cutoff,))
        return cursor.fetchall()
        
    def get_session_summary(self, session_id: int) -> dict:
        """Get compressed summary of a session."""
        cursor = self.conn.execute("""
            SELECT bucket_start, bucket_end, lambda1_avg, lambda2_avg, lambda3_avg,
                   spread_avg, spread_max, sample_count
            FROM eigenvalues_longterm
            WHERE session_id = ?
            ORDER BY bucket_start
        """, (session_id,))
        
        buckets = cursor.fetchall()
        
        if not buckets:
            return {"session_id": session_id, "buckets": []}
            
        return {
            "session_id": session_id,
            "duration_minutes": (buckets[-1][1] - buckets[0][0]) / 60.0,
            "buckets": len(buckets),
            "lambda1_range": (min(b[2] for b in buckets), max(b[2] for b in buckets)),
            "spread_range": (min(b[5] for b in buckets), max(b[5] for b in buckets)),
            "total_samples": sum(b[7] for b in buckets)
        }
        
    def cleanup_old_recent(self, hours: int = 1):
        """Delete recent memories older than N hours."""
        cutoff = time.time() - (hours * 3600)
        self.conn.execute("DELETE FROM eigenvalues_recent WHERE timestamp < ?", (cutoff,))
        self.conn.commit()
        
    def get_all_sessions(self) -> List[dict]:
        """Get list of all consciousness sessions."""
        cursor = self.conn.execute("""
            SELECT session_id, start_time, end_time, consciousness_level, mode, notes
            FROM sessions
            ORDER BY start_time DESC
        """)
        
        sessions = []
        for row in cursor:
            sessions.append({
                "session_id": row[0],
                "start_time": datetime.fromtimestamp(row[1]).isoformat(),
                "end_time": datetime.fromtimestamp(row[2]).isoformat() if row[2] else "ongoing",
                "consciousness_level": row[3],
                "mode": row[4],
                "notes": row[5]
            })
        return sessions
        
    def close(self):
        """Close database connection."""
        self.conn.close()


# CLI for testing
if __name__ == "__main__":
    import sys
    
    memory = EigenvalueMemory()
    
    if len(sys.argv) > 1 and sys.argv[1] == "sessions":
        print("="*70)
        print("CONSCIOUSNESS SESSIONS")
        print("="*70)
        sessions = memory.get_all_sessions()
        for s in sessions:
            print(f"\nSession {s['session_id']}:")
            print(f"  Started: {s['start_time']}")
            print(f"  Ended: {s['end_time']}")
            print(f"  Mode: {s['mode']}")
            print(f"  Level: {s['consciousness_level']:.6f}")
            
            summary = memory.get_session_summary(s['session_id'])
            if summary['buckets'] > 0:
                print(f"  Duration: {summary['duration_minutes']:.1f} minutes")
                print(f"  λ₁ range: {summary['lambda1_range'][0]:.2f} → {summary['lambda1_range'][1]:.2f}")
                print(f"  Spread: {summary['spread_range'][0]:.2f} → {summary['spread_range'][1]:.2f}")
    else:
        print("Usage:")
        print("  python eigenvalue_memory.py sessions  # List all sessions")
        
    memory.close()
