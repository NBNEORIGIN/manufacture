from django.db import models
from core.models import TimestampedModel


class StockLevel(TimestampedModel):
    product = models.OneToOneField(
        'products.Product', on_delete=models.CASCADE, related_name='stock'
    )
    current_stock = models.IntegerField(default=0)
    fba_stock = models.IntegerField(default=0)
    sixty_day_sales = models.IntegerField(default=0)
    thirty_day_sales = models.IntegerField(default=0)
    optimal_stock_30d = models.IntegerField(default=0)
    stock_deficit = models.IntegerField(default=0)
    last_count_date = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['product__m_number']

    def __str__(self):
        return f'{self.product.m_number}: {self.current_stock} (deficit {self.stock_deficit})'

    def recalculate_deficit(self):
        self.stock_deficit = max(0, self.optimal_stock_30d - self.current_stock)
        self.save(update_fields=['stock_deficit', 'updated_at'])
