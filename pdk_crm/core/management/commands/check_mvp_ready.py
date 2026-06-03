"""
Check MacBook MVP trial readiness (Phase 10.MVP).

Usage:
  python manage.py check_mvp_ready
"""
from django.core.management.base import BaseCommand

from core.services.mvp_demo import mvp_demo_readiness_issues


class Command(BaseCommand):
    help = "Verify MVP demo seed data exists (org, tax season, demo users)."

    def handle(self, *args, **options):
        issues = mvp_demo_readiness_issues()
        if issues:
            self.stdout.write(self.style.ERROR("MVP trial NOT ready:"))
            for issue in issues:
                self.stdout.write(f"  - {issue}")
            self.stdout.write("")
            self.stdout.write("Fix: docker compose exec crm_web python manage.py seed_mvp_demo")
            raise SystemExit(1)

        self.stdout.write(self.style.SUCCESS("MVP trial seed data OK."))
        self.stdout.write("Next: docker compose up, log in as preparer@demo.pdk.local, walk docs/MVP_TRIAL.md")
