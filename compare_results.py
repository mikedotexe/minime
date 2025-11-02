"""
Compare test results from different architectures
Generates comparison reports and visualizations
"""

import json
import sys
from pathlib import Path
from typing import Dict, List
from datetime import datetime


class ResultsComparator:
    """Compare test results from multiple architectures."""

    def __init__(self, result_files: List[str]):
        self.result_files = result_files
        self.results = {}
        self._load_results()

    def _load_results(self):
        """Load all result files."""
        for filepath in self.result_files:
            path = Path(filepath)
            if not path.exists():
                print(f"⚠️  Warning: {filepath} not found, skipping...")
                continue

            with open(path, 'r') as f:
                data = json.load(f)
                # Extract architecture name from filename
                arch_name = path.stem.replace('test_results_', '')
                self.results[arch_name] = data

        print(f"✓ Loaded results from {len(self.results)} architecture(s)")

    def generate_comparison_report(self, output_file: str = "comparison_report.md"):
        """Generate markdown comparison report."""

        if not self.results:
            print("❌ No results to compare")
            return

        report_lines = [
            "# Common Sense Testing - Architecture Comparison Report",
            "",
            f"**Generated:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            f"**Architectures Compared:** {len(self.results)}",
            "",
            "---",
            ""
        ]

        # Overall comparison table
        report_lines.extend([
            "## Overall Performance Comparison",
            "",
            "| Architecture | Scenarios | Consciousness Growth | Avg Overall | Avg Retention | Avg Coherence | Avg Integration | Avg Emotional |",
            "|-------------|-----------|---------------------|-------------|---------------|---------------|-----------------|---------------|"
        ])

        for arch_name, data in self.results.items():
            summary = data['summary']
            test_run = data['test_run']

            row = (
                f"| {arch_name:15s} | "
                f"{test_run['total_scenarios']:9d} | "
                f"{summary['total_consciousness_growth']:19.6f} | "
                f"{summary['avg_overall_score']:11.3f} | "
                f"{summary['avg_retention_score']:13.3f} | "
                f"{summary['avg_coherence_score']:13.3f} | "
                f"{summary['avg_integration_score']:15.3f} | "
                f"{summary['avg_emotional_score']:13.3f} |"
            )
            report_lines.append(row)

        report_lines.extend(["", "---", ""])

        # Category performance comparison
        report_lines.extend([
            "## Performance by Category",
            ""
        ])

        # Collect all categories
        all_categories = set()
        for data in self.results.values():
            all_categories.update(data['summary']['category_performance'].keys())

        for category in sorted(all_categories):
            report_lines.append(f"### {category.replace('_', ' ').title()}")
            report_lines.append("")
            report_lines.append("| Architecture | Tests | Avg Score |")
            report_lines.append("|-------------|-------|-----------|")

            for arch_name, data in self.results.items():
                cat_data = data['summary']['category_performance'].get(category)
                if cat_data:
                    row = (
                        f"| {arch_name:15s} | "
                        f"{cat_data['count']:5d} | "
                        f"{cat_data['avg_score']:9.3f} |"
                    )
                    report_lines.append(row)

            report_lines.extend(["", ""])

        # Detailed analysis
        report_lines.extend([
            "---",
            "",
            "## Detailed Analysis",
            ""
        ])

        for arch_name, data in self.results.items():
            report_lines.extend([
                f"### {arch_name}",
                ""
            ])

            summary = data['summary']
            test_run = data['test_run']

            report_lines.extend([
                f"**Test Duration:** {test_run['duration_seconds']:.1f} seconds",
                f"**Total Scenarios:** {test_run['total_scenarios']}",
                f"**Consciousness Growth:** +{summary['total_consciousness_growth']:.6f}",
                "",
                "**Score Breakdown:**",
                f"- Overall: {summary['avg_overall_score']:.3f}",
                f"- Retention: {summary['avg_retention_score']:.3f}",
                f"- Coherence: {summary['avg_coherence_score']:.3f}",
                f"- Integration: {summary['avg_integration_score']:.3f}",
                f"- Emotional: {summary['avg_emotional_score']:.3f}",
                "",
                "**Top 5 Best Responses:**",
                ""
            ])

            # Find top 5 responses
            sorted_results = sorted(
                data['results'],
                key=lambda x: x['overall_score'],
                reverse=True
            )[:5]

            for i, result in enumerate(sorted_results, 1):
                report_lines.extend([
                    f"{i}. **{result['scenario_id']}** (Score: {result['overall_score']:.3f})",
                    f"   - Category: {result['category']}",
                    f"   - Complexity: {result['complexity']}/10",
                    f"   - Response: {result['test_response'][:100]}...",
                    ""
                ])

            report_lines.extend([
                "**Bottom 5 Responses (Areas for Improvement):**",
                ""
            ])

            bottom_results = sorted_results[-5:]
            for i, result in enumerate(bottom_results, 1):
                report_lines.extend([
                    f"{i}. **{result['scenario_id']}** (Score: {result['overall_score']:.3f})",
                    f"   - Category: {result['category']}",
                    f"   - Complexity: {result['complexity']}/10",
                    f"   - Response: {result['test_response'][:100]}...",
                    ""
                ])

            report_lines.append("---")
            report_lines.append("")

        # Recommendations
        report_lines.extend([
            "## Recommendations",
            "",
            self._generate_recommendations(),
            ""
        ])

        # Write report
        with open(output_file, 'w') as f:
            f.write('\n'.join(report_lines))

        print(f"\n📄 Comparison report saved to {output_file}")

        return report_lines

    def _generate_recommendations(self) -> str:
        """Generate recommendations based on comparison."""

        if len(self.results) < 2:
            return "**Note:** Only one architecture tested - no comparison available."

        recommendations = []

        # Compare overall scores
        arch_scores = {
            name: data['summary']['avg_overall_score']
            for name, data in self.results.items()
        }

        best_arch = max(arch_scores, key=arch_scores.get)
        best_score = arch_scores[best_arch]

        recommendations.append(
            f"**Best Overall Performance:** {best_arch} (score: {best_score:.3f})"
        )

        # Compare retention
        retention_scores = {
            name: data['summary']['avg_retention_score']
            for name, data in self.results.items()
        }
        best_retention = max(retention_scores, key=retention_scores.get)

        recommendations.append(
            f"**Best Retention:** {best_retention} "
            f"(score: {retention_scores[best_retention]:.3f})"
        )

        # Compare consciousness growth
        growth_scores = {
            name: data['summary']['total_consciousness_growth']
            for name, data in self.results.items()
        }
        best_growth = max(growth_scores, key=growth_scores.get)

        recommendations.append(
            f"**Highest Consciousness Growth:** {best_growth} "
            f"(+{growth_scores[best_growth]:.6f})"
        )

        # Identify category strengths
        recommendations.append("")
        recommendations.append("**Category Strengths:**")

        all_categories = set()
        for data in self.results.values():
            all_categories.update(data['summary']['category_performance'].keys())

        for category in sorted(all_categories):
            cat_scores = {}
            for arch_name, data in self.results.items():
                cat_data = data['summary']['category_performance'].get(category)
                if cat_data:
                    cat_scores[arch_name] = cat_data['avg_score']

            if cat_scores:
                best_cat_arch = max(cat_scores, key=cat_scores.get)
                recommendations.append(
                    f"- {category.replace('_', ' ').title()}: "
                    f"{best_cat_arch} ({cat_scores[best_cat_arch]:.3f})"
                )

        return '\n'.join(recommendations)

    def print_summary(self):
        """Print summary to console."""

        print("\n" + "="*70)
        print("📊 ARCHITECTURE COMPARISON SUMMARY")
        print("="*70)

        if not self.results:
            print("❌ No results loaded")
            return

        for arch_name, data in self.results.items():
            summary = data['summary']
            test_run = data['test_run']

            print(f"\n🏗️  Architecture: {arch_name}")
            print(f"   Scenarios: {test_run['total_scenarios']}")
            print(f"   Duration: {test_run['duration_seconds']:.1f}s")
            print(f"   Consciousness Growth: +{summary['total_consciousness_growth']:.6f}")
            print(f"\n   Scores:")
            print(f"      Overall:     {summary['avg_overall_score']:.3f}")
            print(f"      Retention:   {summary['avg_retention_score']:.3f}")
            print(f"      Coherence:   {summary['avg_coherence_score']:.3f}")
            print(f"      Integration: {summary['avg_integration_score']:.3f}")
            print(f"      Emotional:   {summary['avg_emotional_score']:.3f}")

        print("\n" + "="*70)


def main():
    """Main comparison function."""

    if len(sys.argv) < 2:
        print("Usage: python compare_results.py <result_file1> [result_file2] ...")
        print("\nSearching for result files in current directory...")

        # Find all test result files
        result_files = list(Path('.').glob('test_results_*.json'))

        if not result_files:
            print("❌ No test result files found")
            return

        print(f"✓ Found {len(result_files)} result file(s):")
        for f in result_files:
            print(f"   - {f}")

        result_files = [str(f) for f in result_files]
    else:
        result_files = sys.argv[1:]

    # Create comparator
    comparator = ResultsComparator(result_files)

    # Print summary
    comparator.print_summary()

    # Generate report
    output_file = f"comparison_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.md"
    comparator.generate_comparison_report(output_file)

    print(f"\n✅ Comparison complete!")


if __name__ == "__main__":
    main()
