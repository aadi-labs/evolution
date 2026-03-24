#!/usr/bin/env python3
"""Grader for the Stanford OpenVaccine benchmark."""

import sys
import os

def main():
    try:
        seed_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "seed")
        sys.path.insert(0, seed_dir)
        from model import evaluate

        score = evaluate()
        print(score)
    except Exception as e:
        print(999.0)
        print(e, file=sys.stderr)

if __name__ == "__main__":
    main()
