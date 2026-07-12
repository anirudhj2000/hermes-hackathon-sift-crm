import os
import sys

from django.apps import AppConfig


class PipelinesConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "pipelines"

    def ready(self):
        # Start the interval scheduler exactly once per server process:
        # - under runserver's autoreloader, only the serving child has
        #   RUN_MAIN=true (the watcher parent must not schedule);
        # - with --noreload there is a single process and RUN_MAIN is unset;
        # - never start for one-off management commands (migrate, seed, ...).
        argv = sys.argv[1:2]
        if argv != ["runserver"]:
            return
        if os.environ.get("RUN_MAIN") != "true" and "--noreload" not in sys.argv:
            return
        try:
            from . import scheduler

            scheduler.start()
        except Exception:
            pass  # scheduling is best-effort; never block startup
