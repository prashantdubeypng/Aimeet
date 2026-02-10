from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ('agora', '0010_documentupload_chunk_count'),
    ]

    operations = [
        migrations.CreateModel(
            name='MeetingAgendaPoint',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('text', models.TextField()),
                ('order', models.IntegerField(default=0)),
                ('is_ai_generated', models.BooleanField(default=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('created_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, to='auth.user')),
                ('meeting', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='agenda_points', to='agora.meetingroom')),
            ],
            options={
                'ordering': ['order', 'created_at'],
            },
        ),
    ]
