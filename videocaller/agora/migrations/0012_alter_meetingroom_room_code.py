from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ('agora', '0011_meeting_agenda_point'),
    ]

    operations = [
        migrations.AlterField(
            model_name='meetingroom',
            name='room_code',
            field=models.CharField(max_length=15, unique=True),
        ),
    ]
