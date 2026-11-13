from django.core.validators import MaxValueValidator
from django.db import migrations, models
from django.utils import timezone

import users.models


class Migration(migrations.Migration):
    dependencies = [('users', '0001_initial')]

    operations = [
        migrations.RemoveField(model_name='user', name='username'),
        migrations.AddField(
            model_name='user', name='date_of_birth',
            field=models.DateField(
                'Fecha de nacimiento', blank=True, null=True,
                validators=[MaxValueValidator(timezone.localdate)],
            ),
        ),
        migrations.AlterModelManagers(
            name='user', managers=[('objects', users.models.UserManager())],
        ),
    ]
