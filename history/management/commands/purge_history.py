from django.core.management.base import BaseCommand

from history import recorder


class Command(BaseCommand):
    help = "刪除超過保留日數（FB_CALC_HISTORY_DAYS，預設 180 日）的計價紀錄"

    def handle(self, *args, **options):
        n = recorder.purge()
        if options.get("verbosity", 1) > 0:
            self.stdout.write(self.style.SUCCESS(
                f"已刪除 {n} 筆超過 {recorder.keep_days()} 日的計價紀錄"))
