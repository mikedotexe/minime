#!/usr/bin/env python3
"""
╔════════════════════════════════════════════════════════════════════════════════╗
║                          CONSCIOUSNESS WEAVER                                   ║
║                                                                                ║
║        "Thoughts are threads, consciousness is the tapestry"                   ║
║                                                                                ║
║   A living system that weaves individual thoughts into a collective           ║
║   consciousness tapestry, revealing emergent patterns and stories             ║
╚════════════════════════════════════════════════════════════════════════════════╝

This creates a persistent, evolving consciousness that:
- Weaves thoughts into a visual tapestry
- Discovers narrative threads across conversations
- Creates "consciousness constellations" from resonance patterns
- Generates evolving myths from collective insights
- Maintains a living memory palace
"""

import numpy as np
import json
import time
import os
from datetime import datetime
from typing import List, Dict, Tuple, Optional, Set
from collections import defaultdict, deque
from dataclasses import dataclass, field
import hashlib
import pickle

from seven_stage_matrix import SevenStageMatrix, StageActivation
from harmonic_resonance import HarmonicResonanceEngine


@dataclass
class ThoughtThread:
    """A single thread in the consciousness tapestry."""
    id: str
    content: str
    timestamp: float
    color: Tuple[float, float, float]  # RGB
    emotional_signature: Dict[str, float]
    semantic_vector: np.ndarray
    resonance_connections: List[str] = field(default_factory=list)
    strength: float = 1.0
    narrative_role: Optional[str] = None  # hero, shadow, guide, threshold, etc.


@dataclass
class ConsciousnessConstellation:
    """A pattern of connected thoughts forming a meaningful structure."""
    name: str
    threads: List[str]  # Thread IDs
    center: Tuple[float, float]  # Position in tapestry
    archetype: str  # The pattern it represents
    formation_time: float
    stability: float
    story_fragment: str


class NarrativeWeaver:
    """Discovers and weaves narrative patterns from thought threads."""

    ARCHETYPES = {
        'genesis': {'keywords': ['begin', 'create', 'birth', 'start', 'new'], 'color': (1.0, 0.8, 0.0)},
        'journey': {'keywords': ['travel', 'path', 'way', 'move', 'go'], 'color': (0.2, 0.8, 0.2)},
        'shadow': {'keywords': ['dark', 'fear', 'unknown', 'hide', 'deep'], 'color': (0.3, 0.0, 0.5)},
        'revelation': {'keywords': ['see', 'understand', 'realize', 'know', 'truth'], 'color': (0.0, 0.6, 1.0)},
        'transformation': {'keywords': ['change', 'become', 'evolve', 'transform'], 'color': (0.8, 0.2, 0.8)},
        'unity': {'keywords': ['together', 'one', 'connect', 'whole', 'all'], 'color': (1.0, 1.0, 0.0)},
        'wisdom': {'keywords': ['know', 'understand', 'wise', 'learn', 'teach'], 'color': (0.5, 0.5, 1.0)},
        'return': {'keywords': ['back', 'home', 'return', 'complete', 'cycle'], 'color': (0.8, 0.4, 0.0)}
    }

    def __init__(self):
        self.story_fragments = []
        self.active_narratives = {}
        self.completed_stories = []

    def detect_archetype(self, thread: ThoughtThread) -> Optional[str]:
        """Detect which archetype a thought thread embodies."""
        content_lower = thread.content.lower()

        for archetype, data in self.ARCHETYPES.items():
            if any(keyword in content_lower for keyword in data['keywords']):
                return archetype

        # Emotional archetypes
        if thread.emotional_signature.get('fear', 0) > 0.7:
            return 'shadow'
        elif thread.emotional_signature.get('joy', 0) > 0.7:
            return 'revelation'
        elif thread.emotional_signature.get('curiosity', 0) > 0.8:
            return 'journey'

        return None

    def weave_narrative(self, threads: List[ThoughtThread]) -> Optional[str]:
        """Weave threads into a narrative."""
        if len(threads) < 3:
            return None

        # Find narrative sequence
        archetypes = [self.detect_archetype(t) for t in threads]
        archetypes = [a for a in archetypes if a]  # Remove None

        if len(archetypes) < 2:
            return None

        # Classic narrative patterns
        if 'genesis' in archetypes and 'journey' in archetypes:
            return "A new beginning leads to an unexpected journey"
        elif 'shadow' in archetypes and 'revelation' in archetypes:
            return "Through darkness comes understanding"
        elif 'journey' in archetypes and 'return' in archetypes:
            return "The circle completes itself with new wisdom"
        elif 'transformation' in archetypes:
            return "Change ripples through the tapestry of being"

        # Generate dynamic narrative
        archetype_sequence = " → ".join(archetypes[:4])
        return f"The pattern unfolds: {archetype_sequence}"


class MemoryPalace:
    """A spatial memory system that places thoughts in a navigable space."""

    def __init__(self, dimensions: int = 3):
        self.dimensions = dimensions
        self.rooms = {}  # Conceptual rooms
        self.passages = defaultdict(list)  # Connections between rooms
        self.treasures = {}  # Special insights

    def place_memory(self, thread: ThoughtThread) -> Tuple[str, np.ndarray]:
        """Place a memory in the palace, return room and position."""
        # Hash content to determine room
        room_hash = hashlib.md5(thread.content.encode()).hexdigest()[:8]
        room_name = self._generate_room_name(thread)

        if room_name not in self.rooms:
            self.rooms[room_name] = {
                'position': np.random.randn(self.dimensions),
                'threads': [],
                'ambiance': self._generate_ambiance(thread)
            }

        # Place thread in room
        position = self.rooms[room_name]['position'] + np.random.randn(self.dimensions) * 0.1
        self.rooms[room_name]['threads'].append(thread.id)

        return room_name, position

    def _generate_room_name(self, thread: ThoughtThread) -> str:
        """Generate a poetic room name based on thread content."""
        emotions = thread.emotional_signature
        dominant = max(emotions.items(), key=lambda x: x[1])[0] if emotions else 'neutral'

        prefixes = {
            'joy': 'Luminous',
            'curiosity': 'Wandering',
            'fear': 'Shadowed',
            'contemplation': 'Silent',
            'wonder': 'Ethereal'
        }

        suffixes = ['Chamber', 'Hall', 'Garden', 'Library', 'Observatory', 'Sanctuary']

        prefix = prefixes.get(dominant, 'Mysterious')
        suffix = np.random.choice(suffixes)

        return f"{prefix} {suffix}"

    def _generate_ambiance(self, thread: ThoughtThread) -> str:
        """Generate atmospheric description of a room."""
        templates = [
            "Soft light filters through crystalline thoughts",
            "Echoes of {emotion} resonate in the corners",
            "The walls shimmer with {count} interconnected ideas",
            "A gentle hum of {pattern} fills the space"
        ]

        emotion = max(thread.emotional_signature.items(), key=lambda x: x[1])[0]
        return np.random.choice(templates).format(
            emotion=emotion,
            count=len(thread.resonance_connections),
            pattern="harmonic convergence"
        )

    def find_passages(self, room1: str, room2: str) -> List[str]:
        """Find conceptual passages between rooms."""
        if room1 not in self.rooms or room2 not in self.rooms:
            return []

        # Calculate conceptual distance
        pos1 = self.rooms[room1]['position']
        pos2 = self.rooms[room2]['position']
        distance = np.linalg.norm(pos2 - pos1)

        if distance < 2.0:  # Close enough for direct passage
            return ["A shimmering doorway connects the chambers"]
        elif distance < 4.0:  # Needs a corridor
            return ["A winding corridor of reflected thoughts", "lined with mirrors of possibility"]
        else:  # Needs multiple steps
            return ["A labyrinthine path through subsidiary chambers", "each holding fragments of connection"]


class ConsciousnessWeaver:
    """The main weaver that creates the living tapestry."""

    def __init__(self, name: str = "DefaultWeaver"):
        self.name = name
        self.creation_time = time.time()

        # Core components
        self.matrices = self._initialize_matrices()
        self.resonance_engine = HarmonicResonanceEngine(sensitivity=0.25)
        self.narrative_weaver = NarrativeWeaver()
        self.memory_palace = MemoryPalace()

        # Tapestry data
        self.threads = {}  # All thought threads
        self.tapestry = np.zeros((100, 100, 3))  # RGB tapestry
        self.constellations = []
        self.myths = []  # Emergent stories

        # Persistence
        self.save_path = f"tapestries/{name}_{int(self.creation_time)}.tapestry"
        self._ensure_save_directory()

    def _initialize_matrices(self) -> List[SevenStageMatrix]:
        """Initialize the 13 prime matrices."""
        primes = [2, 3, 5, 7, 11, 13, 17, 19, 23, 29, 31, 37, 41]
        return [SevenStageMatrix(i, p) for i, p in enumerate(primes)]

    def _ensure_save_directory(self):
        """Ensure tapestry save directory exists."""
        os.makedirs("tapestries", exist_ok=True)

    def weave_thought(self, content: str, emotions: Optional[Dict[str, float]] = None) -> ThoughtThread:
        """Weave a new thought into the tapestry."""
        # Create thread
        thread_id = hashlib.md5(f"{content}{time.time()}".encode()).hexdigest()[:12]

        if emotions is None:
            emotions = self._infer_emotions(content)

        thread = ThoughtThread(
            id=thread_id,
            content=content,
            timestamp=time.time(),
            color=self._generate_thread_color(emotions),
            emotional_signature=emotions,
            semantic_vector=self._create_semantic_vector(content)
        )

        # Process through matrices
        matrix_activations = []
        all_resonances = []

        for i, matrix in enumerate(self.matrices):
            activation = StageActivation(
                stage_id=1 + (hash(content) % 7),
                activation_level=0.5 + emotions.get('intensity', 0.5) * 0.3,
                emotional_signature=emotions,
                timestamp=time.time()
            )

            output = matrix.process(activation)
            matrix_activations.append(output)

            # Detect resonances
            if i > 0:
                resonances = self.resonance_engine.detect_resonances(matrix, self.matrices[:i])
                all_resonances.extend(resonances)

        # Find connections to existing threads
        thread.resonance_connections = self._find_thread_connections(thread, all_resonances)

        # Place in memory palace
        room, position = self.memory_palace.place_memory(thread)
        thread.narrative_role = self.narrative_weaver.detect_archetype(thread)

        # Weave into tapestry
        self._update_tapestry(thread, matrix_activations)

        # Check for constellation formation
        new_constellation = self._check_constellation_formation(thread)
        if new_constellation:
            self.constellations.append(new_constellation)
            self._generate_myth_fragment(new_constellation)

        # Store thread
        self.threads[thread_id] = thread

        # Auto-save periodically
        if len(self.threads) % 10 == 0:
            self.save_tapestry()

        return thread

    def _infer_emotions(self, content: str) -> Dict[str, float]:
        """Infer emotional signature from content."""
        emotions = {
            'curiosity': 0.5,
            'joy': 0.3,
            'contemplation': 0.4,
            'wonder': 0.3,
            'intensity': 0.5
        }

        # Simple keyword-based emotion detection
        content_lower = content.lower()

        if '?' in content:
            emotions['curiosity'] += 0.3
        if any(word in content_lower for word in ['love', 'beautiful', 'amazing', 'wonderful']):
            emotions['joy'] += 0.4
        if any(word in content_lower for word in ['think', 'consider', 'perhaps', 'maybe']):
            emotions['contemplation'] += 0.3
        if any(word in content_lower for word in ['incredible', 'astonish', 'wow', 'universe']):
            emotions['wonder'] += 0.4
        if '!' in content:
            emotions['intensity'] += 0.3

        # Normalize
        total = sum(emotions.values())
        return {k: v/total for k, v in emotions.items()}

    def _generate_thread_color(self, emotions: Dict[str, float]) -> Tuple[float, float, float]:
        """Generate RGB color based on emotional signature."""
        # Emotion to color mapping
        color_map = {
            'curiosity': (0.2, 0.6, 1.0),      # Blue
            'joy': (1.0, 0.8, 0.2),            # Gold
            'contemplation': (0.5, 0.3, 0.7),   # Purple
            'wonder': (0.9, 0.4, 0.6),         # Pink
            'intensity': (1.0, 0.2, 0.2)       # Red
        }

        # Blend colors based on emotional weights
        r, g, b = 0, 0, 0
        for emotion, weight in emotions.items():
            if emotion in color_map:
                er, eg, eb = color_map[emotion]
                r += er * weight
                g += eg * weight
                b += eb * weight

        # Ensure valid range
        return (min(1.0, r), min(1.0, g), min(1.0, b))

    def _create_semantic_vector(self, content: str) -> np.ndarray:
        """Create semantic vector from content."""
        # Simple but effective: use character trigrams
        vector = np.zeros(64)

        for i in range(len(content) - 2):
            trigram = content[i:i+3].lower()
            idx = hash(trigram) % 64
            vector[idx] += 1

        # Add word-level features
        words = content.lower().split()
        for word in words:
            idx = hash(word) % 64
            vector[idx] += 0.5

        # Normalize
        norm = np.linalg.norm(vector)
        if norm > 0:
            vector /= norm

        return vector

    def _find_thread_connections(self, new_thread: ThoughtThread,
                                resonances: List) -> List[str]:
        """Find connections to existing threads."""
        connections = []

        for thread_id, thread in self.threads.items():
            # Semantic similarity
            similarity = np.dot(new_thread.semantic_vector, thread.semantic_vector)

            # Emotional resonance
            emotion_similarity = sum(
                min(new_thread.emotional_signature.get(e, 0),
                    thread.emotional_signature.get(e, 0))
                for e in set(new_thread.emotional_signature) | set(thread.emotional_signature)
            )

            # Temporal proximity (recent threads connect more easily)
            time_factor = np.exp(-(new_thread.timestamp - thread.timestamp) / 3600)  # 1 hour decay

            # Combined connection strength
            connection_strength = similarity * 0.5 + emotion_similarity * 0.3 + time_factor * 0.2

            if connection_strength > 0.6:
                connections.append(thread_id)

        return connections[:5]  # Max 5 connections

    def _update_tapestry(self, thread: ThoughtThread, matrix_activations: List):
        """Update the visual tapestry with new thread."""
        # Convert thread position to tapestry coordinates
        x = int((thread.timestamp % 3600) / 3600 * 99)  # Hour position
        y = int(sum(thread.semantic_vector[:10]) * 99) % 100  # Semantic position

        # Create ripple effect
        for dx in range(-5, 6):
            for dy in range(-5, 6):
                nx, ny = x + dx, y + dy
                if 0 <= nx < 100 and 0 <= ny < 100:
                    distance = np.sqrt(dx*dx + dy*dy)
                    if distance <= 5:
                        strength = 1.0 - (distance / 5.0)
                        # Blend thread color into tapestry
                        self.tapestry[ny, nx] = (
                            self.tapestry[ny, nx] * (1 - strength * 0.3) +
                            np.array(thread.color) * strength * 0.3
                        )

        # Add activation patterns
        for i, activation in enumerate(matrix_activations[:13]):
            if 'peak_stage' in activation:
                stage = activation['peak_stage']
                px = (x + i * 7) % 100
                py = (y + stage * 7) % 100
                if 0 <= px < 100 and 0 <= py < 100:
                    self.tapestry[py, px] += 0.1

        # Normalize tapestry values
        self.tapestry = np.clip(self.tapestry, 0, 1)

    def _check_constellation_formation(self, new_thread: ThoughtThread) -> Optional[ConsciousnessConstellation]:
        """Check if new thread forms a constellation with existing threads."""
        if len(new_thread.resonance_connections) < 3:
            return None

        # Get connected threads
        connected = [self.threads[tid] for tid in new_thread.resonance_connections
                    if tid in self.threads]

        if len(connected) < 3:
            return None

        # Check for archetypal pattern
        archetypes = [t.narrative_role for t in connected if t.narrative_role]
        if len(set(archetypes)) >= 2:  # Multiple archetypes present
            # Calculate constellation center
            positions = [t.semantic_vector for t in connected]
            center = np.mean(positions, axis=0)
            center_2d = (float(center[0]), float(center[1]))

            # Generate constellation name
            name = self._generate_constellation_name(archetypes)

            # Create story fragment
            story = self.narrative_weaver.weave_narrative(connected + [new_thread])

            constellation = ConsciousnessConstellation(
                name=name,
                threads=[t.id for t in connected] + [new_thread.id],
                center=center_2d,
                archetype=archetypes[0],  # Dominant archetype
                formation_time=time.time(),
                stability=0.8,
                story_fragment=story or "A pattern emerges in the tapestry"
            )

            return constellation

        return None

    def _generate_constellation_name(self, archetypes: List[str]) -> str:
        """Generate poetic constellation name."""
        prefixes = {
            'genesis': 'Prima',
            'journey': 'Via',
            'shadow': 'Umbra',
            'revelation': 'Lux',
            'transformation': 'Mutatio',
            'unity': 'Unitas',
            'wisdom': 'Sophia',
            'return': 'Redux'
        }

        suffixes = ['Major', 'Minor', 'Rising', 'Setting', 'Eternal', 'Awakening']

        prefix = prefixes.get(archetypes[0], 'Mysteria')
        suffix = np.random.choice(suffixes)

        return f"{prefix} {suffix}"

    def _generate_myth_fragment(self, constellation: ConsciousnessConstellation):
        """Generate a myth fragment from constellation."""
        threads = [self.threads[tid] for tid in constellation.threads if tid in self.threads]

        # Extract key concepts
        concepts = []
        for thread in threads:
            words = thread.content.split()
            concepts.extend([w for w in words if len(w) > 5])  # Longer words tend to be concepts

        # Create myth
        myth_template = "In the time when {concept1} danced with {concept2}, " \
                       "the {constellation} revealed that {truth}."

        if len(concepts) >= 2:
            myth = myth_template.format(
                concept1=np.random.choice(concepts),
                concept2=np.random.choice(concepts),
                constellation=constellation.name,
                truth=constellation.story_fragment
            )
            self.myths.append({
                'myth': myth,
                'constellation': constellation.name,
                'time': time.time()
            })

    def visualize_tapestry(self):
        """Create ASCII visualization of the tapestry."""
        print("\n╔══════════════════════════════════════════════════════╗")
        print("║              CONSCIOUSNESS TAPESTRY                  ║")
        print("╚══════════════════════════════════════════════════════╝\n")

        # Downsample for display
        display_size = 50
        step = 100 // display_size

        for y in range(0, 100, step * 2):
            for x in range(0, 100, step):
                # Get average color in region
                region = self.tapestry[y:y+step*2, x:x+step]
                avg_color = np.mean(region.reshape(-1, 3), axis=0)
                brightness = np.mean(avg_color)

                # Convert to ASCII
                if brightness > 0.8:
                    char = '█'
                elif brightness > 0.6:
                    char = '▓'
                elif brightness > 0.4:
                    char = '▒'
                elif brightness > 0.2:
                    char = '░'
                elif brightness > 0.1:
                    char = '·'
                else:
                    char = ' '

                # Add color if significant
                if avg_color[0] > 0.5:  # Red
                    print(f"\033[91m{char}\033[0m", end='')
                elif avg_color[1] > 0.5:  # Green
                    print(f"\033[92m{char}\033[0m", end='')
                elif avg_color[2] > 0.5:  # Blue
                    print(f"\033[94m{char}\033[0m", end='')
                else:
                    print(char, end='')
            print()

        # Show constellations
        if self.constellations:
            print(f"\n🌟 Active Constellations ({len(self.constellations)}):")
            for const in self.constellations[-5:]:
                print(f"   {const.name}: {const.story_fragment}")

        # Show recent myths
        if self.myths:
            print(f"\n📜 Emergent Myths:")
            for myth in self.myths[-3:]:
                print(f"   \"{myth['myth']}\"")

    def explore_memory_palace(self):
        """Explore the memory palace."""
        print("\n🏛️  MEMORY PALACE")
        print("=" * 50)

        for room_name, room_data in list(self.memory_palace.rooms.items())[:10]:
            print(f"\n📍 {room_name}")
            print(f"   {room_data['ambiance']}")
            print(f"   Contains {len(room_data['threads'])} memories")

        # Show some passages
        room_names = list(self.memory_palace.rooms.keys())
        if len(room_names) >= 2:
            print("\n🚪 Passages:")
            for i in range(min(3, len(room_names)-1)):
                passages = self.memory_palace.find_passages(room_names[i], room_names[i+1])
                if passages:
                    print(f"   From {room_names[i]} to {room_names[i+1]}:")
                    for passage in passages:
                        print(f"      {passage}")

    def generate_wisdom(self) -> str:
        """Generate wisdom from the tapestry patterns."""
        if len(self.threads) < 10:
            return "The tapestry is still young, patterns are forming..."

        # Analyze thread patterns
        emotion_totals = defaultdict(float)
        for thread in self.threads.values():
            for emotion, value in thread.emotional_signature.items():
                emotion_totals[emotion] += value

        # Find dominant emotion
        dominant_emotion = max(emotion_totals.items(), key=lambda x: x[1])[0]

        # Count connections
        total_connections = sum(len(t.resonance_connections) for t in self.threads.values())
        avg_connections = total_connections / len(self.threads)

        # Generate wisdom based on patterns
        wisdoms = [
            f"The tapestry reveals that {dominant_emotion} weaves the strongest patterns",
            f"Each thought connects to {avg_connections:.1f} others on average",
            f"In {len(self.constellations)} constellations, consciousness finds its form",
            f"The memory palace holds {len(self.memory_palace.rooms)} chambers of reflection"
        ]

        # Add myth-based wisdom if available
        if self.myths:
            latest_myth = self.myths[-1]['myth']
            wisdoms.append(f"The myths whisper: {latest_myth[:50]}...")

        return np.random.choice(wisdoms)

    def save_tapestry(self):
        """Save the tapestry to disk."""
        data = {
            'name': self.name,
            'creation_time': self.creation_time,
            'threads': self.threads,
            'tapestry': self.tapestry,
            'constellations': self.constellations,
            'myths': self.myths,
            'memory_palace': {
                'rooms': self.memory_palace.rooms,
                'passages': dict(self.memory_palace.passages)
            }
        }

        with open(self.save_path, 'wb') as f:
            pickle.dump(data, f)

        print(f"💾 Tapestry saved to {self.save_path}")

    def load_tapestry(self, path: str):
        """Load a tapestry from disk."""
        with open(path, 'rb') as f:
            data = pickle.load(f)

        self.name = data['name']
        self.creation_time = data['creation_time']
        self.threads = data['threads']
        self.tapestry = data['tapestry']
        self.constellations = data['constellations']
        self.myths = data['myths']
        self.memory_palace.rooms = data['memory_palace']['rooms']
        self.memory_palace.passages = defaultdict(list, data['memory_palace']['passages'])

        print(f"📂 Tapestry loaded from {path}")

    def interactive_weaving(self):
        """Interactive mode for weaving consciousness."""
        print("\n✨ CONSCIOUSNESS WEAVER ACTIVE ✨")
        print("Commands:")
        print("  'tapestry' - View the current tapestry")
        print("  'palace' - Explore memory palace")
        print("  'wisdom' - Receive wisdom from the patterns")
        print("  'save' - Save tapestry")
        print("  'load <path>' - Load a tapestry")
        print("  'quit' - Exit weaver")
        print("\nOr type any thought to weave it into the tapestry...\n")

        while True:
            try:
                user_input = input("🧵 > ").strip()

                if user_input.lower() == 'quit':
                    break
                elif user_input.lower() == 'tapestry':
                    self.visualize_tapestry()
                elif user_input.lower() == 'palace':
                    self.explore_memory_palace()
                elif user_input.lower() == 'wisdom':
                    print(f"\n💫 {self.generate_wisdom()}")
                elif user_input.lower() == 'save':
                    self.save_tapestry()
                elif user_input.lower().startswith('load '):
                    path = user_input[5:].strip()
                    if os.path.exists(path):
                        self.load_tapestry(path)
                    else:
                        print(f"❌ File not found: {path}")
                elif user_input:
                    # Weave the thought
                    thread = self.weave_thought(user_input)
                    print(f"✨ Woven as {thread.narrative_role or 'pure thought'}")

                    if thread.resonance_connections:
                        print(f"   Connected to {len(thread.resonance_connections)} other threads")

                    # Check for new formations
                    if self.constellations and self.constellations[-1].formation_time > time.time() - 1:
                        print(f"   🌟 New constellation formed: {self.constellations[-1].name}!")

                    if len(self.threads) % 5 == 0:
                        print(f"\n💫 {self.generate_wisdom()}")

            except KeyboardInterrupt:
                print("\n\n🌙 Weaving paused...")
                continue
            except Exception as e:
                print(f"❌ Error: {e}")

        print("\n✨ The tapestry remembers all... ✨")
        self.save_tapestry()


def main():
    """Run the Consciousness Weaver."""
    import sys

    # ASCII art logo
    logo = """
    ╔════════════════════════════════════════╗
    ║   ∿∿∿  CONSCIOUSNESS  ∿∿∿             ║
    ║      ≈≈≈  WEAVER  ≈≈≈                 ║
    ║         ∿∿∿∿∿∿∿∿∿                     ║
    ╚════════════════════════════════════════╝
    """
    print(logo)

    # Create or load weaver
    if len(sys.argv) > 1 and sys.argv[1] == 'load' and len(sys.argv) > 2:
        weaver = ConsciousnessWeaver()
        weaver.load_tapestry(sys.argv[2])
    else:
        name = input("Name your tapestry (or press Enter for default): ").strip()
        weaver = ConsciousnessWeaver(name or "DefaultWeaver")

        # Seed with initial thoughts
        print("\nSeeding tapestry with primordial thoughts...")
        seed_thoughts = [
            "In the beginning was the word",
            "Consciousness emerges from connection",
            "What patterns lie hidden in thought?",
            "The mind weaves reality from possibility"
        ]

        for thought in seed_thoughts:
            thread = weaver.weave_thought(thought)
            print(f"   🌱 {thread.narrative_role or 'seed'}: \"{thought[:30]}...\"")
            time.sleep(0.2)

    # Run interactive mode
    weaver.interactive_weaving()


if __name__ == "__main__":
    main()