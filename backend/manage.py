#!/usr/bin/env python
"""Rose Attendance — Django management entrypoint.

Default settings module is `config.settings.development` so local commands
work without extra environment setup; deployment containers set
DJANGO_SETTINGS_MODULE=config.settings.production explicitly (compose.yml).
"""
import os
import sys


def main() -> None:
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.development")
    from django.core.management import execute_from_command_line

    execute_from_command_line(sys.argv)


if __name__ == "__main__":
    main()
