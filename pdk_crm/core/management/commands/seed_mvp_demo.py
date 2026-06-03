"""
Seed MacBook MVP trial data (Phase 10.MVP).

Usage:
  python manage.py seed_mvp_demo
  python manage.py seed_mvp_demo --with-sample-client
  python manage.py seed_mvp_demo --reset-passwords
"""
import os

from django.core.management.base import BaseCommand, CommandError

from core.services.mvp_demo import DEMO_USERS, seed_mvp_demo


class Command(BaseCommand):
    help = "Seed organization, tax season, and demo users for MacBook MVP trial."

    def add_arguments(self, parser):
        parser.add_argument(
            "--password",
            default=os.getenv("MVP_DEMO_PASSWORD", "demo-mvp"),
            help="Password for demo users (default: MVP_DEMO_PASSWORD env or 'demo-mvp').",
        )
        parser.add_argument(
            "--with-sample-client",
            action="store_true",
            help="Create Demo Client enrolled in intake (TIN 900000001).",
        )
        parser.add_argument(
            "--reset-passwords",
            action="store_true",
            help="Reset passwords for existing demo users.",
        )

    def handle(self, *args, **options):
        password = (options["password"] or "").strip()
        if not password:
            raise CommandError("Password must not be empty.")

        try:
            result = seed_mvp_demo(
                password=password,
                with_sample_client=options["with_sample_client"],
                reset_passwords=options["reset_passwords"],
            )
        except ValueError as exc:
            raise CommandError(str(exc)) from exc

        self.stdout.write(
            self.style.SUCCESS(
                f'MVP demo seed OK — org="{result.organization.name}" '
                f'tax_season={result.tax_season.year} '
                f"users_created={result.users_created} users_updated={result.users_updated}"
            )
        )
        if result.sample_client:
            self.stdout.write(
                self.style.SUCCESS(
                    f'Sample client: {result.sample_client.name} (TIN {result.sample_client.TIN})'
                )
            )

        self.stdout.write("")
        self.stdout.write("Demo logins (dev only):")
        for spec in DEMO_USERS:
            self.stdout.write(f"  {spec['email']}  ({spec['role']})")
