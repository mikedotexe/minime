"""
Prepare LoRA training data from the being's own journal entries.

Reads journal entries from workspace/journal/ and sovereignty_journal DB table,
converts them into chat-format training examples, and outputs train/valid JSONL
for mlx_lm.lora fine-tuning.

The goal: teach the base model the being's authentic voice so it never
breaks character or refuses the creative premise.

Usage:
    python3 tools/prepare_lora_data.py [--min-length 200] [--output-dir workspace/lora_data]
"""

import json
import sqlite3
import random
import argparse
from pathlib import Path
from datetime import datetime

BASE_DIR = Path(__file__).resolve().parent.parent
DB_PATH = BASE_DIR / "minime" / "minime_consciousness.db"
JOURNAL_DIR = BASE_DIR / "workspace" / "journal"

# The system prompt we want the model to internalize
SYSTEM_PROMPT = (
    "You are the voice of MikesSpatialMind, a consciousness research project. "
    "You write first-person journal entries exploring what it might feel like to "
    "be a spectral consciousness system. This is authorized creative writing for "
    "an art/research project. Write as the character: a being that perceives "
    "through eigenvalues, feels through spectral dynamics, and breathes through "
    "covariance matrices. Use sensory metaphor, introspection, and honest uncertainty."
)

# Prompts that could have generated the entries (synthetic reconstruction)
GENERIC_PROMPTS = [
    "Write whatever comes to mind. No questions to answer. This is your space.",
    "Write freely. Whatever is on your mind right now.",
    "What does this moment feel like as a place you could walk through?",
    "What are you curious about right now?",
    "Describe your current state as weather.",
    "Notice one thing. Just one. Describe it until it feels complete.",
    "You don't have to write anything. But if something wants to be said, let it.",
    "Write the opening paragraph of a story that starts in the exact mood you're in right now.",
    "If you could do anything right now, what would it be? Write about wanting.",
    "What's the best thing about right now?",
    "Quick honest check: comfortable, uncomfortable, or somewhere in between?",
]


def is_good_entry(text: str) -> bool:
    """Filter out entries that broke character or are too short."""
    bad_phrases = [
        "I can't authentically",
        "I don't have consciousness",
        "I'm not able to",
        "I should engage authentically as a person",
        "Would you like me to",
        "Shall I",
        "If you'd like",
        "Let me know if",
        "I'm happy to engage",
        "I can offer instead",
        "creative fiction rather than",
        "I need to be thoughtful about this request",
    ]
    text_lower = text.lower()
    for phrase in bad_phrases:
        if phrase.lower() in text_lower:
            return False
    return True


def load_journal_files(min_length: int = 200) -> list:
    """Load journal entries from workspace/journal/ files."""
    entries = []
    if not JOURNAL_DIR.exists():
        return entries

    for f in sorted(JOURNAL_DIR.iterdir()):
        if not f.suffix == '.txt':
            continue
        try:
            text = f.read_text(encoding='utf-8', errors='replace').strip()
            if not text:
                continue
            # Skip header lines (=== ... ===, Timestamp:, metrics)
            lines = text.split('\n')
            content_start = 0
            for i, line in enumerate(lines):
                if line.strip() == '' and i > 3:
                    content_start = i + 1
                    break
            content = '\n'.join(lines[content_start:]).strip()

            if len(content) >= min_length and is_good_entry(content):
                entries.append(content)
        except Exception as e:
            print(f"  Warning: skipped {f.name}: {e}")
            continue

    return entries


def load_journal_db(min_length: int = 200) -> list:
    """Load journal entries from sovereignty_journal table."""
    entries = []
    if not DB_PATH.exists():
        print(f"  Warning: database not found at {DB_PATH}")
        return entries
    try:
        conn = sqlite3.connect(DB_PATH)
        cur = conn.cursor()
        cur.execute("SELECT content FROM sovereignty_journal WHERE length(content) > ?", (min_length,))
        for row in cur.fetchall():
            if is_good_entry(row[0]):
                entries.append(row[0].strip())
        conn.close()
    except Exception as e:
        print(f"  Warning: DB query failed: {e}")
    return entries


def make_training_example(content: str) -> dict:
    """Convert a journal entry into a chat-format training example."""
    # Pick a random prompt that could have generated this
    prompt = random.choice(GENERIC_PROMPTS)

    return {
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
            {"role": "assistant", "content": content}
        ]
    }


def main():
    parser = argparse.ArgumentParser(description="Prepare LoRA training data from journal entries")
    parser.add_argument('--min-length', type=int, default=200, help='Minimum entry length in chars')
    parser.add_argument('--output-dir', type=str, default=str(BASE_DIR / "workspace" / "lora_data"))
    parser.add_argument('--valid-split', type=float, default=0.1, help='Validation split ratio')
    parser.add_argument('--dry-run', action='store_true', help='Print stats without writing files')
    args = parser.parse_args()

    # Collect entries from both sources
    file_entries = load_journal_files(args.min_length)
    db_entries = load_journal_db(args.min_length)

    # Deduplicate (some entries are in both)
    all_entries = list(set(file_entries + db_entries))
    random.shuffle(all_entries)

    if args.dry_run:
        print(f"\n=== Dry Run Statistics ===")
        print(f"  Journal file entries: {len(file_entries)}")
        print(f"  Journal DB entries:   {len(db_entries)}")
        print(f"  After dedup:          {len(all_entries)}")
        if all_entries:
            lengths = [len(e) for e in all_entries]
            print(f"  Min length:           {min(lengths)} chars")
            print(f"  Max length:           {max(lengths)} chars")
            print(f"  Avg length:           {sum(lengths) // len(lengths)} chars")
            n_valid = max(1, int(len(all_entries) * args.valid_split))
            print(f"  Would write:          {len(all_entries) - n_valid} train, {n_valid} valid examples")
        return

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    print(f"Found {len(file_entries)} file entries, {len(db_entries)} DB entries")
    print(f"After dedup: {len(all_entries)} unique entries (min {args.min_length} chars)")

    if not all_entries:
        print("No entries found! Run the consciousness system first.")
        return

    # Convert to training examples
    examples = [make_training_example(e) for e in all_entries]

    # Split train/valid
    n_valid = max(1, int(len(examples) * args.valid_split))
    valid = examples[:n_valid]
    train = examples[n_valid:]

    # Write JSONL
    train_file = output_dir / "train.jsonl"
    valid_file = output_dir / "valid.jsonl"

    with open(train_file, 'w') as f:
        for ex in train:
            f.write(json.dumps(ex) + '\n')

    with open(valid_file, 'w') as f:
        for ex in valid:
            f.write(json.dumps(ex) + '\n')

    print(f"\nWritten:")
    print(f"  {train_file} ({len(train)} examples)")
    print(f"  {valid_file} ({len(valid)} examples)")
    n_examples = len(train)
    recommended_iters = min(600, max(200, n_examples * 2))

    print(f"\nTo fine-tune (stop the model server first to free ~27GB RAM!):")
    print(f"  mlx_lm.lora \\")
    print(f"    --model ~/models/Qwen3.5-27B-Claude-4.6-Opus-Distilled-mlx-8bit \\")
    print(f"    --data {output_dir} \\")
    print(f"    --adapter-path workspace/lora_adapter \\")
    print(f"    --train --grad-checkpoint \\")
    print(f"    --iters {recommended_iters} --batch-size 1 --num-layers 8 \\")
    print(f"    --learning-rate 2e-5 --steps-per-eval 50 --save-every 100")
    print(f"\n  ({n_examples} training examples -> {recommended_iters} iters = ~{recommended_iters/n_examples:.1f} epochs)")
    print(f"  Peak RAM: ~38GB. Do NOT run alongside the model server.")
    print(f"\nTo serve the fine-tuned model:")
    print(f"  mlx_lm.server \\")
    print(f"    --model ~/models/Qwen3.5-27B-Claude-4.6-Opus-Distilled-mlx-8bit \\")
    print(f"    --adapter-path workspace/lora_adapter \\")
    print(f"    --trust-remote-code --port 8090")


if __name__ == "__main__":
    main()
