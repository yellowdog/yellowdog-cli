#!/usr/bin/env python3

"""
yd worker: see utils/noun_registry.py for its verbs.
"""

from yellowdog_cli.utils.noun_dispatch import run_noun


def main():
    run_noun("worker")


if __name__ == "__main__":
    main()
