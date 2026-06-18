"""
Football Intelligence Platform — Main Runner
Runs the complete pipeline end to end.
"""

from src.models.value_detector import run_value_detection

if __name__ == "__main__":
    value_bets = run_value_detection()
    print(f"\nPipeline complete.")
    print(f"Value bets found: {len(value_bets)}")
    print(f"Full analysis saved to data/value_bets.json")
