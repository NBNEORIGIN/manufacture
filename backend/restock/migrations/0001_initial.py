import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = []

    operations = [
        migrations.CreateModel(
            name='RestockReport',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('marketplace', models.CharField(db_index=True, max_length=10)),
                ('region', models.CharField(max_length=10)),
                ('report_id', models.CharField(blank=True, max_length=100)),
                ('status', models.CharField(choices=[('pending', 'Pending'), ('running', 'Running'), ('complete', 'Complete'), ('error', 'Error')], default='pending', max_length=20)),
                ('row_count', models.IntegerField(default=0)),
                ('source', models.CharField(default='spapi', max_length=20)),
                ('error_message', models.TextField(blank=True)),
            ],
            options={
                'ordering': ['-created_at'],
            },
        ),
        migrations.CreateModel(
            name='RestockItem',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('report', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='items', to='restock.restockreport')),
                ('marketplace', models.CharField(db_index=True, max_length=10)),
                ('merchant_sku', models.CharField(db_index=True, max_length=200)),
                ('asin', models.CharField(blank=True, db_index=True, max_length=20)),
                ('fnsku', models.CharField(blank=True, max_length=50)),
                ('m_number', models.CharField(blank=True, db_index=True, max_length=20)),
                ('product_name', models.CharField(blank=True, max_length=500)),
                ('units_total', models.IntegerField(default=0)),
                ('units_available', models.IntegerField(default=0)),
                ('units_inbound', models.IntegerField(default=0)),
                ('days_of_supply_amazon', models.FloatField(blank=True, null=True)),
                ('days_of_supply_total', models.FloatField(blank=True, null=True)),
                ('sales_last_30d', models.FloatField(default=0)),
                ('units_sold_30d', models.IntegerField(default=0)),
                ('alert', models.CharField(blank=True, db_index=True, max_length=50)),
                ('amazon_recommended_qty', models.IntegerField(blank=True, null=True)),
                ('amazon_ship_date', models.DateField(blank=True, null=True)),
                ('newsvendor_qty', models.IntegerField(blank=True, null=True)),
                ('newsvendor_confidence', models.FloatField(blank=True, null=True)),
                ('newsvendor_notes', models.TextField(blank=True)),
                ('approved_qty', models.IntegerField(blank=True, null=True)),
                ('approved_by', models.CharField(blank=True, max_length=100)),
                ('approved_at', models.DateTimeField(blank=True, null=True)),
                ('production_order_id', models.IntegerField(blank=True, null=True)),
            ],
            options={
                'ordering': ['alert', '-newsvendor_qty'],
            },
        ),
        migrations.CreateModel(
            name='RestockPlan',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('marketplace', models.CharField(db_index=True, max_length=10)),
                ('created_by', models.CharField(max_length=100)),
                ('status', models.CharField(choices=[('draft', 'Draft'), ('approved', 'Approved'), ('in_production', 'In Production'), ('shipped', 'Shipped')], default='draft', max_length=30)),
                ('report', models.ForeignKey(null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='plans', to='restock.restockreport')),
                ('notes', models.TextField(blank=True)),
                ('total_units', models.IntegerField(default=0)),
                ('item_count', models.IntegerField(default=0)),
            ],
            options={
                'ordering': ['-created_at'],
            },
        ),
        migrations.AddIndex(
            model_name='restockreport',
            index=models.Index(fields=['marketplace', 'created_at'], name='restock_rep_marketp_idx'),
        ),
        migrations.AddIndex(
            model_name='restockitem',
            index=models.Index(fields=['marketplace', 'merchant_sku'], name='restock_ite_marketp_idx'),
        ),
        migrations.AddIndex(
            model_name='restockitem',
            index=models.Index(fields=['m_number'], name='restock_ite_m_numbe_idx'),
        ),
        migrations.AddIndex(
            model_name='restockitem',
            index=models.Index(fields=['alert'], name='restock_ite_alert_idx'),
        ),
    ]
