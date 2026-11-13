from django.db import migrations


def deactivate_suspended_users(apps, schema_editor):
    User = apps.get_model('users', 'User')
    User.objects.using(schema_editor.connection.alias).filter(
        is_suspended=True,
    ).update(is_active=False)


class Migration(migrations.Migration):
    dependencies = [('users', '0002_email_login_date_of_birth')]

    operations = [
        migrations.RunPython(deactivate_suspended_users, migrations.RunPython.noop),
        migrations.RemoveField(model_name='user', name='is_suspended'),
    ]
