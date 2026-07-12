import os
import sys

from django.apps import AppConfig


class PipelinesConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "pipelines"

    def ready(self):
        # Start the interval scheduler once per serving process:
        # - under runserver's autoreloader, only the serving child has
        #   RUN_MAIN=true (the watcher parent must not schedule);
        # - with --noreload there is a single process and RUN_MAIN is unset;
        # - under gunicorn (Docker) each worker starts one; _loop desyncs the
        #   ticks by pid and _tick's pending/running check prevents duplicates;
        # - never start for one-off management commands (migrate, seed, ...).
        if sys.argv[1:2] == ["runserver"]:
            if os.environ.get("RUN_MAIN") != "true" and "--noreload" not in sys.argv:
                return
        elif "gunicorn" not in os.path.basename(sys.argv[0] or ""):
            return
        try:
            from . import scheduler

            scheduler.start()
        except Exception:
            pass  # scheduling is best-effort; never block startup
