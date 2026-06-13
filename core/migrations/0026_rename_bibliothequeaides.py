from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0025_devis_zone_financement_ext_finx'),
    ]

    operations = [
        migrations.RenameModel(
            old_name='BibliothèqueAides',
            new_name='BibliothequeAides',
        ),
    ]
