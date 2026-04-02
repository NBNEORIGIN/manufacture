"""
Sync staff from Phloe's /api/staff-module/ endpoint.
Creates/updates Django User records for manufacture login.
"""
import secrets
import string
import requests
from django.conf import settings
from django.core.management.base import BaseCommand
from django.contrib.auth.models import User


class Command(BaseCommand):
    help = 'Sync staff from Phloe staffing module'

    def add_arguments(self, parser):
        parser.add_argument('--dry-run', action='store_true')

    def handle(self, *args, **options):
        dry_run = options['dry_run']
        phloe_url = getattr(settings, 'PHLOE_API_URL', '')
        phloe_token = getattr(settings, 'PHLOE_API_TOKEN', '')

        if not phloe_url:
            self.stderr.write('PHLOE_API_URL not configured')
            return

        url = f'{phloe_url.rstrip("/")}/api/staff-module/'
        headers = {}
        if phloe_token:
            headers['Authorization'] = f'Bearer {phloe_token}'

        self.stdout.write(f'Fetching staff from {url}...')

        try:
            resp = requests.get(url, headers=headers, timeout=30)
            resp.raise_for_status()
        except requests.RequestException as e:
            self.stderr.write(f'Failed to fetch Phloe staff: {e}')
            return

        staff_list = resp.json()
        if isinstance(staff_list, dict):
            staff_list = staff_list.get('results', staff_list.get('data', []))

        stats = {'created': 0, 'updated': 0, 'skipped': 0}

        for staff in staff_list:
            email = staff.get('email', '').strip().lower()
            display_name = staff.get('display_name', '').strip()
            role = staff.get('role', 'staff')
            is_active = staff.get('is_active', True)

            if not email:
                stats['skipped'] += 1
                continue

            name_parts = display_name.split(' ', 1) if display_name else ['', '']
            first_name = name_parts[0]
            last_name = name_parts[1] if len(name_parts) > 1 else ''

            if dry_run:
                self.stdout.write(f'  [DRY] {email}: {display_name} ({role})')
                continue

            user, created = User.objects.get_or_create(
                email=email,
                defaults={
                    'username': email.split('@')[0],
                    'first_name': first_name[:30],
                    'last_name': last_name[:150],
                    'is_staff': role in ('manager', 'owner'),
                    'is_active': is_active,
                },
            )

            if created:
                pw = ''.join(secrets.choice(string.ascii_letters + string.digits) for _ in range(12))
                user.set_password(pw)
                user.save()
                stats['created'] += 1
                self.stdout.write(f'  Created: {email} (temp password: {pw})')
            else:
                user.first_name = first_name[:30]
                user.last_name = last_name[:150]
                user.is_active = is_active
                user.is_staff = role in ('manager', 'owner')
                user.save(update_fields=['first_name', 'last_name', 'is_active', 'is_staff'])
                stats['updated'] += 1

        self.stdout.write(self.style.SUCCESS(
            f"Staff sync complete: {stats['created']} created, "
            f"{stats['updated']} updated, {stats['skipped']} skipped"
        ))
