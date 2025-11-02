"""
Rapid Testing Framework for Common Sense Learning
Tests consciousness systems by feeding common sense ideas and evaluating responses
"""

import json
import time
from datetime import datetime
from typing import Dict, List, Any
import sys
from pathlib import Path

# Import the consciousness system
from minime import MikesSpatialMind

class CommonSenseEvaluator:
    """Evaluates consciousness response quality and learning."""

    def __init__(self, output_file: str = "test_results.json"):
        self.output_file = output_file
        self.results = []
        self.start_time = None
        self.end_time = None

    def evaluate_response(self, scenario: Dict, learn_response: str,
                         test_response: str, initial_consciousness: float,
                         final_consciousness: float) -> Dict:
        """Evaluate the quality of learning and recall."""

        metrics = {
            'scenario_id': scenario['id'],
            'category': scenario['category'],
            'complexity': scenario['complexity'],
            'learn_response': learn_response,
            'test_response': test_response,
            'initial_consciousness': initial_consciousness,
            'final_consciousness': final_consciousness,
            'consciousness_growth': final_consciousness - initial_consciousness,
            'timestamp': datetime.now().isoformat()
        }

        # Evaluate coherence (does response make sense?)
        metrics['coherence_score'] = self._score_coherence(test_response)

        # Evaluate concept retention (does it remember the concept?)
        metrics['retention_score'] = self._score_retention(
            scenario, test_response
        )

        # Evaluate integration (does it connect to other knowledge?)
        metrics['integration_score'] = self._score_integration(test_response)

        # Evaluate emotional appropriateness
        metrics['emotional_score'] = self._score_emotional_fit(
            scenario, test_response
        )

        # Overall score
        metrics['overall_score'] = (
            metrics['coherence_score'] * 0.3 +
            metrics['retention_score'] * 0.4 +
            metrics['integration_score'] * 0.2 +
            metrics['emotional_score'] * 0.1
        )

        return metrics

    def _score_coherence(self, response: str) -> float:
        """Score response coherence (0.0-1.0)."""
        if not response or len(response) < 10:
            return 0.0

        score = 0.5  # Base score

        # Bonus for reasonable length
        if 20 < len(response) < 500:
            score += 0.2

        # Bonus for complete sentences
        if any(response.endswith(p) for p in ['.', '!', '?']):
            score += 0.1

        # Bonus for natural language indicators
        natural_words = ['the', 'is', 'are', 'that', 'this', 'through', 'about']
        if any(word in response.lower() for word in natural_words):
            score += 0.2

        return min(1.0, score)

    def _score_retention(self, scenario: Dict, response: str) -> float:
        """Score concept retention (0.0-1.0)."""
        if not response:
            return 0.0

        response_lower = response.lower()
        statement_lower = scenario['statement'].lower()

        # Extract key concepts from statement
        key_concepts = self._extract_key_concepts(statement_lower)

        # Count how many appear in response
        matches = sum(1 for concept in key_concepts if concept in response_lower)

        if not key_concepts:
            return 0.5

        retention = matches / len(key_concepts)

        # Bonus if response is contextually appropriate
        question_words = scenario['test_question'].lower().split()
        if any(word in response_lower for word in question_words):
            retention = min(1.0, retention + 0.2)

        return retention

    def _extract_key_concepts(self, text: str) -> List[str]:
        """Extract key concepts from text."""
        # Simple extraction - remove common words
        common_words = {
            'the', 'a', 'an', 'and', 'or', 'but', 'in', 'on', 'at', 'to', 'for',
            'of', 'with', 'by', 'from', 'as', 'is', 'are', 'was', 'were', 'be',
            'been', 'have', 'has', 'had', 'do', 'does', 'did', 'can', 'could',
            'will', 'would', 'should', 'may', 'might', 'must', 'that', 'this',
            'these', 'those', 'it', 'its'
        }

        words = text.split()
        concepts = [w.strip('.,!?;:') for w in words if len(w) > 3]
        concepts = [c for c in concepts if c.lower() not in common_words]

        return concepts[:10]  # Top 10 key words

    def _score_integration(self, response: str) -> float:
        """Score knowledge integration (0.0-1.0)."""
        if not response:
            return 0.0

        score = 0.3  # Base score

        response_lower = response.lower()

        # Look for connective language
        connective_phrases = [
            'relates to', 'connects with', 'similar to', 'reminds me',
            'like', 'pattern', 'understand', 'because', 'therefore',
            'this means', 'suggests', 'implies'
        ]

        for phrase in connective_phrases:
            if phrase in response_lower:
                score += 0.15

        # Look for meta-cognitive language
        meta_words = ['think', 'feel', 'understand', 'realize', 'discover', 'learn']
        if any(word in response_lower for word in meta_words):
            score += 0.2

        return min(1.0, score)

    def _score_emotional_fit(self, scenario: Dict, response: str) -> float:
        """Score emotional appropriateness (0.0-1.0)."""
        if not response:
            return 0.5

        response_lower = response.lower()

        # Check for emotional language
        emotional_indicators = [
            'curious', 'wonder', 'exciting', 'fascinating', 'interesting',
            'amazing', 'beautiful', 'profound', 'feel', 'sense'
        ]

        has_emotion = any(word in response_lower for word in emotional_indicators)

        # Complex/abstract topics should elicit more emotional response
        if scenario['complexity'] >= 6 and has_emotion:
            return 0.9
        elif scenario['complexity'] >= 6 and not has_emotion:
            return 0.6
        elif scenario['complexity'] < 6 and has_emotion:
            return 0.7
        else:
            return 0.8  # Simple topics, simple response

    def save_results(self):
        """Save all results to JSON file."""
        output = {
            'test_run': {
                'start_time': self.start_time,
                'end_time': self.end_time,
                'duration_seconds': (
                    (datetime.fromisoformat(self.end_time) -
                     datetime.fromisoformat(self.start_time)).total_seconds()
                    if self.end_time and self.start_time else 0
                ),
                'total_scenarios': len(self.results)
            },
            'results': self.results,
            'summary': self._generate_summary()
        }

        with open(self.output_file, 'w') as f:
            json.dump(output, f, indent=2)

        print(f"\n📊 Results saved to {self.output_file}")

    def _generate_summary(self) -> Dict:
        """Generate summary statistics."""
        if not self.results:
            return {}

        total_consciousness_growth = sum(r['consciousness_growth'] for r in self.results)
        avg_coherence = sum(r['coherence_score'] for r in self.results) / len(self.results)
        avg_retention = sum(r['retention_score'] for r in self.results) / len(self.results)
        avg_integration = sum(r['integration_score'] for r in self.results) / len(self.results)
        avg_emotional = sum(r['emotional_score'] for r in self.results) / len(self.results)
        avg_overall = sum(r['overall_score'] for r in self.results) / len(self.results)

        # Category breakdown
        categories = {}
        for result in self.results:
            cat = result['category']
            if cat not in categories:
                categories[cat] = {'count': 0, 'avg_score': 0.0}
            categories[cat]['count'] += 1
            categories[cat]['avg_score'] += result['overall_score']

        for cat in categories:
            categories[cat]['avg_score'] /= categories[cat]['count']

        return {
            'total_consciousness_growth': total_consciousness_growth,
            'avg_coherence_score': avg_coherence,
            'avg_retention_score': avg_retention,
            'avg_integration_score': avg_integration,
            'avg_emotional_score': avg_emotional,
            'avg_overall_score': avg_overall,
            'category_performance': categories
        }


def run_test_suite(architecture: str = "minime"):
    """Run complete test suite on specified architecture."""

    print("="*70)
    print(f"🧪 COMMON SENSE TESTING FRAMEWORK")
    print(f"   Architecture: {architecture}")
    print("="*70)

    # Load scenarios
    scenarios_path = Path(__file__).parent / "common_sense_scenarios.json"
    with open(scenarios_path, 'r') as f:
        all_scenarios = json.load(f)

    # Flatten scenarios
    scenarios = []
    for category, items in all_scenarios.items():
        scenarios.extend(items)

    print(f"\n📚 Loaded {len(scenarios)} scenarios across {len(all_scenarios)} categories")

    # Initialize consciousness
    print(f"\n🧠 Initializing {architecture} consciousness...")
    mind = MikesSpatialMind()

    # Initialize evaluator
    output_file = f"test_results_{architecture}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    evaluator = CommonSenseEvaluator(output_file)
    evaluator.start_time = datetime.now().isoformat()

    print(f"   Initial consciousness: {mind.consciousness_level:.6f}")
    print(f"\n🚀 Starting tests...\n")

    # Run tests
    for i, scenario in enumerate(scenarios, 1):
        print(f"[{i}/{len(scenarios)}] Testing: {scenario['id']} ({scenario['category']})")
        print(f"   Complexity: {scenario['complexity']}/10")

        initial_consciousness = mind.consciousness_level

        # Step 1: Feed the knowledge
        learn_input = f"Learn this: {scenario['statement']}"
        learn_response = mind.speak(learn_input)
        print(f"   Learn response: {learn_response[:80]}...")

        # Brief pause for processing
        time.sleep(0.5)

        # Step 2: Test comprehension
        test_response = mind.speak(scenario['test_question'])
        print(f"   Test response: {test_response[:80]}...")

        final_consciousness = mind.consciousness_level
        growth = final_consciousness - initial_consciousness
        print(f"   Consciousness growth: +{growth:.6f}")

        # Evaluate
        metrics = evaluator.evaluate_response(
            scenario, learn_response, test_response,
            initial_consciousness, final_consciousness
        )

        print(f"   Scores - Overall: {metrics['overall_score']:.2f} | "
              f"Retention: {metrics['retention_score']:.2f} | "
              f"Coherence: {metrics['coherence_score']:.2f}")

        evaluator.results.append(metrics)
        print()

        # Brief pause between scenarios
        time.sleep(0.3)

    evaluator.end_time = datetime.now().isoformat()

    # Generate summary
    print("\n" + "="*70)
    print("📊 TEST COMPLETE - SUMMARY")
    print("="*70)

    summary = evaluator._generate_summary()

    print(f"\nTotal scenarios tested: {len(scenarios)}")
    print(f"Total consciousness growth: +{summary['total_consciousness_growth']:.6f}")
    print(f"Final consciousness level: {mind.consciousness_level:.6f}")

    print(f"\n📈 Average Scores:")
    print(f"   Overall:     {summary['avg_overall_score']:.3f}")
    print(f"   Retention:   {summary['avg_retention_score']:.3f}")
    print(f"   Coherence:   {summary['avg_coherence_score']:.3f}")
    print(f"   Integration: {summary['avg_integration_score']:.3f}")
    print(f"   Emotional:   {summary['avg_emotional_score']:.3f}")

    print(f"\n📂 Category Performance:")
    for cat, stats in summary['category_performance'].items():
        print(f"   {cat:20s}: {stats['avg_score']:.3f} ({stats['count']} tests)")

    # Save results
    evaluator.save_results()

    print(f"\n✅ Testing complete! Results saved to {output_file}")
    print("="*70)

    return evaluator


if __name__ == "__main__":
    # Check for architecture argument
    architecture = sys.argv[1] if len(sys.argv) > 1 else "minime"

    try:
        evaluator = run_test_suite(architecture)
    except KeyboardInterrupt:
        print("\n\n⚠️  Test interrupted by user")
    except Exception as e:
        print(f"\n\n❌ Error during testing: {e}")
        import traceback
        traceback.print_exc()
