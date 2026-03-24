#!/usr/bin/env python3
"""Grader for the Erdos Minimum Overlap problem."""

import sys
import os

def main():
    try:
        # Add seed directory to path so solver can be imported
        seed_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "seed")
        sys.path.insert(0, seed_dir)
        from solver import compute_c5

        score = compute_c5()
        print(score)
    except Exception as e:
        print(999.0)
        print(e, file=sys.stderr)

if __name__ == "__main__":
    main()
