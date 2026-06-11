"""
Seed shareholder QA demo users (one per role at @pdkentrust.com).

Usage:
  python manage.py seed_role_demos
  python manage.py seed_role_demos --reset-passwords
"""
import os

from django.core.management.base import BaseCommand, CommandError

from core.services.role_demos import ROLE_DEMO_SPECS, SUPERUSER_EMAIL, seed_role_demos


class Command(BaseCommand):
    help = "Seed role demo users for shareholder QA (@pdkentrust.com) and confirm superuser profile."

    def add_arguments(self, parser):
        parser.add_argument(
            "--password",
            default=os.getenv("ROLE_DEMO_PASSWORD", "demo"),
            help="Password for role demo users (default: ROLE_DEMO_PASSWORD env or 'demo').",
        )
        parser.add_argument(
            "--reset-passwords",
            action="store_true",
            help="Reset passwords for existing role demo users.",
        )

    def handle(self, *args, **options):
        password = (options["password"] or "").strip()
        if not password:
            raise CommandError("Password must not be empty.")

        try:
            result = seed_role_demos(
                password=password,
                reset_passwords=options["reset_passwords"],
            )
        except ValueError as exc:
            raise CommandError(str(exc)) from exc

        self.stdout.write(
            self.style.SUCCESS(
                f'Role demo seed OK — org="{result.organization.name}" '
                f"users_created={result.users_created} users_updated={result.users_updated} "
                f"superuser_profile_updated={result.superuser_updated}"
            )
        )

        self.stdout.write("")
        self.stdout.write(f"Superuser (password unchanged): {SUPERUSER_EMAIL}")
        self.stdout.write("")
        self.stdout.write("Role demo logins:")
        for role, _display in ROLE_DEMO_SPECS:
            self.stdout.write(f"  {role}@pdkentrust.com  ({role})  password={password}")
