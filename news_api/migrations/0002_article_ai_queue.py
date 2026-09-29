from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("news_api", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="article",
            name="ai_status",
            field=models.CharField(default="pending", max_length=20),
        ),
        migrations.AddField(
            model_name="article",
            name="ai_locked_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="article",
            name="ai_completed_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]
