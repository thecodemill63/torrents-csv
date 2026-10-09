#!/usr/bin/env python
"""Django management entrypoint for the torrent search UI."""
import os
import sys


def main():
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "torrentsearch.settings")
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from django.core.management import execute_from_command_line
    execute_from_command_line(sys.argv)


if __name__ == "__main__":
    main()
