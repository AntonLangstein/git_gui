#!/usr/bin/env python3
"""Startdatei für die Git GUI direkt aus dem Repo heraus. Usage: git_gui.py [repo ...]

Der eigentliche Code liegt im Paket `gitgui/`; installiert heißt der Befehl `git-gui`.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))  # realpath: auch über den Symlink ~/.local/bin/gitgui

from gitgui.app import main  # noqa: E402

main()
